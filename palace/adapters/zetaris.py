"""Zetaris adapter: read-only SQL over the organisation's records (docs/open-agent-design.md §3). Stdlib only.

One REST call per query, through the Zetaris UI proxy:

    POST {base}/api/proxy/sql-editor/sqls/run-query   {"sql": …, "limit": N}
    headers: Authorization: Bearer <token>, X-Org-ID: <org>, X-Request-ID: <fresh uuid4>
    -> {"headers": [...], "data": [[...]], "total": n}

Every result is a RecordSet whose id ("zetaris:q-<8 hex of sha256(sql)>") is the citation the answer uses, so
the same query always cites the same id. If Zetaris doesn't answer, query() raises ZetarisOffline and Palace says
so; it never invents rows. An auth or SQL error is a ZetarisError, not an outage.

The planner's tools are the templates below. Their parameters are values, never SQL: each one must be a plain
value (letters, digits, spaces and . : / ( ) -) or an ISO date, and anything else returns an empty RecordSet
without a query being sent. The REST endpoint has no bind parameters, and Zetaris's Spark-like dialect and the
test double's SQLite quote strings differently, so an allow-list is safer than escaping.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass

QUERY_PATH = "/api/proxy/sql-editor/sqls/run-query"
LOGIN_PATH = "/api/auth/login"
DB = "PALACE_DEMO"
_VALUE = re.compile(r"[A-Za-z0-9 .:/()-]{1,80}")
_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
# A proxy in front of a stopped API answers with a gateway error: that is an outage, not a bad request.
_OUTAGE = {502, 503, 504}


class ZetarisError(RuntimeError):
    """Zetaris answered, but refused or failed the request (auth, SQL)."""


class ZetarisOffline(ZetarisError):
    def __init__(self, why: str):
        super().__init__(f"Zetaris: offline ({why})")


@dataclass(frozen=True)
class RecordSet:
    id: str
    sql: str
    columns: list[str]
    rows: list[list]
    row_count: int
    latency_ms: int

    def cite(self) -> str:
        return f"[{self.id}]"


def record_id(sql: str) -> str:
    return f"zetaris:q-{hashlib.sha256(sql.encode()).hexdigest()[:8]}"


def _value(v: str) -> str | None:
    return v if isinstance(v, str) and _VALUE.fullmatch(v) else None


def _date(v: str) -> str | None:
    return v if isinstance(v, str) and _DATE.fullmatch(v) else None


class Zetaris:
    def __init__(self, base_url: str, token: str, org_id: str, timeout: float = 30.0):
        self.base, self.token, self.org_id, self.timeout = base_url.rstrip("/"), token, str(org_id), timeout

    @classmethod
    def login(cls, base_url: str, email: str, password: str, timeout: float = 30.0) -> "Zetaris":
        """Sign in with a Zetaris user; the token and org id come from the login response, never assumed."""
        req = urllib.request.Request(base_url.rstrip("/") + LOGIN_PATH, method="POST",
                                     data=json.dumps({"username": email, "password": password}).encode(),
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                body = json.loads(r.read())
        except urllib.error.HTTPError as e:
            if e.code in _OUTAGE:
                raise ZetarisOffline(f"HTTP {e.code} at login") from None
            raise ZetarisError(f"Zetaris login failed: HTTP {e.code}") from None
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            raise ZetarisOffline(str(getattr(e, "reason", e))) from None
        token = body.get("idToken") or body.get("token") or body.get("accessToken")
        org = body.get("orgId") or (body.get("user") or {}).get("orgId")
        if not token or org is None:
            raise ZetarisError("Zetaris login answered without a token or an org id")
        return cls(base_url, token, str(org), timeout)

    # --- the REST call ----------------------------------------------------------------------------

    def query(self, sql: str, limit: int = 100) -> RecordSet:
        req = urllib.request.Request(self.base + QUERY_PATH, method="POST",
                                     data=json.dumps({"sql": sql, "limit": limit}).encode(),
                                     headers={"Content-Type": "application/json",
                                              "Authorization": f"Bearer {self.token}",
                                              "X-Org-ID": self.org_id, "X-Request-ID": str(uuid.uuid4())})
        t0 = time.monotonic()
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                body = json.loads(r.read())
        except urllib.error.HTTPError as e:
            detail = e.read()[:300].decode(errors="replace")
            if e.code in _OUTAGE:
                raise ZetarisOffline(f"HTTP {e.code}") from None
            raise ZetarisError(f"Zetaris refused the query: HTTP {e.code} {detail}") from None
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            raise ZetarisOffline(str(getattr(e, "reason", e))) from None
        rows = [["" if v is None else str(v) for v in row] for row in body.get("data") or []][:limit]
        total = body.get("total")
        return RecordSet(record_id(sql), sql, list(body.get("headers") or []), rows,
                         int(total) if total is not None else len(rows), int((time.monotonic() - t0) * 1000))

    def health(self) -> bool:
        try:
            return self.query("SELECT 1").rows == [["1"]]
        except ZetarisError:
            return False

    # --- the planner's templates --------------------------------------------------------------------

    def _refused(self, template: str) -> RecordSet:
        sql = f"-- {template}: refused, a parameter was not a plain value"
        return RecordSet(record_id(sql), sql, [], [], 0, 0)

    def decisions(self, topic: str, status: str | None = None) -> RecordSet:
        t, s = _value(topic), _value(status) if status is not None else ""
        if t is None or s is None:
            return self._refused("decisions")
        where = f"topic = '{t}'" + (f" AND status = '{s}'" if status is not None else "")
        return self.query(f"SELECT decision_id, date, decision, status, supersedes FROM {DB}.decisions "
                          f"WHERE {where} ORDER BY date")

    def count_devices(self, since: str, until: str | None = None, type: str | None = None) -> RecordSet:
        a, b = _date(since), _date(until) if until is not None else ""
        k = _value(type) if type is not None else ""
        if a is None or b is None or k is None:
            return self._refused("count_devices")
        where = f"handed_out >= '{a}'" + (f" AND handed_out <= '{b}'" if until else "") + \
                (f" AND type = '{k}'" if type else "")
        return self.query(f"SELECT count(*) AS devices FROM {DB}.device_ledger WHERE {where}")

    def attendance(self, since: str, until: str | None = None, class_name: str | None = None) -> RecordSet:
        a, b = _date(since), _date(until) if until is not None else ""
        c = _value(class_name) if class_name is not None else ""
        if a is None or b is None or c is None:
            return self._refused("attendance")
        where = f"date >= '{a}'" + (f" AND date <= '{b}'" if until else "") + (f" AND class = '{c}'" if class_name else "")
        return self.query(f"SELECT sum(attendees) AS attendees, count(*) AS sessions FROM {DB}.class_sessions "
                          f"WHERE {where}")

    def tickets(self, status: str | None = None, since: str | None = None) -> RecordSet:
        s = _value(status) if status is not None else ""
        a = _date(since) if since is not None else ""
        if s is None or a is None:
            return self._refused("tickets")
        conds = [f"status = '{s}'"] if status else []
        if since:   # tickets.opened is MM/DD/YYYY; compare it as YYYYMMDD
            conds.append(f"substr(opened, 7, 4) || substr(opened, 1, 2) || substr(opened, 4, 2) >= '{a.replace('-', '')}'")
        return self.query(f"SELECT ticket, opened, device, donor, issue, status FROM {DB}.tickets"
                          + (" WHERE " + " AND ".join(conds) if conds else "") + " ORDER BY ticket")

    def meeting_notes(self, search: str, since: str | None = None) -> RecordSet:
        q, a = _value(search), _date(since) if since is not None else ""
        if q is None or a is None:
            return self._refused("meeting_notes")
        where = f"lower(notes) LIKE '%{q.lower()}%'" + (f" AND date >= '{a}'" if since else "")
        return self.query(f"SELECT meeting_id, date, body, notes FROM {DB}.meeting_notes WHERE {where} ORDER BY date")


def open_zetaris(env=None) -> Zetaris | None:
    """The configured Zetaris, or None when ZETARIS_BASE_URL is unset (answers then come from memory alone).
    Auth: ZETARIS_TOKEN + ZETARIS_ORG_ID (an API token), or ZETARIS_EMAIL + ZETARIS_PASSWORD (a login)."""
    import os
    e = os.environ if env is None else env
    base = e.get("ZETARIS_BASE_URL")
    if not base:
        return None
    timeout = float(e.get("ZETARIS_TIMEOUT") or 60)
    if e.get("ZETARIS_TOKEN"):
        if not e.get("ZETARIS_ORG_ID"):
            raise ZetarisError("ZETARIS_TOKEN is set without ZETARIS_ORG_ID (read the org id from your Zetaris login)")
        return Zetaris(base, e["ZETARIS_TOKEN"], e["ZETARIS_ORG_ID"], timeout)
    if e.get("ZETARIS_EMAIL") and e.get("ZETARIS_PASSWORD"):
        return Zetaris.login(base, e["ZETARIS_EMAIL"], e["ZETARIS_PASSWORD"], timeout)
    raise ZetarisError("ZETARIS_BASE_URL is set, but neither ZETARIS_TOKEN nor ZETARIS_EMAIL/ZETARIS_PASSWORD is")


class Unreachable:
    """Stands in for a Zetaris that was offline at sign-in: every template raises the same ZetarisOffline, so the
    turn reports the outage and the model is told not to guess, exactly as when a query fails mid-turn."""

    def __init__(self, err: ZetarisOffline):
        self.err = err

    def __getattr__(self, name):
        def fail(*a, **kw):
            raise self.err
        return fail
