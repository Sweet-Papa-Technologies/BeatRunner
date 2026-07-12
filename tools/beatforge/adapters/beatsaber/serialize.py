"""serialize.py — emit a Beat Saber song folder (Info.dat + v3 beatmap .dat per
difficulty) via BeatSaber-JSMap (SABERFORGE spec §7, REQ-BS-06/REQ-POS-01/03).

We NEVER hand-format the map JSON: the Node helper `jsmap_serialize.mjs` owns the
grammar through `bsmap`, and this module owns the note-object payload, metadata,
the AI-assisted marker, and the sort/offset-clean pass for a ChroMapper handoff.
If Node or `bsmap` is unavailable the build degrades loudly: it writes a clean,
sorted v3 fallback and marks the map "unverified" (mirrors the external-checker
graceful degradation of REQ-BS-09)."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from .realize import SaberObject

_HELPER = Path(__file__).resolve().parent / "jsmap_serialize.mjs"
AI_MARKER = "SABERFORGE (AI-assisted draft)"
_SNAP = 64.0            # clean beats to 1/64 so ChroMapper sees no float snap errors


def _clean(beat: float) -> float:
    return round(round(beat * _SNAP) / _SNAP, 6)


def _difficulty_filename(difficulty_name: str) -> str:
    return f"{difficulty_name}Standard.dat"


def objects_to_payload(objs: list[SaberObject]) -> dict:
    """Split realized SaberObjects into the v3 collections (all three required
    ones always present, even empty — REQ-BS-06), sorted + precision-cleaned.
    Arcs/chains emit their head (and arc tail) as color notes so the map is
    playable and loads, plus the slider/chain object for the mechanic."""
    color_notes, bombs, obstacles, arcs, chains = [], [], [], [], []
    for o in sorted(objs, key=lambda o: (o.beat, o.color)):
        if o.kind == "bomb":
            bombs.append({"b": _clean(o.beat), "x": o.x, "y": o.y})
        elif o.kind == "note":
            color_notes.append({"b": _clean(o.beat), "x": o.x, "y": o.y,
                                "c": o.color, "d": o.direction, "a": o.angle})
        elif o.kind == "arc":
            color_notes.append({"b": _clean(o.beat), "x": o.x, "y": o.y,
                                "c": o.color, "d": o.direction, "a": o.angle})
            if o.tail_beat is not None:
                td = o.tail_direction if o.tail_direction is not None else o.direction
                color_notes.append({"b": _clean(o.tail_beat), "x": o.tail_x, "y": o.tail_y,
                                    "c": o.color, "d": td, "a": 0})
                arcs.append({"b": _clean(o.beat), "x": o.x, "y": o.y, "c": o.color,
                             "d": o.direction, "tb": _clean(o.tail_beat),
                             "tx": o.tail_x, "ty": o.tail_y, "td": td, "mu": 1, "tmu": 1, "m": 0})
        elif o.kind == "chain":
            color_notes.append({"b": _clean(o.beat), "x": o.x, "y": o.y,
                                "c": o.color, "d": o.direction, "a": o.angle})
            if o.tail_beat is not None:
                chains.append({"b": _clean(o.beat), "x": o.x, "y": o.y, "c": o.color,
                               "d": o.direction, "tb": _clean(o.tail_beat),
                               "tx": o.tail_x, "ty": o.tail_y,
                               "sc": o.slice_count or 3, "s": o.squish})
    return {"colorNotes": color_notes, "bombNotes": bombs, "obstacles": obstacles,
            "arcs": arcs, "chains": chains}


def build_payload(track_meta: dict, analysis: dict, per_difficulty: dict,
                  out_dir: Path) -> dict:
    """per_difficulty: {key: {"difficulty","rank","njs","offset","objects","lighting"}}."""
    from .grammar import BUDGETS
    diffs = []
    for key, info in per_difficulty.items():
        payload = objects_to_payload(info["objects"])
        diffs.append({
            "key": key,
            "difficulty": BUDGETS[key].difficulty_name,
            "label": BUDGETS[key].difficulty_name,
            "rank": info["rank"],
            "filename": _difficulty_filename(BUDGETS[key].difficulty_name),
            "njs": info["njs"], "offset": info["offset"],
            "basicEvents": info.get("lighting", []),
            **payload,
        })
    return {
        "outDir": str(out_dir),
        "info": {
            "title": track_meta["title"], "artist": track_meta["artist"],
            "mapper": AI_MARKER, "marker": AI_MARKER,
            "bpm": round(analysis["bpm"], 3),
            "songFilename": track_meta["music"],
            "coverImageFilename": track_meta.get("cover", "cover.jpg"),
            "previewStart": _preview_start(analysis),
            "previewDuration": 12,
        },
        "difficulties": diffs,
    }


def _preview_start(analysis: dict) -> float:
    bpm, offset = analysis["bpm"], analysis["offset"]
    best = max(analysis.get("sections", []), key=lambda s: s.get("energy_pct", 0), default=None)
    if not best:
        return 0.0
    return round(offset + best["start_bar"] * 4 / bpm * 60, 3)


def write_song_folder(track_meta: dict, analysis: dict, per_difficulty: dict,
                      audio_src: str, out_dir: Path) -> dict:
    """Write the CustomLevels-ready song folder. Returns {files, roundtrip_ok,
    verified}. Runs the JSMap helper; falls back to a clean fallback (marked
    unverified) if Node/bsmap is missing."""
    out_dir.mkdir(parents=True, exist_ok=True)
    payload = build_payload(track_meta, analysis, per_difficulty, out_dir)
    payload_path = out_dir / ".saberforge_payload.json"
    payload_path.write_text(json.dumps(payload))

    result = _run_jsmap(payload_path)
    if result is None or not result.get("ok"):
        result = _fallback_write(payload, out_dir)
    payload_path.unlink(missing_ok=True)      # transient — not part of the song folder

    # copy audio into the folder
    audio_dst = out_dir / track_meta["music"]
    if Path(audio_src).exists() and Path(audio_src).resolve() != audio_dst.resolve():
        shutil.copyfile(audio_src, audio_dst)
    result.setdefault("files", {})["audio"] = str(audio_dst)
    return result


def _run_jsmap(payload_path: Path) -> dict | None:
    if not shutil.which("node"):
        return None
    try:
        proc = subprocess.run(["node", str(_HELPER), str(payload_path)],
                              capture_output=True, text=True, timeout=120,
                              cwd=str(_repo_root()))
    except Exception:
        return None
    if proc.returncode != 0 and not proc.stdout.strip():
        return None
    try:
        res = json.loads(proc.stdout.strip() or "{}")
    except json.JSONDecodeError:
        return None
    res["verified"] = bool(res.get("ok") and res.get("roundtrip_ok"))
    if not res.get("ok"):
        res["stderr"] = proc.stderr[-500:]
    return res


def _repo_root() -> Path:
    from ... import config
    return config.REPO_ROOT


def _fallback_write(payload: dict, out_dir: Path) -> dict:
    """No Node/bsmap: emit a clean sorted v3 map by hand as a LAST resort. Marked
    unverified so QA/CLI flag that JSMap round-trip did not run (spec §7/§9)."""
    print("[saberforge] WARNING: node/bsmap unavailable — writing UNVERIFIED "
          "fallback map (install `bsmap` + Node for the JSMap round-trip).")
    files = {}
    for d in payload["difficulties"]:
        dat = {
            "version": "3.3.0",
            "bpmEvents": [], "rotationEvents": [],
            "colorNotes": d["colorNotes"], "bombNotes": d["bombNotes"],
            "obstacles": d["obstacles"], "sliders": d["arcs"], "burstSliders": d["chains"],
            "waypoints": [], "basicBeatmapEvents": d.get("basicEvents", []),
            "colorBoostBeatmapEvents": [], "lightColorEventBoxGroups": [],
            "lightRotationEventBoxGroups": [], "lightTranslationEventBoxGroups": [],
            "basicEventTypesWithKeywords": {"d": []}, "useNormalEventsAsCompatibleEvents": True,
        }
        path = out_dir / d["filename"]
        path.write_text(json.dumps(dat))
        files[d["key"]] = str(path)
    info = _fallback_info(payload)
    info_path = out_dir / "Info.dat"
    info_path.write_text(json.dumps(info))
    files["info"] = str(info_path)
    return {"ok": True, "files": files, "roundtrip_ok": False, "verified": False,
            "fallback": True}


def _fallback_info(payload: dict) -> dict:
    info = payload["info"]
    beatmaps = [{
        "_difficulty": d["difficulty"], "_difficultyRank": d["rank"],
        "_beatmapFilename": d["filename"], "_noteJumpMovementSpeed": d["njs"],
        "_noteJumpStartBeatOffset": d["offset"], "_beatmapColorSchemeIdx": 0,
        "_environmentNameIdx": 0,
        "_customData": {"_difficultyLabel": d["label"], "_information": [info["marker"]]},
    } for d in payload["difficulties"]]
    return {
        "_version": "2.1.0", "_songName": info["title"], "_songSubName": "",
        "_songAuthorName": info["artist"], "_levelAuthorName": info["marker"],
        "_beatsPerMinute": info["bpm"], "_songTimeOffset": 0, "_shuffle": 0,
        "_shufflePeriod": 0.5, "_previewStartTime": info["previewStart"],
        "_previewDuration": info["previewDuration"], "_songFilename": info["songFilename"],
        "_coverImageFilename": info["coverImageFilename"],
        "_environmentName": "DefaultEnvironment",
        "_allDirectionsEnvironmentName": "GlassDesertEnvironment",
        "_customData": {"_saberforge": info["marker"]},
        "_difficultyBeatmapSets": [{
            "_beatmapCharacteristicName": "Standard", "_difficultyBeatmaps": beatmaps}],
    }
