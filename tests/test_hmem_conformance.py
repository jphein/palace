"""The H-MEM conformance suite, ported from Meterless's conformance/runner.ts to pytest, check for check, and run
against Palace's H-MEM (palace/engines/hmem.py). The vectors are the spec's own (tests/hmem/README.md).

As in the runner, the exact tier is asserted: formula arithmetic, deltas, gates and boundaries the spec fully
determines. Absolute scores depend on the embedder and are not asserted; order is, where the spec makes it
embedding-independent. This is "vectors ported", not the official TypeScript runner (design §4)."""

import json
import math
from pathlib import Path

import pytest

from palace.engines.hmem import HMEM

V = json.loads((Path(__file__).parent / "hmem" / "vectors.json").read_text())
T0 = V["clock"]
DAY = 24 * 60 * 60 * 1000
S = V["sections"]


def _ids(section):
    return [c["id"] for c in S[section]]


def test_every_section_of_the_vectors_is_ported():
    assert set(S) == {"record-validation", "feedback-deltas", "ranking-order", "sleep-guardrails", "conflict-gate",
                      "ledger-audit", "dream-boundary"}
    assert sum(len(v) for v in S.values()) == 13


@pytest.mark.parametrize("c", S["record-validation"], ids=_ids("record-validation"))
def test_record_validation(c):
    h = HMEM(clock=lambda: T0)
    try:
        h.add(content=c["input"]["content"], source=c["input"]["source"])
        rejected = False
    except ValueError:
        rejected = True
    assert rejected == (c["expect"] == "reject")


@pytest.mark.parametrize("c", S["feedback-deltas"], ids=_ids("feedback-deltas"))
def test_feedback_deltas(c):
    h = HMEM(clock=lambda: T0)
    m = h.add(content="feedback target record", confidence=c["start"], source="conformance")
    before = m.accessCount
    h.feedback(m.id, c["kind"])
    after = h.store.get(m.id)
    assert math.isclose(after.confidence, c["expectConfidence"], abs_tol=1e-9)
    if "expectAccessDelta" in c:
        assert after.accessCount - before == c["expectAccessDelta"]
    if "expectTag" in c:
        assert c["expectTag"] in after.tags


@pytest.mark.parametrize("c", S["ranking-order"], ids=_ids("ranking-order"))
def test_ranking_order(c):
    h = HMEM(clock=lambda: T0)
    by = {r["key"]: h.add(content=r["content"], confidence=r["confidence"], layer=r["layer"], source="conformance")
          for r in c["records"]}
    for r in c["records"]:
        if r.get("supersededByKey"):
            by[r["key"]].supersededBy = by[r["supersededByKey"]].id
    order = [x.memory.id for x in h.query(c["query"], threshold=0, topN=10).memories]
    want = [by[k].id for k in c["expectOrder"]]
    for a, b in zip(want, want[1:]):
        assert order.index(a) < order.index(b), (c["expectOrder"], order)


@pytest.mark.parametrize("c", S["sleep-guardrails"], ids=_ids("sleep-guardrails"))
def test_sleep_guardrails(c):
    now = [T0]
    h = HMEM(clock=lambda: now[0])
    by = {r["key"]: h.add(content=r["content"], source=r["source"], derivedFrom=r.get("derivedFrom")) for r in c["records"]}
    now[0] = T0 + c["ageDays"] * DAY
    before = sorted(m.id for m in h.store.all())
    preview = h.sleep.preview()
    assert sorted(m.id for m in h.store.all()) == before, "preview mutated the store"
    for k in c["expectArchived"]:
        assert by[k].id in preview["toArchive"], f"{k} should be archivable"
    for k in c["expectProtected"]:
        assert by[k].id not in preview["toArchive"], f"{k} is guardrail-protected"
    report = h.sleep.execute(preview)
    for k in c["expectProtected"]:
        assert h.store.get(by[k].id) is not None, f"{k} deleted despite guardrails"
    assert isinstance(report["backupId"], str) and report["backupId"]


@pytest.mark.parametrize("c", S["conflict-gate"], ids=_ids("conflict-gate"))
def test_conflict_gate(c):
    h = HMEM(clock=lambda: T0)
    a = h.add(content=c["a"]["content"], confidence=c["a"]["confidence"], source="conformance")
    b = h.add(content=c["b"]["content"], confidence=c["b"]["confidence"], source="conformance")
    found = h.conflicts.scan()
    assert found, "opposing always/never pair on similar content must be detected"
    outcome = h.conflicts.autoResolve(found[0])
    assert outcome in ("resolved", "queued")
    if outcome == "resolved":
        assert any(m.supersededBy for m in (h.store.get(a.id), h.store.get(b.id))), "loser must be supersededBy"
    assert h.store.get(a.id) and h.store.get(b.id), "conflict resolution must never delete records"


@pytest.mark.parametrize("c", S["ledger-audit"], ids=_ids("ledger-audit"))
def test_ledger_audit(c):
    h = HMEM(clock=lambda: T0)
    m = h.add(content="audited record", confidence=c["start"], source="conformance")
    h.feedback(m.id, c["kind"])
    hist = h.ledger.history(m.id)
    assert [e["action"] for e in hist] == c["expectActions"]
    assert math.isclose(hist[-1]["previousState"]["confidence"], c["expectPrev"], abs_tol=1e-9)
    assert math.isclose(hist[-1]["newState"]["confidence"], c["expectNew"], abs_tol=1e-9)


@pytest.mark.parametrize("c", S["dream-boundary"], ids=_ids("dream-boundary"))
def test_dream_boundary(c):
    h = HMEM(clock=lambda: T0)
    for r in c["records"]:
        h.add(content=r["content"], type=r["type"], source="conformance")
    n = len(h.store.all())
    proposals = h.dreaming.dream()
    assert proposals, "two related preferences must produce at least one proposal"
    assert len(h.store.all()) == n, "dreaming must not materialize anything before approval"
    created = h.dreaming.approve(proposals[0]["id"])
    if created:
        assert created.layer == "long_term" and created.derivedFrom
