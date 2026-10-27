import json
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from palace.config import Config
from palace.memory import DemoMemory
from palace.tokenfactory import Completion
from palace.web import make_handler


def _server(chat):
    cfg = Config.from_env({})
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(cfg, DemoMemory(), chat))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, f"http://127.0.0.1:{httpd.server_address[1]}"


@pytest.fixture
def preview():
    httpd, base = _server(None)
    yield base
    httpd.shutdown()


def _get(url):
    with urllib.request.urlopen(url, timeout=5) as r:
        return r.status, r.headers, r.read()


def _post(url, body: bytes):
    req = urllib.request.Request(url, data=body, method="POST", headers={"content-type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def test_page_favicon_and_status(preview):
    code, headers, body = _get(preview + "/")
    assert code == 200 and b"What leaves the house" in body and b'rel="icon"' in body
    assert "frame-ancestors 'none'" in headers["content-security-policy"]
    assert _get(preview + "/favicon.svg")[1]["content-type"] == "image/svg+xml"
    status = json.loads(_get(preview + "/api/status")[2])
    assert status["mode"] == "preview" and "synthetic" in status["memory"]
    version = json.loads(_get(preview + "/version")[2])
    assert "name" in version and "https://github.com/jphein/palace" in version.values(), "AGPL source offer"


def test_page_onboards_and_labels_which_model_does_what(preview):
    """The judges' asks: action first (a starter question), a 3-step card, and per-step model labels."""
    body = _get(preview + "/")[2].decode()
    assert 'id="start"' in body and body.count("<li>") >= 3, "3-step onboarding card"
    assert "STARTER" in body and "Start here: " in body, "the coordinator reversal is the first example"
    for row in ("<dt>Recall</dt>", "<dt>Routing</dt>", "<dt>Answer</dt>"):
        assert row in body, row
    assert "keyword rules, no model" in body and "on Nebius Token Factory" in body
    assert "prefers-reduced-motion" in body


def test_preview_ask_sends_nothing_but_shows_payload(preview):
    code, t = _post(preview + "/api/ask", json.dumps({"question": "When is the next county report due?"}).encode())
    assert code == 200 and t["mode"] == "preview" and t["answer"] is None
    assert t["route"]["tier"] == "nano" and t["egress"]["sent"] is False
    ids = [s["id"] for s in t["egress"]["snippets"]]
    assert "demo-019" in ids
    user_msg = t["egress"]["messages"][1]["content"]
    assert all(f"[{i}" in user_msg for i in ids)  # the panel shows the literal prompt


@pytest.mark.parametrize("body", [b"", b"not json", json.dumps({"question": ""}).encode(),
                                  json.dumps({"question": "x" * 501}).encode(), b"[1,2]"])
def test_bad_requests_are_400(preview, body):
    code, err = _post(preview + "/api/ask", body) if body else _post(preview + "/api/ask", b"")
    assert code == 400 and "error" in err


def test_live_mode_uses_chat_and_marks_sent():
    seen = {}

    def chat(tier, msgs):
        seen["tier"] = tier
        return Completion("Your next report is due October 15 [demo-019, 2026-09-04].", "fake-nemotron", 120, 30, 0.4)

    httpd, base = _server(chat)
    try:
        code, t = _post(base + "/api/ask", json.dumps({"question": "When is the next county report due?"}).encode())
        assert code == 200 and t["mode"] == "live" and t["egress"]["sent"] is True
        assert t["answer"].startswith("Your next report") and t["model"] == "fake-nemotron" and seen["tier"] == "nano"
        assert t["usage"]["prompt_tokens"] == 120 and t["cost_usd"] == pytest.approx((120 * 0.06 + 30 * 0.24) / 1e6)
        code, t = _post(base + "/api/ask", json.dumps({"question": "When is it?", "dry_run": True}).encode())
        assert t["mode"] == "preview" and t["answer"] is None
    finally:
        httpd.shutdown()


def test_model_failure_is_502_not_a_crash():
    def chat(tier, msgs):
        raise OSError("network down")

    httpd, base = _server(chat)
    try:
        code, err = _post(base + "/api/ask", json.dumps({"question": "hi there"}).encode())
        assert code == 502 and "network down" in err["error"]
        assert _get(base + "/api/status")[0] == 200
    finally:
        httpd.shutdown()


def test_hourly_cap_limits_live_calls_only():
    from palace.web import HourlyCap
    now = [1000.0]
    cap = HourlyCap(2, clock=lambda: now[0])
    assert cap.take() and cap.take() and not cap.take()
    now[0] += 3600
    assert cap.take()
    assert all(HourlyCap(0).take() for _ in range(100))

    day = HourlyCap(0, clock=lambda: now[0], per_day=3)          # daily cap alone, over a rolling 24 h
    assert day.take() and day.take()
    now[0] += 7200
    assert day.take() and not day.take() and day.refused == "daily"
    now[0] += 86400 - 7200                                       # the first two age out, the third doesn't
    assert day.take() and day.take() and not day.take()
    both = HourlyCap(1, clock=lambda: now[0], per_day=2)        # both caps: the hourly one bites first
    assert both.take() and not both.take() and both.refused == "hourly"
    now[0] += 3600
    assert both.take() and not both.take() and both.refused == "daily"

    calls = []
    cfg = Config.from_env({})
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(
        cfg, DemoMemory(), lambda tier, msgs: Completion(calls.append(tier) or "ok [demo-019]", "m", None, None), HourlyCap(1)))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{httpd.server_address[1]}"
    try:
        body = json.dumps({"question": "When is the next county report due?"}).encode()
        assert _post(base + "/api/ask", body)[0] == 200
        code, err = _post(base + "/api/ask", body)
        assert code == 429 and err["limit"] is True and len(calls) == 1 and "hourly limit" in err["error"]
        code, t = _post(base + "/api/ask", json.dumps({"question": "When?", "dry_run": True}).encode())
        assert code == 200 and t["mode"] == "preview"     # the page's fallback still works over the cap
    finally:
        httpd.shutdown()
