"""Generate the synthetic, multi-source "organisation data" for the Juniper Street Tech Hub (fictional),
to load into the hackathon's Zetaris instance once access exists. Deterministic (fixed seed).

Same fictional world as demo/seed.jsonl, and the numbers AGREE with its memories:
  - first quarterly county report (demo-014, filed 2026-07-14): 41 class attendees, 12 devices distributed
    (both counted 2026-04-01 .. 2026-06-30);
  - county grant $8,000, devices/hotspots/materials only (demo-012);
  - coordinator hire decided 2026-07-10 (demo-013), reversed 2026-08-05 (demo-016);
  - SMART-check rule after two failing SSDs (demo-008); hotspot one-week loans (demo-018).
Deliberately fragmented like real org data: tickets use MM/DD/YYYY dates and nicknames ("Priya S."),
the decision log is ISO and formal, meeting notes are free text, and one note (2026-08-01) still says the
coordinator hire is on, four days before the decision log reverses it.

    python3 generate.py            # writes the CSV/JSONL files next to this script
"""
from __future__ import annotations

import csv
import datetime as dt
import json
import random
from pathlib import Path

OUT = Path(__file__).resolve().parent
R = random.Random(20261019)
D = dt.date


def day(s: str) -> D:
    return D.fromisoformat(s)


def us(d: D) -> str:          # the ticket system's date format
    return d.strftime("%m/%d/%Y")


# --- decisions (board decision log; source of record for "what did we decide") ----------------
DECISIONS = [
    ("DEC-2026-001", "2026-03-02", "board", "hours", "Open Saturdays 10:00-14:00; drop Friday evenings.", "active", ""),
    ("DEC-2026-002", "2026-03-15", "board", "grants", "Apply for the county Digital Inclusion mini-grant ($8,000), not the state grant.", "active", ""),
    ("DEC-2026-003", "2026-05-01", "board", "grants", "Report to the county quarterly: Jul 15, Oct 15, Jan 15.", "active", ""),
    ("DEC-2026-004", "2026-05-12", "ops", "devices", "SMART-check every donated machine before accepting it.", "active", ""),
    ("DEC-2026-005", "2026-06-03", "ops", "signup", "Move the class sign-up sheet to a web form; keep paper as backup.", "active", ""),
    ("DEC-2026-006", "2026-07-10", "board", "staffing", "Hire a part-time coordinator in the fall, funded from general donations.", "superseded", ""),
    ("DEC-2026-007", "2026-07-22", "ops", "signup", "Cap each Saturday slot at 4 and send a confirmation text.", "active", ""),
    ("DEC-2026-008", "2026-08-05", "board", "staffing", "No coordinator hire this fall (donations 40% under plan). Revisit in January.", "active", "DEC-2026-006"),
    ("DEC-2026-009", "2026-08-30", "ops", "hotspots", "Hotspot loans are one week, with a text reminder on day 6.", "active", ""),
    ("DEC-2026-010", "2026-09-25", "board", "classes", "Co-host 'scam spotting' with the library, Nov 7 10:00, library community room.", "active", ""),
]

# --- meeting notes (free text, the messiest source) --------------------------------------------
NOTES = [
    ("MTG-0302", "2026-03-02", "board", ["Jordan", "Priya", "Marcus", "Dee"], "Friday nights averaged 3 people; the two Saturday pilots drew 14. Agreed to switch to Saturdays."),
    ("MTG-0315", "2026-03-15", "board", ["Jordan", "Dee"], "State grant needs audited financials we don't have. Going for the county mini-grant instead."),
    ("MTG-0512", "2026-05-12", "ops", ["Jordan", "Priya"], "Two donated laptops died within a week (SSDs). Priya will SMART-check all donations from now on."),
    ("MTG-0630", "2026-06-30", "board", ["Jordan", "Marcus", "Dee"], "County grant awarded, $8,000. Restricted: devices, hotspots, class materials. No wages."),
    ("MTG-0710", "2026-07-10", "board", ["Jordan", "Priya", "Marcus", "Dee"], "Coordinator: yes for fall, from general donations. Jordan drafts the posting."),
    ("MTG-0801", "2026-08-01", "ops", ["Priya", "Dee"], "Coordinator posting still on for September per July meeting; Dee to share it with the library."),
    ("MTG-0805", "2026-08-05", "board", ["Jordan", "Marcus", "Dee"], "Donations 40% under plan. Coordinator hire is off for fall; revisit in January. Pull the posting."),
    ("MTG-0830", "2026-08-30", "ops", ["Jordan", "Dee"], "Hotspot returns were 60%. Trial of one-week loans + day-6 text got 95%. Making it the rule."),
    ("MTG-0910", "2026-09-10", "ops", ["Priya", "Dee"], "Priya out Tuesdays in October. Dee covers the first two repair nights."),
    ("MTG-0925", "2026-09-25", "board", ["Jordan", "Marcus"], "Library agreed to co-host scam spotting Nov 7. Marcus will adapt the 18pt one-page guide."),
]

PEOPLE_TICKET_NAMES = {"Priya": "Priya S.", "Dee": "D. Okafor", "Marcus": "marcus", "Jordan": "J. (director)"}
DONORS = ["Pine Ridge Credit Union", "St. Anne's parish", "Hollis Dental", "a neighbour", "Riverside Library surplus",
          "Kim family", "County IT surplus"]
