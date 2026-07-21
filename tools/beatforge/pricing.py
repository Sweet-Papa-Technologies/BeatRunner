"""pricing.py — the checked-in price table the cost ledger bills against
(REQ-R2-COST-01).

Why a file and not a constant: the $80-for-30-songs number in the Round 2 brief
was unattributable because nothing in the pipeline ever converted tokens to
dollars. Cost has to be computed from a table that is *in the repo*, *dated*, and
*editable*, so that a number in a report can be re-derived months later and a
price change is a diff instead of a mystery.

Rates are USD per 1,000,000 tokens, per modality, because Gemini bills audio
input at a different rate from text input and that distinction is the entire
point of hypothesis #1 in the autopsy.

`verified` marks whether the rate was checked against the live Vertex pricing
page/SKU by a human. UNVERIFIED rates still produce numbers, but every report
that touches one carries a warning — a confidently-wrong dollar figure is worse
than an admittedly-uncertain one.

Note the spec asked for `config/pricing.py`. `beatforge/config` cannot be a
package because `beatforge/config.py` already exists (Python would not resolve
both), so the table lives here, next to it, and `config` re-exports nothing.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

# Date the rates below were last reviewed. Bump it when you touch a rate.
PRICING_AS_OF = "2026-07-21"

# IMPORTANT — endpoint affects the rate. Vertex charges ~10% more on non-global
# (regional) endpoints as of 2026-07-01. `vertex.py::_endpoint` routes every
# `gemini-3*` model to location=`global`, so the GLOBAL rates below are the ones
# beatforge actually pays. If that routing ever changes, these rates get ~10%
# worse and this comment is the reason why.

# Source of record for the Vertex rates (paste the page you checked, don't guess).
PRICING_SOURCE = "https://cloud.google.com/vertex-ai/generative-ai/pricing"


@dataclass(frozen=True)
class ModelPrice:
    """USD per 1e6 tokens, split by the modalities Vertex meters separately."""
    model: str
    text_in: float
    audio_in: float
    out: float
    # Cached input tokens (Vertex context caching) bill at a discount. If a model
    # has no caching SKU, leave this equal to text_in.
    cached_in: float = 0.0
    # Thinking/reasoning tokens. Gemini bills them as OUTPUT tokens; keeping the
    # field explicit means the ledger can attribute them separately even though
    # the rate matches `out`.
    thinking_out: float = 0.0
    verified: bool = False
    note: str = ""

    def __post_init__(self):
        # dataclass is frozen; use object.__setattr__ for the derived defaults.
        if self.cached_in == 0.0:
            object.__setattr__(self, "cached_in", round(self.text_in * 0.25, 6))
        if self.thinking_out == 0.0:
            object.__setattr__(self, "thinking_out", self.out)


# --------------------------------------------------------------------------- #
# The table.
# --------------------------------------------------------------------------- #
# gemini-3.5-flash is what the pipeline is CONFIGURED to use. Whether it is what
# the pipeline actually used is a question for the ledger, not for this file
# (autopsy hypothesis #4 exists because config lied once already).
TABLE: dict[str, ModelPrice] = {
    # VERIFIED 2026-07-21 against cloud.google.com/vertex-ai/generative-ai/pricing.
    # Two things here are counter-intuitive and both matter to the autopsy:
    #   1. Audio input is NOT priced at a premium — 3.5 Flash bills audio at the
    #      same $1.50 as text ("Text/Image/Video/Audio input" is one line item).
    #      An earlier guess had audio at 3.3x text, which overstated its share.
    #   2. Reasoning tokens bill at the OUTPUT rate ("Text output (response and
    #      reasoning)"), i.e. $9.00 — six times the input rate. Thinking is the
    #      most expensive token this pipeline can emit.
    # Cached input at $0.15 is a 10x discount on $1.50, which is what makes
    # context caching the highest-leverage structural fix available.
    "gemini-3.5-flash": ModelPrice(
        "gemini-3.5-flash", text_in=1.50, audio_in=1.50, out=9.00,
        cached_in=0.15, thinking_out=9.00, verified=True,
        note="Verified 2026-07-21, GLOBAL endpoint (what vertex.py routes to). "
             "Non-global would be $1.65 / $1.65 / $9.90 / $0.165."),
    "gemini-3-flash-preview": ModelPrice(
        "gemini-3-flash-preview", text_in=0.50, audio_in=1.00, out=3.00,
        cached_in=0.05, thinking_out=3.00, verified=True,
        note="Verified 2026-07-21. Unlike 3.5 Flash, this one DOES price audio "
             "at a 2x premium over text."),
    "gemini-3.1-flash-lite": ModelPrice(
        "gemini-3.1-flash-lite", text_in=0.25, audio_in=0.50, out=1.50,
        cached_in=0.025, thinking_out=1.50, verified=True,
        note="Verified 2026-07-21, global endpoint."),
    "gemini-2.5-flash": ModelPrice(
        "gemini-2.5-flash", text_in=0.30, audio_in=1.00, out=2.50,
        verified=False, note="UNVERIFIED — legacy entry, not used by the pipeline."),
    "gemini-2.5-pro": ModelPrice(
        "gemini-2.5-pro", text_in=1.25, audio_in=1.25, out=10.00,
        verified=False, note="UNVERIFIED — legacy entry, not used by the pipeline."),
    "lyria-002": ModelPrice(
        "lyria-002", text_in=0.0, audio_in=0.0, out=0.0,
        verified=False,
        note="Lyria bills PER GENERATED CLIP, not per token; see CLIP_PRICES."),
}

# Non-token SKUs: flat price per unit of work.
CLIP_PRICES: dict[str, float] = {
    "lyria-002": 0.06,          # USD per generated 30s clip — UNVERIFIED
}

# Compute (non-LLM) rates, REQ-R2-COST-02. Colab bills in compute units, not
# dollars, so this is the operator's own conversion — override it to match the
# plan you actually pay for.
GPU_USD_PER_MINUTE: dict[str, float] = {
    "T4": float(os.environ.get("BEATFORGE_PRICE_GPU_T4", "0.0035")),
    "L4": float(os.environ.get("BEATFORGE_PRICE_GPU_L4", "0.0117")),
    "A100": float(os.environ.get("BEATFORGE_PRICE_GPU_A100", "0.0613")),
    "V100": float(os.environ.get("BEATFORGE_PRICE_GPU_V100", "0.0410")),
    "none": 0.0,                # local CPU backend: no metered spend
    "cpu": 0.0,
}

# A model string we have never seen must NOT silently bill at $0 — that would
# hide exactly the kind of model swap hypothesis #4 is looking for.
UNKNOWN_MODEL_FALLBACK = ModelPrice(
    "<unknown>", text_in=1.50, audio_in=1.50, out=9.00, verified=False,
    note="UNKNOWN MODEL — billed at the gemini-3.5-flash rate as a placeholder. "
         "Add it to pricing.TABLE.")


def price_for(model: str) -> ModelPrice:
    """Look up a model's rate. Unknown ids fall back loudly, never to zero."""
    if model in TABLE:
        return TABLE[model]
    # tolerate versioned suffixes: "gemini-3.5-flash-002" -> "gemini-3.5-flash"
    for known in TABLE:
        if model.startswith(known):
            return TABLE[known]
    return ModelPrice(
        model, text_in=UNKNOWN_MODEL_FALLBACK.text_in,
        audio_in=UNKNOWN_MODEL_FALLBACK.audio_in, out=UNKNOWN_MODEL_FALLBACK.out,
        verified=False, note=UNKNOWN_MODEL_FALLBACK.note)


