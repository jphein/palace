"""One turn: recall -> route -> ask Nemotron -> answer with citations and an egress record.

The egress record ("what left the house") lists exactly which memory snippets were sent to the
model for this answer. The memory store itself never leaves the user's server.
Hermes Agent integration (tools + persona) wraps this same turn; see README "Roadmap"."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from .config import DEFAULT_PRICES
from .memory import Memory, MemoryBackend
from .router import Route, route
from .tokenfactory import Completion

SYSTEM = """You are Palace, a private personal assistant with access to the user's own long-term memory.
Answer ONLY from the numbered memories provided. Cite every claim with the memory's bracketed id, e.g. [demo-004].
If the memories don't contain the answer, say so plainly and suggest what to ask instead. Be brief and warm."""

MAX_SNIPPET = 600


@dataclass
class Turn:
    question: str
    route: Route
    memories: list[Memory]
    prompt: list[dict]
    answer: str | None = None
    model: str | None = None
    egress: list[dict] = field(default_factory=list)
    usage: dict | None = None        # prompt/completion tokens and latency of the model call
    cost_usd: float | None = None    # tokens x the routed tier's price; None if usage is unknown


def build_prompt(question: str, memories: list[Memory]) -> list[dict]:
    lines = [f"{m.cite()} ({m.wing}/{m.room}) {m.text[:MAX_SNIPPET]}" for m in memories]
    context = "\n".join(lines) if lines else "(no relevant memories found)"
    return [{"role": "system", "content": SYSTEM},
            {"role": "user", "content": f"Memories:\n{context}\n\nQuestion: {question}"}]


def cost(tier: str, prompt_tokens: int | None, completion_tokens: int | None,
         prices: dict[str, tuple[float, float]] = DEFAULT_PRICES) -> float | None:
    if prompt_tokens is None or completion_tokens is None:
        return None
    p_in, p_out = prices[tier]
    return round((prompt_tokens * p_in + completion_tokens * p_out) / 1e6, 8)


def run_turn(question: str, memory: MemoryBackend, chat: Callable[[str, list[dict]], Completion] | None,
             limit: int = 8, prices: dict[str, tuple[float, float]] = DEFAULT_PRICES) -> Turn:
    """chat(tier, messages) -> Completion. Pass None for a dry run (no network, prompt only)."""
    mems = memory.search(question, limit=limit)
    r = route(question, len(mems))
    prompt = build_prompt(question, mems)
    turn = Turn(question, r, mems, prompt,
                egress=[{"id": m.id, "chars": min(len(m.text), MAX_SNIPPET)} for m in mems])
    if chat is not None:
        c = chat(r.tier, prompt)
        turn.answer, turn.model = c.text, c.model
        turn.usage = {"prompt_tokens": c.prompt_tokens, "completion_tokens": c.completion_tokens, "latency_s": c.latency_s}
        turn.cost_usd = cost(r.tier, c.prompt_tokens, c.completion_tokens, prices)
    return turn
