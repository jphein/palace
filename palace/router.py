"""Pick a Nemotron tier per request: Nano for quick lookups, Super by default, Ultra only when the
question needs real reasoning. Cheap, transparent heuristics first; the reason is returned so the
UI can show why a tier was chosen."""
from __future__ import annotations

import re
from dataclasses import dataclass

ULTRA_CUES = re.compile(
    r"\b(plan|planning|prioriti[sz]e|compare|trade-?offs?|reconcile|contradict|conflict|why did|should i|"
    r"strategy|decide|weigh|pros and cons|summari[sz]e (the|my) (month|year|quarter))\b", re.I)
NANO_CUES = re.compile(r"^(when|what time|what day|where|who|which|did i|have i|is there)\b", re.I)


@dataclass(frozen=True)
class Route:
    tier: str      # "nano" | "super" | "ultra"
    reason: str


def route(question: str, n_memories: int = 0) -> Route:
    q = question.strip()
    if ULTRA_CUES.search(q):
        return Route("ultra", "asks for planning, comparison or a judgement call")
    if n_memories > 12:
        return Route("ultra", f"has to reconcile {n_memories} memories")
    if NANO_CUES.search(q) and len(q) < 120:
        return Route("nano", "a short factual lookup")
    return Route("super", "default")
