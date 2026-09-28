"""Memory backends. DaemonMemory talks to a palace-daemon (MIT, github.com/rboarescu/palace-daemon)
over HTTP; DemoMemory is an offline stand-in over demo/seed.jsonl so the project runs, and its tests
pass, with no server at all. Both return the same Memory records."""
from __future__ import annotations

import json
import math
import re
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from .config import Config

SEED = Path(__file__).resolve().parent.parent / "demo" / "seed.jsonl"
ROOMS = {"architecture", "decisions", "problems", "planning", "sessions", "references", "discoveries"}


@dataclass(frozen=True)
class Memory:
    id: str
    date: str | None
    wing: str
    room: str
    text: str
    score: float

    def cite(self) -> str:
        return f"[{self.id}{', ' + self.date if self.date else ''}]"


class MemoryBackend(Protocol):
    def search(self, query: str, limit: int = 8) -> list[Memory]: ...
    def write(self, text: str, wing: str, room: str = "discoveries") -> str: ...


_WORD = re.compile(r"[a-z0-9']+")
STOP = set("a an the and or of to in on for with is are was were be been i my me we our it this that what when "
           "did do does have has had about from at by as".split())


def _terms(s: str) -> list[str]:
    return [w for w in _WORD.findall(s.lower()) if w not in STOP]


class DemoMemory:
    """BM25 over the synthetic seed. Deterministic and dependency-free."""

    def __init__(self, path: Path = SEED):
        self.rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
        self.docs = [_terms(r["text"] + " " + r.get("wing", "")) for r in self.rows]
        self.avg = sum(map(len, self.docs)) / max(1, len(self.docs))
        self.df: dict[str, int] = {}
        for d in self.docs:
            for t in set(d):
                self.df[t] = self.df.get(t, 0) + 1

    def search(self, query: str, limit: int = 8) -> list[Memory]:
        q = _terms(query)
        n, k1, b = len(self.docs), 1.4, 0.75
        scored = []
        for row, doc in zip(self.rows, self.docs):
            s = 0.0
            for t in q:
                f = doc.count(t)
                if f:
                    idf = math.log(1 + (n - self.df[t] + 0.5) / (self.df[t] + 0.5))
                    s += idf * f * (k1 + 1) / (f + k1 * (1 - b + b * len(doc) / self.avg))
            if s > 0:
                scored.append((s, row))
        scored.sort(key=lambda x: -x[0])
        return [Memory(r["id"], r.get("date"), r["wing"], r["room"], r["text"], round(s, 3)) for s, r in scored[:limit]]

    def write(self, text: str, wing: str, room: str = "discoveries") -> str:
        rid = f"demo-{len(self.rows) + 1:03d}"
        row = {"id": rid, "date": None, "wing": wing, "room": room if room in ROOMS else "discoveries", "text": text}
        self.rows.append(row)
        self.docs.append(_terms(text + " " + wing))
        for t in set(self.docs[-1]):
            self.df[t] = self.df.get(t, 0) + 1
        self.avg = sum(map(len, self.docs)) / len(self.docs)
        return rid


class DaemonMemory:
    """GET /search?q=&limit=  and  POST /memory {content, wing, room}, with header X-API-Key."""

    def __init__(self, cfg: Config, timeout: float = 20.0):
        cfg.check_palace_url()  # belt and braces: never a real palace
        assert cfg.palace_url
        self.base = cfg.palace_url.rstrip("/")
        self.key = cfg.palace_api_key
        self.timeout = timeout

    def _req(self, method: str, path: str, body: dict | None = None) -> dict:
        req = urllib.request.Request(self.base + path, method=method,
                                     data=None if body is None else json.dumps(body).encode(),
                                     headers={"content-type": "application/json", **({"x-api-key": self.key} if self.key else {})})
        with urllib.request.urlopen(req, timeout=self.timeout) as r:
            return json.loads(r.read() or b"{}")

    def search(self, query: str, limit: int = 8) -> list[Memory]:
        data = self._req("GET", "/search?" + urllib.parse.urlencode({"q": query, "limit": limit}))
        hits = data.get("results") or data.get("hits") or []
        out = []
        for h in hits:
            meta = h.get("metadata") or {}
            out.append(Memory(
                id=str(h.get("id") or h.get("drawer_id") or meta.get("drawer_id") or "?"),
                date=(meta.get("date") or meta.get("filed_at") or h.get("date") or None),
                wing=h.get("wing") or meta.get("wing") or "?",
                room=h.get("room") or meta.get("room") or "?",
                text=h.get("text") or h.get("content") or h.get("document") or "",
                score=float(h.get("score") or h.get("similarity") or 0.0),
            ))
        return out

    def write(self, text: str, wing: str, room: str = "discoveries") -> str:
        data = self._req("POST", "/memory", {"content": text, "wing": wing, "room": room})
        return str(data.get("drawer_id") or data.get("id") or "")


def open_memory(cfg: Config) -> MemoryBackend:
    return DaemonMemory(cfg) if cfg.palace_url else DemoMemory()
