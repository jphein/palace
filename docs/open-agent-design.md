# Palace for Open Agent Hackathon 2026: design

Entry: **Wildcard [Tinkerer]: Bring Your Own Project** ("bring an existing project, prototype or concept and
extend it using Zetaris and Meterless"). Team Palace, solo.

Palace is a private personal AI over a person's own memories. It answers from what you remember, cites the
memory it used, and shows exactly what leaves the house on every turn. For Open Agent it gains a second source,
the organisation's records in **Zetaris**, and **Meterless** engines that decide which source wins when they
disagree. **Meterless Nightshift**, with NVIDIA Nemotron lanes, becomes the primary AI provider.

## 1. Pre-existing vs. built in the window

The window opened on 22 Oct 00:00 UTC. Everything committed before it is pre-existing and is declared here, in
the README and in `metadata.json`.

| Pre-existing (before 22 Oct 00:00 UTC) | Built in the window |
|---|---|
| Recall over a synthetic palace (offline BM25, or a memory daemon over HTTP) | **Zetaris adapter**: the organisation's records over Zetaris REST, as the source of record |
| Keyword tier router (Nano / Super / Ultra, with a stated reason) | **Planner**: intent → guard → route → tier and cost ceiling, replacing the keyword router |
| Grounded prompt with numbered citations, plus the "what leaves the house" egress record | **H-MEM memory layer** (Meterless engine): provenance, confidence, superseded penalty, contradiction records, append-only trust ledger |
| Web chat and egress panel, container, hourly cap, real-palace guard | **World Model event log** (Meterless engine) over the Zetaris records: canonical, append-only, stable ids |
| Nebius Token Factory client (Nemotron 3 Nano / Super / Ultra), `palace models`, `palace eval` (26 questions), per-turn cost | **Meterless Nightshift provider** (primary): OpenAI-compatible, tier → Nemotron lanes |
| Live eval (2026-10-19): expected-cited 0.958, citation valid 1.0, abstain 1.0; keyword router tier accuracy **0.731**, the "before" for the planner | **JSONL evidence log** of every Zetaris, Nightshift/Nemotron and engine call; eval extension; FAILURES.md |
| **Declared pre-window prep** (written 2026-10-19, committed in the window): this design document, plus the synthetic Zetaris dataset (`demo/zetaris/`: 5 tables, `ground_truth.json`) and its generator | |

**As built, 26 Oct 2026** (each merged on `public` after tests, a perturbation that went red, and a secret scan):

| Window item | Status | Where |
|---|---|---|
| Zetaris adapter, query templates, live tests, dataset loader | **built** | jphein/palace#10 (`5d4be0e`): `palace/adapters/zetaris.py`, `palace/orgplan.py` |
| Meterless Nightshift provider (primary), Nemotron pinned per tier, receipts | **built** | #11 (`3e4b1f1`): `palace/providers/meterless.py` |
| H-MEM memory layer in every turn, conformance vectors ported (13/13), trust ledger | **built** | #12 (`4adfef0`): `palace/engines/hmem.py` |
| FAILURES.md, test-env isolation | **built** | this table's PR |
| Planner replacing the keyword router | **not built**: `palace/orgplan.py` picks Zetaris templates by rule; the tier router is still the pre-existing one (0.731) | |
| World Model event log | **not built** | |
| JSONL evidence log of every call; eval extension | **partly**: the H-MEM trust ledger (`PALACE_TRUST_LEDGER`) and per-answer receipts; no eval extension | |

No Zetaris or Meterless code existed before the window. The dataset, its generator and this document were
written before the window and are declared as prep, not presented as window work.

## 2. Architecture

```
question
   │
   ▼
┌──────────────────────────────── Planner ────────────────────────────────────────────────┐
│ sense: intent + confidence  ·  guard: injection / scope (read-only; never writes)          │
│ route: memory? organisation records? both?  ·  recommend: tier (Nano|Super|Ultra) + cost   │
│ ceiling → a signed plan {intent, tools[], tier, ceiling_usd, reasons}                       │
└───────────────┬─────────────────────────────────────────────┬─────────────────────────────┘
                │ recall(query)                               │ org_query(template, params)
     ┌──────────▼───────────┐                      ┌──────────▼──────────────────────────────┐
     │ H-MEM over the palace│                      │ Zetaris adapter (REST, read-only)        │
     │ (what the person     │                      │ decisions, meeting_notes, class_sessions, │
     │ remembers): source,  │                      │ tickets, device_ledger                    │
     │ trust, superseded,   │                      │      │ rows → World Model event log        │
     │ contradictions       │                      │      ▼   (canonical, stable ids)           │
     └──────────┬───────────┘                      └──────────┬──────────────────────────────┘
                │ [demo-019] (+ conflict record)               │ [wm:DEC-2026-008] [zetaris:q-…]
     ┌──────────▼─────────────────────────────────────────────▼──────────────────────────────┐
     │ Answerer: a Nemotron lane through Meterless Nightshift, grounded only in the memories  │
     │ and record sets; cites both; names any conflict and which source of record won          │
     └──────────┬───────────────────────────────────────────────────────────────────────────────┘
                ▼
   answer + citations + egress record + cost; every step appended to logs/agent-YYYY-MM-DD.jsonl,
   and every memory change appended to the H-MEM trust ledger
```

**Why each sponsor is load-bearing.** The test: take it out, and named evals fail.
- **Zetaris.** "What numbers go in the October county report?" needs 72 attendees and 27 devices. Those are
  aggregates over `class_sessions` and `device_ledger`, and the palace memory only says what is *needed*
  (demo-019). Without Zetaris, Palace can say what you remember but not what the records say.
- **Meterless H-MEM.** "Is the coordinator hire on?" has three sources that disagree: the July memory, the
  August reversal and a stale meeting note (MTG-0801). H-MEM's superseded penalty and contradiction records
  decide the ranking, and the trust ledger explains it ("why did it say no?" → a ledger trace).
- **Meterless World Model.** Zetaris rows become canonical entities with stable ids, so a decision cited twice
  has one id, and conflicts between the decision log and the notes are explicit events.
- **Meterless Nightshift + NVIDIA.** Every model call goes through Nightshift to Nemotron lanes (§4b). Remove
  Nightshift and Palace can't answer. The pre-existing direct Token Factory provider stays selectable.

## 3. Zetaris adapter (`palace/adapters/zetaris.py`)

Zetaris runs locally under Docker (the participant bundle). It was checked on our install before the window:
`verify.sh` passed all 9 checks, a REST `SELECT 1` returned `[["1"]]` from another machine, and the dataset's
`decisions.csv` loaded as a Lightning filestore table that reads back its 10 rows.

| | |
|---|---|
| Base URL | `ZETARIS_BASE_URL`, the UI proxy origin (default `http://localhost:3000`). The API's own port stays bound to loopback, as the bundle ships it |
| Auth | `Authorization: Bearer <token>` (an API token from Management → API tokens, or a login token), `X-Org-ID: <org id>` (`ZETARIS_ORG_ID`, often `1`; read it from the login response, never assume it), `X-Request-ID: <uuid4>` |
| Query | `POST /api/proxy/sql-editor/sqls/run-query`, body `{"sql": …, "limit": N}` → `{"headers": […], "data": [[…]], "total": n}` |
| Health | `SELECT 1` → `[["1"]]` |
| Data | One Lightning database, `PALACE_DEMO`, with one `CREATE LIGHTNING FILESTORE TABLE … FORMAT CSV` per dataset file |

```python
class Zetaris:
    def query(self, sql: str, limit: int = 100) -> RecordSet: ...   # one REST call; logs rows and latency
    def health(self) -> bool: ...
@dataclass(frozen=True)
class RecordSet:
    id: str          # citation id "zetaris:q-<8 hex of sha256(sql)>"
    sql: str; columns: list[str]; rows: list[list]; row_count: int; latency_ms: int
```

- **Query templates are the planner's tools.** It fills the parameters; there's no free-form SQL in v1.
  The templates: `count_devices(since, until, type?)`, `attendance(since, until, class?)`,
  `decisions(topic, status?)`, `tickets(status?, since?)`, `meeting_notes(search, since?)`.
  Ticket dates are MM/DD/YYYY and are normalised in the World Model ingest (a FAILURES.md topic).
- **Egress:** record sets sent to Nemotron appear in the egress record next to the memory snippets, with a row
  cap per record set.
- **Offline:** if Zetaris doesn't answer, Palace says "Zetaris: offline". It never shows invented rows.

## 4. Meterless engines

Meterless staff, on the requirements (HackOS help channel, 2026-10-21):
> - **Build:** "Integrate at least one open-source Meterless Engine (H-MEM, Markovian or World Model) into your
>   application." "H-MEM and World Model absolutely count toward the Build requirement."
> - **Power:** "Add Meterless Nightshift as an AI provider for your app, just like you would OpenAI or
>   Anthropic." And "implementing the engines alone doesn't cover both parts."

Palace meets **Build** with **H-MEM** and **World Model**. The planner is Palace's own and is not claimed for
Build. The engines come from github.com/Meterless/Meterless, open source with no key. Each is "an implementation
spec for coding agents … Clone a folder, give it to your agent, and finish when the suite passes", and Palace's
are implemented in Python from each engine's `AGENTS.md`, in Cursor (§7).

| Engine | In Palace | Done when |
|---|---|---|
| **H-MEM** (`palace/engines/hmem.py`) | Records with source, confidence and lineage (rejected without a source); feedback deltas; a superseded penalty in ranking; contradiction records; an append-only trust ledger (`logs/trust-ledger.jsonl`) | The H-MEM conformance vectors (language-neutral JSON) ported to pytest and green for the implemented sections; unimplemented sections listed, not hidden |
| **World Model** (`palace/engines/world_model.py`) | Zetaris rows → an append-only canonical event log (`logs/world-model.jsonl`); content-addressed stable ids; idempotent re-ingest; derived views (decision status by topic) | World Model vectors ported where language-neutral; re-ingesting the same rows gives a byte-identical log |
| **Markovian** | Not in v1: Palace turns are short | n/a |

"Official conformance green" is claimed only if the engine's own TypeScript runner passes against Palace's
engine. Otherwise the claim is "vectors ported".

## 4b. Power: Meterless Nightshift as the primary AI provider

- **Rules.** "Your application must support Meterless Nightshift as a primary AI provider." The NVIDIA award
  needs "at least one NVIDIA Nemotron model through Meterless Nightshift" in a working feature.
- **Path.** Palace → Nightshift (Windows desktop edition, in a VM on the home network) → Nemotron through
  Nightshift's Providers tab (an NVIDIA key from build.nvidia.com: Nano, Super, Ultra). The NVIDIA key lives in
  Nightshift, never in Palace.
- **Endpoint.** Staff: "normally http://127.0.0.1:8088/v1, with a locally generated access token". Palace
  reaches the VM's runtime through a firewalled forward on the LAN.
- **Built in Cursor** from Meterless's own "POWER → Add Meterless as a provider" prompt (meterless.ai), the
  workshop's suggested route. The generated code is reviewed against the contract below before it merges.

| Contract item (POWER prompt) | Palace (`palace/providers/meterless.py`) |
|---|---|
| Base URL, default `http://127.0.0.1:8088/v1`; pasted URLs normalised to `<host>/v1`, never `/v1/v1` | `METERLESS_BASE_URL`, normalised; a reachable remote URL is allowed |
| `Authorization: Bearer <runtime token>`; the placeholder `rt-local` is rejected | `METERLESS_API_KEY` (or `METERLESS_RUNTIME_TOKEN`) from the environment; never committed or logged |
| `meterless-app: <stable id>` on every request; `meterless-scope: user` on chat | `meterless-app: palace` |
| Discovery: `GET /v1/models` → `meterless/*` routes; unknown ids kept | `palace models --provider meterless` lists the routes and maps them to tiers |
| States: 401/403 → unauthorized; 200 + meterless ids → online; anything else → offline. `/healthz` is process-up only | Shown in the web panel and in `palace models`. A green `/healthz` is never reported as "model connected" |
| 180 s timeout (model loads) | The provider timeout is 180 s |

- **Tier → lane.** Planner tier `nano` → `meterless/fast`, and `super` and `ultra` → `meterless/deep`. Both lanes
  are configured to Nemotron models in Nightshift. `meterless/auto` isn't used for award evidence, since it "may
  route to a non-NVIDIA model".
- **Proving Nemotron served it.** Each response's `model` field is logged per request and cross-checked against
  Nightshift's run details. The video shows the Providers tab (NVIDIA connected, keys hidden), a lane on Nemotron,
  and one real request passing through.
- **Staff's fallback**, should the desktop edition misbehave without a dedicated GPU: "the web version and connect
  it to vLLM or Ollama or LM Studio". Recorded here next to the setup guide's note that the web edition alone
  doesn't count.
- **No simulated Nightshift, ever.** Unit checks of the provider run against fakes, and those fakes are never
  presented as Nightshift. Only a real Nightshift answer is claimed live.

## 5. Evidence log format

Each day writes `logs/agent-YYYY-MM-DD.jsonl`, one event per line, flushed per event. `palace log --pretty`
renders it as readable lines ("the executor queried Zetaris and returned 5 records").

```json
{"ts":"2026-10-23T17:04:11.203Z","turn":"t-7f3a","agent":"planner","event":"plan","intent":"report_numbers","confidence":0.91,"tools":["memory","zetaris"],"tier":"super","ceiling_usd":0.002,"signed":true}
{"ts":"…","turn":"t-7f3a","agent":"memory","event":"engine_call","engine":"hmem","op":"query","hits":3,"superseded_demoted":1,"conflicts":[]}
{"ts":"…","turn":"t-7f3a","agent":"executor","event":"sponsor_call","sponsor":"zetaris","endpoint":"POST /api/proxy/sql-editor/sqls/run-query","template":"count_devices","params":{"since":"2026-07-01"},"rows":5,"latency_ms":184,"status":200,"record_set":"zetaris:q-1a2b3c4d"}
{"ts":"…","turn":"t-7f3a","agent":"world_model","event":"engine_call","engine":"world-model","op":"ingest","events_appended":0,"idempotent":true}
{"ts":"…","turn":"t-7f3a","agent":"answerer","event":"sponsor_call","sponsor":"meterless","provider":"nightshift","endpoint":"POST /v1/chat/completions","route":"meterless/deep","served_by":"<model id from the response>","prompt_tokens":812,"completion_tokens":143,"latency_ms":2310,"status":200}
{"ts":"…","turn":"t-7f3a","agent":"answerer","event":"answer","cited":["demo-019","zetaris:q-1a2b3c4d"],"egress_chars":2104,"cost_usd":0.000372,"under_ceiling":true}
```

No headers, keys or bearer tokens are ever logged. Endpoints are logged as paths relative to the configured base.

## 6. Evals extension

- About 10 new questions with `expect_records` (template + value from `ground_truth.json`) and `expect_conflict`:
  - the October report numbers (72 attendees; 27 devices by type);
  - Q2 consistency (41 / 12, matching memory demo-014);
  - SMART-check rejections (3);
  - coordinator status (DEC-2026-008 wins over MTG-0801 and demo-013).
- New metrics: record accuracy, source-of-record wins, Zetaris queries per answer, planner tier accuracy (vs. the
  keyword router's 0.731), cost per answer vs. the planner's ceiling, and H-MEM vectors passed / total.
- Each live run is reported against the pre-window runs in `evals/runs/`.

## 7. Cursor

> **Update, 26 Oct 2026.** Cursor was not used in the end: the adapter, the Nightshift provider and H-MEM
> were written with Claude Code, which the 22 Oct change allows. The plan below is kept as written.
>
> **Update, 23 Oct 2026 (in the window).** On 22 Oct the organisers made Cursor optional ("any AI coding tool …
> Cursor, Claude Code, Windsurf or GitHub Copilot"), and no Cursor credits come with the event. Palace still uses
> Cursor for part of the window's code, on its free plan, and keeps the evidence as described below. The rest is
> built in Claude Code. What the change keeps unchanged is that at least one Meterless engine must work in a feature,
> shown by a passing test or a live demo (§4).

- Development of the engines, the Zetaris adapter and the Nightshift provider happens in Cursor (its agent CLI),
  starting from each engine's `AGENTS.md` and Meterless's POWER prompt.
- The README and `metadata.json` say how Cursor was used. Prompts and session logs are kept in
  `docs/cursor-evidence/`, and commits made from Cursor sessions carry a `Cursor-Session:` trailer.
