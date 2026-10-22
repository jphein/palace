"""Contract tests for palace/adapters/zetaris.py (docs/open-agent-design.md §3), written before the adapter exists.

The whole module skips until the adapter lands, then becomes its acceptance test. They run against the TEST DOUBLE in
tests/zetaris_double.py; a live run against a real Zetaris is the adapter's own evidence, not these.

The contract, as these tests pin it:
- `Zetaris(base_url, token, org_id, timeout=...)`
- `query(sql, limit=100) -> RecordSet`; `health() -> bool` (never raises)
- `RecordSet(id, sql, columns, rows, row_count, latency_ms)`, with id `zetaris:q-<first 8 hex of sha256(sql)>`
- unreachable Zetaris -> `ZetarisOffline` (str contains "Zetaris: offline"); rows are never invented
- the planner's templates: `decisions(topic, status=None)`, `count_devices(since, until=None, type=None)`,
  `attendance(since, until=None, class_name=None)`, `tickets(status=None, since=None)`,
  `meeting_notes(search, since=None)`. Parameters are values, never SQL.
"""

import hashlib
import json
import re
import socket
import uuid

import pytest

zetaris = pytest.importorskip("palace.adapters.zetaris", reason="the Zetaris adapter is window work, built in Cursor")
from zetaris_double import DATASET, QUERY_PATH, ZetarisDouble  # noqa: E402

TRUTH = json.loads((DATASET / "ground_truth.json").read_text())


@pytest.fixture
def double():
    with ZetarisDouble() as d:
        yield d


@pytest.fixture
def z(double):
    return zetaris.Zetaris(base_url=double.base_url, token=double.token, org_id=double.org_id, timeout=5)


def _closed_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_health_and_select_1(z):
    assert z.health() is True
    rs = z.query("SELECT 1")
    assert rs.rows == [["1"]] and rs.row_count == 1


def test_record_set_id_is_a_stable_citation(z):
    sql = "SELECT decision_id FROM PALACE_DEMO.decisions"
    a, b = z.query(sql), z.query(sql)
    assert a.id == b.id == f"zetaris:q-{hashlib.sha256(sql.encode()).hexdigest()[:8]}"
    assert a.sql == sql and a.columns == ["decision_id"] and a.row_count == 10
    assert isinstance(a.latency_ms, int) and a.latency_ms >= 0


def test_sends_the_auth_headers_with_a_fresh_request_id(z, double):
    z.query("SELECT 1")
    z.query("SELECT 1")
    sent = [{k.lower(): v for k, v in r["headers"].items()} for r in double.requests if r["path"] == QUERY_PATH]
    assert len(sent) == 2
    for h in sent:
        assert h["authorization"] == f"Bearer {double.token}" and h["x-org-id"] == double.org_id
        uuid.UUID(h["x-request-id"], version=4)
    assert sent[0]["x-request-id"] != sent[1]["x-request-id"]


def test_limit_caps_rows_and_row_count_is_the_total(z):
    rs = z.query("SELECT ticket FROM PALACE_DEMO.tickets", limit=5)
    assert len(rs.rows) == 5 and rs.row_count == 50


def test_offline_raises_and_health_is_false():
    off = zetaris.Zetaris(base_url=f"http://127.0.0.1:{_closed_port()}", token="t", org_id="1", timeout=2)
    assert off.health() is False
    with pytest.raises(zetaris.ZetarisOffline, match="Zetaris: offline"):
        off.query("SELECT 1")


def test_bad_token_is_not_reported_as_offline(double):
    bad = zetaris.Zetaris(base_url=double.base_url, token="wrong", org_id=double.org_id, timeout=5)
    with pytest.raises(Exception) as e:
        bad.query("SELECT 1")
    assert not isinstance(e.value, zetaris.ZetarisOffline), "an auth failure is not an outage"


# --- the planner's templates ----------------------------------------------------------------------

def test_decisions_finds_the_reversal(z):
    active = z.decisions("staffing", status="active")
    assert [r[active.columns.index("decision_id")] for r in active.rows] == [TRUTH["active_staffing_decision"]]
    every = z.decisions("staffing")
    ids = {r[every.columns.index("decision_id")]: r[every.columns.index("status")] for r in every.rows}
    assert ids.get("DEC-2026-006") == "superseded" and ids.get("DEC-2026-008") == "active"


def test_count_devices_matches_ground_truth(z):
    def n(rs):
        return int(rs.rows[0][0])
    assert n(z.count_devices(since="2026-07-01")) == TRUTH["devices_out_since_jul"]
    assert n(z.count_devices(since="2026-04-01", until="2026-06-30")) == TRUTH["q2_devices_out"]
    for kind, want in TRUTH["devices_out_since_jul_by_type"].items():
        assert n(z.count_devices(since="2026-07-01", type=kind)) == want, kind


def test_attendance_matches_ground_truth(z):
    assert int(z.attendance(since="2026-04-01", until="2026-06-30").rows[0][0]) == TRUTH["q2_attendees"]
    assert int(z.attendance(since="2026-07-01").rows[0][0]) == TRUTH["q3q4_attendees_since_jul"]


def test_tickets_and_meeting_notes(z):
    rejected = z.tickets(status="rejected (SMART fail)")
    assert rejected.row_count == TRUTH["smart_rejections"]
    notes = z.meeting_notes("coordinator")
    ids = {r[notes.columns.index("meeting_id")] for r in notes.rows}
    assert "MTG-0801" in ids, "the Aug 1 note that still says the hire is on must be findable"


@pytest.mark.parametrize("evil", ["staffing' OR '1'='1", "x'; DROP TABLE PALACE_DEMO.decisions; --", "%"])
def test_template_parameters_are_values_not_sql(z, evil):
    rs = z.decisions(evil)
    assert rs.row_count == 0, "a parameter must never widen or change the query"
    assert z.query("SELECT count(*) FROM PALACE_DEMO.decisions").rows == [[str(TRUTH["rows"]["decisions"])]]


def test_template_sql_is_recorded_on_the_record_set(z):
    rs = z.count_devices(since="2026-07-01")
    assert re.search(r"device_ledger", rs.sql) and rs.id.startswith("zetaris:q-")
