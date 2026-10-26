"""Load the synthetic dataset into a running Zetaris as the Lightning database PALACE_DEMO, through Palace's own adapter.

    python3 demo/zetaris/load_zetaris.py csv OUT_DIR       # write the five CSVs Zetaris reads (meeting notes flattened)
    # copy OUT_DIR/*.csv to customer-data/shared/palace/ in the Zetaris driver container, e.g.
    #   docker cp OUT_DIR/. <driver container>:/home/zetaris/customer-data/shared/palace/
    python3 demo/zetaris/load_zetaris.py load BASE_URL < login.json   # {"username": …, "password": …} on stdin

The login JSON is read from stdin so credentials never reach argv or disk. Re-running `load` is safe: a table that
already exists is reported and kept. It ends by checking every table's row count against ground_truth.json.
"""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent))
from palace.adapters.zetaris import Zetaris, ZetarisError  # noqa: E402

TABLES = ("decisions", "meeting_notes", "class_sessions", "tickets", "device_ledger")
PATH = "file:///home/zetaris/customer-data/shared/palace/{}.csv"


def write_csvs(out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    for name in TABLES:
        if name != "meeting_notes":
            (out / f"{name}.csv").write_bytes((HERE / f"{name}.csv").read_bytes())
    notes = [json.loads(line) for line in (HERE / "meeting_notes.jsonl").read_text().splitlines() if line.strip()]
    with open(out / "meeting_notes.csv", "w", newline="") as f:
        w = csv.writer(f, quoting=csv.QUOTE_MINIMAL)
        w.writerow(["meeting_id", "date", "body", "attendees", "notes"])
        for n in notes:
            w.writerow([n["meeting_id"], n["date"], n["body"], ", ".join(n["attendees"]), n["notes"]])
    print(f"wrote {len(TABLES)} CSVs to {out}")


def load(base_url: str, login: dict) -> int:
    z = Zetaris.login(base_url, login["username"], login["password"], timeout=120)
    for sql in ['CREATE LIGHTNING DATABASE PALACE_DEMO DESCRIBE BY "Juniper_Street_Tech_Hub-fictional,synthetic_org_data"'] + [
            f'CREATE LIGHTNING FILESTORE TABLE {t} FROM PALACE_DEMO FORMAT CSV OPTIONS '
            f'(PATH "{PATH.format(t)}", HEADER "true", INFERSCHEMA "true")' for t in TABLES]:
        try:
            z.query(sql)
            print(f"ok    {sql[:70]}")
        except ZetarisError as e:
            if "already exists" not in str(e).lower():
                raise
            print(f"kept  {sql[:70]} (already exists)")
    want = json.loads((HERE / "ground_truth.json").read_text())["rows"]
    bad = 0
    for t in TABLES:
        rs = z.query(f"SELECT count(*) FROM PALACE_DEMO.{t}")
        n = int(rs.rows[0][0])
        bad += n != want[t]
        print(f"{'PASS' if n == want[t] else 'FAIL'}  PALACE_DEMO.{t}: {n} rows (want {want[t]})  {rs.id} {rs.latency_ms} ms")
    return 1 if bad else 0


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "csv":
        write_csvs(Path(sys.argv[2]))
    elif len(sys.argv) == 3 and sys.argv[1] == "load":
        sys.exit(load(sys.argv[2], json.loads(sys.stdin.read())))
    else:
        sys.exit(__doc__)
