"""palace serve: a small web chat with a "what leaves the house" panel (stdlib only).

Routes
  GET  /                 the chat page (palace/static/index.html)
  GET  /favicon.svg      icon
  GET  /version          realm-sigil version document (if the optional realm_sigil package is installed)
  GET  /api/status       mode (live | preview), memory backend, model ids, model host
  POST /api/ask          {"question": "...", "dry_run": false} -> the turn as JSON

PALACE_MAX_ASKS_PER_HOUR caps LIVE model calls across all visitors (a public demo must not drain the credits);
over the cap, /api/ask answers 429. Unset or 0 means no cap. Preview (dry-run) asks are never capped.

With no NEBIUS_API_KEY the server runs in PREVIEW mode: it recalls and routes, and shows exactly what
WOULD be sent to Token Factory, but makes no model call. Binds to 127.0.0.1 unless --host says otherwise."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from collections import deque
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Callable
from urllib.parse import urlparse

from . import __version__
from .agent import Turn, run_turn
from .config import Config
from .memory import DaemonMemory, MemoryBackend, open_memory

STATIC = Path(__file__).resolve().parent / "static"
MAX_QUESTION = 500
MAX_BODY = 8 * 1024
REPO = "https://github.com/jphein/palace-nemotron"  # GitHub redirects after a transfer to techempower-org
STARTED = time.time()


def turn_to_dict(turn: Turn, cfg: Config, live: bool) -> dict:
    """Everything the UI shows. `sent` is the literal payload that went (or would go) to the model."""
    by_id = {m.id: m for m in turn.memories}
    return {
        "question": turn.question,
        "mode": "live" if live else "preview",
        "route": {"tier": turn.route.tier, "reason": turn.route.reason, "model": cfg.models[turn.route.tier]},
        "answer": turn.answer,
        "model": turn.model,
        "usage": turn.usage,
        "cost_usd": turn.cost_usd,
        "memories": [{"id": m.id, "date": m.date, "wing": m.wing, "room": m.room, "text": m.text, "score": m.score}
                     for m in turn.memories],
        "egress": {
            "destination": urlparse(cfg.base_url).hostname,
            "sent": live,
            "snippets": [{**e, "date": by_id[e["id"]].date} for e in turn.egress],
            "total_chars": sum(len(msg["content"]) for msg in turn.prompt),
            "messages": turn.prompt,
        },
    }


def _git(*args: str) -> str:
    try:
        return subprocess.run(["git", *args], cwd=STATIC.parent.parent, capture_output=True, text=True,
                              timeout=2).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def version_doc() -> dict:
    h = _git("rev-parse", "--short", "HEAD") or "dev"
    try:
        from realm_sigil import version_dict  # optional; LGPL-3.0, github.com/jphein/sigil.realm.watch
    except ImportError:
        return {"name": "palace-nemotron", "version": __version__, "hash": h}
    return version_dict("palace-nemotron", "Private personal AI on Nemotron via Nebius Token Factory", "fantasy", REPO,
                        hash=h, branch=_git("rev-parse", "--abbrev-ref", "HEAD") or "unknown",
                        dirty=bool(_git("status", "--porcelain")), started=time.strftime(
                            "%Y-%m-%dT%H:%M:%SZ", time.gmtime(STARTED)), uptime=int(time.time() - STARTED),
                        runtime=f"python {sys.version.split()[0]}", pid=os.getpid())


class HourlyCap:
    """At most `limit` events in any rolling hour (thread-safe). limit <= 0 means unlimited."""

    def __init__(self, limit: int, clock: Callable[[], float] = time.monotonic):
        self.limit, self.clock, self.times, self.lock = limit, clock, deque(), threading.Lock()

    def take(self) -> bool:
        if self.limit <= 0:
            return True
        with self.lock:
            now = self.clock()
            while self.times and now - self.times[0] >= 3600:
                self.times.popleft()
            if len(self.times) >= self.limit:
                return False
            self.times.append(now)
            return True


def make_handler(cfg: Config, memory: MemoryBackend, chat: Callable | None,
                 cap: HourlyCap | None = None) -> type[BaseHTTPRequestHandler]:
    live = chat is not None
    cap = cap or HourlyCap(0)
    status = {
        "mode": "live" if live else "preview",
        "memory": "palace-daemon" if isinstance(memory, DaemonMemory) else "synthetic demo palace (offline)",
        "models": cfg.models,
        "model_host": urlparse(cfg.base_url).hostname,
        "version": __version__,
    }

    class Handler(BaseHTTPRequestHandler):
        server_version = f"palace/{__version__}"

        def log_message(self, fmt, *args):  # quiet; one line per request to stderr
            sys.stderr.write(f"palace-web {self.command} {self.path} {args[1] if len(args) > 1 else ''}\n")

        def _send(self, code: int, body: bytes, ctype: str) -> None:
            self.send_response(code)
            self.send_header("content-type", ctype)
            self.send_header("content-length", str(len(body)))
            self.send_header("x-content-type-options", "nosniff")
            self.send_header("referrer-policy", "no-referrer")
            self.send_header("content-security-policy",
                             "default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'; "
                             "img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, code: int, obj: dict) -> None:
            self._send(code, json.dumps(obj).encode(), "application/json")

        def do_GET(self):
            path = urlparse(self.path).path
            if path in ("/", "/index.html"):
                return self._send(200, (STATIC / "index.html").read_bytes(), "text/html; charset=utf-8")
            if path == "/favicon.svg":
                return self._send(200, (STATIC / "favicon.svg").read_bytes(), "image/svg+xml")
            if path == "/api/status":
                return self._json(200, status)
            if path == "/version":
                return self._json(200, version_doc())
            return self._json(404, {"error": "not found"})

        def do_POST(self):
            if urlparse(self.path).path != "/api/ask":
                return self._json(404, {"error": "not found"})
            try:
                n = int(self.headers.get("content-length") or 0)
            except ValueError:
                n = -1
            if n <= 0 or n > MAX_BODY:
                return self._json(HTTPStatus.BAD_REQUEST, {"error": "body missing or too large"})
            try:
                req = json.loads(self.rfile.read(n))
                q = str(req.get("question", "")).strip()
            except (ValueError, AttributeError):
                return self._json(HTTPStatus.BAD_REQUEST, {"error": "expected JSON {question}"})
            if not q or len(q) > MAX_QUESTION:
                return self._json(HTTPStatus.BAD_REQUEST, {"error": f"question must be 1-{MAX_QUESTION} characters"})
            use_chat = None if req.get("dry_run") else chat
            if use_chat is not None and not cap.take():
                return self._json(HTTPStatus.TOO_MANY_REQUESTS,
                                  {"error": "This demo's hourly limit on model calls is used up; please try again later.",
                                   "limit": True})
            try:
                turn = run_turn(q, memory, use_chat, prices=cfg.prices)
            except Exception as e:  # model/network failure: report, don't crash the server
                return self._json(HTTPStatus.BAD_GATEWAY, {"error": f"{type(e).__name__}: {e}"})
            return self._json(200, turn_to_dict(turn, cfg, live=use_chat is not None))

    return Handler


def build_chat(cfg: Config) -> Callable | None:
    if not cfg.api_key:
        return None
    from .tokenfactory import TokenFactory
    tf = TokenFactory(cfg)
    return tf.chat


def serve(host: str = "127.0.0.1", port: int = 8765, cfg: Config | None = None) -> None:
    cfg = cfg or Config.from_env()
    memory = open_memory(cfg)
    chat = build_chat(cfg)
    try:
        limit = int(os.environ.get("PALACE_MAX_ASKS_PER_HOUR") or 0)
    except ValueError:
        limit = 0
    httpd = ThreadingHTTPServer((host, port), make_handler(cfg, memory, chat, HourlyCap(limit)))
    mode = "LIVE (Token Factory)" if chat else "PREVIEW (no NEBIUS_API_KEY: nothing is sent)"
    print(f"palace: http://{host}:{port}/  mode={mode}  cap={limit or 'none'}/hour", file=sys.stderr)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
