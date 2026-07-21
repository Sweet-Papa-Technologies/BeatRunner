"""ledger.py — per-call cost telemetry (REQ-R2-COST-01/02).

We instrument before we optimize. Every model call and every unit of metered
compute appends one JSON line to `build/<song>/cost_ledger.jsonl`, carrying the
stage, the song, the difficulty, the attempt number, the model string the call
ACTUALLY used (not the one config claims), the token counts split by modality,
the latency, and the dollars computed from `pricing.py`.

Two design choices worth stating:

  * **Ambient context, not threaded parameters.** The call sites that know the
    stage/song/difficulty (design.py, adapter.py, analyze.py) are far from the
    call site that knows the tokens (vertex.py). Threading four extra arguments
    through the LLMClient protocol would change every backend's signature and
    every fake in the tests. A contextvar stack keeps the seam at one place:
    `with ledger.stage("designer", song=..., difficulty=..., attempt=n): ...`.

  * **Never silently drop an entry.** If no stage context is active the call is
    still recorded, under stage "unattributed" in `build/_unattributed/`. An
    un-instrumented call path showing up as a mystery line in a report is the
    behaviour we want; a call that costs money and leaves no trace is what got
    us here.

Recording is best-effort with respect to the pipeline: a ledger write failure
warns and continues rather than killing a chart mid-batch.
"""
from __future__ import annotations

import contextvars
import json
import os
import threading
import time
from contextlib import contextmanager
from pathlib import Path

from . import config, pricing

LEDGER_FILENAME = "cost_ledger.jsonl"
LEDGER_SCHEMA_VERSION = 1

# Set BEATFORGE_COST_LEDGER=0 to disable writes entirely (used by tests that
# don't want stray files, and by anyone who genuinely does not want the record).
_ENABLED_DEFAULT = os.environ.get("BEATFORGE_COST_LEDGER", "1") not in ("0", "false", "")

_WRITE_LOCK = threading.Lock()

_CTX: contextvars.ContextVar[dict] = contextvars.ContextVar(
    "beatforge_ledger_ctx", default={})

# Test/aggregation hook: when set, entries are also appended here in memory.
_SINK: list[dict] | None = None


# --------------------------------------------------------------------------- #
# Context
# --------------------------------------------------------------------------- #
@contextmanager
def stage(name: str, *, song: str | None = None, difficulty: str | None = None,
          attempt: int | None = None, **extra):
    """Attribute every model call made inside this block to (stage, song, ...).

    Nesting inherits: an inner `stage("critic")` inside an outer
    `stage(song="x")` keeps the song. Inner values win on conflict.
    """
    parent = _CTX.get()
    merged = dict(parent)
    merged["stage"] = name
    for k, v in (("song", song), ("difficulty", difficulty), ("attempt", attempt)):
        if v is not None:
            merged[k] = v
    merged.update({k: v for k, v in extra.items() if v is not None})
    token = _CTX.set(merged)
    try:
        yield merged
    finally:
        _CTX.reset(token)


def current() -> dict:
    return dict(_CTX.get())


def enabled() -> bool:
    return _ENABLED_DEFAULT


# --------------------------------------------------------------------------- #
# Paths
# --------------------------------------------------------------------------- #
def ledger_dir(song: str | None) -> Path:
    base = config.TRACK_CATALOGUE.get(song, song) if song else None
    return config.COST_DIR / (base or "_unattributed")


def ledger_path(song: str | None) -> Path:
    return ledger_dir(song) / LEDGER_FILENAME


def all_ledgers() -> list[Path]:
    if not config.COST_DIR.exists():
        return []
    return sorted(config.COST_DIR.glob(f"*/{LEDGER_FILENAME}"))


