"""The adapter against a REAL Zetaris (docs/open-agent-design.md §3): the same ground truth as the contract tests,
on the real engine's dialect. Skipped unless ZETARIS_BASE_URL, ZETARIS_EMAIL and ZETARIS_PASSWORD are set and
PALACE_DEMO is loaded (demo/zetaris/load_zetaris.py)."""

import json
import os

import pytest

from palace.adapters.zetaris import Zetaris
from zetaris_double import DATASET

NEED = ("ZETARIS_BASE_URL", "ZETARIS_EMAIL", "ZETARIS_PASSWORD")
pytestmark = pytest.mark.skipif(not all(os.environ.get(k) for k in NEED), reason="no live Zetaris configured")
TRUTH = json.loads((DATASET / "ground_truth.json").read_text())


@pytest.fixture(scope="module")
def z():
    return Zetaris.login(os.environ["ZETARIS_BASE_URL"], os.environ["ZETARIS_EMAIL"], os.environ["ZETARIS_PASSWORD"],
                         timeout=120)


def _n(rs):
    return int(rs.rows[0][0])


def test_live_health(z):
    assert z.health() is True


def test_live_row_counts(z):
    for table, want in TRUTH["rows"].items():
        assert _n(z.query(f"SELECT count(*) FROM PALACE_DEMO.{table}")) == want, table


def test_live_templates_match_ground_truth(z):
    assert _n(z.count_devices(since="2026-07-01")) == TRUTH["devices_out_since_jul"]
    assert _n(z.count_devices(since="2026-04-01", until="2026-06-30")) == TRUTH["q2_devices_out"]
    for kind, want in TRUTH["devices_out_since_jul_by_type"].items():
        assert _n(z.count_devices(since="2026-07-01", type=kind)) == want, kind
    assert _n(z.attendance(since="2026-04-01", until="2026-06-30")) == TRUTH["q2_attendees"]
    assert _n(z.attendance(since="2026-07-01")) == TRUTH["q3q4_attendees_since_jul"]
    assert z.tickets(status="rejected (SMART fail)").row_count == TRUTH["smart_rejections"]


def test_live_decisions_and_notes(z):
    active = z.decisions("staffing", status="active")
    assert [r[active.columns.index("decision_id")] for r in active.rows] == [TRUTH["active_staffing_decision"]]
    notes = z.meeting_notes("coordinator")
    assert "MTG-0801" in {r[notes.columns.index("meeting_id")] for r in notes.rows}


def test_live_tickets_since_parses_mm_dd_yyyy(z):
    every, recent = z.tickets(), z.tickets(since="2026-07-01")
    assert 0 < recent.row_count < every.row_count == TRUTH["rows"]["tickets"]
