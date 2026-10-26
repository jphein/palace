"""The planner's Zetaris step in a turn: which records a question pulls, how they reach the prompt and the egress
record, and what happens when Zetaris is offline. Runs against the test double (tests/zetaris_double.py)."""

import json

import pytest

from palace.adapters.zetaris import Unreachable, Zetaris, ZetarisOffline, open_zetaris
from palace.agent import normalise_answer, run_turn
from palace.config import Config
from palace.memory import DemoMemory
from palace.orgplan import org_plan
from palace.web import turn_to_dict
from zetaris_double import DATASET, ZetarisDouble

TRUTH = json.loads((DATASET / "ground_truth.json").read_text())


@pytest.fixture
def org():
    with ZetarisDouble() as d:
        yield Zetaris(d.base_url, d.token, d.org_id, timeout=5)


def _templates(q):
    return [(s.template, s.params) for s in org_plan(q)]


def test_plan_for_the_october_report():
    assert _templates("What numbers go in the October county report?") == [
        ("attendance", {"since": "2026-07-01"}), ("count_devices", {"since": "2026-07-01"})]


def test_plan_for_the_first_report_uses_q2():
    assert _templates("Did the first report's numbers hold up?") == [
        ("attendance", {"since": "2026-04-01", "until": "2026-06-30"}),
        ("count_devices", {"since": "2026-04-01", "until": "2026-06-30"})]


def test_plan_for_staffing_and_smart():
    assert [t for t, _ in _templates("Is the coordinator hire on?")] == ["decisions", "meeting_notes"]
    assert _templates("How many donations failed the SMART check?") == [("tickets", {"status": "rejected (SMART fail)"})]


def test_plan_for_a_decision_topic():
    assert _templates("What did we decide about the Saturday hours?") == [("decisions", {"topic": "hours"})]


@pytest.mark.parametrize("q", ["When is Mom's birthday dinner, and where?", "What is the Wi-Fi password at the hub?"])
def test_personal_questions_ask_nothing_of_zetaris(q):
    assert org_plan(q) == []


def test_turn_sends_cited_record_sets(org):
    t = run_turn("What numbers go in the October county report?", DemoMemory(), None, org=org)
    assert t.org_status == "ok" and len(t.records) == 2
    att, dev = t.records
    assert int(att.rows[0][0]) == TRUTH["q3q4_attendees_since_jul"] and int(dev.rows[0][0]) == TRUTH["devices_out_since_jul"]
    user = t.prompt[1]["content"]
    assert "Organisation records (Zetaris, read-only):" in user and att.cite() in user and dev.cite() in user
    assert [e["id"] for e in t.record_egress] == [att.id, dev.id] and all(e["chars"] > 0 for e in t.record_egress)


def test_turn_without_zetaris_is_unchanged():
    a = run_turn("Is the coordinator hire on?", DemoMemory(), None)
    assert a.org_status is None and a.records == [] and "Organisation records" not in a.prompt[1]["content"]


def test_offline_zetaris_is_said_not_guessed():
    t = run_turn("Is the coordinator hire on?", DemoMemory(), None, org=Unreachable(ZetarisOffline("refused")))
    assert t.records == [] and t.org_status.startswith("Zetaris: offline")
    assert "Do not guess" in t.prompt[1]["content"]


def test_open_zetaris_needs_auth():
    assert open_zetaris({}) is None
    with pytest.raises(RuntimeError, match="ZETARIS_TOKEN|ZETARIS_EMAIL"):
        open_zetaris({"ZETARIS_BASE_URL": "http://localhost:3000"})
    z = open_zetaris({"ZETARIS_BASE_URL": "http://localhost:3000", "ZETARIS_TOKEN": "t", "ZETARIS_ORG_ID": "1"})
    assert z.org_id == "1"


def test_lenticular_record_citations_are_normalised():
    assert normalise_answer("72 attendees 【zetaris:q-46c5ea53】") == "72 attendees [zetaris:q-46c5ea53]"


def test_web_payload_carries_the_records(org):
    t = run_turn("How many donations failed the SMART check?", DemoMemory(), None, org=org)
    d = turn_to_dict(t, Config.from_env({}), live=False)
    assert d["zetaris"]["status"] == "ok"
    [r] = d["zetaris"]["records"]
    assert r["template"] == "tickets" and r["row_count"] == TRUTH["smart_rejections"]
    assert d["egress"]["records"][0]["id"] == r["id"]
