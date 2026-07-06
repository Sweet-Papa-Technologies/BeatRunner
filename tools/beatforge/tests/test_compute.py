"""Compute-backend contract tests (REQ-COMPUTE-01/03/05). No Colab is ever
provisioned; ColabBackend is exercised via a fake CLI runner."""
import pytest

from beatforge import config
from beatforge.compute import (AnalysisResult, ColabBackend, ColabError,
                              InMemoryBackend, LocalCpuBackend)


def test_inmemory_backend_satisfies_protocol(make_analysis):
    """REQ-COMPUTE-01: a fake backend lets downstream run with zero network."""
    a = make_analysis()
    be = InMemoryBackend({"t.ogg": a})
    res = be.run_analysis("/x/t.ogg", config.RunOptions())
    assert isinstance(res, AnalysisResult)
    assert res.analysis["bpm"] == a["bpm"]
    be.close()
    assert be.closed == 1


def test_local_backend_stamps_degradation(monkeypatch, make_analysis):
    """REQ-COMPUTE-05/DSP-06: local path stamps stem_source=none."""
    a = make_analysis()
    monkeypatch.setattr("beatforge.compute.dsp.analyze_signal", lambda p: dict(a))
    res = LocalCpuBackend().run_analysis("/x/t.ogg", config.RunOptions())
    assert res.analysis["stem_source"] == "none"
    assert res.job_meta["backend"] == "local"


class _FakeColab(ColabBackend):
    """ColabBackend with the CLI stubbed so teardown/reuse can be asserted."""
    def __init__(self, fail_on=None):
        self.gpu = "T4"; self.session = "beatforge-test"
        self._started = False; self._log = []
        self.new_calls = 0; self.stop_calls = 0
        self._fail_on = fail_on

    def _run(self, args, timeout=1800):
        self._log.append("colab " + " ".join(args))
        if args and args[0] == "new":
            self.new_calls += 1
        if args and args[0] == "stop":
            self.stop_calls += 1
        if self._fail_on and args and args[0] == self._fail_on:
            raise ColabError("simulated failure")
        return ""


def test_colab_teardown_on_exception():
    """REQ-COMPUTE-03: teardown runs even when a job blows up mid-run."""
    be = _FakeColab(fail_on="exec")
    be._started = True
    with pytest.raises(Exception):
        be._run(["exec", "-f", "job.py"])
    be.close()
    assert be.stop_calls == 1  # stop invoked in teardown


def test_colab_stop_is_idempotent():
    be = _FakeColab()
    be._started = True
    be.close()
    be.close()  # second close must not error or double-stop a live session
    assert be.stop_calls == 1


def test_missing_colab_cli_fails_loudly(monkeypatch):
    monkeypatch.setattr("beatforge.compute.shutil.which", lambda _: None)
    with pytest.raises(ColabError, match="colab CLI not found"):
        ColabBackend()
