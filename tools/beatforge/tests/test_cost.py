"""test_cost.py — Workstream A cost telemetry (REQ-R2-COST-01/02/03).

Offline: no Vertex, no Colab. The Vertex/OpenAI clients are exercised through a
stubbed `_post`, which is the right seam — it proves the ledger reads real
response shapes (`usageMetadata`, `promptTokensDetails`) rather than a shape we
invented for the test.
"""
from __future__ import annotations

import json

import pytest

from beatforge import costreport, ledger, pricing
from beatforge.llm import OpenAICompatClient
from beatforge.vertex import VertexClient


# --------------------------------------------------------------------------- #
# Response fixtures — the shapes Vertex/OpenAI actually return.
# --------------------------------------------------------------------------- #
def _vertex_resp(text="{}", *, prompt=12000, audio=9000, out=1500, thinking=800,
                 cached=0):
    details = [{"modality": "TEXT", "tokenCount": prompt - audio - cached}]
    if audio:
        details.append({"modality": "AUDIO", "tokenCount": audio})
    um = {"promptTokenCount": prompt, "candidatesTokenCount": out,
          "thoughtsTokenCount": thinking, "promptTokensDetails": details}
    if cached:
        um["cachedContentTokenCount"] = cached
    return {"candidates": [{"content": {"parts": [{"text": text}]}}],
            "usageMetadata": um}


@pytest.fixture
def vertex(monkeypatch, tmp_path):
    c = VertexClient()
    monkeypatch.setattr(c, "_get_token", lambda force=False: "fake-token")
    monkeypatch.setattr(c, "_post", lambda url, body, timeout=600: _vertex_resp())
    return c


@pytest.fixture
def audio_file(tmp_path):
    p = tmp_path / "song.ogg"
    p.write_bytes(b"OggS" + b"\0" * 4096)
    return str(p)


# --------------------------------------------------------------------------- #
# REQ-R2-COST-01 — every model call is ledgered, with a valid schema
# --------------------------------------------------------------------------- #
def test_vertex_call_writes_one_ledger_entry(vertex, audio_file):
    with ledger.capture() as entries:
        with ledger.stage("designer", song="the_pools", difficulty="hard", attempt=2):
            vertex.generate("place some notes", audio_path=audio_file)
    assert len(entries) == 1
    e = entries[0]
    assert ledger.validate_entry(e) == []
    assert (e["stage"], e["song"], e["difficulty"], e["attempt"]) == \
        ("designer", "the_pools", "hard", 2)
    assert e["provider"] == "vertex"
    assert e["kind"] == "model"


def test_audio_tokens_are_recorded_separately_from_text(vertex, audio_file):
    """Hypothesis #1 of the autopsy is unanswerable unless audio input tokens are
    split out of the prompt total. This is that split."""
    with ledger.capture() as entries:
        vertex.generate("hi", audio_path=audio_file)
    e = entries[0]
    assert e["audio_tokens"] == 9000
    assert e["text_tokens"] == 3000            # 12000 prompt - 9000 audio
    assert e["input_tokens"] == 12000
    assert e["audio_attached"] is True
    assert e["modality_breakdown_available"] is True
    # and audio must dominate the dollar figure at these rates
    assert e["cost_usd"]["audio_in"] > e["cost_usd"]["text_in"]


def test_thinking_and_cached_tokens_are_recorded(monkeypatch, audio_file):
    """Hypotheses #5 (thinking tokens) and #2 (is the inventory cached?) both need
    their own counters — they bill differently and diagnose differently."""
    c = VertexClient()
    monkeypatch.setattr(c, "_get_token", lambda force=False: "t")
    monkeypatch.setattr(c, "_post", lambda u, b, timeout=600:
                        _vertex_resp(prompt=20000, thinking=2500, cached=4000))
    with ledger.capture() as entries:
        c.generate("hi", audio_path=audio_file)
    e = entries[0]
    assert e["thinking_tokens"] == 2500
    assert e["cached_tokens"] == 4000
    # cached tokens are a discount, not a double-charge: they bill below text rate
    assert e["cost_usd"]["cached_in"] < e["cost_usd"]["text_in"]


