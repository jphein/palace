"""Self-tests for the Zetaris test double: it must look like the real endpoint and serve the dataset faithfully.

If these fail, the adapter's contract tests (tests/test_zetaris_adapter.py) prove nothing.
"""

import json
import urllib.error
import urllib.request
import uuid

import pytest

from zetaris_double import DATASET, QUERY_PATH, ZetarisDouble


@pytest.fixture
def z():
    with ZetarisDouble() as double:
        yield double


def _run(z, sql, limit=100, token=None, org=None, request_id=None):
    req = urllib.request.Request(z.base_url + QUERY_PATH, method="POST",
                                 data=json.dumps({"sql": sql, "limit": limit}).encode(),
                                 headers={"content-type": "application/json",
                                          "authorization": f"Bearer {token or z.token}",
                                          "x-org-id": org or z.org_id,
                                          "x-request-id": request_id or str(uuid.uuid4())})
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def test_select_1_has_the_shape_the_real_endpoint_returned(z):
    code, body = _run(z, "SELECT 1")
    assert code == 200 and body["data"] == [["1"]] and body["total"] == 1     # real Zetaris: [["1"]] (pre-window check)


@pytest.mark.parametrize("kw,code", [({"token": "wrong"}, 400),   # the real bundle: 400 {"msg": "Bad Request"}
                                      ({"org": "2"}, 403), ({"request_id": "not-a-uuid"}, 400)])
def test_auth_headers_are_enforced(z, kw, code):
    assert _run(z, "SELECT 1", **kw)[0] == code


def test_every_table_has_its_documented_row_count(z):
    truth = json.loads((DATASET / "ground_truth.json").read_text())
    for table, n in truth["rows"].items():
        assert _run(z, f"SELECT count(*) FROM PALACE_DEMO.{table}")[1]["data"] == [[str(n)]], table


def test_ground_truth_reproduces_through_sql(z):
    t = json.loads((DATASET / "ground_truth.json").read_text())
    one = lambda sql: int(_run(z, sql)[1]["data"][0][0])
    assert one("SELECT sum(attendees) FROM PALACE_DEMO.class_sessions WHERE date BETWEEN '2026-04-01' AND '2026-06-30'") \
        == t["q2_attendees"]
    assert one("SELECT count(*) FROM PALACE_DEMO.device_ledger WHERE handed_out BETWEEN '2026-04-01' AND '2026-06-30'") \
        == t["q2_devices_out"]
    assert one("SELECT sum(attendees) FROM PALACE_DEMO.class_sessions WHERE date >= '2026-07-01'") \
        == t["q3q4_attendees_since_jul"]
    assert one("SELECT count(*) FROM PALACE_DEMO.device_ledger WHERE handed_out >= '2026-07-01'") == t["devices_out_since_jul"]
    by_type = _run(z, "SELECT type, count(*) FROM PALACE_DEMO.device_ledger WHERE handed_out >= '2026-07-01' "
                      "GROUP BY type ORDER BY type")[1]["data"]
    assert {k: int(v) for k, v in by_type} == t["devices_out_since_jul_by_type"]
    assert one("SELECT count(*) FROM PALACE_DEMO.tickets WHERE status LIKE 'rejected%'") == t["smart_rejections"]
    active = _run(z, "SELECT decision_id FROM PALACE_DEMO.decisions WHERE topic = 'staffing' AND status = 'active'")[1]
    assert active["data"] == [[t["active_staffing_decision"]]]


def test_limit_caps_rows_but_total_counts_all(z):
    code, body = _run(z, "SELECT ticket FROM PALACE_DEMO.tickets", limit=5)
    assert code == 200 and len(body["data"]) == 5 and body["total"] == 50


def test_bad_sql_is_a_400_not_a_crash(z):
    assert _run(z, "SELECT nope FROM PALACE_DEMO.missing")[0] == 400
    assert _run(z, "SELECT 1")[0] == 200
