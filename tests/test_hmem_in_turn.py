"""H-MEM in a working feature: every `palace ask` turn ranks the recalled memories with Palace's H-MEM engine,
links supersession, and labels superseded memories in the prompt (docs/open-agent-design.md §4)."""

import json

from palace.agent import hmem_rank, run_turn
from palace.memory import DemoMemory


def test_the_reversal_supersedes_the_july_decision():
    t = run_turn("Is the coordinator hire on?", DemoMemory(), None)
    assert t.superseded.get("demo-013") == "demo-016"
    ids = [m.id for m in t.memories]
    assert ids.index("demo-016") < ids.index("demo-013"), "the current decision ranks above the superseded one"
    assert "[SUPERSEDED by demo-016]" in t.prompt[1]["content"]
    assert "demo-013" in ids, "superseded memories are kept and labelled, never dropped"


def test_trace_and_ledger_are_recorded(tmp_path):
    path = tmp_path / "trust-ledger.jsonl"
    t = run_turn("Is the coordinator hire on?", DemoMemory(), None, ledger_path=str(path))
    assert t.hmem["ledger"]["create"] == len(t.memories) and t.hmem["ledger"]["update"] >= 1
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    sup = [r for r in rows if r["action"] == "update" and r["memoryId"] == "demo-013"]
    assert sup and sup[0]["newState"]["supersededBy"] == "demo-016" and sup[0]["previousState"]["supersededBy"] is None


def test_unrelated_memories_are_not_superseded():
    _, sup, _ = hmem_rank("When is Mom's birthday dinner?", DemoMemory().search("When is Mom's birthday dinner?"))
    assert "demo-017" not in sup


def test_no_memories_is_fine():
    assert hmem_rank("q", []) == ([], {}, {"scores": {}, "retrievalReason": "no memories", "ledger": {}})


def test_superseded_penalty_not_insertion_order_decides():
    # ro-001 with the insertion order reversed: with identical relevance, only the -0.20 penalty puts fresh first.
    from palace.engines.hmem import HMEM
    h = HMEM(clock=lambda: 1750000000000)
    old = h.add(content="we deploy the api with docker on fridays", confidence=0.9, layer="long_term", source="t")
    fresh = h.add(content="we deploy the api with docker on mondays", confidence=0.9, layer="long_term", source="t")
    old.supersededBy = fresh.id
    r = h.query("when do we deploy the api with docker", threshold=0, topN=10)
    assert [x.memory.id for x in r.memories] == [fresh.id, old.id]
    assert "superseded and penalised" in r.retrievalReason
