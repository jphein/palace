"""Evals over the synthetic palace: does recall find the right memories, does the router pick the right
tier, and (live) does the answer cite only memories it was given, and abstain when none apply?

Offline mode needs no network and scores recall@k and tier accuracy. Live mode also runs each question
through Nemotron and scores citation validity, expected-citation hits and abstention."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Callable

from .agent import run_turn
from .config import DEFAULT_PRICES
from .memory import MemoryBackend
from .tokenfactory import Completion

QUESTIONS = Path(__file__).resolve().parent.parent / "evals" / "questions.jsonl"
_CITE = re.compile(r"[\[【](demo-\d+)")


def load_questions(path: Path = QUESTIONS) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def cited_ids(answer: str) -> list[str]:
    return list(dict.fromkeys(_CITE.findall(answer or "")))


def _mean(xs: list[bool]) -> float | None:
    return round(sum(xs) / len(xs), 3) if xs else None


def run_eval(questions: list[dict], memory: MemoryBackend, chat: Callable[[str, list[dict]], Completion] | None,
             k: int = 8, prices: dict[str, tuple[float, float]] = DEFAULT_PRICES) -> dict:
    rows = []
    for q in questions:
        turn = run_turn(q["question"], memory, chat, limit=k, prices=prices)
        got = [m.id for m in turn.memories]
        expect = q["expect_ids"]
        row = {"id": q["id"], "question": q["question"], "tier": turn.route.tier, "expect_tier": q["expect_tier"],
               "tier_ok": turn.route.tier == q["expect_tier"], "reason": turn.route.reason, "recalled_ids": got,
               "recalled": all(e in got for e in expect) if expect else None, "should_abstain": not expect}
        if chat is not None:
            cites = cited_ids(turn.answer)
            invented = [c for c in cites if c not in got]
            row.update(answer=turn.answer, model=turn.model, usage=turn.usage, cost_usd=turn.cost_usd,
                       cited_ids=cites, invented_ids=invented, citation_valid=not invented,
                       expected_cited=any(e in cites for e in expect) if expect else None,
                       abstained=not cites if not expect else None)
        rows.append(row)

    answerable = [r for r in rows if not r["should_abstain"]]
    summary = {"mode": "offline" if chat is None else "live", "questions": len(rows), "k": k,
               "recall_at_k": _mean([r["recalled"] for r in answerable]),
               "tier_accuracy": _mean([r["tier_ok"] for r in rows]),
               "tiers": {t: sum(r["tier"] == t for r in rows) for t in DEFAULT_PRICES}}
    if chat is not None:
        summary.update(
            citation_valid=_mean([r["citation_valid"] for r in rows]),
            expected_cited=_mean([r["expected_cited"] for r in answerable]),
            abstain_accuracy=_mean([r["abstained"] for r in rows if r["should_abstain"]]),
            prompt_tokens=sum((r["usage"] or {}).get("prompt_tokens") or 0 for r in rows),
            completion_tokens=sum((r["usage"] or {}).get("completion_tokens") or 0 for r in rows),
            cost_usd=round(sum(r["cost_usd"] or 0 for r in rows), 6),
            latency_s=round(sum((r["usage"] or {}).get("latency_s") or 0 for r in rows), 3),
            models=sorted({r["model"] for r in rows if r["model"]}))
    return {"summary": summary, "rows": rows}
