"""OpenAI-compatible backend tests. The real Gemma server is on another subnet
and unreachable from CI, so we validate the client end-to-end against a local
mock that records what it receives — proving the request shape, the audio
attachment, and JSON parsing are correct before it ever talks to the real box."""
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from beatforge.llm import OpenAICompatClient, OpenAICompatError, make_llm_client

_LAST = {}  # records the last request body the mock received


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):  # silence
        pass

    def do_GET(self):
        if self.path.endswith("/models"):
            self._json({"data": [{"id": "gemma-4-12b"}]})
        else:
            self.send_error(404)

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(n) or b"{}")
        _LAST["body"] = body
        _LAST["auth"] = self.headers.get("Authorization")
        # echo a canned "analysis" as an OpenAI chat completion
        content = json.dumps({"tempo_bpm": 120, "has_kick": True,
                              "section_count": 3, "one_line": "driving synthwave"})
        self._json({"choices": [{"message": {"role": "assistant", "content": content}}]})

    def _json(self, obj):
        data = json.dumps(obj).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


@pytest.fixture
def mock_server():
    srv = HTTPServer(("127.0.0.1", 0), _Handler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    host, port = srv.server_address
    yield f"http://{host}:{port}/v1"
    srv.shutdown()


def test_factory_selects_openai(monkeypatch):
    monkeypatch.setattr("beatforge.config.LLM_BACKEND", "openai")
    assert isinstance(make_llm_client(), OpenAICompatClient)


def test_list_models(mock_server):
    c = OpenAICompatClient(base_url=mock_server, model="gemma-4-12b")
    assert "gemma-4-12b" in c.list_models()


def test_text_generate_json(mock_server):
    c = OpenAICompatClient(base_url=mock_server, model="gemma-4-12b", api_key="k")
    out = c.generate_json("describe", audio_path=None)
    assert out["tempo_bpm"] == 120 and out["has_kick"] is True
    # request carried a bearer token and a text-only user message
    assert _LAST["auth"] == "Bearer k"
    msg = _LAST["body"]["messages"][-1]
    assert msg["role"] == "user"
    assert any(p["type"] == "text" for p in msg["content"])
    assert _LAST["body"]["response_format"] == {"type": "json_object"}


def test_audio_attached_as_input_audio(mock_server, click_wav):
    """The audio part must be an OpenAI `input_audio` block with the configured
    format and non-empty base64 — the whole point of an audio-in model."""
    wav = click_wav(bpm=120.0, dur_s=4.0)
    c = OpenAICompatClient(base_url=mock_server, model="gemma-4-12b", audio_format="wav")
    c.generate_json("analyze this audio", audio_path=wav)
    parts = _LAST["body"]["messages"][-1]["content"]
    audio = [p for p in parts if p["type"] == "input_audio"]
    assert len(audio) == 1
    assert audio[0]["input_audio"]["format"] == "wav"
    assert len(audio[0]["input_audio"]["data"]) > 100  # real base64 payload


def test_unreachable_server_fails_loudly():
    c = OpenAICompatClient(base_url="http://127.0.0.1:1/v1", model="x")
    with pytest.raises(OpenAICompatError, match="cannot reach"):
        c.generate("hi")


class _SlowHandler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_POST(self):
        import time
        time.sleep(3)  # exceed the client timeout -> read timeout


@pytest.fixture
def slow_server():
    srv = HTTPServer(("127.0.0.1", 0), _SlowHandler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    host, port = srv.server_address
    yield f"http://{host}:{port}/v1"
    srv.shutdown()


def test_timeout_becomes_graceful_error(slow_server):
    """A slow/looping model (read timeout after the request is accepted) must
    surface as an OpenAICompatError, not a raw TimeoutError that crashes the run
    — this is exactly what took down the operator's `compare` on Gemma."""
    c = OpenAICompatClient(base_url=slow_server, model="gemma-4-12b", timeout=1)
    with pytest.raises(OpenAICompatError, match="timed out"):
        c.generate("analyze")