def cost_usd(
    model: str, *, text_in: int = 0, audio_in: int = 0, cached_in: int = 0,
    out: int = 0, thinking: int = 0,
) -> dict:
    """Bill one model call. Returns the per-component breakdown AND the total, so
    a report can say *which* component dominated without re-deriving it.

    `cached_in` is a SUBSET of the prompt tokens that were served from cache; the
    caller passes non-cached text separately (see ledger.usage_from_vertex).
    `thinking` is billed at the output rate but reported apart from visible output.
    """
    p = price_for(model)
    parts = {
        "text_in": text_in / 1e6 * p.text_in,
        "audio_in": audio_in / 1e6 * p.audio_in,
        "cached_in": cached_in / 1e6 * p.cached_in,
        "out": out / 1e6 * p.out,
        "thinking": thinking / 1e6 * p.thinking_out,
    }
    parts = {k: round(v, 8) for k, v in parts.items()}
    parts["total"] = round(sum(parts.values()), 8)
    parts["rate_verified"] = p.verified
    return parts


def gpu_cost_usd(gpu: str, minutes: float) -> float:
    rate = GPU_USD_PER_MINUTE.get(gpu, GPU_USD_PER_MINUTE.get(str(gpu).upper(), 0.0))
    return round(rate * max(0.0, minutes), 8)


def table_snapshot() -> dict:
    """The exact rates a report was computed against, for embedding in artifacts.
    A cost report without its price table is not reproducible."""
    return {
        "pricing_as_of": PRICING_AS_OF,
        "source": PRICING_SOURCE,
        "models": {
            m: {"text_in": p.text_in, "audio_in": p.audio_in, "out": p.out,
                "cached_in": p.cached_in, "thinking_out": p.thinking_out,
                "verified": p.verified, "note": p.note}
            for m, p in TABLE.items()},
        "gpu_usd_per_minute": dict(GPU_USD_PER_MINUTE),
        "clip_prices": dict(CLIP_PRICES),
    }


def unverified_models() -> list[str]:
    return sorted(m for m, p in TABLE.items() if not p.verified)
