"""llm.py — swappable LLM backend for the designer / critic / A&R calls.

The pipeline's audio-understanding model is behind one small interface so an
alternative (e.g. a self-hosted Gemma 4 12B on an OpenAI-compatible server) can
be dropped in and benchmarked against Gemini 3.5 Flash with zero caller changes.

  * LLMClient        — the protocol every backend satisfies (VertexClient already
                       does; see vertex.py).
  * OpenAICompatClient — talks to any OpenAI /v1/chat/completions server, sending
                       audio as an `input_audio` content part (the format vLLM &
                       friends expect for audio-in models).
  * make_llm_client  — factory picking the backend from config.LLM_BACKEND.

Lyria (music generation) is Vertex-only and does NOT go through here.
"""
from __future__ import annotations

import base64
import json
import os
import shutil
import socket
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Protocol

from . import config, ledger
from .vertex import VertexClient, VertexError, _parse_json


class LLMClient(Protocol):
    def generate(self, prompt: str, *, audio_path=None, system=None, model=None,
                 thinking_level=None, json_out=False, timeout=600) -> str: ...

    def generate_json(self, prompt: str, *, audio_path=None, system=None,
                      model=None, thinking_level=None, timeout=600) -> dict: ...


class OpenAICompatError(RuntimeError):
    pass


def _encode_audio(path: str | Path, fmt: str) -> str:
    """Return base64 of the audio in `fmt`, transcoding from the source (usually
    .ogg) with ffmpeg when needed. wav is the safe default — universally decoded
    by audio-in serving stacks."""
    path = str(path)
    src_ext = os.path.splitext(path)[1].lower().lstrip(".")
    sr, mono = config.OPENAI_AUDIO_SR, config.OPENAI_AUDIO_MONO
    # When no resample/downmix is requested and the source already matches, pass
    # the bytes straight through. Otherwise transcode (and shrink) via ffmpeg.
    if src_ext == fmt and sr <= 0 and not mono:
        data = Path(path).read_bytes()
    else:
        if not shutil.which("ffmpeg"):
            raise OpenAICompatError(
                f"ffmpeg needed to transcode {src_ext}->{fmt} for the audio part")
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / f"a.{fmt}"
            codec = {"wav": "pcm_s16le", "mp3": "libmp3lame", "flac": "flac",
                     "ogg": "libvorbis"}.get(fmt, "pcm_s16le")
            cmd = ["ffmpeg", "-y", "-loglevel", "error", "-i", path, "-c:a", codec]
            if sr > 0:                       # downsample: fewer audio tokens -> less VRAM
                cmd += ["-ar", str(sr)]
            if mono:                         # downmix to 1 channel: half the payload
                cmd += ["-ac", "1"]
            cmd.append(str(out))
            subprocess.run(cmd, check=True, capture_output=True)
            data = out.read_bytes()
    return base64.b64encode(data).decode()


