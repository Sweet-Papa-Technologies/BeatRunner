#!/usr/bin/env python3
"""stepcapture — record autoplay gameplay of a StepMania pack with OBS, one video
per song, unattended.

    python3 stepcapture.py install                 # one-time: theme + prefs + obs-websocket
    python3 stepcapture.py check                   # verify everything is wired up
    python3 stepcapture.py record --pack "SweetPapa Dream Mix - Founder Mix" \
                                  --difficulty Challenge --out ~/Desktop/gameplay

How it fits together
--------------------
ITGmania runs a purpose-built theme (StepCapture) whose only job is to walk a
queue of songs, set AutoPlay, and drop into gameplay. On each song boundary the
theme calls this script's local HTTP server via NETWORK:HttpRequest, and the
server drives OBS over obs-websocket.

The important detail is that /song-start does not return until OBS has confirmed
it is recording — the theme waits for the HTTP response before entering gameplay.
That is what makes the cut frame-accurate instead of a sleep-and-pray.

    ITGmania (Lua)                 this script                 OBS
    --------------                 ----------                 ---
    /song-start        --------->  StartRecord    --------->
                                   (poll until outputActive)
                       <---------  200 OK
    enter gameplay ...
    (song plays in autoplay)
    /song-end          --------->  wait TAIL, StopRecord --->
                                   rename outputPath -> "01 - Title (Challenge).mkv"
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
import urllib.parse
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

APP_SUPPORT = Path("~/Library/Application Support/ITGmania").expanduser()
SONGS_DIR = APP_SUPPORT / "Songs"
THEMES_DIR = APP_SUPPORT / "Themes"
SAVE_DIR = APP_SUPPORT / "Save"
PREFS = SAVE_DIR / "Preferences.ini"
QUEUE = SAVE_DIR / "stepcapture" / "queue.tsv"
ITG_BIN = Path("/Applications/ITGmania.app/Contents/MacOS/ITGmania")
OBS_BIN = Path("/Applications/OBS.app/Contents/MacOS/OBS")
OBS_WS_CONFIG = Path(
    "~/Library/Application Support/obs-studio/plugin_config/obs-websocket/config.json"
).expanduser()
THEME_SRC = Path(__file__).parent / "theme"
THEME_NAME = "StepCapture"
PORT = 8777

DIFFICULTIES = ("Beginner", "Easy", "Medium", "Hard", "Challenge")

# Seconds to keep recording after the chart's last note, so the outro and the
# fade aren't guillotined. Trimmed off nothing — it's just tail.
TAIL_SECONDS = 2.5


# --------------------------------------------------------------------------- #
# OBS
# --------------------------------------------------------------------------- #
def obs_ws_settings() -> dict:
    if not OBS_WS_CONFIG.exists():
        raise SystemExit(
            f"No obs-websocket config at {OBS_WS_CONFIG}.\n"
            "Launch OBS once so it writes its config, then re-run `install`."
        )
    return json.loads(OBS_WS_CONFIG.read_text())


def obs_connect():
    try:
        import obsws_python as obsws
    except ImportError:
        raise SystemExit("pip install obsws-python")
    cfg = obs_ws_settings()
    if not cfg.get("server_enabled"):
        raise SystemExit(
            "obs-websocket is disabled. Run `stepcapture.py install` with OBS CLOSED."
        )
    return obsws.ReqClient(
        host="localhost",
        port=cfg.get("server_port", 4455),
        password=cfg.get("server_password", ""),
        timeout=10,
    )


def enable_obs_websocket() -> str:
    """Flip server_enabled in OBS's own config. Must be done with OBS closed, or
    OBS will overwrite it on exit. The CLI flags (--websocket_port/--websocket_
    password) only OVERRIDE port and password; none of them can turn the server
    on, which is why we edit the file."""
    if is_running("OBS"):
        return "OBS is running — quit it and re-run `install` to enable the websocket."
    cfg = obs_ws_settings()
    if cfg.get("server_enabled"):
        return f"already enabled on port {cfg.get('server_port')}"
    cfg["server_enabled"] = True
    OBS_WS_CONFIG.write_text(json.dumps(cfg, indent=4))
    return f"ENABLED on port {cfg.get('server_port')}"


def is_running(app: str) -> bool:
    return subprocess.run(["pgrep", "-x", app], capture_output=True).returncode == 0


# What we upload.
OUT_W, OUT_H = 1920, 1080

# The game's viewport, in POINTS — must match DisplayWidth/DisplayHeight in
# PREFS_PATCH. The capture comes back in backing pixels (this display is HiDPI, so
# points != pixels), and this is what lets us convert between the two.
GAME_PT_W, GAME_PT_H = 1600, 900

# macOS restores an app's window size across launches. That is actively harmful
# here: the game renders its 1600x900 viewport into whatever oversized window was
# restored from a previous run, leaving dead black margins in the capture. Nuking
# the saved state makes the window size a function of our prefs and nothing else.
SAVED_STATE = Path("~/Library/Saved Application State").expanduser()


def calibrate_obs(obs, scene: str) -> str:
    """Point OBS at the ITGmania *window* and make the frame a clean 1920x1080.

    Application- and display-capture both hand back the whole screen with the game
    floating inside it (menu bar, desktop, black margins — verified the hard way).
    Window capture crops to the window for us, so the game's screen position stops
    mattering. The window id changes on every launch, so this is re-run per session
    rather than being something you set up once in the OBS UI.
    """
    items = obs.get_scene_item_list(scene).scene_items
    cap = next((i for i in items if i["inputKind"] == "screen_capture"), None)
    if not cap:
        raise RuntimeError(f"scene '{scene}' has no macOS Screen Capture source")
    name, item_id = cap["sourceName"], cap["sceneItemId"]

    # Ask OBS which windows it can see, and find the game's.
    #
    # Match on the OWNING APPLICATION, not the title. OBS names these
    # "[<app>] <window title>", and the game's title is literally "StepMania" —
    # so a naive substring match on "stepmania" cheerfully picked up a Finder
    # window that happened to be showing the fofo-stepmania-songs folder.
    windows = obs.get_input_properties_list_property_items(name, "window").property_items
    win = next((w for w in windows
                if str(w.get("itemName", "")).lower().startswith("[itgmania]")), None)
    if not win:
        seen = ", ".join(str(w.get("itemName")) for w in windows[:8])
        raise RuntimeError(f"OBS sees no [ITGmania] window. Windows it can see: {seen}")

    obs.set_input_settings(name, {"type": 1,                    # 0=display 1=window 2=app
                                  "window": win["itemValue"],
                                  "show_cursor": False}, True)

    # The source reports 0x0 until it has actually bound to the window.
    for _ in range(50):
        t = obs.get_scene_item_transform(scene, item_id).scene_item_transform
        sw, sh = int(t["sourceWidth"]), int(t["sourceHeight"])
        if sw > 0 and sh > 0:
            break
        time.sleep(0.2)
    else:
        raise RuntimeError("OBS window source never reported a size (still 0x0)")

    # Crop away everything that isn't the game's viewport: the title bar on top, and
    # any dead window margin to the right/bottom that the game didn't draw into.
    #
    # The window capture arrives in backing pixels while the viewport is specified in
    # points, so derive the HiDPI scale from the width (the game's viewport spans the
    # window's full content width) and use it to place the crop.
    scale = sw / GAME_PT_W
    game_h_px = round(GAME_PT_H * scale)
    crop_top = max(0, sh - game_h_px)      # title bar + any bottom margin, all on top
    vis_w, vis_h = sw, sh - crop_top

    obs.set_scene_item_transform(scene, item_id, {
        "cropTop": crop_top, "cropBottom": 0, "cropLeft": 0, "cropRight": 0,
        "positionX": 0.0, "positionY": 0.0,
        "scaleX": 1.0, "scaleY": 1.0,
        "boundsType": "OBS_BOUNDS_NONE",
        "alignment": 5,   # top-left
    })

    # Canvas := the cropped viewport, so nothing rescales the game. Only the OUTPUT
    # is scaled, and only to 1080p when the result is genuinely 16:9 — a correctly
    # shaped smaller video beats a stretched big one.
    sixteen_by_nine = abs((vis_w / vis_h) - (16 / 9)) < 0.02
    ow, oh = (OUT_W, OUT_H) if sixteen_by_nine else (vis_w, vis_h)
    obs.set_video_settings(30, 1, vis_w, vis_h, ow, oh)

    note = "" if sixteen_by_nine else "  (NOT 16:9 — kept native to avoid stretching)"
    return (f"window {sw}x{sh} @{scale:g}x, cropped {crop_top}px chrome "
            f"-> {vis_w}x{vis_h} -> output {ow}x{oh}{note}")


# --------------------------------------------------------------------------- #
# ITGmania preferences
# --------------------------------------------------------------------------- #
# A dedicated "[Recording]" section driven by `--Type=Recording` was the obvious
# design, and it does not work. Two reasons, both found the hard way:
#
#   1. `Theme` is a GAME-SPECIFIC preference — it lives in [Game-dance], which is
#      read regardless of --Type, so the section's Theme= was simply ignored.
#   2. ITGmania rewrites Preferences.ini wholesale on exit from its in-memory
#      prefs, which DELETES any section it doesn't know about. The [Recording]
#      block evaporated after a single run.
#
# So instead:
#   * theme      -> the documented `--theme=StepCapture` command-line argument.
#   * AutoPlay   -> set from Lua at runtime (PREFSMAN:SetPreference), no ini needed.
#   * everything below -> patched into [Options] before the run and RESTORED from
#     a backup afterwards, because these are the ones that genuinely cannot be set
#     any other way.
#
# HttpEnabled/HttpAllowHosts are PreferenceType::Immutable: read once at startup,
# unsettable from Lua. Without localhost on the allowlist, NETWORK:HttpRequest
# silently refuses to call us and the whole handshake dies quietly.
PREFS_PATCH = {
    "HttpEnabled": "1",
    "HttpAllowHosts": "localhost,127.0.0.1,*.groovestats.com,*.itgmania.com",
    "AutoPlay": "Autoplay",          # NOT "Cpu" — that one misses notes on purpose
    "Windowed": "1",
    # 16:9, and small enough to actually FIT. A 1920x1080 window does not fit on a
    # 1080-tall display once the menu bar and title bar take their cut — macOS
    # silently clamps it to 1920x1009, which is a 1.90 aspect and would letterbox.
    # 1600x900 fits with room to spare and OBS upscales it to 1080p on output.
    "DisplayWidth": "1600",
    "DisplayHeight": "900",
    "DisplayAspectRatio": "1.777778",
    "EventMode": "1",                # no "insert coin", no stage limit
    "MenuTimer": "0",
}

BACKUP = SAVE_DIR / "Preferences.ini.stepcapture-backup"


def read_ini(path: Path) -> dict[str, dict[str, str]]:
    """Minimal INI reader. configparser is not used on purpose: Preferences.ini
    contains values with '%' and ';' that configparser mangles or chokes on."""
    sections: dict[str, dict[str, str]] = {}
    current = None
    if not path.exists():
        return sections
    for line in path.read_text(errors="replace").splitlines():
        s = line.strip()
        if s.startswith("[") and s.endswith("]"):
            current = s[1:-1]
            sections.setdefault(current, {})
        elif current and "=" in s and not s.startswith("#"):
            k, v = s.split("=", 1)
            sections[current][k.strip()] = v.strip()
    return sections


def patch_prefs() -> str:
    """Apply PREFS_PATCH to [Options], keeping a backup to restore afterwards."""
    if BACKUP.exists():
        # A previous run died before restoring. That backup is the pristine one —
        # keep it and roll back to it rather than backing up our own patched file.
        shutil.copy2(BACKUP, PREFS)
    else:
        shutil.copy2(PREFS, BACKUP)

    lines = PREFS.read_text(errors="replace").splitlines()
    out, remaining, in_options, done = [], dict(PREFS_PATCH), False, False

    for line in lines:
        s = line.strip()
        if s.startswith("[") and s.endswith("]"):
            if in_options and not done:
                # leaving [Options]: flush any keys that weren't already present
                out.extend(f"{k}={v}" for k, v in remaining.items())
                remaining, done = {}, True
            in_options = (s == "[Options]")
            out.append(line)
            continue
        if in_options and "=" in s:
            k = s.split("=", 1)[0].strip()
            if k in remaining:
                out.append(f"{k}={remaining.pop(k)}")
                continue
        out.append(line)

    if in_options and remaining:      # [Options] ran to EOF
        out.extend(f"{k}={v}" for k, v in remaining.items())

    PREFS.write_text("\n".join(out) + "\n")
    return f"patched {len(PREFS_PATCH)} keys in [Options] (backup: {BACKUP.name})"


def restore_prefs() -> str:
    """Put the user's Preferences.ini back exactly as it was. ITGmania will have
    rewritten the file on exit; this stomps whatever it wrote."""
    if not BACKUP.exists():
        return "no backup to restore"
    shutil.move(str(BACKUP), str(PREFS))
    return "Preferences.ini restored"


# --------------------------------------------------------------------------- #
# install / check
# --------------------------------------------------------------------------- #
def cmd_install(args):
    print("stepcapture install\n" + "-" * 60)

    THEMES_DIR.mkdir(parents=True, exist_ok=True)
    dst = THEMES_DIR / THEME_NAME
    if dst.exists() or dst.is_symlink():
        if dst.is_symlink():
            dst.unlink()
        else:
            shutil.rmtree(dst)
    shutil.copytree(THEME_SRC, dst)
    print(f"  theme     : installed -> {dst}")

    QUEUE.parent.mkdir(parents=True, exist_ok=True)
    print(f"  queue dir : {QUEUE.parent}")

    print(f"  prefs     : patched at record time, restored on exit (not touched now)")
    print(f"  obs ws    : {enable_obs_websocket()}")

    print("\nOne manual step remains, and it cannot be scripted:")
    print("  System Settings -> Privacy & Security -> Screen Recording -> enable OBS.")
    print("  (macOS SIP-protects the TCC database; `tccutil` can only RESET grants,")
    print("   never create them. An MDM profile is the only non-click alternative.)")
    print("\nIn OBS, build ONE scene containing a single 'macOS Screen Capture'")
    print("source, method = Application, application = ITGmania, with audio")
    print("capture on. That gives you video AND game audio from one source — no")
    print("BlackHole or Loopback needed on macOS 13+.")
    print("\nThen: python3 stepcapture.py check")


def cmd_check(args):
    ok = True

    def line(label, good, detail):
        nonlocal ok
        ok = ok and good
        print(f"  [{'OK ' if good else 'XX '}] {label:<22} {detail}")

    print("stepcapture check\n" + "-" * 60)
    line("theme installed", (THEMES_DIR / THEME_NAME).is_dir(), str(THEMES_DIR / THEME_NAME))
    line("theme scripts", (THEMES_DIR / THEME_NAME / "Scripts" / "99 StepCapture.lua").is_file(),
         "99 StepCapture.lua")
    line("prefs backup clean", not BACKUP.exists(),
         "stale backup — a previous run died; it will be rolled back"
         if BACKUP.exists() else "no stale backup")

    try:
        cfg = obs_ws_settings()
        line("obs-websocket cfg", bool(cfg.get("server_enabled")),
             f"port {cfg.get('server_port')}, enabled={cfg.get('server_enabled')}")
    except SystemExit as e:
        line("obs-websocket cfg", False, str(e).splitlines()[0])

    if is_running("OBS"):
        try:
            cl = obs_connect()
            ver = cl.get_version()
            line("obs reachable", True, f"OBS {ver.obs_version} / ws {ver.obs_web_socket_version}")
            rec = cl.get_record_status()
            line("obs recording idle", not rec.output_active, f"active={rec.output_active}")
            scenes = cl.get_scene_list()
            line("obs scene", True, f"current: {scenes.current_program_scene_name}")
        except Exception as e:
            line("obs reachable", False, f"{type(e).__name__}: {e}")
    else:
        line("obs running", False, "OBS is not running — launch it, then re-check")

    line("ffmpeg", bool(shutil.which("ffmpeg")), shutil.which("ffmpeg") or "not found")
    print("\n" + ("All green. Ready to record." if ok else "Fix the XX rows above first."))
    return 0 if ok else 1


# --------------------------------------------------------------------------- #
# The control server — what the Lua theme talks to
# --------------------------------------------------------------------------- #
@dataclass
class Session:
    out_dir: Path
    difficulty: str
    dry_run: bool = False
    obs: object = None
    scene: str | None = None
    calibrated: bool = False
    postprocess: bool = True
    crop: tuple | None = None
    crop_done: bool = False
    songs: list = field(default_factory=list)      # completed: {index,title,path}
    current: dict | None = None
    done: threading.Event = field(default_factory=threading.Event)
    failed: str | None = None
    lock: threading.Lock = field(default_factory=threading.Lock)


def detect_crop(path: Path) -> tuple[int, int, int, int] | None:
    """Find the game's actual content box inside the recording.

    Window capture pads the frame with black to the right and bottom (the window's
    backing surface is larger than the game's GL viewport, and no amount of arguing
    with the OBS transform changes that). Rather than model macOS's compositor, just
    measure it.

    NOTE the limit=24. OBS writes limited-range video where black is Y=16, so
    cropdetect's default limit of 24/255 *in full-range terms* reads those pixels as
    content and reports no border at all. This cost an embarrassing amount of time.
    """
    out = subprocess.run(
        ["ffmpeg", "-hide_banner", "-ss", "20", "-t", "8", "-i", str(path),
         "-vf", "cropdetect=limit=24:round=2:reset=0", "-f", "null", "-"],
        capture_output=True, text=True).stderr
    boxes = re.findall(r"crop=(\d+):(\d+):(\d+):(\d+)", out)
    if not boxes:
        return None
    w, h, x, y = (int(v) for v in boxes[-1])

    # Sanity guard. These songs are dark — a night-city background with black sky in
    # the corners — and cropdetect will happily call real gameplay a black bar. When
    # it did, the frame got cropped into the content AND stretched back to 16:9.
    # Any "border" bigger than a few percent is cropdetect being fooled, not a border.
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v",
         "-show_entries", "stream=width,height", "-of", "csv=p=0:s=x", str(path)],
        capture_output=True, text=True).stdout.strip()
    fw, fh = (int(v) for v in probe.split("x"))
    if w < fw * 0.95 or h < fh * 0.95:
        return None
    return w, h, x, y


def finalize(src: Path, dst: Path, crop: tuple | None) -> str:
    """Scale to 1080p and transcode to something YouTube actually wants: H.264 + a
    single AAC track (OBS emits HEVC and two identical audio tracks). Hardware
    encoder, so this costs seconds, not minutes.

    `crop` is decided ONCE per session and reused for every song. Detecting it per
    song means each video gets framed slightly differently depending on how dark its
    background happens to be — which is exactly the bug this signature exists to
    prevent."""
    vf = "scale=1920:1080:flags=lanczos"
    note = "no crop"
    if crop:
        w, h, x, y = crop
        vf = f"crop={w}:{h}:{x}:{y},scale=1920:1080:flags=lanczos"
        note = f"crop {w}x{h}+{x}+{y}"

    r = subprocess.run(
        ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", str(src),
         "-map", "0:v:0", "-map", "0:a:0",          # drop OBS's duplicate audio track
         "-vf", vf,
         "-c:v", "h264_videotoolbox", "-b:v", "12M",
         "-c:a", "aac", "-b:a", "192k",
         "-movflags", "+faststart", str(dst)],
        capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"ffmpeg finalize failed: {r.stderr[-300:]}")
    src.unlink()
    return note


def slugify(title: str) -> str:
    """Filesystem-safe, but keeps unicode — one of the songs is titled 消えてゆく
    and mangling that into '???' would be worse than a few non-ASCII bytes."""
    s = re.sub(r'[/\\:*?"<>|]', "-", title).strip()
    return re.sub(r"\s+", " ", s)


class Handler(BaseHTTPRequestHandler):
    session: Session = None   # set by serve()

    def log_message(self, *a):
        pass   # the default logger spams stderr with one line per request

    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        q = {k: v[0] for k, v in urllib.parse.parse_qs(u.query).items()}
        s = Handler.session
        try:
            if u.path == "/song-start":
                self._song_start(s, q)
            elif u.path == "/song-end":
                self._song_end(s, q)
            elif u.path == "/done":
                print(f"\n[queue] complete — {len(s.songs)} songs recorded")
                s.done.set()
            else:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Length", "2")
            self.end_headers()
            self.wfile.write(b"ok")
        except Exception as e:
            s.failed = f"{type(e).__name__}: {e}"
            print(f"\n[error] {s.failed}")
            s.done.set()
            try:
                self.send_error(500)
            except Exception:
                pass

    def _song_start(self, s: Session, q: dict):
        title = q.get("title", "unknown")
        idx, total = q.get("index", "?"), q.get("total", "?")
        print(f"[{idx}/{total}] {title} ({q.get('difficulty')}, meter {q.get('meter')}) … ", end="", flush=True)

        with s.lock:
            s.current = q
            if s.dry_run:
                print("recording (DRY RUN)")
                return

            # First song: the game window now exists, so bind OBS to it. Doing this
            # here (rather than at launch) is the whole point — the game is blocked
            # on this request, so it cannot start playing before the frame is right.
            if not s.calibrated and s.scene:
                print()
                print(f"  calibrating: {calibrate_obs(s.obs, s.scene)}")
                s.calibrated = True
                print(f"[{idx}/{total}] {title} … ", end="", flush=True)

            s.obs.start_record()
            # Do not trust the ack — poll until OBS says the output is actually
            # live. This request is what the game is blocking on, so the cost of
            # waiting here is exactly the cost of correctness.
            for _ in range(100):          # 10s ceiling
                if s.obs.get_record_status().output_active:
                    break
                time.sleep(0.1)
            else:
                raise RuntimeError("OBS did not start recording within 10s")
            print("recording")

    def _song_end(self, s: Session, q: dict):
        with s.lock:
            cur = s.current or {}
            time.sleep(TAIL_SECONDS)     # let the outro breathe
            if s.dry_run:
                print(f"        -> stopped (DRY RUN)")
                s.songs.append({"index": cur.get("index"), "title": cur.get("title"), "path": None})
                return

            res = s.obs.stop_record()
            src = Path(res.output_path)   # StopRecord hands back the file it wrote
            for _ in range(50):           # OBS finalizes the container after the ack
                if src.exists() and src.stat().st_size > 0:
                    break
                time.sleep(0.1)

            n = int(cur.get("index", len(s.songs) + 1))
            name = f"{n:02d} - {slugify(cur.get('title', 'song'))} ({s.difficulty}).mp4"
            dst = s.out_dir / name
            s.out_dir.mkdir(parents=True, exist_ok=True)

            if s.postprocess:
                if not s.crop_done:          # decide the framing once, on song 1
                    s.crop = detect_crop(src)
                    s.crop_done = True
                note = finalize(src, dst, s.crop)
            else:
                shutil.move(str(src), str(dst.with_suffix(src.suffix)))
                dst, note = dst.with_suffix(src.suffix), "raw"

            mb = dst.stat().st_size / 1e6
            print(f"        -> {name}  ({mb:.0f} MB, {note})")
            s.songs.append({"index": n, "title": cur.get("title"), "path": str(dst)})
            s.current = None


def serve(session: Session) -> ThreadingHTTPServer:
    Handler.session = session
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


# --------------------------------------------------------------------------- #
# record
# --------------------------------------------------------------------------- #
def build_queue(pack: str, difficulty: str, only: list[str] | None) -> list[tuple[str, str]]:
    pack_dir = SONGS_DIR / pack
    if not pack_dir.is_dir():
        raise SystemExit(f"No pack at {pack_dir}")

    entries = []
    for song_dir in sorted(p for p in pack_dir.iterdir() if p.is_dir()):
        if not any(song_dir.glob("*.sm")) and not any(song_dir.glob("*.ssc")):
            continue
        if only and song_dir.name not in only:
            continue
        # StepMania's VFS path, which is what song:GetSongDir() returns: rooted at
        # /Songs, with a trailing slash. Must match exactly or the Lua can't find it.
        entries.append((f"/Songs/{pack}/{song_dir.name}/", difficulty))

    if not entries:
        raise SystemExit(f"No songs matched in {pack_dir}")

    QUEUE.parent.mkdir(parents=True, exist_ok=True)
    QUEUE.write_text("".join(f"{d}\t{diff}\n" for d, diff in entries), encoding="utf-8")
    return entries


def cmd_record(args):
    difficulty = args.difficulty
    if difficulty not in DIFFICULTIES:
        raise SystemExit(f"--difficulty must be one of {', '.join(DIFFICULTIES)}")

    out_dir = Path(args.out).expanduser()
    entries = build_queue(args.pack, difficulty, args.only)

    print(f"stepcapture record\n" + "-" * 60)
    print(f"  pack       : {args.pack}")
    print(f"  difficulty : {difficulty}")
    print(f"  songs      : {len(entries)}")
    print(f"  output     : {out_dir}")
    print(f"  mode       : {'DRY RUN (no OBS)' if args.dry_run else 'recording'}")
    print()

    session = Session(out_dir=out_dir, difficulty=difficulty, dry_run=args.dry_run,
                      scene=args.scene, postprocess=not args.no_postprocess)

    if not args.dry_run:
        if not is_running("OBS"):
            print("  launching OBS…")
            subprocess.Popen([str(OBS_BIN)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            time.sleep(8)
        session.obs = obs_connect()
        if session.obs.get_record_status().output_active:
            raise SystemExit("OBS is already recording. Stop it and re-run.")
        if args.scene:
            session.obs.set_current_program_scene(args.scene)
        print(f"  OBS        : connected, scene '{session.obs.get_scene_list().current_program_scene_name}'\n")

    srv = serve(session)

    if is_running("ITGmania"):
        raise SystemExit("ITGmania is already running. Quit it first — the recording "
                         "run must start with the patched preferences.")

    print(f"  prefs      : {patch_prefs()}")

    # Drop macOS's restored window geometry so the window is sized purely by our
    # prefs. Without this the game draws its 1600x900 viewport into whatever larger
    # window was restored from last time, and the capture carries dead black margins.
    for d in SAVED_STATE.glob("*ITGmania*.savedState"):
        shutil.rmtree(d, ignore_errors=True)

    # --theme is a real command-line argument (StepMania.cpp), unlike the Theme
    # preference, which is game-specific and lives in [Game-dance].
    game = subprocess.Popen([str(ITG_BIN), f"--theme={THEME_NAME}"],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    # Watchdog: total runtime of the pack, plus generous slack for load screens.
    budget = 300 + sum(180 for _ in entries)
    try:
        finished = session.done.wait(timeout=budget)
        if not finished:
            print(f"\n[timeout] no /done after {budget}s — giving up")
    except KeyboardInterrupt:
        print("\n[interrupt] shutting down")
    finally:
        srv.shutdown()
        if not session.dry_run and session.obs:
            try:
                if session.obs.get_record_status().output_active:
                    session.obs.stop_record()
            except Exception:
                pass
        if game.poll() is None:
            game.send_signal(signal.SIGTERM)
            try:
                game.wait(timeout=10)
            except subprocess.TimeoutExpired:
                game.kill()
        # Only after the game is fully dead — it rewrites Preferences.ini on exit,
        # so restoring any earlier would just get stomped.
        print(f"\n  prefs      : {restore_prefs()}")

    print("\n" + "-" * 60)
    for s in session.songs:
        print(f"  {s['index']:>2}. {s['title']}")
    print(f"\n{len(session.songs)}/{len(entries)} recorded -> {out_dir}")
    if session.failed:
        print(f"FAILED: {session.failed}")
        return 1
    return 0 if len(session.songs) == len(entries) else 1


def main():
    p = argparse.ArgumentParser(prog="stepcapture", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("install", help="install the theme, prefs, and enable obs-websocket")
    sub.add_parser("check", help="verify the setup")

    r = sub.add_parser("record", help="record a pack")
    r.add_argument("--pack", required=True, help="pack folder name under ITGmania/Songs")
    r.add_argument("--difficulty", default="Challenge", help=f"one of: {', '.join(DIFFICULTIES)}")
    r.add_argument("--out", default="~/Desktop/gameplay", help="where to put the videos")
    r.add_argument("--scene", help="OBS scene to switch to before recording")
    r.add_argument("--only", nargs="+", metavar="SONGDIR",
                   help="record only these song folders (for a one-song dry run)")
    r.add_argument("--no-postprocess", action="store_true",
                   help="keep OBS's raw file — skip the crop/scale/H.264 pass")
    r.add_argument("--dry-run", action="store_true",
                   help="drive ITGmania but never touch OBS — proves the queue and "
                        "the song-start/song-end signalling work")

    args = p.parse_args()
    return {"install": cmd_install, "check": cmd_check, "record": cmd_record}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main() or 0)
