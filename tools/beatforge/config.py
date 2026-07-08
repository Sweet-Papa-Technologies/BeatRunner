"""config.py — ALL beatforge tunables in one place (spec §2, §3, §6).

Models, budgets, thresholds, paths, difficulty table. Nothing tunable should
live outside this file.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

# --------------------------------------------------------------------------- #
# Paths
# --------------------------------------------------------------------------- #
# repo root = three levels up from this file: tools/beatforge/config.py -> repo
REPO_ROOT = Path(__file__).resolve().parents[2]
TRACKS_SRC = REPO_ROOT / "assets" / "tracks"
TRACKS_PUB = REPO_ROOT / "public" / "assets" / "tracks"
MAPS_PUB = REPO_ROOT / "public" / "maps"
BUILD_DIR = REPO_ROOT / "build" / "analysis"
STEPMANIA_DIR = REPO_ROOT / "build" / "stepmania"
PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"
SCHEMAS_DIR = Path(__file__).resolve().parent / "schemas"
JOBS_DIR = Path(__file__).resolve().parent / "jobs"

# --------------------------------------------------------------------------- #
# Models & API (spec §3 — verified against `assetforge models` for project
# `sweet-papa-technologies` @ us-central1 on 2026-07-05).
# --------------------------------------------------------------------------- #
#
# Gemini 3.5 Flash — the audio-analysis brain of this whole pipeline. VERIFIED
# LIVE against the Vertex project on 2026-07-05 (spec §3 mandates verify-before-
# hardcode; do NOT trust the assetforge cheat-sheet, whose static text predates
# the 3.5 release and omits this id):
#   * `gemini-3.5-flash` :generateContent -> 200 OK, project HAS access.
#   * Reachable ONLY from location=`global` on the `v1beta1` endpoint. This is
#     why the assetforge `models` list (which probes regional us-central1) misses
#     it. vertex.py routes any `gemini-3*` id to global/v1beta1 automatically.
#   * Accepts AUDIO input (inlineData audio part -> usage modality=AUDIO). It
#     actually hears the track: on overdrive_pulse it returned ~115 BPM + "clear
#     kick" from audio alone.
#   * Supports reasoning via `generationConfig.thinkingConfig.thinkingLevel`
#     (minimal|low|medium|high); high produced thoughtsTokenCount>0.
GEMINI_MODEL = os.environ.get("BEATFORGE_GEMINI_MODEL", "gemini-3.5-flash")

# thinking_level (spec §3): Gemini 3.x uses `thinkingLevel`; the pipeline requests
# "high" (full thinking power, user directive). vertex.py emits the correct
# request shape for the model family GEMINI_MODEL belongs to.
THINKING_LEVEL = os.environ.get("BEATFORGE_THINKING_LEVEL", "high")

# --------------------------------------------------------------------------- #
# LLM backend selection — the designer/critic/A&R model is swappable so an
# alternative audio-capable model (e.g. a self-hosted Gemma 4 12B on an
# OpenAI-compatible server) can be dropped in and benchmarked against Gemini 3.5
# Flash. Lyria (music generation) always stays on Vertex.
#   BEATFORGE_LLM_BACKEND = "gemini" (Vertex, default) | "openai" (OpenAI-compatible)
# --------------------------------------------------------------------------- #
LLM_BACKEND = os.environ.get("BEATFORGE_LLM_BACKEND", "gemini")
# OpenAI-compatible server (vLLM/llama.cpp/etc). Point at the local Gemma server:
#   export BEATFORGE_LLM_BACKEND=openai
#   export BEATFORGE_OPENAI_BASE_URL=http://192.168.1.99:8000/v1
#   export BEATFORGE_OPENAI_MODEL=<model id from GET /v1/models>
OPENAI_BASE_URL = os.environ.get("BEATFORGE_OPENAI_BASE_URL", "http://192.168.1.99:8000/v1")
OPENAI_MODEL = os.environ.get("BEATFORGE_OPENAI_MODEL", "gemma-4-12b")
OPENAI_API_KEY = os.environ.get("BEATFORGE_OPENAI_API_KEY", "not-needed")
# Audio is sent as an OpenAI `input_audio` content part; base64 in this format.
# The tracks are .ogg — transcoded to this on the fly (wav is universally decoded;
# set to "ogg" to send as-is if your server accepts it).
OPENAI_AUDIO_FORMAT = os.environ.get("BEATFORGE_OPENAI_AUDIO_FORMAT", "wav")
# Downsample the audio sent to a local model to keep the audio-token count (and
# thus KV-cache / VRAM) small. Full 44.1kHz stereo of a 2.5min song is ~25MB and
# balloons the context; 16kHz mono (~5MB) is plenty for tempo/onset perception
# and cut the RAM spill that makes a VRAM-starved 12B model crawl. 0 = leave as-is.
OPENAI_AUDIO_SR = int(os.environ.get("BEATFORGE_OPENAI_AUDIO_SR", "16000"))
OPENAI_AUDIO_MONO = os.environ.get("BEATFORGE_OPENAI_AUDIO_MONO", "1") not in ("0", "", "false")
# A full chart JSON is ~2.5-4k tokens; 8192 let a slow/looping local model run
# far past that and fill VRAM before timing out. 4096 fits any chart with margin
# and caps runaway generation. Raise if a dense chart ever truncates.
OPENAI_MAX_TOKENS = int(os.environ.get("BEATFORGE_OPENAI_MAX_TOKENS", "4096"))
# Per-request read timeout (s). Local 12B models are much slower than Gemini on
# the heavy designer call; raise for slow hardware, lower to fail fast.
OPENAI_TIMEOUT = int(os.environ.get("BEATFORGE_OPENAI_TIMEOUT", "300"))
# A little sampling temperature helps local models avoid the degenerate
# repetition loops that greedy (temp=0) decoding can fall into on long JSON.
OPENAI_TEMPERATURE = float(os.environ.get("BEATFORGE_OPENAI_TEMPERATURE", "0.7"))

# Music generation (Workstream A) — unchanged from tools/generate_overdrive_assets.py.
LYRIA_MODEL = os.environ.get("BEATFORGE_LYRIA_MODEL", "lyria-002")

# Vertex project / location / creds. Mirror assetforge's config so beatforge and
# assetforge share one service-account key.
VERTEX_PROJECT = os.environ.get("VERTEX_PROJECT", "sweet-papa-technologies")
VERTEX_LOCATION = os.environ.get("VERTEX_LOCATION", "us-central1")
ASSETFORGE_KEY = os.path.expanduser(
    os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "~/.assetforge/sa-key.json")
)

# --------------------------------------------------------------------------- #
# DSP analysis parameters (Workstream B). These are baked into the cache key, so
# changing any of them invalidates cached analysis (REQ-COMPUTE-04).
# --------------------------------------------------------------------------- #
ANALYSIS_SR = 22050          # mono analysis sample rate (matches diagnosis §0)
HOP_LENGTH = 256             # STFT hop (samples) -> ~11.6ms frames at 22050
N_FFT = 2048
# Tempo octave/metre candidates to disambiguate (REQ-DSP-02).
TEMPO_MULTIPLIERS = (0.5, 2.0 / 3.0, 0.75, 1.0, 4.0 / 3.0, 1.5, 2.0)
TEMPO_PRIOR_BAND = (84.0, 150.0)    # synthwave genre prior; tie-break target
# Log-Gaussian perceptual tempo prior (octaves): weights the alignment score so
# octave/metre errors (e.g. 258 vs 129 BPM) are suppressed without discarding a
# genuinely fast or slow track. Center ~ middle of the synthwave band.
TEMPO_PRIOR_CENTER = 120.0
TEMPO_PRIOR_SIGMA_OCT = 0.9
OFFSET_SWEEP_MS = 60.0       # ±60ms offset refinement (REQ-DSP-03)
OFFSET_STEP_MS = 1.0
ONSET_SNAP_MAX_MS = 35.0     # grid alignment tolerance (REQ-DSP-03/REQ-VAL-02)
SUSTAIN_MIN_BEATS = 1.0      # harmonic plateau >= 1 beat -> hold candidate
ONSET_COUNT_SANITY = (50, 400)  # sanity gate for a ~33s track (REQ-DSP-04)
BEAT_ANALYSIS_VERSION = "local_dsp_v1"  # bump to invalidate all caches

# --------------------------------------------------------------------------- #
# Compute backend (spec §3.5)
# --------------------------------------------------------------------------- #
DEFAULT_BACKEND = os.environ.get("BEATFORGE_BACKEND", "local")  # local | colab
COLAB_GPU = os.environ.get("BEATFORGE_COLAB_GPU", "T4")         # T4 | L4 | A100 | H100
COLAB_SESSION_PREFIX = "beatforge"

# --------------------------------------------------------------------------- #
# Generation loop (Workstream A)
# --------------------------------------------------------------------------- #
GEN_CANDIDATES_PER_ROUND = 4   # REQ-GEN-01 N
GEN_MAX_ROUNDS = 3             # REQ-GEN-01 K
GEN_SHIP_THRESHOLD = 8.0       # weighted scorecard ship threshold (REQ-GEN-03)
# Scorecard rubric weights (REQ-GEN-02). Keys must match schemas/scorecard.json.
GEN_RUBRIC_WEIGHTS = {
    "tempo_stability": 1.0,
    "transient_clarity": 1.5,
    "structural_contrast": 1.5,
    "intro_cleanliness": 1.0,
    "mix_punch": 1.0,
    "genre_fit": 1.0,
}
TARGET_LUFS = -14.0            # REQ-GEN-04
TARGET_TRUE_PEAK_DBTP = -1.0
MAX_LEADING_SILENCE_MS = 120.0
ENABLE_LONGER_TRACKS = False   # REQ-GEN-06 stretch, default off

# --------------------------------------------------------------------------- #
# Difficulty budgets (spec §6 — hard constraints enforced in Workstream D)
# --------------------------------------------------------------------------- #
DIFFICULTIES = ("casual", "standard", "overdrive")


@dataclass(frozen=True)
class DifficultyBudget:
    name: str
    min_gap_beats: float
    min_gap_ms: float
    finest_subdiv: float          # smallest legal grid step, in beats
    max_nps_4s: float             # max sustained notes-per-second over any 4s window
    jack_limit: int               # same-lane consecutive limit
    taps_during_hold: int         # allowed taps in OTHER lanes during a hold
    hold_len_beats: tuple         # (min, max) hold length in beats
    hold_share: tuple             # (min, max) fraction of events that are holds
    onset_align_min: float        # REQ-QA-01 alignment floor


BUDGETS = {
    "casual": DifficultyBudget(
        name="casual",
        min_gap_beats=1.0, min_gap_ms=350.0,
        finest_subdiv=1.0,
        max_nps_4s=2.0,
        jack_limit=2,
        taps_during_hold=0,
        hold_len_beats=(2.0, 8.0),
        hold_share=(0.10, 0.20),
        onset_align_min=0.80,   # sparse charts skip onsets, not miss them
    ),
    "standard": DifficultyBudget(
        name="standard",
        min_gap_beats=0.5, min_gap_ms=200.0,
        finest_subdiv=0.5,
        max_nps_4s=4.0,
        jack_limit=3,
        taps_during_hold=1,
        hold_len_beats=(1.0, 8.0),
        hold_share=(0.05, 0.15),
        onset_align_min=0.90,
    ),
    "overdrive": DifficultyBudget(
        name="overdrive",
        min_gap_beats=0.25, min_gap_ms=120.0,
        finest_subdiv=0.25,
        max_nps_4s=7.0,
        jack_limit=4,
        taps_during_hold=2,
        hold_len_beats=(1.0, 8.0),
        hold_share=(0.05, 0.12),
        onset_align_min=0.90,
    ),
}

# QA gate thresholds (spec §7)
LANE_BALANCE_RANGE = (0.22, 0.45)   # each lane 22-45% (REQ-QA-01)
MAX_REPAIR_FRACTION = 0.15          # >15% repaired -> chart fails (REQ-VAL-03)
DENSITY_ENERGY_SPEARMAN_MIN = 0.55  # REQ-QA-02
# REQ-QA-02 density-SHAPE gates (spearman/peak-in-drop/breathes) assume the track
# HAS dynamic contrast (build→drop). Uniform loops (the existing keep-the-hits
# tracks measure CV 0.04-0.08) cannot follow an energy curve that doesn't move —
# forcing it would make the designer fabricate contrast the music lacks. Tracks
# below this energy-curve CV are recorded `flat_track_exempt` for the shape gates
# (alignment/lane/NPS/hold/repair still fully enforced). Workstream A tracks,
# which are generated WITH contrast, clear this bar and get the full gate.
DENSITY_GATE_MIN_CV = 0.12
# The section-level shape gates (peak-in-drop, breathes) require the track to have
# ≥2 sections whose energy actually differs by at least this much (0..1 scale). A
# steady groove with bar-level oscillation but one uniform section does not, so
# those two gates exempt (the bar-level Spearman gate still applies).
SECTION_STRUCTURE_MIN_SPREAD = 0.15
CRITIC_SHIP_THRESHOLD = 7.0         # REQ-QA-04
DESIGN_MAX_ATTEMPTS = 3             # REQ-QA-03 re-prompt loop cap

# Playable window (mirrors make_overdrive_maps.py): events before beat 4 or after
# (duration - PLAYABLE_TAIL_S) are dropped (REQ-VAL-02).
FIRST_PLAYABLE_BEAT = 4.0
PLAYABLE_TAIL_S = 1.4

# Judgment windows — the contract from src/core/timing.ts DEFAULT_WINDOWS.
PERFECT_WINDOW_S = 0.05
GOOD_WINDOW_S = 0.12

# Catalogue (id -> source ogg basename). Mirrors src/game/tracks.ts.
TRACK_CATALOGUE = {
    "overdrive": "overdrive_pulse",
    "midnight": "midnight_run",
    "neon": "neon_nights",
    "groove": "sweetpapa_groove",
    "hope": "worth_the_hope",
}

# Song metadata for StepMania export (title/artist), mirrors src/game/tracks.ts.
TRACK_META = {
    "overdrive": ("Overdrive Pulse", "Sweet Papa & the Tones"),
    "midnight": ("Midnight Run", "Sweet Papa & the Tones"),
    "neon": ("Neon Nights", "Sweet Papa & the Tones"),
    "groove": ("Sweet Papa Groove", "Sweet Papa & the Tones"),
    "hope": ("Worth the Hope", "Sweet Papa Technologies"),
}


@dataclass
class RunOptions:
    """Runtime knobs threaded from the CLI into every stage."""
    backend: str = DEFAULT_BACKEND
    force: bool = False
    skip_gen: bool = True          # keep-the-hits default (REQ-GEN-05)
    allow_local_fallback: bool = False
    tracks: tuple = field(default_factory=lambda: tuple(TRACK_CATALOGUE))
    difficulties: tuple = DIFFICULTIES
    gpu: str = COLAB_GPU
    offline: bool = False          # skip all Vertex calls (fixture/test mode)