DEVICES = ["Chromebook", "laptop", "laptop", "tablet", "desktop", "hotspot"]


def sessions() -> list[dict]:
    """Class sessions. Apr-Jun attendance sums to exactly 41 (the first county report)."""
    rows, n = [], 0
    classes = [("phone basics (seniors)", "Marcus"), ("laptop repair night", "Priya"), ("Saturday open lab", "Dee")]
    q2_counts = [3, 4, 2, 5, 3, 4, 2, 3, 4, 3, 5, 3]          # 12 sessions, sum 41
    assert sum(q2_counts) == 41
    d = day("2026-04-04")
    for c in q2_counts:
        cls, lead = classes[n % 3]
        n += 1
        rows.append({"session_id": f"S{n:03d}", "date": d.isoformat(), "class": cls, "lead": lead, "attendees": c})
        d += dt.timedelta(days=7)
    d = day("2026-07-04")
    while d <= day("2026-10-17"):
        cls, lead = classes[n % 3]
        if cls == "laptop repair night" and d.month == 10 and d.day <= 14:
            lead = "Dee"                                     # demo-020: Dee covers Priya's October nights
        n += 1
        rows.append({"session_id": f"S{n:03d}", "date": d.isoformat(), "class": cls, "lead": lead,
                     "attendees": R.randint(2, 7)})
        d += dt.timedelta(days=7)
    return rows


def tickets_and_devices() -> tuple[list[dict], list[dict]]:
    """Repair/intake tickets and the device ledger. 12 devices go out Apr-Jun (first county report)."""
    tickets, ledger, n = [], [], 0
    d = day("2026-04-02")
    out_q2 = 0
    while d <= day("2026-10-16"):
        n += 1
        kind = DEVICES[R.randrange(len(DEVICES))]
        donor = DONORS[R.randrange(len(DONORS))]
        smart_fail = kind in ("laptop", "desktop") and R.random() < 0.15
        if d < day("2026-05-12") and kind == "laptop" and n in (9, 11):
            smart_fail = True                                 # the two dead SSDs before the SMART rule
        status = "rejected (SMART fail)" if smart_fail and d >= day("2026-05-12") else "closed"
        tech = PEOPLE_TICKET_NAMES["Priya"] if d.month != 10 else PEOPLE_TICKET_NAMES["Dee"]
        closed = d + dt.timedelta(days=R.randint(1, 9))
        issue = "intake check" if kind != "hotspot" else "hotspot setup"
        if smart_fail and d < day("2026-05-12"):
            issue, status = "failed SSD after handout", "closed (device recalled)"
        tickets.append({"ticket": f"T-{1000 + n}", "opened": us(d), "closed": us(closed) if closed <= day("2026-10-17") else "",
                        "device": kind, "donor": donor, "issue": issue, "tech": tech, "status": status})
        distributable = status == "closed"
        if distributable:
            in_q2 = day("2026-04-01") <= closed <= day("2026-06-30")
            if in_q2 and out_q2 >= 12:
                distributable = False                         # keep Q2 handouts at exactly 12
            if distributable and closed <= day("2026-10-17"):
                out_q2 += in_q2
                ledger.append({"asset": f"JSH-{n:04d}", "type": kind, "ticket": f"T-{1000 + n}",
                               "handed_out": closed.isoformat(), "funding": "county grant" if closed >= day("2026-06-30") else "donated",
                               "loan_days": 7 if kind == "hotspot" and closed >= day("2026-08-30") else ""})
        d += dt.timedelta(days=R.choice([3, 4, 5]))
    assert out_q2 == 12, out_q2
    return tickets, ledger


def write_csv(name: str, rows: list[dict]) -> None:
    with open(OUT / name, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


def main() -> None:
    write_csv("decisions.csv", [dict(zip(["decision_id", "date", "body", "topic", "decision", "status", "supersedes"], r))
                                for r in DECISIONS])
    with open(OUT / "meeting_notes.jsonl", "w") as f:
        for mid, date, body, who, text in NOTES:
            f.write(json.dumps({"meeting_id": mid, "date": date, "body": body, "attendees": who, "notes": text}) + "\n")
    s = sessions()
    write_csv("class_sessions.csv", s)
    t, led = tickets_and_devices()
    write_csv("tickets.csv", t)
    write_csv("device_ledger.csv", led)

    since_jul = [r for r in led if r["handed_out"] >= "2026-07-01"]
    truth = {
        "q2_attendees": sum(r["attendees"] for r in s if "2026-04-01" <= r["date"] <= "2026-06-30"),
        "q2_devices_out": sum("2026-04-01" <= r["handed_out"] <= "2026-06-30" for r in led),
        "q3q4_attendees_since_jul": sum(r["attendees"] for r in s if r["date"] >= "2026-07-01"),
        "devices_out_since_jul": len(since_jul),
        "devices_out_since_jul_by_type": {k: sum(r["type"] == k for r in since_jul) for k in sorted({r["type"] for r in since_jul})},
        "smart_rejections": sum(r["status"].startswith("rejected") for r in t),
        "active_staffing_decision": "DEC-2026-008",
        "rows": {"decisions": len(DECISIONS), "meeting_notes": len(NOTES), "class_sessions": len(s), "tickets": len(t),
                 "device_ledger": len(led)},
    }
    (OUT / "ground_truth.json").write_text(json.dumps(truth, indent=2) + "\n")
    print(json.dumps(truth, indent=2))


if __name__ == "__main__":
    main()
