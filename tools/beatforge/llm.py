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
import subprocess
import tempfile
import urllib.error
import urllib.request
from pathlib import Path
from typing import Protocol

from . import config
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
    if src_ext == fmt:
        data = Path(path).read_bytes()
    else:
        if not shutil.which("ffmpeg"):
            raise OpenAICompatError(
                f"ffmpeg needed to transcode {src_ext}->{fmt} for the audio part")
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / f"a.{fmt}"
            codec = {"wav": "pcm_s16le", "mp3": "libmp3lame", "flac": "flac",
                     "ogg": "libvorbis"}.get(fmt, "pcm_s16le")
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", path,
                            "-c:a", codec, str(out)], check=True, capture_output=True)
            data = out.read_bytes()
    return base64.b64encode(data).decode()


class OpenAICompatClient:
    """OpenAI /v1/chat/completions client with audio-in support. Matches the
    VertexClient.generate/generate_json interface so it's a drop-in swap."""

    name = "openai"

    def __init__(self, base_url=None, model=None, api_key=None, audio_format=None):
        self.base_url = (base_url or config.OPENAI_BASE_URL).rstrip("/")
        self.model = model or config.OPENAI_MODEL
        self.api_key = api_key or config.OPENAI_API_KEY
        self.audio_format = audio_format or config.OPENAI_AUDIO_FORMAT

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
        except urllib.error.URLError as e:
            raise OpenAICompatError(
                f"cannot reach OpenAI-compatible server at {self.base_url}: {e.reason}")

    def list_models(self, timeout=15) -> list[str]:
        req = urllib.request.Request(
            f"{self.base_url}/models",
            headers={"Authorization": f"Bearer {self.api_key}"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read())
        return [m.get("id") for m in data.get("data", [])]

    def generate(self, prompt: str, *, audio_path=None, system=None, model=None,
                 thinking_level=None, json_out=False, timeout=600) -> str:
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
        body: dict = {"model": model or self.model, "messages": messages,
                      "max_tokens": config.OPENAI_MAX_TOKENS}
        if json_out:
            body["response_format"] = {"type": "json_object"}
        resp = self._post(body, timeout)
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
