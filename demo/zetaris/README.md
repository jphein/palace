# Synthetic Zetaris dataset: Juniper Street Tech Hub (fictional)

**Status:** declared **pre-window prep**. It was written on 2026-10-19, before the Open Agent window, and committed in the
window's first commit (22 Oct 00:00 UTC = 21 Oct 17:00 PDT) unchanged except for this status line. Loading it into Zetaris is window work.

Regenerate with `python3 -I generate.py`. The seed is fixed, so two runs give byte-identical output
(md5 `eea92363…`, from concatenating `*.csv *.jsonl ground_truth.json`).

This is the same fictional world as `demo/seed.jsonl`, and the numbers agree with its memories (see the
`generate.py` docstring). The palace holds *what the person remembers*; Zetaris holds *the organisation's
records*. Some questions need both.

| Source (table) | Rows | Shape | Deliberate mess |
|---|---|---|---|
| `decisions.csv` | 10 | `decision_id, date, body, topic, decision, status, supersedes` | the formal log; `DEC-2026-006` is `superseded` by `DEC-2026-008` |
| `meeting_notes.jsonl` | 10 | `meeting_id, date, body, attendees[], notes` | free text; **MTG-0801 (Aug 1) still says the coordinator hire is on** |
| `class_sessions.csv` | 28 | `session_id, date, class, lead, attendees` | ISO dates |
| `tickets.csv` | 50 | `ticket, opened, closed, device, donor, issue, tech, status` | **MM/DD/YYYY** dates, nicknames (`Priya S.`, `D. Okafor`) |
| `device_ledger.csv` | 39 | `asset, type, ticket, handed_out, funding, loan_days` | joins to tickets on `ticket` |

## Questions only Zetaris can answer (ground truth in `ground_truth.json`)
- "What numbers go in the October county report?" → attendees since Jul 1 (**72**) and devices handed out since Jul 1
  (**27**: 5 Chromebook, 8 desktop, 6 hotspot, 4 laptop, 4 tablet). The palace memory (demo-019) only says what is
  *needed*; the counts live in `class_sessions` and `device_ledger`.
- "Did the first report's numbers hold up?" → Q2 attendees **41** and devices **12**, which match demo-014.
- "How many donations failed the SMART check?" → **3** rejected tickets.
- "Is the coordinator hire on?" → active `DEC-2026-008` (no). The trap is MTG-0801, a stale note from before the
  reversal. The agent should cite the decision log as the source of record and flag the stale note.
