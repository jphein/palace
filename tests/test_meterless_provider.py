"""The Meterless Nightshift provider (docs/open-agent-design.md §4b) against a FAKE runtime. The fake is a test
fixture only and never evidence of Nightshift; the live check is `palace models` / `palace ask` on a real one."""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from palace.agent import run_turn
from palace.config import Config, ConfigError
from palace.memory import DemoMemory
from palace.providers.meterless import Nightshift, normalise_base_url, strip_think


class FakeRuntime:
    def __init__(self, token="tok", code=200, ids=("meterless/fast", "nvidia/nemotron-3-ultra-550b-a55b")):
        self.token, self.code, self.ids, self.requests = token, code, ids, []
        fake = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _send(self, code, body):
                raw = json.dumps(body).encode()
                self.send_response(code)
                self.send_header("content-length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def _auth(self):
                fake.requests.append({"path": self.path, "headers": {k.lower(): v for k, v in self.headers.items()}})
                if fake.code != 200:
                    self._send(fake.code, {"error": "x"})
                    return False
                if self.headers.get("authorization") != f"Bearer {fake.token}":
                    self._send(401, {"error": "unauthorized"})
                    return False
                return True

            def do_GET(self):
                if self._auth():
                    self._send(200, {"data": [{"id": i} for i in fake.ids]})

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["content-length"])))
                if self._auth():
                    fake.requests[-1]["body"] = body
                    self._send(200, {"model": body["model"],
                                     "choices": [{"message": {"content": "Thinking about it.</think>Due Oct 15 [demo-019]."}}],
                                     "usage": {"prompt_tokens": 50, "completion_tokens": 9},
                                     "meterless": {"receipt_id": "rcpt_req_fake0001"}})

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}"

    def __enter__(self):
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        return self

    def __exit__(self, *a):
        self.httpd.shutdown()


def _cfg(url, token="tok", **extra):
    return Config.from_env({"METERLESS_BASE_URL": url, "METERLESS_API_KEY": token, **extra})


@pytest.mark.parametrize("raw,want", [("127.0.0.1:8088", "http://127.0.0.1:8088/v1"),
                                      ("http://h:8088/", "http://h:8088/v1"), ("http://h:8088/v1/", "http://h:8088/v1"),
                                      ("http://h:8088/v1/v1", "http://h:8088/v1")])
def test_base_url_is_normalised(raw, want):
    assert normalise_base_url(raw) == want


@pytest.mark.parametrize("raw,want", [("<think>hm</think>Yes.", "Yes."), ("tail of thought.</think>2 + 2 = 4.", "2 + 2 = 4."),
                                      ("Plain answer [demo-001].", "Plain answer [demo-001].")])
def test_think_text_is_stripped(raw, want):
    assert strip_think(raw) == want


def test_meterless_is_primary_when_configured():
    assert Config.from_env({}).provider == "tokenfactory"
    c = _cfg("http://h:8088")
    assert c.provider == "meterless" and c.active_models["nano"].startswith("nvidia/") and c.model_host == "h"
    assert Config.from_env({"METERLESS_BASE_URL": "http://h:8088", "PALACE_PROVIDER": "tokenfactory"}).provider == "tokenfactory"
    with pytest.raises(ConfigError):
        Config.from_env({"PALACE_PROVIDER": "openai"})


def test_placeholder_token_is_rejected():
    with pytest.raises(ConfigError, match="rt-local"):
        Nightshift(_cfg("http://h:8088", token="rt-local"))


def test_chat_sends_the_contract_headers_and_the_pinned_model():
    with FakeRuntime() as f:
        c = Nightshift(_cfg(f.url)).chat("ultra", [{"role": "user", "content": "q"}])
    req = f.requests[-1]
    assert req["path"] == "/v1/chat/completions" and req["headers"]["meterless-app"] == "palace"
    assert req["headers"]["meterless-scope"] == "user" and req["body"]["model"] == "nvidia/nemotron-3-ultra-550b-a55b"
    assert c.text == "Due Oct 15 [demo-019]." and c.receipt_id == "rcpt_req_fake0001" and c.provider == "meterless"


def test_status_follows_the_provider_contract():
    with FakeRuntime() as f:
        assert Nightshift(_cfg(f.url)).status() == "online"
        assert "meterless-scope" not in f.requests[-1]["headers"], "scope is for chat requests only"
        assert Nightshift(_cfg(f.url, token="wrong")).status() == "unauthorized"
    with FakeRuntime(ids=("some/other",)) as f:
        assert Nightshift(_cfg(f.url)).status() == "offline", "200 without meterless routes is not online"
    with FakeRuntime(code=500) as f:
        assert Nightshift(_cfg(f.url)).status() == "offline"


def test_turn_records_the_receipt_and_states_no_palace_cost():
    with FakeRuntime() as f:
        t = run_turn("When is the next county report due?", DemoMemory(), Nightshift(_cfg(f.url)).chat)
    assert t.provider == "meterless" and t.receipt_id == "rcpt_req_fake0001" and t.cost_usd is None
    assert t.answer == "Due Oct 15 [demo-019]."
