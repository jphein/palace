"""H-MEM, Meterless's memory engine, implemented in Python from its spec (github.com/meterless/meterless,
engines/hmem/AGENTS.md, Apache-2.0; read at commit 1742dec, 2026-10-19). Stdlib only.

Implemented, and checked by the spec's own conformance vectors (tests/test_hmem_conformance.py):
- the memory record: `source` is mandatory (a record without one is rejected), with provenance and lineage
  fields (`supersedes`, `supersededBy`, `derivedFrom`, `relatedTo`);
- retrieval: the canonical eight-signal hybrid score, clamped, times confidence;
- feedback: helpful +0.05 (and +1 access), not_helpful -0.03, wrong -0.20 plus a `review` tag;
- the trust ledger: append-only, with previous and new state (optionally a JSONL file);
- conflicts: opposing-phrase detection, an auto-resolve gate at decision confidence >= 0.70, and the loser
  marked `supersededBy`, never deleted;
- sleep: preview first, with guardrails, then execute with a backup and restore;
- dreaming: proposals only; nothing becomes memory before approval, and approval adds lineage.

Not implemented: LLM mining (Palace's memories come from palace-daemon), chat/goal-run scoping, and the
dream "domain" proposal's model-written text. Palace's embedder is a hashed bag of words, which the spec allows:
absolute scores depend on the embedder, and the vectors assert only order.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import re
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable

DAY_MS = 24 * 60 * 60 * 1000
LAYER_WEIGHT = {"long_term": 1.0, "working": 0.8, "short_term": 0.6}
FEEDBACK = {"helpful": 0.05, "not_helpful": -0.03, "wrong": -0.20}
ACTIONS = {"create", "read", "update", "delete", "feedback", "promote", "demote", "merge", "conflict_detected",
           "conflict_resolved", "sleep_consolidate", "sleep_archive", "sleep_synthesize", "dream_proposed",
           "dream_approved", "dream_rejected", "restore"}
DEFAULTS = {"top_n": 5, "threshold": 0.35, "consolidate_days": 7, "archive_days": 30, "archive_max_access": 2,
            "synth_cosine": 0.82, "dream_min_cluster": 2, "dream_relatedness": 0.35, "dream_max_per_type": 8,
            "auto_resolve": 0.70, "entity_cap": 10, "related_cap": 5, "recency_tau_days": 14}
OPPOSITES = [("always", "never"), ("enable", "disable"), ("before", "after"), ("yes", "no"), ("on", "off"),
             ("allow", "forbid"), ("hire", "no hire")]
UPDATE_LANGUAGE = re.compile(r"\b(revers\w*|no longer|instead|changed?|cancel\w*|replac\w*|switch\w*|now)\b", re.I)
_TOKEN = re.compile(r"[a-z0-9][a-z0-9'-]*")
STOP = set("a an the and or of to in on for with is are was were be been i my me we our it this that what when "
           "did do does have has had about from at by as so but not no can can't will would should".split())
DOMAINS = {"work": "grant report county board decision hire coordinator budget donations staff meeting",
           "tech": "laptop device ssd smart repair hotspot api docker deploy python telemetry",
           "personal": "mom birthday dinner dentist health garden"}


def _tokens(text: str) -> list[str]:
    return [t for t in _TOKEN.findall(text.lower()) if t not in STOP]


def _embed(text: str, dim: int = 256) -> list[float]:
    v = [0.0] * dim
    for t in _tokens(text):
        v[int(hashlib.md5(t.encode()).hexdigest(), 16) % dim] += 1.0
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / n for x in v]


def _cos(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


def _jaccard(a, b) -> float:
    a, b = set(a), set(b)
    return len(a & b) / len(a | b) if a | b else 0.0


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


def _domain(text: str, tags=()) -> str:
    toks = set(_tokens(text)) | {t.split(":", 1)[-1] for t in tags}
    scores = {d: len(toks & set(words.split())) for d, words in DOMAINS.items()}
    best = max(scores, key=scores.get)
    return best if scores[best] else "general"


def _entities(text: str, cap: int) -> list[str]:
    # Capitalised names and known nouns, normalised; a heuristic, as the spec allows.
    names = re.findall(r"\b[A-Z][a-z]+(?:\s[A-Z][a-z]+)?\b", text)
    known = [t for t in _tokens(text) if any(t in w.split() for w in DOMAINS.values())]
    return list(dict.fromkeys([n.lower() for n in names] + known))[:cap]


@dataclass
class Memory:
    id: str
    content: str
    source: str
    confidence: float
    type: str = "general"
    layer: str = "working"
    timestamp: int = 0
    lastAccessed: int = 0
    accessCount: int = 0
    tags: list[str] = field(default_factory=list)
    provenance: dict = field(default_factory=dict)
    domain: str = "general"
    entities: list[str] = field(default_factory=list)
    relatedTo: list[str] = field(default_factory=list)
    supersedes: str | None = None
    supersededBy: str | None = None
    derivedFrom: list[str] = field(default_factory=list)
    embedding: list[float] = field(default_factory=list, repr=False)

    def state(self) -> dict:
        d = asdict(self)
        d.pop("embedding")
        return d


class Ledger:
    """Append-only. Entries are never rewritten or pruned; with a path, each one is also appended to a JSONL file."""

    def __init__(self, clock: Callable[[], int], path: Path | None = None):
        self.clock, self.path, self.entries = clock, Path(path) if path else None, []

    def log(self, memory_id: str, action: str, actor: str = "palace", previous: dict | None = None,
            new: dict | None = None, **details) -> dict:
        assert action in ACTIONS, action
        e = {"memoryId": memory_id, "action": action, "actor": actor, "timestamp": self.clock(),
             "previousState": previous, "newState": new, "details": details}
        self.entries.append(e)
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.path, "a") as f:
                f.write(json.dumps(e) + "\n")
        return e

    def history(self, memory_id: str) -> list[dict]:
        return [e for e in self.entries if e["memoryId"] == memory_id]

    def stats(self) -> dict:
        out: dict[str, int] = {}
        for e in self.entries:
            out[e["action"]] = out.get(e["action"], 0) + 1
        return out


class Store:
    def __init__(self):
        self.records: dict[str, Memory] = {}

    def get(self, mid: str) -> Memory | None:
        return self.records.get(mid)

    def all(self) -> list[Memory]:
        return list(self.records.values())


@dataclass
class Scored:
    memory: Memory
    score: float
    signals: dict


@dataclass
class QueryResult:
    memories: list[Scored]
    retrievalReason: str
    strategy: str


class Conflicts:
    def __init__(self, h: "HMEM"):
        self.h, self.open, self.queue = h, [], []

    def scan(self) -> list[dict]:
        found, recs = [], self.h.store.all()
        for i, a in enumerate(recs):
            for b in recs[i + 1:]:
                if a.supersedes == b.id or b.supersedes == a.id or a.supersededBy == b.id or b.supersededBy == a.id:
                    continue        # an intended replacement, not a conflict
                pair = self._opposed(a.content, b.content)
                if not pair:
                    continue
                strip = lambda s: [t for t in _tokens(s) if t not in pair]  # noqa: E731
                sim = _jaccard(strip(a.content), strip(b.content))
                if sim < 0.5:
                    continue
                conf = _clamp01(0.5 + 0.3 * sim + (0.1 if set(a.entities) & set(b.entities) else 0)
                                + (0.1 if a.domain == b.domain else 0))
                c = {"id": f"conflict_{uuid.uuid4().hex[:8]}", "memoryA": a.id, "memoryB": b.id,
                     "reason": f"opposing phrases {pair[0]}/{pair[1]} on similar content", "confidence": round(conf, 3),
                     "status": "open"}
                found.append(c)
                self.h.ledger.log(a.id, "conflict_detected", details_conflict=c["id"], other=b.id)
        self.open += found
        return found

    @staticmethod
    def _opposed(x: str, y: str):
        tx, ty = set(_tokens(x)) | set(x.lower().split()), set(_tokens(y)) | set(y.lower().split())
        for p, q in OPPOSITES:
            if (p in tx and q in ty and q not in tx) or (q in tx and p in ty and p not in tx):
                return (p, q)
        return None

    def _merit(self, m: Memory) -> float:
        return (0.35 * m.confidence + 0.2 * (m.timestamp / max(1, self.h.clock())) + 0.15 * min(1, m.accessCount / 10)
                + 0.15 * min(1, len(m.content) / 200) + 0.15 * (1.0 if m.source == "user_correction" else 0.5))

    def autoResolve(self, conflict: dict) -> str:
        a, b = self.h.store.get(conflict["memoryA"]), self.h.store.get(conflict["memoryB"])
        ma, mb = self._merit(a), self._merit(b)
        decision = _clamp01(0.5 + abs(ma - mb) * 1.5)
        if decision < DEFAULTS["auto_resolve"]:
            conflict["status"] = "queued"
            self.queue.append(conflict)
            return "queued"
        winner, loser = (a, b) if ma >= mb else (b, a)
        prev = loser.state()
        loser.supersededBy = winner.id
        conflict.update(status="resolved", strategy="keep_a" if winner is a else "keep_b",
                        decisionConfidence=round(decision, 3))
        self.h.ledger.log(loser.id, "conflict_resolved", previous=prev, new=loser.state(), conflict=conflict["id"],
                          winner=winner.id)
        return "resolved"


class Sleep:
    def __init__(self, h: "HMEM"):
        self.h, self.backups = h, {}

    def _referenced(self, m: Memory) -> bool:
        return any(m.id in o.relatedTo or m.id in o.derivedFrom or o.supersedes == m.id or o.supersededBy == m.id
                   for o in self.h.store.all() if o.id != m.id)

    def _protected(self, m: Memory) -> bool:
        return bool(m.supersedes or m.derivedFrom or len(m.relatedTo) >= 3 or m.source == "dreaming")

    def preview(self) -> dict:
        now, recs = self.h.clock(), self.h.store.all()
        consolidate = [m.id for m in recs if m.layer == "short_term"
                       and now - m.lastAccessed >= DEFAULTS["consolidate_days"] * DAY_MS]
        archive = [m.id for m in recs if now - m.timestamp >= DEFAULTS["archive_days"] * DAY_MS
                   and m.accessCount <= DEFAULTS["archive_max_access"] and not self._referenced(m)
                   and not self._protected(m) and m.id not in consolidate]
        synth, seen = [], set()
        for i, a in enumerate(recs):
            group = [a.id] + [b.id for b in recs[i + 1:] if b.id not in seen
                              and _cos(a.embedding, b.embedding) >= DEFAULTS["synth_cosine"]]
            if len(group) > 1 and a.id not in seen:
                synth.append(group)
                seen |= set(group)
        return {"toConsolidate": consolidate, "toArchive": archive, "toSynthesize": synth}

    def execute(self, preview: dict) -> dict:
        backup = f"backup_{uuid.uuid4().hex[:10]}"
        self.backups[backup] = copy.deepcopy(self.h.store.records)
        log = []
        for mid in preview["toConsolidate"]:
            m = self.h.store.get(mid)
            if m:
                prev = m.state()
                m.layer = "long_term"
                self.h.ledger.log(mid, "sleep_consolidate", previous=prev, new=m.state())
                log.append(("consolidate", mid))
        for mid in preview["toArchive"]:
            m = self.h.store.get(mid)
            if m and not self._protected(m):      # re-checked at execute time: the guardrail is not advisory
                self.h.ledger.log(mid, "sleep_archive", previous=m.state())
                del self.h.store.records[mid]
                log.append(("archive", mid))
        for group in preview["toSynthesize"]:
            srcs = [self.h.store.get(i) for i in group if self.h.store.get(i) and not self._protected(self.h.store.get(i))]
            if len(srcs) < 2:
                continue
            merged = self.h.add(content=max((s.content for s in srcs), key=len), source="sleep_synthesis",
                                layer="long_term", type=srcs[0].type, confidence=max(s.confidence for s in srcs),
                                tags=sorted({t for s in srcs for t in s.tags}), derivedFrom=[s.id for s in srcs])
            for s in srcs:
                self.h.ledger.log(s.id, "sleep_synthesize", previous=s.state(), into=merged.id)
                del self.h.store.records[s.id]
            log.append(("synthesize", merged.id))
        return {"backupId": backup, "actions": log,
                "counts": {k: sum(1 for a, _ in log if a == k) for k in ("consolidate", "archive", "synthesize")}}

    def restore(self, backup_id: str) -> None:
        self.h.store.records = copy.deepcopy(self.backups[backup_id])
        self.h.ledger.log("*", "restore", backup=backup_id)


class Dreaming:
    def __init__(self, h: "HMEM"):
        self.h, self.proposals = h, {}

    def _related(self, a: Memory, b: Memory) -> float:
        return (0.4 * _cos(a.embedding, b.embedding) + 0.15 * _jaccard(a.tags, b.tags)
                + 0.15 * (a.domain == b.domain) + 0.15 * (a.type == b.type) + 0.15 * _jaccard(a.entities, b.entities))

    def dream(self) -> list[dict]:
        recs, clusters, used = self.h.store.all(), [], set()
        for a in recs:
            if a.id in used:
                continue
            group = [a] + [b for b in recs if b.id != a.id and b.id not in used
                           and self._related(a, b) >= DEFAULTS["dream_relatedness"]]
            if len(group) >= DEFAULTS["dream_min_cluster"]:
                clusters.append(group)
                used |= {m.id for m in group}
        out = [self._propose("insight", "Across these memories: " + "; ".join(m.content for m in g), g)
               for g in clusters[:DEFAULTS["dream_max_per_type"]]]
        # Spec §7.3 step 5: invariants come from preference, personal and correction signals, not from clusters.
        signals = [m for m in recs if m.type in ("preference", "personal") or m.source == "user_correction"]
        if len(signals) >= DEFAULTS["dream_min_cluster"]:
            for i in range(0, min(len(signals), DEFAULTS["dream_max_per_type"] * 4), 4):
                g = signals[i:i + 4]
                if len(g) >= DEFAULTS["dream_min_cluster"]:
                    out.append(self._propose("invariant", "Stable preference: " + "; ".join(m.content for m in g), g))
        return out

    def _propose(self, kind: str, text: str, group: list[Memory]) -> dict:
        ids = [m.id for m in group]
        p = {"id": f"dream_{uuid.uuid4().hex[:8]}", "type": kind, "content": text, "sources": ids, "status": "proposed"}
        self.proposals[p["id"]] = p
        self.h.ledger.log(p["id"], "dream_proposed", kind=kind, sources=ids)
        return p

    def approve(self, pid: str) -> Memory | None:
        p = self.proposals[pid]
        p["status"] = "approved"
        m = self.h.add(content=p["content"], source="dreaming", layer="long_term",
                       type="preference" if p["type"] == "invariant" else "factual", derivedFrom=list(p["sources"]))
        self.h.ledger.log(pid, "dream_approved", created=m.id)
        return m

    def reject(self, pid: str) -> None:
        self.proposals[pid]["status"] = "rejected"
        self.h.ledger.log(pid, "dream_rejected")


class HMEM:
    def __init__(self, clock: Callable[[], int] | None = None, ledger_path: Path | None = None):
        self.clock = clock or (lambda: int(time.time() * 1000))
        self.store = Store()
        self.ledger = Ledger(self.clock, ledger_path)
        self.conflicts, self.sleep, self.dreaming = Conflicts(self), Sleep(self), Dreaming(self)

    def add(self, content: str, source: str, confidence: float = 0.7, layer: str = "working", type: str = "general",
            tags: list[str] | None = None, derivedFrom: list[str] | None = None, id: str | None = None,
            timestamp: int | None = None, origin: str = "import", label: str | None = None) -> Memory:
        if not source or not str(source).strip():
            raise ValueError("H-MEM: a memory record needs a source")
        if not content or not content.strip():
            raise ValueError("H-MEM: a memory record needs content")
        now = self.clock()
        ts = now if timestamp is None else timestamp
        tags = list(tags or [])
        m = Memory(id=id or f"mem_{uuid.uuid4().hex[:12]}", content=content, source=source,
                   confidence=_clamp01(confidence), type=type, layer=layer, timestamp=ts, lastAccessed=ts, tags=tags,
                   provenance={"origin": origin, "learnedAt": ts, "label": label or f"from {source}"},
                   domain=_domain(content, tags), entities=_entities(content, DEFAULTS["entity_cap"]),
                   derivedFrom=list(derivedFrom or []), embedding=_embed(content))
        self.store.records[m.id] = m
        self.ledger.log(m.id, "create", new=m.state())
        return m

    def feedback(self, mid: str, kind: str) -> Memory:
        m = self.store.records[mid]
        prev = m.state()
        m.confidence = _clamp01(round(m.confidence + FEEDBACK[kind], 10))
        if kind == "helpful":
            m.accessCount += 1
        if kind == "wrong" and "review" not in m.tags:
            m.tags.append("review")
        self.ledger.log(mid, "feedback", previous=prev, new=m.state(), kind=kind)
        return m

    def link_supersession(self) -> list[tuple[str, str]]:
        """Enrichment: a newer record in the same domain that uses update language ("reversed", "instead", "no
        longer") about the same things supersedes the older one. The older one is kept and penalised in ranking."""
        out, recs = [], sorted(self.store.all(), key=lambda m: m.timestamp)
        for i, new in enumerate(recs):
            if not UPDATE_LANGUAGE.search(new.content):
                continue
            nt = set(_tokens(new.content))
            for old in reversed(recs[:i]):
                ot = set(_tokens(old.content))
                overlap = len(nt & ot) / max(1, min(len(nt), len(ot)))
                if old.supersededBy or old.timestamp >= new.timestamp or overlap < 0.3 or old.domain != new.domain:
                    continue
                if not (set(old.tags) & set(new.tags)):
                    continue
                prev = old.state()
                old.supersededBy, new.supersedes = new.id, old.id
                self.ledger.log(old.id, "update", previous=prev, new=old.state(), reason="superseded", by=new.id)
                out.append((old.id, new.id))
                break
        return out

    def query(self, text: str, threshold: float | None = None, topN: int | None = None,
              log_reads: bool = True) -> QueryResult:
        threshold = DEFAULTS["threshold"] if threshold is None else threshold
        topN = DEFAULTS["top_n"] if topN is None else topN
        now, q_emb, q_tok = self.clock(), _embed(text), _tokens(text)
        q_top, q_dom, q_ent = q_tok[:8], _domain(text), _entities(text, DEFAULTS["entity_cap"])
        tau = DEFAULTS["recency_tau_days"] * DAY_MS
        scored = []
        for m in self.store.all():
            s = {"semantic": _clamp01(_cos(q_emb, m.embedding)), "keyword": _jaccard(q_top, _tokens(m.content)),
                 "tag": _jaccard(q_tok, [t.split(":", 1)[-1] for t in m.tags]) if m.tags else 0.0,
                 "domain": 1.0 if m.domain == q_dom else 0.0, "entity": _jaccard(q_ent, m.entities),
                 "layer": LAYER_WEIGHT[m.layer], "recency": math.exp(-max(0, now - m.lastAccessed) / tau),
                 "superseded": 1.0 if m.supersededBy else 0.0}
            raw = (0.35 * s["semantic"] + 0.20 * s["keyword"] + 0.10 * s["tag"] + 0.10 * s["domain"]
                   + 0.15 * s["entity"] + 0.05 * s["layer"] + 0.05 * s["recency"] - 0.20 * s["superseded"])
            score = _clamp01(raw) * m.confidence
            if score >= threshold:
                scored.append(Scored(m, round(score, 6), s))
        scored.sort(key=lambda x: x.score, reverse=True)
        top = scored[:topN]
        if log_reads:
            for x in top:
                self.ledger.log(x.memory.id, "read", score=x.score)
        suppressed = [x.memory.id for x in top if x.memory.supersededBy]
        reason = f"{len(top)} of {len(self.store.records)} memories at or above {threshold}" + (
            f"; superseded and penalised: {', '.join(suppressed)}" if suppressed else "")
        return QueryResult(top, reason, "comprehensive" if len(top) > 3 else "minimal")