def read_ledger(path: str | Path) -> list[dict]:
    """Read one JSONL ledger. Malformed lines are skipped with a warning rather
    than aborting a report — a truncated final line (killed batch) is common."""
    out: list[dict] = []
    p = Path(path)
    if not p.exists():
        return out
    for i, line in enumerate(p.read_text().splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            print(f"[ledger] WARNING: {p}:{i} is not valid JSON; skipped")
    return out


# --------------------------------------------------------------------------- #
# Usage extraction — provider response -> our modality split
# --------------------------------------------------------------------------- #
def usage_from_vertex(resp: dict) -> dict:
    """Pull `usageMetadata` out of a Vertex generateContent response.

    Vertex reports prompt tokens as a total PLUS a per-modality breakdown in
    `promptTokensDetails` ([{modality: "AUDIO", tokenCount: N}, ...]). Audio has
    to come from that breakdown — the total alone cannot answer autopsy
    hypothesis #1, which is the whole reason this function exists.

    `cachedContentTokenCount` is a SUBSET of promptTokenCount; we subtract it out
    of the billable text so a cache hit shows up as a discount, not double-billing.
    """
    um = (resp or {}).get("usageMetadata") or {}
    total_in = int(um.get("promptTokenCount", 0) or 0)
    out = int(um.get("candidatesTokenCount", 0) or 0)
    thinking = int(um.get("thoughtsTokenCount", 0) or 0)
    cached = int(um.get("cachedContentTokenCount", 0) or 0)

    by_modality: dict[str, int] = {}
    for d in um.get("promptTokensDetails") or []:
        mod = str(d.get("modality", "UNKNOWN")).upper()
        by_modality[mod] = by_modality.get(mod, 0) + int(d.get("tokenCount", 0) or 0)
    audio = by_modality.get("AUDIO", 0)
    # Text = everything in the prompt that isn't audio and isn't served from
    # cache. If the modality breakdown is absent (older API surface), fall back to
    # "all non-cached prompt tokens are text" and mark it so the report can say so.
    if by_modality:
        text = max(0, total_in - audio - cached)
        modality_known = True
    else:
        text = max(0, total_in - cached)
        modality_known = False
    return {
        "input_tokens": total_in,
        "text_tokens": text,
        "audio_tokens": audio,
        "cached_tokens": cached,
        "output_tokens": out,
        "thinking_tokens": thinking,
        "modality_breakdown_available": modality_known,
        "raw_modalities": by_modality,
    }


def usage_from_openai(resp: dict) -> dict:
    """OpenAI-compatible `usage`. Most local servers report only prompt/completion
    totals; audio tokens are folded into prompt_tokens with no split available."""
    u = (resp or {}).get("usage") or {}
    total_in = int(u.get("prompt_tokens", 0) or 0)
    out = int(u.get("completion_tokens", 0) or 0)
    details = u.get("prompt_tokens_details") or {}
    audio = int(details.get("audio_tokens", 0) or 0)
    cached = int(details.get("cached_tokens", 0) or 0)
    ctd = u.get("completion_tokens_details") or {}
    thinking = int(ctd.get("reasoning_tokens", 0) or 0)
    return {
        "input_tokens": total_in,
        "text_tokens": max(0, total_in - audio - cached),
        "audio_tokens": audio,
        "cached_tokens": cached,
        "output_tokens": out,
        "thinking_tokens": thinking,
        "modality_breakdown_available": bool(details),
        "raw_modalities": {"AUDIO": audio} if audio else {},
    }


# --------------------------------------------------------------------------- #
# Recording
# --------------------------------------------------------------------------- #
def record_model_call(
    *, provider: str, model: str, usage: dict, latency_s: float,
    prompt_bytes: int = 0, audio_attached: bool = False,
    audio_path: str | None = None, audio_bytes: int = 0,
    thinking_level: str | None = None, error: str | None = None,
    ctx: dict | None = None,
) -> dict:
    """Append one model-call entry. Returns the entry (also handy for tests)."""
    c = dict(ctx if ctx is not None else _CTX.get())
    cost = pricing.cost_usd(
        model,
        text_in=usage.get("text_tokens", 0),
        audio_in=usage.get("audio_tokens", 0),
        cached_in=usage.get("cached_tokens", 0),
        out=usage.get("output_tokens", 0),
        thinking=usage.get("thinking_tokens", 0),
    )
    entry = {
        "schema": LEDGER_SCHEMA_VERSION,
        "kind": "model",
        "ts": time.time(),
        "stage": c.get("stage", "unattributed"),
        "song": c.get("song"),
        "difficulty": c.get("difficulty"),
        "attempt": c.get("attempt"),
        "target": c.get("target"),               # stepmania | beatsaber | core
        "provider": provider,
        "model": model,                          # the string ACTUALLY sent
        "thinking_level": thinking_level,
        "input_tokens": usage.get("input_tokens", 0),
        "text_tokens": usage.get("text_tokens", 0),
        "audio_tokens": usage.get("audio_tokens", 0),
        "cached_tokens": usage.get("cached_tokens", 0),
        "output_tokens": usage.get("output_tokens", 0),
        "thinking_tokens": usage.get("thinking_tokens", 0),
        "modality_breakdown_available": usage.get("modality_breakdown_available", False),
        "latency_s": round(float(latency_s), 3),
        "prompt_bytes": int(prompt_bytes),
        "audio_attached": bool(audio_attached),
        "audio_file": os.path.basename(audio_path) if audio_path else None,
        "audio_bytes": int(audio_bytes),
        "cost_usd": cost,
        "pricing_as_of": pricing.PRICING_AS_OF,
        "error": error,
    }
    _append(entry)
    return entry


def record_compute(
    *, stage_name: str, song: str | None, backend: str, gpu: str | None,
    minutes: float, cache_hit: bool, estimated: bool = False,
    detail: dict | None = None,
) -> dict:
    """REQ-R2-COST-02: non-LLM compute (Demucs/madmom on Colab, or local CPU).

    `cache_hit=True` means no compute was provisioned at all — the entry exists
    precisely so a re-run visibly shows $0 analysis rather than showing nothing,
    which is indistinguishable from "we forgot to log it".
    `estimated=True` marks minutes the CLI could not report and we inferred.
    """
    gpu = gpu or "none"
    usd = 0.0 if cache_hit else pricing.gpu_cost_usd(gpu, minutes)
    entry = {
        "schema": LEDGER_SCHEMA_VERSION,
        "kind": "compute",
        "ts": time.time(),
        "stage": stage_name,
        "song": song,
        "difficulty": None,
        "attempt": None,
        "backend": backend,
        "gpu": gpu,
        "gpu_minutes": 0.0 if cache_hit else round(float(minutes), 4),
        "cache_hit": bool(cache_hit),
        "minutes_estimated": bool(estimated),
        "cost_usd": {"total": usd, "compute": usd, "rate_verified": False},
        "pricing_as_of": pricing.PRICING_AS_OF,
        "detail": detail or {},
    }
    _append(entry)
    return entry


def _append(entry: dict) -> None:
    if _SINK is not None:
        _SINK.append(entry)
    if not _ENABLED_DEFAULT:
        return
    try:
        d = ledger_dir(entry.get("song"))
        d.mkdir(parents=True, exist_ok=True)
        with _WRITE_LOCK:
            with open(d / LEDGER_FILENAME, "a") as f:
                f.write(json.dumps(entry) + "\n")
    except OSError as e:      # telemetry must never take down a batch
        print(f"[ledger] WARNING: could not write cost ledger: {e}")


# --------------------------------------------------------------------------- #
# Schema validation (REQ-R2-COST-01 accept: "unit test validates schema")
# --------------------------------------------------------------------------- #
MODEL_ENTRY_REQUIRED = (
    "schema", "kind", "ts", "stage", "song", "difficulty", "attempt", "provider",
    "model", "input_tokens", "text_tokens", "audio_tokens", "cached_tokens",
    "output_tokens", "thinking_tokens", "latency_s", "prompt_bytes",
    "audio_attached", "cost_usd", "pricing_as_of",
)
COMPUTE_ENTRY_REQUIRED = (
    "schema", "kind", "ts", "stage", "song", "backend", "gpu", "gpu_minutes",
    "cache_hit", "cost_usd", "pricing_as_of",
)


def validate_entry(entry: dict) -> list[str]:
    """Return a list of schema problems; empty means the entry is well-formed."""
    problems: list[str] = []
    kind = entry.get("kind")
    if kind not in ("model", "compute"):
        return [f"unknown kind {kind!r}"]
    required = MODEL_ENTRY_REQUIRED if kind == "model" else COMPUTE_ENTRY_REQUIRED
    for k in required:
        if k not in entry:
            problems.append(f"missing field {k!r}")
    cost = entry.get("cost_usd")
    if not isinstance(cost, dict) or "total" not in cost:
        problems.append("cost_usd must be a dict containing 'total'")
    elif not isinstance(cost["total"], (int, float)) or cost["total"] < 0:
        problems.append("cost_usd.total must be a non-negative number")
    if kind == "model":
        for k in ("input_tokens", "output_tokens", "audio_tokens", "cached_tokens",
                  "thinking_tokens", "text_tokens"):
            v = entry.get(k)
            if not isinstance(v, int) or v < 0:
                problems.append(f"{k} must be a non-negative int (got {v!r})")
        # audio tokens without an attached audio part is a contradiction that
        # would silently corrupt hypothesis #1.
        if entry.get("audio_tokens", 0) > 0 and not entry.get("audio_attached"):
            problems.append("audio_tokens > 0 but audio_attached is False")
    return problems


# --------------------------------------------------------------------------- #
# Test helper
# --------------------------------------------------------------------------- #
@contextmanager
def capture(write: bool = False):
    """Collect entries in memory (optionally suppressing disk writes)."""
    global _SINK, _ENABLED_DEFAULT
    prev_sink, prev_enabled = _SINK, _ENABLED_DEFAULT
    sink: list[dict] = []
    _SINK = sink
    _ENABLED_DEFAULT = write
    try:
        yield sink
    finally:
        _SINK, _ENABLED_DEFAULT = prev_sink, prev_enabled


__all__ = ["stage", "current", "ledger_path", "ledger_dir", "all_ledgers",
           "read_ledger", "record_model_call", "record_compute",
           "usage_from_vertex", "usage_from_openai", "validate_entry", "capture",
           "LEDGER_FILENAME", "LEDGER_SCHEMA_VERSION"]
