# stepcapture

Record autoplay gameplay of a StepMania pack with OBS — one video per song,
unattended. Built to turn the *SweetPapa Dream Mix — Founder Mix* pack into 13
YouTube-ready MP4s without a human touching the game.

```bash
python3 stepcapture.py install     # one-time
python3 stepcapture.py check       # verify
python3 stepcapture.py record --pack "SweetPapa Dream Mix - Founder Mix" \
                              --difficulty Challenge \
                              --out ~/Desktop/gameplay
```

## How it works

ITGmania runs a purpose-built theme (`theme/`, installed to
`ITGmania/Themes/StepCapture`) that inherits *everything* visual from Simply Love
and changes only the flow:

```
ScreenStepCapture -> ScreenGameplay -> ScreenStepCapture -> ...
```

The title menu, song wheel, and evaluation screen are never visited. On each song
boundary the theme calls this script's local HTTP server via `NETWORK:HttpRequest`,
and the server drives OBS over obs-websocket.

The load-bearing detail: **`/song-start` does not return until OBS confirms it is
recording.** The theme waits on the HTTP response before entering gameplay, so the
cut is frame-accurate rather than sleep-and-pray.

```
ITGmania (Lua)              stepcapture.py            OBS
--------------              --------------            ---
/song-start     ---------->  StartRecord   ---------->
                             poll until outputActive
                <----------  200 OK
enter gameplay
(autoplay bot plays the chart)
/song-end       ---------->  wait 2.5s, StopRecord --->
                             rename -> "01 - Title (Challenge).mkv"
```

## Things that are not obvious (and cost real time to find)

**`--Type=Recording` does not give you a private preferences section.** It looked
like the clean way to keep recording settings out of the user's config. It isn't:
`Theme` is a *game-specific* preference living in `[Game-dance]`, which is read
regardless of `--Type`; and ITGmania **rewrites `Preferences.ini` wholesale on
exit**, deleting any section it doesn't recognise. A `[Recording]` block does not
survive one run. We use the `--theme=` CLI arg instead, and patch/restore
`[Options]` around the run.

**`NETWORK:HttpRequest` has a URL allowlist.** It defaults to
`*.groovestats.com,*.itgmania.com` and *silently refuses* everything else — the
request just never fires. `localhost` must be added to `HttpAllowHosts`. That and
`HttpEnabled` are `PreferenceType::Immutable`: read once at startup, unsettable
from Lua. They have to be in the ini before launch, which is the only reason this
tool touches preferences at all.

**`AutoPlay=Autoplay`, not `Cpu`.** `Cpu` is the arcade AI opponent and it misses
notes on purpose. `Autoplay` is the one that plays a perfect run.

**`GAMESTATE:Reset()` leaves PlayMode invalid.** Enter `ScreenGameplay` after a
reset without `SetCurrentPlayMode('PlayMode_Regular')` and the game hard-crashes
with `Invalid PlayMode: 7`. Normally `ScreenSelectPlayMode` sets it; we skip that
screen, so we set it ourselves.

**Don't guess the `StepsType` enum's casing.** `song:GetOneSteps(StepsType_Dance_Single, …)`
fails with a bare `Expected StepsType; got nil` — the enum globals are built at
runtime. `StepCapture.FindSteps()` iterates `song:GetAllSteps()` and compares the
values the game itself returns, which can't be spelled wrong.

**`GAMESTATE:SetMasterPlayerNumber` does not exist.** `JoinPlayer(PLAYER_1)` sets
the master player already.

**Don't call `SCREENMAN:SetNewScreen()` from a screen's first Init/On pass.** The
runner sleeps a frame first. Doing it during construction is a reliable crash.

### …and on the OBS side

**Application capture and display capture both give you the whole screen.** The
game floats inside it with the menu bar and desktop visible. Only *window* capture
(`type: 1`) crops to the game. The window id changes every launch, so `calibrate_obs()`
re-binds it at the start of each session rather than it being something you set up
once in the OBS UI.

**Match the window on the owning app, not the title.** OBS lists windows as
`[<app>] <title>`, and ITGmania's window title is literally `StepMania` — a
substring match on `"stepmania"` happily selected a **Finder window showing the
`fofo-stepmania-songs` folder** and recorded that instead. Match on `[itgmania]`.

**macOS restores window geometry across launches.** The game will render its
1600x900 viewport into whatever larger window was restored from last time, leaving
dead black margins in the capture. `record` deletes
`~/Library/Saved Application State/*ITGmania*` before launching.

**A 1920x1080 window does not fit on a 1080-tall display.** The menu bar and title
bar take their cut and macOS silently clamps it to 1920x1009 — a 1.90 aspect that
letterboxes. The game renders at 1600x900 and OBS upscales the output to 1080p.

**`cropdetect` will tell you there are no black bars when there are.** OBS writes
limited-range video where black is **Y=16**, and cropdetect's default `limit=24`
reads those pixels as content. Use `limit=24` explicitly against the *right* range
— or better, measure with `signalstats` (`mean Y = 16.00` is pure black). This is
why `detect_crop()` exists and why the pipeline crops in post rather than trusting
the OBS transform.

## The finalize pass

OBS emits HEVC with two identical audio tracks and possible black padding. After
each song, `finalize()`:

1. `cropdetect`s the real content box and crops to it,
2. scales to exactly 1920x1080 (lanczos),
3. transcodes to **H.264 + a single AAC track** via `h264_videotoolbox` (hardware —
   seconds, not minutes), `+faststart`.

The result is what YouTube actually wants. `--no-postprocess` keeps OBS's raw file.

## Preferences safety

`record` backs up `Preferences.ini`, patches `[Options]`, and restores the backup
**after the game has fully exited** (it rewrites prefs on exit, so restoring any
earlier gets stomped). If a run dies mid-way the backup is left in place, and the
next run rolls back to it rather than backing up its own patched file. `check`
reports a stale backup.

## Setup steps that cannot be scripted

1. **Screen Recording permission for OBS** — System Settings → Privacy & Security →
   Screen Recording. macOS SIP-protects the TCC database; `tccutil` can only
   *reset* grants, never create them. An MDM profile is the only alternative.
2. **One OBS scene** containing a single **macOS Screen Capture** source, method
   = *Application*, application = *ITGmania*, with audio capture enabled. On
   macOS 13+ that source captures the app's audio too — no BlackHole or Loopback
   needed.

Pass `--scene "Name"` to `record` to select it, or leave it on the current scene.

## Flags

| Flag | Purpose |
|---|---|
| `--pack` | pack folder name under `ITGmania/Songs` |
| `--difficulty` | `Beginner` / `Easy` / `Medium` / `Hard` / `Challenge` |
| `--out` | where the videos land |
| `--scene` | OBS scene to switch to first |
| `--only "Song Dir" …` | record just these songs — use for a one-song trial |
| `--dry-run` | drive ITGmania but never touch OBS. Proves the queue and the song-start/song-end handshake work without needing screen-recording permission. Start here. |

## Uploading

Do **not** push these to YouTube with the Data API. Videos uploaded from an
un-audited API project are locked to private *with no appeal* — they're burned.
Drag the finished MP4s into YouTube Studio (Studio uploads aren't subject to the
lock), then use the API for metadata only (`videos.update` / `playlistItems.insert`
/ `thumbnails.set`), which is cheap and carries no lock risk.
