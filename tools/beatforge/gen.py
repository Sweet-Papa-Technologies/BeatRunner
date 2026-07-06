"""gen.py — Workstream A: better source tracks via a Lyria × Gemini A&R loop.

Generate N candidates per round, have Gemini 3.5 Flash HEAR each and score its
chartability, rewrite the Lyria prompt against the weakest dimensions, iterate
<= K rounds, pick the winner, then master it deterministically (trim → loudnorm
→ -14 LUFS → ogg). Music understanding is where the model earns its keep — it is
the A&R ear, not the composer. (REQ-GEN-01..05.)

Runnable per-track; the keep-the-hits default (`all --skip-gen`) skips this.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path

from . import config
from .vertex import VertexClient

# Per-track generation brief (genre intent for the A&R critic + seed prompt).
BRIEFS = {
    "overdrive": "driving 120-BPM synthwave with a punchy four-on-the-floor kick, "
                 "bright arps, and a clear build into a drop.",
    "midnight": "128-BPM darkwave night-drive: steady kick, gated snare, moody "
                "analog bass, a hooky lead in the second half.",
    "neon": "upbeat ~136-BPM retrowave with crisp claps, shimmering leads, and a "
            "clean 8-bar build into a bright hook.",
    "groove": "88-BPM lo-fi synth-funk groove: fat kick, snappy snare, warm "
              "Rhodes-ish chords, relaxed pocket.",
}


def _weighted(score: dict) -> float:
    w = config.GEN_RUBRIC_WEIGHTS
    total = sum(w.values())
    return sum(score.get(k, 0) * wt for k, wt in w.items()) / total


def score_candidate(wav_path: str, brief: str, client: VertexClient) -> dict:
    tmpl = (config.PROMPTS_DIR / "ar_critic.md").read_text().replace("{brief}", brief)
    card = client.generate_json(tmpl, audio_path=wav_path)
    card["weighted"] = round(_weighted(card), 3)
    return card


def generate_track(track_id: str, opts: config.RunOptions, client: VertexClient) -> dict:
    """Run the candidate→score→rewrite loop and master the winner (REQ-GEN-01..04)."""
    base = config.TRACK_CATALOGUE.get(track_id, track_id)
    brief = BRIEFS.get(track_id, "punchy 120-BPM synthwave, drums forward.")
    work = config.BUILD_DIR / f"{base}.gen"
    work.mkdir(parents=True, exist_ok=True)
    log = []
    prompt = brief
    best = None

    for rnd in range(1, config.GEN_MAX_ROUNDS + 1):
        round_cards = []
        for c in range(config.GEN_CANDIDATES_PER_ROUND):
            wav = work / f"round{rnd}_cand{c}.wav"
            if not wav.exists() or opts.force:
                audio = client.lyria(prompt, seed=1000 * rnd + c)
                wav.write_bytes(audio)
            card = score_candidate(str(wav), brief, client)
            card.update({"round": rnd, "candidate": c, "wav": str(wav), "prompt": prompt})
            round_cards.append(card)
            if best is None or card["weighted"] > best["weighted"]:
                best = card
        log.append({"round": rnd, "prompt": prompt, "cards": round_cards})
        if best and best["weighted"] >= config.GEN_SHIP_THRESHOLD:
            break
        # rewrite the prompt targeting the weakest dimensions (REQ-GEN-03)
        weakest = min(round_cards, key=lambda c: c["weighted"])
        prompt = weakest.get("prompt_rewrite") or _fallback_rewrite(brief, weakest)

    (work / "gen-log.json").write_text(json.dumps(log, indent=2))
    (config.BUILD_DIR / f"{base}.gen-log.json").write_text(json.dumps(log, indent=2))

    winner_wav = best["wav"]
    ogg = _master(winner_wav, base)
    (config.BUILD_DIR / f"{base}.winner-scorecard.json").write_text(json.dumps(best, indent=2))
    return {"track": track_id, "winner_score": best["weighted"], "rounds": len(log),
            "audio": str(ogg), "scorecard": best}


def _fallback_rewrite(brief: str, weakest: dict) -> str:
    dims = sorted(config.GEN_RUBRIC_WEIGHTS, key=lambda k: weakest.get(k, 0))[:2]
    hints = {
        "tempo_stability": "lock the tempo, no rubato",
        "transient_clarity": "crisper, well-defined kick and snare transients",
        "structural_contrast": "add a clear 8-bar build into a drop at the midpoint",
        "intro_cleanliness": "start immediately, no silence or long fade-in",
        "mix_punch": "drums forward in the mix, not buried under pads",
        "genre_fit": "stronger synthwave character",
    }
    return brief + "; " + ", ".join(hints[d] for d in dims)


def _master(wav_path: str, base: str) -> Path:
    """Trim leading silence, two-pass loudnorm to -14 LUFS / -1 dBTP, encode ogg
    q6 into assets/ + public/ and update the manifest (REQ-GEN-04)."""
    if not shutil.which("ffmpeg"):
        raise RuntimeError("ffmpeg required for mastering")
    out_src = config.TRACKS_SRC / f"{base}.ogg"
    out_pub = config.TRACKS_PUB / f"{base}.ogg"
    with tempfile.TemporaryDirectory() as td:
        trimmed = Path(td) / "trim.wav"
        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-i", wav_path,
             "-af", "silenceremove=start_periods=1:start_silence=0.1:start_threshold=-50dB",
             str(trimmed)], check=True, capture_output=True)
        # pass 1: measure
        meas = subprocess.run(
            ["ffmpeg", "-i", str(trimmed), "-af",
             f"loudnorm=I={config.TARGET_LUFS}:TP={config.TARGET_TRUE_PEAK_DBTP}:LRA=11:print_format=json",
             "-f", "null", "-"], capture_output=True, text=True)
        stats = _parse_loudnorm(meas.stderr)
        af = (f"loudnorm=I={config.TARGET_LUFS}:TP={config.TARGET_TRUE_PEAK_DBTP}:LRA=11:"
              f"measured_I={stats['input_i']}:measured_TP={stats['input_tp']}:"
              f"measured_LRA={stats['input_lra']}:measured_thresh={stats['input_thresh']}:linear=true")
        for out in (out_src, out_pub):
            out.parent.mkdir(parents=True, exist_ok=True)
            subprocess.run(
                ["ffmpeg", "-y", "-loglevel", "error", "-i", str(trimmed),
                 "-af", af, "-c:a", "libvorbis", "-q:a", "6", str(out)],
                check=True, capture_output=True)
    _update_manifest(base)
    return out_pub


def _parse_loudnorm(stderr: str) -> dict:
    start = stderr.rfind("{")
    end = stderr.rfind("}")
    data = json.loads(stderr[start:end + 1])
    return {"input_i": data["input_i"], "input_tp": data["input_tp"],
            "input_lra": data["input_lra"], "input_thresh": data["input_thresh"]}


def _update_manifest(base: str) -> None:
    for root in (config.TRACKS_SRC, config.TRACKS_PUB):
        man = root / "_manifest.json"
        try:
            data = json.loads(man.read_text()) if man.exists() else {}
        except json.JSONDecodeError:
            data = {}
        data.setdefault("tracks", [])
        if f"{base}.ogg" not in data["tracks"]:
            data["tracks"].append(f"{base}.ogg")
        man.write_text(json.dumps(data, indent=2))
