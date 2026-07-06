"""vertex.py — shared Vertex AI client for beatforge.

Mirrors the auth/endpoint pattern of ~/.assetforge/assetforge.py and
tools/generate_overdrive_assets.py: a service-account (or ADC) bearer token,
Gemini 3.x routed to the v1beta1 `global` endpoint, everything else to the
regional endpoint. Adds what beatforge needs beyond assetforge's CLI:

  * audio-part `generateContent` (Gemini *hears* the track — the whole point),
  * family-aware "full thinking power" config (thinking_level vs thinkingBudget),
  * strict-JSON responses with defensive fence-stripping + one parse retry,
  * Lyria music prediction for Workstream A.

All model calls in beatforge go through here so they sit behind one seam that
tests stub out (see tests/fakes.py / offline mode).
"""
from __future__ import annotations

import base64
import json
import os
import re
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from . import config

_MIME = {
    "wav": "audio/wav", "mp3": "audio/mp3", "ogg": "audio/ogg", "flac": "audio/flac",
    "m4a": "audio/mp4", "aac": "audio/aac", "png": "image/png", "jpg": "image/jpeg",
}


class VertexError(RuntimeError):
    pass


def _guess_mime(path: str | Path) -> str:
    ext = os.path.splitext(str(path))[1].lower().lstrip(".")
    return _MIME.get(ext, "application/octet-stream")


def _b64file(path: str | Path) -> str:
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode()