class OpenAICompatClient:
    """OpenAI /v1/chat/completions client with audio-in support. Matches the
    VertexClient.generate/generate_json interface so it's a drop-in swap."""

    name = "openai"

    def __init__(self, base_url=None, model=None, api_key=None, audio_format=None,
                 timeout=None, temperature=None):
        self.base_url = (base_url or config.OPENAI_BASE_URL).rstrip("/")
        self.model = model or config.OPENAI_MODEL
        self.api_key = api_key or config.OPENAI_API_KEY
        self.audio_format = audio_format or config.OPENAI_AUDIO_FORMAT
        self.timeout = timeout if timeout is not None else config.OPENAI_TIMEOUT
        self.temperature = temperature if temperature is not None else config.OPENAI_TEMPERATURE

    def _post(self, body: dict, timeout: int) -> dict:
        data = json.dumps(body).encode()
        req = urllib.request.Request(
            f"{self.base_url}/chat/completions", data=data, method="POST",
            headers={"Authorization": f"Bearer {self.api_key}",
                     "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")
            raise OpenAICompatError(f"HTTP {e.code} from {self.base_url}:\n{detail[:1500]}")
        except (TimeoutError, socket.timeout) as e:
            # A read timeout AFTER the request was accepted: the model is either
            # too slow for this task on the local hardware or looping (KV cache /
            # VRAM fills as it generates toward max_tokens). NOT caught by URLError.
            raise OpenAICompatError(
                f"request to {self.base_url} timed out after {timeout}s ({e}). The "
                f"model likely ran slow or looped generating up to max_tokens="
                f"{config.OPENAI_MAX_TOKENS}. Try `compare --probe-only` first, lower "
                f"BEATFORGE_OPENAI_MAX_TOKENS, or raise BEATFORGE_OPENAI_TIMEOUT / the "
                f"server's --max-model-len.")
        except urllib.error.URLError as e:
            reason = getattr(e, "reason", e)
            if isinstance(reason, (TimeoutError, socket.timeout)):
                raise OpenAICompatError(
                    f"request to {self.base_url} timed out after {timeout}s. See "
                    f"`--probe-only` / BEATFORGE_OPENAI_TIMEOUT / max_tokens guidance.")
            raise OpenAICompatError(
                f"cannot reach OpenAI-compatible server at {self.base_url}: {reason}")
        except OSError as e:
            raise OpenAICompatError(f"network error talking to {self.base_url}: {e}")

    def list_models(self, timeout=15) -> list[str]:
        req = urllib.request.Request(
            f"{self.base_url}/models",
            headers={"Authorization": f"Bearer {self.api_key}"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read())
        return [m.get("id") for m in data.get("data", [])]

    def generate(self, prompt: str, *, audio_path=None, system=None, model=None,
                 thinking_level=None, json_out=False, timeout=None) -> str:
        # thinking_level is Gemini-specific; ignored here (Gemma has no equivalent).
        content: list[dict] = []
        if audio_path is not None:
            content.append({"type": "input_audio", "input_audio": {
                "data": _encode_audio(audio_path, self.audio_format),
                "format": self.audio_format}})
        content.append({"type": "text", "text": prompt})
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": content})
        sent_model = model or self.model
        body: dict = {"model": sent_model, "messages": messages,
                      "max_tokens": config.OPENAI_MAX_TOKENS,
                      "temperature": self.temperature}
        if json_out:
            body["response_format"] = {"type": "json_object"}
        # REQ-R2-COST-01: the alternate backend is ledgered too. A self-hosted
        # model costs GPU-hours rather than Vertex dollars, but "which backend
        # actually served this call" is exactly what hypothesis #4 asks, and a
        # backend that leaves no trace can't answer it.
        t0 = time.monotonic()
        try:
            resp = self._post(body, timeout if timeout is not None else self.timeout)
        except Exception as e:
            ledger.record_model_call(
                provider="openai", model=sent_model,
                usage=ledger.usage_from_openai({}), latency_s=time.monotonic() - t0,
                prompt_bytes=len(prompt.encode()), audio_attached=audio_path is not None,
                audio_path=str(audio_path or "") or None, error=str(e)[:300])
            raise
        ledger.record_model_call(
            provider="openai", model=sent_model, usage=ledger.usage_from_openai(resp),
            latency_s=time.monotonic() - t0, prompt_bytes=len(prompt.encode()),
            audio_attached=audio_path is not None,
            audio_path=str(audio_path or "") or None,
            audio_bytes=os.path.getsize(audio_path) if audio_path else 0)
        try:
            text = resp["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            raise OpenAICompatError(f"unexpected response shape: {json.dumps(resp)[:400]}")
        if not text or not text.strip():
            raise OpenAICompatError(f"empty response from {self.model}")
        return text.strip()

    def generate_json(self, prompt: str, *, audio_path=None, system=None,
                      model=None, thinking_level=None, timeout=600) -> dict:
        text = self.generate(prompt, audio_path=audio_path, system=system,
                             model=model, json_out=True, timeout=timeout)
        try:
            return _parse_json(text)
        except ValueError as e:
            retry = (f"{prompt}\n\n---\nYour previous reply could not be parsed as "
                     f"JSON: {e}. Respond with ONLY the valid JSON object, no prose, "
                     f"no code fences.")
            text2 = self.generate(retry, audio_path=audio_path, system=system,
                                  model=model, json_out=True, timeout=timeout)
            return _parse_json(text2)


def make_llm_client(backend: str | None = None) -> LLMClient:
    """Pick the designer/critic/A&R model backend (config.LLM_BACKEND by default)."""
    backend = backend or config.LLM_BACKEND
    if backend == "openai":
        return OpenAICompatClient()
    if backend == "gemini":
        return VertexClient()
    raise ValueError(f"unknown LLM backend '{backend}' (use gemini|openai)")


__all__ = ["LLMClient", "OpenAICompatClient", "VertexClient", "VertexError",
           "OpenAICompatError", "make_llm_client"]
