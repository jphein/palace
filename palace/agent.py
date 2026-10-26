"""One turn: recall -> organisation records -> route -> ask Nemotron -> answer with citations and an egress record.

The egress record ("what left the house") lists exactly which memory snippets and Zetaris record sets were
sent to the model for this answer. The memory store itself never leaves the user's server.
Hermes Agent integration (tools + persona) wraps this same turn; see README "Roadmap"."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable

from .config import DEFAULT_PRICES
from .memory import Memory, MemoryBackend
from .orgplan import Step, org_plan
from .router import Route, route
from .tokenfactory import Completion

SYSTEM = """You are Palace, a private personal assistant with access to the user's own long-term memory.
Answer ONLY from the numbered memories and the organisation records provided. Cite every claim with its bracketed
id: a memory as [demo-004], a record set as [zetaris:q-1a2b3c4d] (never a row's own id, such as MTG-0801). The
organisation records (from Zetaris) are the source of record for counts and decisions: if a memory or a meeting note
disagrees with the active entry in the decision log, name that note or memory as out of date. If neither contains the answer, say so plainly and suggest what to ask instead.
Be brief and warm."""

MAX_SNIPPET = 600
MAX_RECORD_ROWS = 20      # rows per record set sent to the model; the egress record shows the cap
# Some Nemotron tiers cite with CJK lenticular brackets (【demo-008】, measured live 2026-10-19); the UI and
# the evals expect [demo-008]. Only memory-id-shaped contents are rewritten.
_LENTICULAR = re.compile(r"【(demo-\d+(?:,\s*[0-9-]{10})?|zetaris:q-[0-9a-f]{8})】")


def normalise_answer(text: str) -> str:
    return _LENTICULAR.sub(r"[\1]", text).strip()


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
    plan: list[Step] = field(default_factory=list)          # what was asked of Zetaris, and why
    records: list = field(default_factory=list)              # RecordSets returned by Zetaris
    record_egress: list[dict] = field(default_factory=list)  # what of them went to the model
    org_status: str | None = None    # None: no records needed; "ok"; or "Zetaris: offline (...)" / an error
    provider: str | None = None      # "meterless" (Nightshift) or "tokenfactory"
    receipt_id: str | None = None    # Nightshift's compute receipt for the model call


def render_record(rs, why: str = "") -> str:
    head = f"{rs.cite()} {why}\n  SQL: {rs.sql}\n  columns: {' | '.join(rs.columns)}"
    body = [f"  {' | '.join(r)}" for r in rs.rows[:MAX_RECORD_ROWS]]
    more = rs.row_count - len(body)
    return "\n".join([head, *body] + ([f"  (+{more} more rows not shown)"] if more > 0 else []))


def build_prompt(question: str, memories: list[Memory], records: list[str] | None = None,
                 org_status: str | None = None) -> list[dict]:
    lines = [f"{m.cite()} ({m.wing}/{m.room}) {m.text[:MAX_SNIPPET]}" for m in memories]
    context = "\n".join(lines) if lines else "(no relevant memories found)"
    user = f"Memories:\n{context}"
    if records:
        user += "\n\nOrganisation records (Zetaris, read-only):\n" + "\n".join(records)
    elif org_status and org_status != "ok":
        user += f"\n\nOrganisation records: unavailable ({org_status}). Do not guess any counts or decisions."
    return [{"role": "system", "content": SYSTEM}, {"role": "user", "content": f"{user}\n\nQuestion: {question}"}]


def fetch_records(org, plan: list[Step]) -> tuple[list, list[str], str | None]:
    """Run each planned template on Zetaris. Offline or failing: no rows, and the status says why."""
    from .adapters.zetaris import ZetarisError
    if not plan or org is None:
        return [], [], (None if not plan else "Zetaris: not configured")
    out, text = [], []
    try:
        for step in plan:
            rs = getattr(org, step.template)(**step.params)
            out.append(rs)
            text.append(render_record(rs, step.why))
    except ZetarisError as e:
        return [], [], str(e)
    return out, text, "ok"


def cost(tier: str, prompt_tokens: int | None, completion_tokens: int | None,
         prices: dict[str, tuple[float, float]] = DEFAULT_PRICES) -> float | None:
    if prompt_tokens is None or completion_tokens is None:
        return None
    p_in, p_out = prices[tier]
    return round((prompt_tokens * p_in + completion_tokens * p_out) / 1e6, 8)


def run_turn(question: str, memory: MemoryBackend, chat: Callable[[str, list[dict]], Completion] | None,
             limit: int = 8, prices: dict[str, tuple[float, float]] = DEFAULT_PRICES, org=None) -> Turn:
    """chat(tier, messages) -> Completion. Pass None for a dry run (no model call, prompt only).
    org: a palace.adapters.zetaris.Zetaris, or None to answer from memory alone. It is read-only, and it is
    queried in dry runs too, so the preview shows the real records that would be sent."""
    mems = memory.search(question, limit=limit)
    plan = org_plan(question) if org is not None else []
    records, texts, status = fetch_records(org, plan)
    r = route(question, len(mems))
    prompt = build_prompt(question, mems, texts, status)
    turn = Turn(question, r, mems, prompt,
                egress=[{"id": m.id, "chars": min(len(m.text), MAX_SNIPPET)} for m in mems],
                plan=plan, records=records, org_status=status,
                record_egress=[{"id": rs.id, "rows": min(len(rs.rows), MAX_RECORD_ROWS), "row_count": rs.row_count,
                                "chars": len(t), "latency_ms": rs.latency_ms} for rs, t in zip(records, texts)])
    if chat is not None:
        c = chat(r.tier, prompt)
        turn.answer, turn.model = normalise_answer(c.text), c.model
        turn.usage = {"prompt_tokens": c.prompt_tokens, "completion_tokens": c.completion_tokens, "latency_s": c.latency_s}
        turn.provider, turn.receipt_id = c.provider, c.receipt_id
        # Token Factory bills per token at the tier's price. Nightshift's NVIDIA calls are metered by Nightshift
        # (its receipt), not by Palace's price table, so Palace states no cost for them.
        turn.cost_usd = None if c.provider == "meterless" else cost(r.tier, c.prompt_tokens, c.completion_tokens, prices)
    return turn