def test_model_string_recorded_is_the_one_sent_not_the_config(monkeypatch, audio_file):
    """Hypothesis #4 exists because config lied once. The ledger records the model
    string that went over the wire, so a silent swap is visible."""
    c = VertexClient()
    monkeypatch.setattr(c, "_get_token", lambda force=False: "t")
    monkeypatch.setattr(c, "_post", lambda u, b, timeout=600: _vertex_resp())
    with ledger.capture() as entries:
        c.generate("hi", model="gemini-2.5-pro")
    assert entries[0]["model"] == "gemini-2.5-pro"


def test_failed_call_is_still_ledgered(monkeypatch):
    """A call that 500s after the prompt was consumed still costs money. Silence
    on the error path is how a bill goes unexplained."""
    c = VertexClient()
    monkeypatch.setattr(c, "_get_token", lambda force=False: "t")

    def boom(*a, **k):
        raise RuntimeError("HTTP 500")
    monkeypatch.setattr(c, "_post", boom)
    with ledger.capture() as entries:
        with pytest.raises(RuntimeError):
            c.generate("hi")
    assert len(entries) == 1
    assert "HTTP 500" in entries[0]["error"]


def test_reprompt_loop_produces_one_entry_per_call(vertex, audio_file):
    """The autopsy wants the DISTRIBUTION of calls per chart. One entry per call
    (not per chart) is what makes a distribution computable at all."""
    with ledger.capture() as entries:
        for attempt in (1, 2, 3):
            with ledger.stage("designer" if attempt == 1 else "reprompt",
                              song="s", difficulty="hard", attempt=attempt):
                vertex.generate("go", audio_path=audio_file)
    assert [e["attempt"] for e in entries] == [1, 2, 3]
    assert [e["stage"] for e in entries] == ["designer", "reprompt", "reprompt"]


def test_unattributed_calls_are_recorded_not_dropped(vertex):
    """An un-instrumented call path must show up as a mystery line, never as
    nothing — the absence of a line is indistinguishable from missing telemetry."""
    with ledger.capture() as entries:
        vertex.generate("no context here")
    assert entries[0]["stage"] == "unattributed"


def test_openai_backend_is_ledgered_too(monkeypatch, audio_file):
    c = OpenAICompatClient(base_url="http://x/v1", model="gemma-4-12b")
    monkeypatch.setattr(c, "_post", lambda body, timeout: {
        "choices": [{"message": {"content": "{}"}}],
        "usage": {"prompt_tokens": 5000, "completion_tokens": 400,
                  "prompt_tokens_details": {"audio_tokens": 4200}}})
    monkeypatch.setattr("beatforge.llm._encode_audio", lambda p, fmt: "BASE64")
    with ledger.capture() as entries:
        with ledger.stage("designer", song="s", difficulty="easy"):
            c.generate("hi", audio_path=audio_file)
    e = entries[0]
    assert ledger.validate_entry(e) == []
    assert e["provider"] == "openai"
    assert e["audio_tokens"] == 4200


# --------------------------------------------------------------------------- #
# Schema validation (REQ-R2-COST-01 accept criterion)
# --------------------------------------------------------------------------- #
def test_validate_entry_rejects_missing_fields():
    assert "missing field 'model'" in ledger.validate_entry(
        {"kind": "model", "schema": 1, "ts": 0, "stage": "x", "song": "s",
         "difficulty": None, "attempt": None, "provider": "vertex",
         "input_tokens": 0, "text_tokens": 0, "audio_tokens": 0, "cached_tokens": 0,
         "output_tokens": 0, "thinking_tokens": 0, "latency_s": 0.0,
         "prompt_bytes": 0, "audio_attached": False, "cost_usd": {"total": 0.0},
         "pricing_as_of": "x"})


