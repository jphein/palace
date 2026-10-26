"""Which organisation records a question needs: the planner's Zetaris step (docs/open-agent-design.md §2-3).

The palace holds what the person remembers; Zetaris holds the organisation's records (attendance, the device
ledger, the decision log). Like the tier router, v1 is transparent rules: each step names the template, its
parameters and why, so the UI can show what was asked of Zetaris. No free-form SQL is ever generated here.

Dates are the synthetic world's calendar (demo/zetaris/README.md): the county year's Q2 report covered
Apr 1 - Jun 30, 2026, and the October report covers Jul 1, 2026 onwards.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

Q2 = {"since": "2026-04-01", "until": "2026-06-30"}
SINCE_JUL = {"since": "2026-07-01"}
# decisions.csv topics, and the words a question uses for them
TOPICS = {"hours": r"hours|open|saturday|friday", "grants": r"grants?", "classes": r"class(es)?",
          "devices": r"devices?|laptops?|donat\w*", "hotspots": r"hotspots?", "signup": r"sign-?ups?|web form"}

_FIRST_REPORT = re.compile(r"\b(first|q2|july|quarterly)\b.*\breport\b|\breport\b.*\b(hold up|first)\b", re.I)
_NEXT_REPORT = re.compile(r"\b(october|county|next)\b.*\breport\b|\bsince july\b|\bnumbers\b", re.I)
_COUNTS = re.compile(r"\bhow many\b.*\b(devices?|attendees|people|handed out)\b|\battendance\b", re.I)
_STAFFING = re.compile(r"\b(coordinator|hire|hiring|staffing)\b", re.I)
_SMART = re.compile(r"\bsmart\b|\breject\w*\b.*\bdonat\w*|\bdonat\w*\b.*\b(reject\w*|fail\w*)\b", re.I)
_DECIDED = re.compile(r"\b(decid\w*|decision|rule|policy)\b", re.I)


@dataclass(frozen=True)
class Step:
    template: str
    params: dict = field(default_factory=dict)
    why: str = ""


def org_plan(question: str) -> list[Step]:
    q = question.strip()
    steps: list[Step] = []
    if _FIRST_REPORT.search(q):
        steps += [Step("attendance", Q2, "class attendance in the Q2 report period"),
                  Step("count_devices", Q2, "devices handed out in the Q2 report period")]
    elif _NEXT_REPORT.search(q) or _COUNTS.search(q):
        steps += [Step("attendance", SINCE_JUL, "class attendance since July 1, for the October report"),
                  Step("count_devices", SINCE_JUL, "devices handed out since July 1, for the October report")]
    if _STAFFING.search(q):
        steps += [Step("decisions", {"topic": "staffing"}, "the decision log is the source of record for staffing"),
                  Step("meeting_notes", {"search": "coordinator"}, "meeting notes that mention the coordinator")]
    if _SMART.search(q):
        steps.append(Step("tickets", {"status": "rejected (SMART fail)"}, "donations rejected by the SMART check"))
    if _DECIDED.search(q) and not _STAFFING.search(q):
        for topic, words in TOPICS.items():
            if re.search(rf"\b({words})\b", q, re.I):
                steps.append(Step("decisions", {"topic": topic}, f"the decision log on {topic}"))
                break
    return steps
