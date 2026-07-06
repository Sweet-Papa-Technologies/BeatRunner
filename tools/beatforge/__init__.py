"""BEATFORGE — music-aware track & chart pipeline for OVERDRIVE.

Deterministic-first: all timing truth (tempo, beat grid, onsets, offsets) comes
from DSP (Workstream B) and is cached as JSON. Gemini Flash (Workstream C) hears
the audio and designs charts by *selecting DSP-provided candidates by ID* — it
never emits a raw timestamp. See IMPROVE.MD for the full spec.
"""

__version__ = "1.0.0"