def test_validate_entry_rejects_audio_tokens_without_audio_attached():
    """A contradiction that would silently corrupt the audio-share number."""
    with ledger.capture() as entries:
        ledger.record_model_call(
            provider="vertex", model="gemini-3.5-flash",
            usage={"input_tokens": 10, "text_tokens": 0, "audio_tokens": 10,
                   "cached_tokens": 0, "output_tokens": 1, "thinking_tokens": 0},
            latency_s=0.1, audio_attached=False)
    problems = ledger.validate_entry(entries[0])
    assert any("audio_attached" in p for p in problems)


def test_ledger_writes_jsonl_to_build_cost_song(tmp_path, monkeypatch):
    """REQ-R2-COST-01 accept: running a song produces <song>/cost_ledger.jsonl."""
    monkeypatch.setattr("beatforge.config.COST_DIR", tmp_path)
    with ledger.stage("designer", song="the_pools", difficulty="hard"):
        ledger.record_model_call(
            provider="vertex", model="gemini-3.5-flash",
            usage=ledger.usage_from_vertex(_vertex_resp()), latency_s=1.0,
            audio_attached=True)
    p = tmp_path / "the_pools" / "cost_ledger.jsonl"
    assert p.exists()
    lines = [json.loads(x) for x in p.read_text().splitlines()]
    assert len(lines) == 1 and ledger.validate_entry(lines[0]) == []


# --------------------------------------------------------------------------- #
# REQ-R2-COST-02 — non-LLM compute, cache hit vs fresh
# --------------------------------------------------------------------------- #
def test_cache_hit_records_zero_cost_compute_entry():
    with ledger.capture() as entries:
        ledger.record_compute(stage_name="analysis", song="s", backend="colab",
                              gpu="T4", minutes=0.0, cache_hit=True)
    e = entries[0]
    assert ledger.validate_entry(e) == []
    assert e["cache_hit"] is True and e["cost_usd"]["total"] == 0.0


def test_fresh_analysis_records_gpu_minutes_and_cost():
    with ledger.capture() as entries:
        ledger.record_compute(stage_name="analysis", song="s", backend="colab",
                              gpu="T4", minutes=6.0, cache_hit=False)
    e = entries[0]
    assert e["gpu_minutes"] == 6.0
    assert e["cost_usd"]["total"] == pytest.approx(pricing.gpu_cost_usd("T4", 6.0))
    assert e["cost_usd"]["total"] > 0


def test_analyze_track_ledgers_a_cache_hit(tmp_path, monkeypatch):
    """The real analyze_track path, not a hand-built entry: a cached re-run must
    leave a $0 trace so 'analysis is free on re-run' is provable."""
    from beatforge import analyze, config

    monkeypatch.setattr(config, "COST_DIR", tmp_path / "cost")
    audio = tmp_path / "s.ogg"
    audio.write_bytes(b"OggS")
    monkeypatch.setattr(analyze, "_audio_for", lambda tid: str(audio))
    monkeypatch.setattr(analyze, "_cache_key", lambda p: "KEY")
    monkeypatch.setattr(analyze, "load_cached", lambda tid: {"cache_key": "KEY"})

    with ledger.capture() as entries:
        analyze.analyze_track("s", config.RunOptions(force=False))
    assert len(entries) == 1
    assert entries[0]["kind"] == "compute" and entries[0]["cache_hit"] is True
    assert entries[0]["cost_usd"]["total"] == 0.0


