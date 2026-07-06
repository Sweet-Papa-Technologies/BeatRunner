"""compute.py — ComputeBackend abstraction (spec §3.5, REQ-COMPUTE-01..05).

An operation runs on Colab iff it needs a GPU or a dependency that's painful to
install locally (Demucs, madmom). Everything else is local. Vertex model calls
never route through here.

Backends:
  * LocalCpuBackend  — numpy/scipy DSP (dsp.py). HPSS-only, no stems. The
                       graceful-degradation path: stamps stem_source="none".
  * ColabBackend     — provisions a GPU Colab session via the installed `colab`
                       CLI, ships jobs/analyze_job.py, pulls back analysis+stems.
  * InMemoryBackend  — test fake: replays a recorded analysis.json, zero network.

Callers (analyze.py) only ever touch a backend's run_analysis(); they never see
the CLI or librosa directly (REQ-COMPUTE-01).
"""
from __future__ import annotations

import json
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from . import config, dsp


@dataclass
class AnalysisResult:
    analysis: dict
    stem_paths: dict = field(default_factory=dict)     # {"drums": path, ...}
    preview_paths: dict = field(default_factory=dict)
    job_meta: dict = field(default_factory=dict)


class ComputeBackend(Protocol):
    name: str

    def run_analysis(self, audio_path: str, opts: config.RunOptions) -> AnalysisResult:
        ...

    def close(self) -> None:
        ...


# --------------------------------------------------------------------------- #
# Local CPU backend (default here; REQ-COMPUTE-05 degraded path)
# --------------------------------------------------------------------------- #
class LocalCpuBackend:
    name = "local"

    def run_analysis(self, audio_path: str, opts: config.RunOptions) -> AnalysisResult:
        t0 = time.monotonic()
        analysis = dsp.analyze_signal(audio_path)
        analysis["stem_source"] = "none"       # HPSS-only, no Demucs (REQ-DSP-06)
        job_meta = {
            "backend": "local",
            "beat_backend": analysis["beat_backend"],
            "stem_source": "none",
            "wall_clock_s": round(time.monotonic() - t0, 2),
            "gpu": None,
            "note": "LocalCpuBackend: numpy/scipy DSP, HPSS-only, no stems "
                    "(reduced fidelity vs Colab Demucs+madmom path).",
        }
        return AnalysisResult(analysis=analysis, job_meta=job_meta)

    def close(self) -> None:
        pass


# --------------------------------------------------------------------------- #
# Colab GPU backend (REQ-COMPUTE-02/03/04)
# --------------------------------------------------------------------------- #
class ColabError(RuntimeError):
    pass


class ColabBackend:
    """Drives the installed `colab` CLI. One session per batch (REQ-COMPUTE-03):
    the session is created lazily on first analysis and reused for every track,
    then torn down by close() — which callers MUST invoke in a finally."""

    name = "colab"

    def __init__(self, gpu: str | None = None, run_id: str = "batch"):
        self.gpu = gpu or config.COLAB_GPU
        self.session = f"{config.COLAB_SESSION_PREFIX}-{run_id}"
        self._started = False
        self._log: list[str] = []
        if not shutil.which("colab"):
            raise ColabError(
                "colab CLI not found. Install with:\n"
                "  uv tool install git+https://github.com/googlecolab/google-colab-cli\n"
                "then run `colab new` once to flush the browser-auth loop.")

    def _run(self, args: list[str], timeout: int = 1800) -> str:
        self._log.append("colab " + " ".join(args))
        proc = subprocess.run(["colab", *args], capture_output=True, text=True,
                             timeout=timeout)
        if proc.returncode != 0:
            raise ColabError(f"`colab {' '.join(args)}` failed:\n{proc.stderr[:800]}")
        return proc.stdout

    def _ensure_session(self):
        if self._started:
            return
        self._run(["new", "--gpu", self.gpu, "-s", self.session])
        # install pinned deps once
        req = config.JOBS_DIR / "requirements.lock"
        self._run(["install", "-r", str(req)], timeout=2400)
        self._started = True

    def run_analysis(self, audio_path: str, opts: config.RunOptions) -> AnalysisResult:
        self._ensure_session()
        job = config.JOBS_DIR / "analyze_job.py"
        remote_name = Path(audio_path).name
        self._run(["upload", audio_path, remote_name])
        # analyze_job reads argv[1] = the uploaded audio, writes analysis.json etc.
        self._run(["exec", "-f", str(job), "--", remote_name], timeout=3600)
        out_dir = config.BUILD_DIR / Path(audio_path).stem
        out_dir.mkdir(parents=True, exist_ok=True)
        for remote in ("analysis.json", "job_meta.json"):
            self._run(["download", remote, str(out_dir / remote)])
        stems = {}
        for stem in ("drums", "bass", "other", "vocals"):
            dest = out_dir / f"{stem}.wav"
            try:
                self._run(["download", f"{stem}.wav", str(dest)])
                stems[stem] = str(dest)
            except ColabError:
                pass  # stem optional if Demucs produced fewer
        analysis = json.loads((out_dir / "analysis.json").read_text())
        job_meta = json.loads((out_dir / "job_meta.json").read_text()) \
            if (out_dir / "job_meta.json").exists() else {}
        job_meta.setdefault("backend", "colab")
        job_meta.setdefault("gpu", self.gpu)
        return AnalysisResult(analysis=analysis, stem_paths=stems, job_meta=job_meta)

    def close(self) -> None:
        # idempotent teardown, logged (REQ-COMPUTE-03)
        if self._started:
            try:
                self._run(["stop", "-s", self.session])
            except ColabError as e:
                self._log.append(f"stop failed (ignored): {e}")
            finally:
                self._started = False

    @property
    def session_log(self) -> list[str]:
        return list(self._log)


# --------------------------------------------------------------------------- #
# In-memory fake for tests (REQ-COMPUTE-01 Accept)
# --------------------------------------------------------------------------- #
class InMemoryBackend:
    """Replays recorded analysis dicts; satisfies ComputeBackend with zero
    network so Workstreams C/D run in tests. Records how many times it was
    provisioned/closed for teardown assertions."""

    name = "inmemory"

    def __init__(self, analyses: dict[str, dict]):
        self._analyses = analyses     # {audio_basename: analysis_dict}
        self.closed = 0
        self.calls = 0

    def run_analysis(self, audio_path: str, opts: config.RunOptions) -> AnalysisResult:
        self.calls += 1
        key = Path(audio_path).name
        if key not in self._analyses:
            raise KeyError(f"InMemoryBackend has no recorded analysis for {key}")
        return AnalysisResult(analysis=dict(self._analyses[key]),
                             job_meta={"backend": "inmemory"})

    def close(self) -> None:
        self.closed += 1


def make_backend(opts: config.RunOptions, run_id: str = "batch") -> ComputeBackend:
    """Backend selection (REQ-COMPUTE-01). Colab failures surface loudly; the
    caller decides whether to fall back (REQ-COMPUTE-05)."""
    if opts.backend == "colab":
        return ColabBackend(gpu=opts.gpu, run_id=run_id)
    return LocalCpuBackend()
