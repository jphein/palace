# Sample inputs and outputs (live, 26 Oct 2026)

Each file is the real `python3 -m palace ask "<question>" --json` output against the running stack: Zetaris (the
participant bundle, `PALACE_DEMO`), Meterless H-MEM, and NVIDIA Nemotron through Meterless Nightshift. The data is
synthetic. Zetaris and Nightshift were reached through SSH tunnels on 127.0.0.1, so no host names appear.

| File | Question | What it shows |
|---|---|---|
| `01.json` | What numbers go in the October county report? | Two Zetaris templates (attendance, devices since Jul 1) → 72 and 27, cited `[zetaris:q-…]` |
| `02.json` | Should I still plan on hiring a coordinator this fall? | H-MEM marks demo-013 superseded by demo-016; the Zetaris decision log (DEC-2026-008) is the source of record |
| `03.json` | How many donations failed the SMART check? | One Zetaris template over the tickets table → 3 rejections |
| `04.json` | When is Mom's birthday dinner, and where? | A personal question: memory only, nothing asked of Zetaris, a quick Nemotron 3.5 Lightning answer |

Each JSON holds the route, the egress record (what left the house), the memories, the answer, the model that actually
ran, Nightshift's `receipt_id`, the H-MEM trace (scores, superseded links, ledger counts), and the Zetaris plan with
the record sets (SQL, columns, rows).

`trust-ledger.jsonl` is the H-MEM trust ledger those four turns appended (`PALACE_TRUST_LEDGER`). It is a trace of
how the agent reached its output: one `create` per recalled memory, the `update` that set `supersededBy`, and a `read`
per ranked memory.