class VertexClient:
    """Thin generateContent / predict wrapper. One token cached per client."""

    def __init__(self):
        self.project = config.VERTEX_PROJECT
        self.location = config.VERTEX_LOCATION
        self.key_file = config.ASSETFORGE_KEY
        self._token: str | None = None

    # ---- auth / endpoint (mirrors assetforge) ---------------------------- #
    def _get_token(self) -> str:
        if self._token:
            return self._token
        scopes = ["https://www.googleapis.com/auth/cloud-platform"]
        import google.auth
        from google.auth.transport.requests import Request
        if self.key_file and os.path.isfile(self.key_file):
            from google.oauth2 import service_account
            creds = service_account.Credentials.from_service_account_file(
                self.key_file, scopes=scopes)
        else:
            creds, _ = google.auth.default(scopes=scopes)
        creds.refresh(Request())
        self._token = creds.token
        return self._token

    def _endpoint(self, model: str) -> tuple[str, str]:
        api, loc = "v1", self.location
        if model.startswith("gemini-3"):
            api, loc = "v1beta1", "global"
        elif model.startswith("lyria-3"):
            api = "v1beta1"
        return api, loc

    def _url(self, model: str, method: str) -> str:
        if not self.project:
            raise VertexError("No Vertex project configured (VERTEX_PROJECT).")
        api, loc = self._endpoint(model)
        host = ("aiplatform.googleapis.com" if loc == "global"
                else f"{loc}-aiplatform.googleapis.com")
        return (f"https://{host}/{api}/projects/{self.project}"
                f"/locations/{loc}/publishers/google/models/{model}:{method}")

    def _post(self, url: str, body: dict, timeout: int = 600) -> dict:
        data = json.dumps(body).encode()
        req = urllib.request.Request(url, data=data, method="POST", headers={
            "Authorization": f"Bearer {self._get_token()}",
            "Content-Type": "application/json",
        })
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")
            raise VertexError(f"HTTP {e.code} from Vertex:\n{detail[:1500]}")

    # ---- thinking config (spec §3: full thinking power) ------------------ #
    def _thinking_config(self, model: str, level: str) -> dict:
        """Return the generationConfig fragment that maxes reasoning for the
        model family. Gemini 3.x speaks `thinkingLevel`; Gemini 2.5 speaks
        `thinkingConfig.thinkingBudget` (-1 = dynamic/max)."""
        if model.startswith("gemini-3"):
            return {"thinkingConfig": {"thinkingLevel": level}}
        # Gemini 2.5 family: -1 lets the model think as much as it needs.
        budget = {"high": -1, "medium": 8192, "low": 2048, "minimal": 512}.get(level, -1)
        return {"thinkingConfig": {"thinkingBudget": budget}}

    def _all_text(self, resp: dict) -> str:
        out = []
        for cand in resp.get("candidates", []):
            for part in cand.get("content", {}).get("parts", []):
                if part.get("thought"):
                    continue
                if "text" in part:
                    out.append(part["text"])
        return "\n".join(out).strip()

    # ---- public: multimodal generate ------------------------------------ #
    def generate(
        self,
        prompt: str,
        *,
        audio_path: str | Path | None = None,
        system: str | None = None,
        model: str | None = None,
        thinking_level: str | None = None,
        json_out: bool = False,
        timeout: int = 600,
    ) -> str:
        """One Gemini call. Optionally attaches an audio part so the model
        *hears* the track. Returns the concatenated non-thought text."""
        model = model or config.GEMINI_MODEL
        level = thinking_level or config.THINKING_LEVEL
        parts: list[dict] = []
        if audio_path is not None:
            parts.append({"inlineData": {
                "mimeType": _guess_mime(audio_path), "data": _b64file(audio_path)}})
        parts.append({"text": prompt})
        gen_cfg: dict[str, Any] = self._thinking_config(model, level)
        if json_out:
            gen_cfg["responseMimeType"] = "application/json"
        body: dict[str, Any] = {
            "contents": [{"role": "user", "parts": parts}],
            "generationConfig": gen_cfg,
        }
        if system:
            body["systemInstruction"] = {"parts": [{"text": system}]}
        resp = self._post(self._url(model, "generateContent"), body, timeout)
        text = self._all_text(resp)
        if not text:
            raise VertexError(f"empty response from {model}: {json.dumps(resp)[:400]}")
        return text

    def generate_json(
        self,
        prompt: str,
        *,
        audio_path: str | Path | None = None,
        system: str | None = None,
        model: str | None = None,
        thinking_level: str | None = None,
        timeout: int = 600,
    ) -> dict:
        """generate() + strict JSON parse with defensive fence-strip and one
        retry that feeds the parse error back (spec §3 structured output)."""
        text = self.generate(prompt, audio_path=audio_path, system=system,
                             model=model, thinking_level=thinking_level,
                             json_out=True, timeout=timeout)
        try:
            return _parse_json(text)
        except ValueError as e:
            retry_prompt = (
                f"{prompt}\n\n---\nYour previous reply could not be parsed as JSON: "
                f"{e}. Respond with ONLY the valid JSON object, no prose, no code fences."
            )
            text2 = self.generate(retry_prompt, audio_path=audio_path, system=system,
                                  model=model, thinking_level=thinking_level,
                                  json_out=True, timeout=timeout)
            return _parse_json(text2)  # raises on second failure -> stage fails

    # ---- public: Lyria music (Workstream A) ----------------------------- #
    def lyria(self, prompt: str, *, seed: int | None = None,
              negative: str | None = None, model: str | None = None) -> bytes:
        model = model or config.LYRIA_MODEL
        inst: dict[str, Any] = {"prompt": prompt}
        if negative:
            inst["negative_prompt"] = negative
        if seed is not None:
            inst["seed"] = seed
        resp = self._post(self._url(model, "predict"),
                          {"instances": [inst], "parameters": {}})
        preds = resp.get("predictions", [])
        if not preds or "bytesBase64Encoded" not in preds[0]:
            raise VertexError(f"no audio returned: {json.dumps(resp)[:400]}")
        return base64.b64decode(preds[0]["bytesBase64Encoded"])


def _parse_json(text: str) -> dict:
    """Extract a JSON object from model text, stripping ``` fences and any
    leading/trailing prose."""
    s = text.strip()
    # strip ```json ... ``` fences
    fence = re.match(r"^```(?:json)?\s*(.*?)\s*```$", s, re.DOTALL)
    if fence:
        s = fence.group(1).strip()
    # if still surrounded by prose, grab the outermost {...}
    if not s.startswith("{"):
        start, end = s.find("{"), s.rfind("}")
        if start == -1 or end == -1 or end < start:
            raise ValueError("no JSON object found in response")
        s = s[start:end + 1]
    try:
        obj = json.loads(s)
    except json.JSONDecodeError as e:
        raise ValueError(f"JSON decode failed: {e}")
    if not isinstance(obj, dict):
        raise ValueError("top-level JSON is not an object")
    return obj
