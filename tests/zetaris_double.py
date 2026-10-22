"""A TEST DOUBLE of the Zetaris SQL REST endpoint. Tests only; never evidence of a real Zetaris call.

It serves the synthetic dataset in demo/zetaris/ from an in-memory SQLite database attached as PALACE_DEMO, so
`SELECT … FROM PALACE_DEMO.decisions` works as it does against the real Lightning database. The request and
response shapes follow what the real UI proxy returned before the window (docs/open-agent-design.md §3):

    POST /api/proxy/sql-editor/sqls/run-query   {"sql": …, "limit": N}
    -> {"headers": [...], "data": [[...]], "total": n}      (every value a string, as Zetaris returns them)

Known gap: SQLite's dialect is not Zetaris's (Spark-like) SQL. A query that passes here can still fail on the real
engine, so the adapter's live run against Zetaris is the real check.
"""

import csv
import json
import sqlite3
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

DATASET = Path(__file__).resolve().parent.parent / "demo" / "zetaris"
QUERY_PATH = "/api/proxy/sql-editor/sqls/run-query"
TABLES = ("decisions", "class_sessions", "tickets", "device_ledger")


def load_dataset(conn: sqlite3.Connection) -> None:
    conn.execute("ATTACH DATABASE ':memory:' AS PALACE_DEMO")
    for name in TABLES:
        with open(DATASET / f"{name}.csv", newline="") as f:
            rows = list(csv.DictReader(f))
        cols = list(rows[0])
        conn.execute(f"CREATE TABLE PALACE_DEMO.{name} ({', '.join(cols)})")
        conn.executemany(f"INSERT INTO PALACE_DEMO.{name} VALUES ({', '.join('?' * len(cols))})",
                         [[_typed(r[c]) for c in cols] for r in rows])
    notes = [json.loads(line) for line in (DATASET / "meeting_notes.jsonl").read_text().splitlines() if line.strip()]
    conn.execute("CREATE TABLE PALACE_DEMO.meeting_notes (meeting_id, date, body, attendees, notes)")
    conn.executemany("INSERT INTO PALACE_DEMO.meeting_notes VALUES (?, ?, ?, ?, ?)",
                     [(n["meeting_id"], n["date"], n["body"], ", ".join(n["attendees"]), n["notes"]) for n in notes])


def _typed(v: str):
    return int(v) if v.isdigit() else v     # INFERSCHEMA makes attendee counts integers; ids and dates stay text


class ZetarisDouble:
    """Start with `with ZetarisDouble() as z:`; `z.base_url`, `z.token`, `z.org_id`, and `z.requests` (what arrived)."""

    def __init__(self, token: str = "test-token", org_id: str = "1"):
        self.token, self.org_id, self.requests = token, org_id, []
        self.db = sqlite3.connect(":memory:", check_same_thread=False)
        self.lock = threading.Lock()
        load_dataset(self.db)
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), self._handler())
        self.base_url = f"http://127.0.0.1:{self.httpd.server_address[1]}"

    def __enter__(self):
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        return self

    def __exit__(self, *exc):
        self.httpd.shutdown()
        self.db.close()

    def _handler(self):
        double = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _send(self, code: int, body: dict):
                raw = json.dumps(body).encode()
                self.send_response(code)
                self.send_header("content-type", "application/json")
                self.send_header("content-length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers.get("content-length") or 0)) or b"{}")
                double.requests.append({"path": self.path, "headers": dict(self.headers), "body": body})
                if self.path != QUERY_PATH:
                    return self._send(404, {"error": "not found"})
                if self.headers.get("authorization") != f"Bearer {double.token}":
                    return self._send(401, {"error": "unauthorized"})
                if self.headers.get("x-org-id") != double.org_id:
                    return self._send(403, {"error": "wrong org"})
                try:
                    uuid.UUID(self.headers.get("x-request-id") or "", version=4)
                except ValueError:
                    return self._send(400, {"error": "X-Request-ID must be a uuid4"})
                try:
                    with double.lock:
                        cur = double.db.execute(body["sql"])
                        rows = cur.fetchall()
                except (sqlite3.Error, KeyError) as e:
                    return self._send(400, {"error": f"query failed: {e}"})
                limit = int(body.get("limit") or 100)
                headers = [d[0] for d in cur.description or ()]
                data = [["" if v is None else str(v) for v in r] for r in rows[:limit]]
                self._send(200, {"headers": headers, "data": data, "total": len(rows)})

        return Handler