# --------------------------------------------------------------------------- #
# REQ-R2-COST-03 — the rollup
# --------------------------------------------------------------------------- #
def _entries_for_two_songs():
    out = []
    with ledger.capture() as sink:
        for song in ("a", "b"):
            ledger.record_compute(stage_name="analysis", song=song, backend="colab",
                                  gpu="T4", minutes=5.0, cache_hit=False)
            for diff in ("easy", "hard"):
                with ledger.stage("designer", song=song, difficulty=diff, attempt=1):
                    ledger.record_model_call(
                        provider="vertex", model="gemini-3.5-flash",
                        usage=ledger.usage_from_vertex(_vertex_resp()),
                        latency_s=5.0, prompt_bytes=90000, audio_attached=True)
                with ledger.stage("critic", song=song, difficulty=diff, attempt=1):
                    ledger.record_model_call(
                        provider="vertex", model="gemini-3.5-flash",
                        usage=ledger.usage_from_vertex(_vertex_resp(out=300)),
                        latency_s=4.0, prompt_bytes=40000, audio_attached=True)
        out = list(sink)
    return out


def test_rollup_reports_per_song_and_per_chart_dollars():
    r = costreport.aggregate(_entries_for_two_songs())
    t = r["totals"]
    assert t["songs"] == 2 and t["charts"] == 4 and t["model_calls"] == 8
    assert t["usd"] == pytest.approx(t["llm_usd"] + t["compute_usd"])
    assert t["usd_per_song"] == pytest.approx(t["usd"] / 2)
    assert t["usd_per_chart"] == pytest.approx(t["usd"] / 4)


def test_rollup_splits_dollars_by_stage():
    r = costreport.aggregate(_entries_for_two_songs())
    assert set(r["by_stage"]) == {"analysis", "designer", "critic"}
    assert sum(b["usd"] for b in r["by_stage"].values()) == \
        pytest.approx(r["totals"]["usd"])


def test_rollup_reports_calls_per_chart_as_a_distribution():
    r = costreport.aggregate(_entries_for_two_songs())
    d = r["calls_per_chart"]
    assert d["n_charts"] == 4 and d["min"] == 2 and d["max"] == 2
    assert d["histogram"] == {2: 4}


def test_rollup_flags_an_unexpected_model():
    entries = _entries_for_two_songs()
    entries[1]["model"] = "gemini-2.5-pro"
    r = costreport.aggregate(entries)
    assert "gemini-2.5-pro" in r["unexpected_models"]


def test_rollup_top_calls_carry_prompt_byte_sizes():
    r = costreport.aggregate(_entries_for_two_songs())
    assert len(r["top_calls"]) == 5
    assert all(c["prompt_bytes"] > 0 for c in r["top_calls"])
    usd = [c["usd"] for c in r["top_calls"]]
    assert usd == sorted(usd, reverse=True)


def test_rollup_reports_audio_share_of_input():
    r = costreport.aggregate(_entries_for_two_songs())
    assert r["tokens"]["audio_share_of_input"] == pytest.approx(9000 / 12000)


def test_markdown_renders_the_rollup():
    md = costreport.render_markdown(costreport.aggregate(_entries_for_two_songs()))
    assert "# beatforge cost report" in md
    assert "$/song" in md and "$/chart" in md
    assert "Top 5 most expensive calls" in md


def test_the_model_the_pipeline_actually_uses_has_a_verified_rate():
    """A dollar figure computed from a guessed rate is worse than no figure. The
    first draft of the autopsy used placeholder rates that were 3.6x low on
    output and it changed the conclusions, so the configured model's rate must
    stay verified."""
    from beatforge import config
    assert pricing.price_for(config.GEMINI_MODEL).verified is True
    assert config.GEMINI_MODEL not in pricing.unverified_models()


def test_report_still_warns_when_an_unverified_rate_is_in_play():
    """The warning must not have been silenced — only earned. Legacy entries are
    still unverified and must still be called out."""
    assert pricing.unverified_models(), "expected some legacy rates to be unverified"
    md = costreport.render_markdown(costreport.aggregate(_entries_for_two_songs()))
    assert "Rates unverified" in md


def test_empty_ledger_rolls_up_without_dividing_by_zero():
    r = costreport.aggregate([])
    assert r["totals"]["usd"] == 0.0 and r["totals"]["usd_per_song"] == 0.0
    costreport.render_markdown(r)        # must not raise
