# Palace

**A private, always-on personal AI with a real long-term memory, running on NVIDIA Nemotron via Nebius Token Factory.**

Ask it what you decided, what you promised, or what happened last time, and it answers with dated citations from your own archive. Your memory stays on your server; only the few snippets needed for each answer go to the model, and a "what leaves the house" log shows exactly which ones.

> Status: a working build for the Nebius x NVIDIA Global AI Hackathon (Personal AI track). Recall, routing, the egress log, the CLI, the web chat and the evals work, and live answers run on Nemotron 3 Nano/Super/Ultra via Token Factory (first live eval 2026-10-19; see Evals). The Hermes Agent persona and public deploy are on the roadmap below.

## How it works

```
question ──► recall (palace-daemon: vector + BM25 + graph)  ──► top memories, with ids and dates
         ──► route (Nemotron Nano | Super | Ultra, with a stated reason)
         ──► Token Factory chat, grounded in the numbered memories only
         ──► answer with [citations] + egress record (which snippets left, how many chars)
```

- **Routing.** Nano for quick lookups ("when is…"), Super by default, Ultra only for planning, comparisons and judgement calls ("should I…", "what did I decide, and did it change?") or when many memories must be reconciled.
- **Memory.** [palace-daemon](https://github.com/rboarescu/palace-daemon) (MIT) over HTTP: `GET /search`, `POST /memory`. With no `PALACE_URL`, an offline BM25 index over the synthetic demo palace stands in.
- **Privacy by construction.** The model sees at most 600 characters per memory, only for the memories recalled for that question, and every turn records exactly what was sent.
- **Demo data is synthetic.** `demo/seed.jsonl` is a made-up archive for a fictional person.
- **A guard against real palaces** (`palace/config.py`). `PALACE_URL` is refused if its host is on your deny-list, or if it looks like a home server: a private or link-local IP, a single-label name (`mybox`), a LAN suffix (`.lan`, `.local`, `.home.arpa`, `.internal`), or a public name that resolves to a private address. Loopback is allowed, because that is where a throwaway demo daemon runs. No real hostnames ship in this repo. Put yours, one per line, in `~/.config/palace/forbidden-hosts` or a gitignored `.forbidden-hosts` at the repo root.

## Run

```bash
python3 -m pytest -q                                   # offline; the live Zetaris tests skip without ZETARIS_*
python3 -m palace ask "When is the next county report due?" --dry-run
python3 -m palace eval                                 # offline: recall@k + router tier accuracy
NEBIUS_API_KEY=... python3 -m palace models            # check the tier ids against the live catalog
NEBIUS_API_KEY=... python3 -m palace ask "Should I still plan on hiring a coordinator?"
NEBIUS_API_KEY=... python3 -m palace eval --live       # also: citation validity, abstention, tokens, cost
python3 -m palace serve                                # web chat on http://127.0.0.1:8765/
# Meterless Nightshift as the provider (primary when METERLESS_BASE_URL is set; Nemotron via its NVIDIA provider):
METERLESS_BASE_URL=http://127.0.0.1:8088 METERLESS_API_KEY=... python3 -m palace models
# with Zetaris (the organisation's records; load them once with demo/zetaris/load_zetaris.py):
ZETARIS_BASE_URL=http://localhost:3000 ZETARIS_EMAIL=... ZETARIS_PASSWORD=... \
  NEBIUS_API_KEY=... python3 -m palace ask "What numbers go in the October county report?"
```

**Web chat.** `palace serve` opens a chat page with a **"What leaves the house"** panel: for every answer it shows the Nemotron tier and why it was chosen, the memories recalled (with ids and dates), how many characters of memory left, and the exact messages sent to Token Factory. Citations in an answer are clickable and highlight the memory they came from. Without `NEBIUS_API_KEY` the page runs in **preview** mode: recall and routing run, and the panel shows what *would* be sent, but nothing is. Light and dark themes; no JavaScript dependencies; binds to `127.0.0.1` unless you pass `--host`.

| Env | Meaning |
|---|---|
| `NEBIUS_API_KEY` | Token Factory API key |
| `NEBIUS_BASE_URL` | OpenAI-compatible base URL (default `https://api.tokenfactory.nebius.com/v1/`, verified live) |
| `PALACE_MODEL_NANO/SUPER/ULTRA` | Model ids per tier (defaults verified in the live catalog 2026-10-19; `palace models` re-checks) |
| `PALACE_PRICE_NANO/SUPER/ULTRA` | `"input,output"` USD per 1M tokens, for the per-answer cost (defaults in `config.py`) |
| `PALACE_URL`, `PALACE_API_KEY` | A **demo** palace-daemon; omit to use the offline synthetic palace |
| `METERLESS_BASE_URL` | Meterless Nightshift's runtime URL (normalised to `…/v1`). When set, Nightshift is the provider |
| `METERLESS_API_KEY` | Nightshift's runtime token (or `METERLESS_RUNTIME_TOKEN`); the `rt-local` placeholder is refused |
| `METERLESS_MODEL_NANO/SUPER/ULTRA` | The NVIDIA Nemotron id pinned per tier (defaults in `config.py`; `palace models` checks them) |
| `PALACE_TRUST_LEDGER` | Append H-MEM's trust ledger (JSONL) to this file; unset keeps it in memory only |
| `PALACE_PROVIDER` | `meterless` or `tokenfactory`, to override the choice above |
| `ZETARIS_BASE_URL` | The Zetaris UI proxy origin, e.g. `http://localhost:3000`; omit to answer from memory alone |
| `ZETARIS_EMAIL`, `ZETARIS_PASSWORD` | A Zetaris login (the token and org id come from the login response); or `ZETARIS_TOKEN` + `ZETARIS_ORG_ID` |
| `PALACE_FORBIDDEN_HOSTS` | Comma-separated hosts that serve a **real** palace (added to the files below); subdomains are covered too |
| `PALACE_FORBIDDEN_HOSTS_FILE` | One more deny-list file (default files: `~/.config/palace/forbidden-hosts`, `./.forbidden-hosts`) |
| `PALACE_ALLOW_HOSTS` | Opts a LAN-looking **demo** daemon back in. It never overrides the deny-list |
| `PALACE_MAX_ASKS_PER_HOUR` | `palace serve`: caps **live** model calls across all visitors (a public demo shouldn't drain your credits). Over the cap, the page falls back to a preview. Unset means no cap |

**Container.** `docker build -t palace-nemotron .` then `docker run --rm -p 8080:8080 -e NEBIUS_API_KEY -e PALACE_MAX_ASKS_PER_HOUR=120 palace-nemotron`. The image serves the web chat on the synthetic demo palace, as a non-root user.

## Evals

`evals/questions.jsonl` holds 26 questions over the synthetic palace, each with the memories a good answer must
cite and the tier it deserves; two have no answer in the palace and should be declined. `palace eval` writes a
report to `evals/runs/`. Offline it scores **recall@k** (are the expected memories in the prompt?) and **tier
accuracy**; `--live` adds **citation validity** (does the answer cite only memories it was given?),
**expected-citation hits**, **abstention** on unanswerable questions, and token, latency and cost totals.

| Run (2026-10-19) | recall@k | tier acc. | citation valid | expected cited | abstain | tokens | cost | time |
|---|---|---|---|---|---|---|---|---|
| `baseline-offline` | 0.958 | 0.731 | | | | | | |
| `live-2026-10-19` (before the fix) | 0.958 | 0.731 | 1.0* | 0.792 | 1.0 | 10,368 + 4,249 | $0.0097 | 40 s |
| `live-2026-10-19-normalised` | 0.958 | 0.731 | 1.0 | 0.958 | 1.0 | 10,368 + 4,382 | $0.0102 | 41 s |

\*Not real evidence. Nemotron 3 Super cited 4 answers as `【demo-008】`, so the scorer saw *no* citations
on them, and "no invented ids" was vacuous. Answers are now normalised to `[demo-008]` and the scorer
reads both forms. Re-scoring the saved answers gives 23/24, and still no invented ids. The remaining miss
(q13) is recall: no stemming, so "hotspots/returned" doesn't match "Hotspot/returns". The tier misses are
the keyword router's (see the "miss" lines from `palace eval`).

## Roadmap to submission (Oct 30, 2026)
1. ~~Confirm the Nemotron 3 Nano/Super/Ultra ids with `palace models`; make the first real call and a live eval run.~~ (done 2026-10-19)
2. Hermes Agent persona: expose `recall`, `remember` and `brief_me` as Hermes tools that call this turn loop.
3. Optional: re-embed the demo wing with an NVIDIA embedding model on Token Factory; compare latency and quality.
4. ~~Web chat with the "what leaves the house" panel (dark/light)~~ (done: `palace serve`); public demo on the synthetic palace.
5. Optional Tavily web-search tool.
6. Demo video (≤3 min) naming Token Factory and Nemotron; README feedback section.

## Open Agent Hackathon 2026 (Wildcard [Tinkerer]: Bring Your Own Project)

**The five questions** (from the organisers' Day 1 brief):
- **Who is the user?** The volunteer coordinator of a small community tech hub (a nonprofit that refurbishes donated
  computers and runs digital-skills classes), who answers to its board and to a county grant.
- **What is the problem?** Before the quarterly county report, the coordinator has to state what was decided and give
  the numbers, but their own memory, the meeting notes and the organisation's records disagree. In the demo data, an
  Aug 1 meeting note still says a coordinator hire is on; the decision log reversed it on Aug 5.
- **What goes in?** A plain-language question, the coordinator's own memories (kept on their server), and the
  organisation's records in Zetaris: decisions, meeting notes, class sessions, repair tickets and the device ledger.
- **What comes out?** A short answer whose numbers come from the records. Every claim cites a memory or a Zetaris
  query, the source of record is named when sources disagree, and the "what leaves the house" record shows what
  was sent to the model.
- **Why does this need an agent?** Each question needs tools chosen at run time: which Zetaris queries to run with
  which parameters, which memories to trust, and which model tier is worth the cost. Then it needs a judgement about
  which source wins when they conflict over time. A single prompt can't query Zetaris, and a script can't read
  free-text notes or weigh a superseded decision.

Status (26 Oct): Zetaris works end to end. `palace ask` and the web chat pick read-only query templates for the
question (`palace/orgplan.py`), run them on Zetaris (`palace/adapters/zetaris.py`), and send the record sets to
Nemotron next to the memories. Each record set is cited as `[zetaris:q-…]` and listed in the egress record. A
live run answers "What numbers go in the October county report?" with 72 attendees and 27 devices, which match
`demo/zetaris/ground_truth.json`. If Zetaris is offline the answer says so and gives no numbers.

**Meterless H-MEM** (`palace/engines/hmem.py`) is implemented in Python from Meterless's open spec (`engines/hmem/AGENTS.md`)
and runs in every turn. The recalled memories become H-MEM records with a source and date. Enrichment links
supersession (Aug 5 "Reversed the July decision…" supersedes the Jul 10 decision), and the spec's hybrid score
(including the −0.20 superseded penalty) orders them. Superseded memories are still sent, labelled
`[SUPERSEDED by …]`, and every change goes to an append-only trust ledger (`PALACE_TRUST_LEDGER=path.jsonl`). The
spec's conformance vectors are ported to pytest (`tests/test_hmem_conformance.py`, 13/13 green). That is "vectors
ported", not the official TypeScript runner. Not implemented: LLM mining and chat scoping. The World Model engine
is not built.

Meterless Nightshift is the primary provider when it's configured (`palace/providers/meterless.py`). Each tier is
pinned to an NVIDIA Nemotron model, and each answer shows the model that actually ran plus Nightshift's compute
receipt id. A live run on 26 Oct answered the coordinator question on Nemotron 3 Ultra 550B through Nightshift. It
named the active decision, DEC-2026-008, and flagged the Aug 1 note MTG-0801 as out of date (receipt
`rcpt_req_hhn1rrhj`). Token Factory stays selectable with `PALACE_PROVIDER=tokenfactory`.

This `public` branch is also the Open Agent Hackathon entry. The window opened on 22 Oct 2026 at 00:00 UTC.
- **Everything committed before that is pre-existing**: recall, the keyword router, the egress log, the web chat
  and the Token Factory client.
- **Declared pre-window prep**, written on 2026-10-19 and committed in the window's first commit:
  [`docs/open-agent-design.md`](docs/open-agent-design.md) and the synthetic dataset in [`demo/zetaris/`](demo/zetaris/).
- The design's §1 table lists, line by line, what is pre-existing and what is built in the window. Its "As built" table says
  what was finished (Zetaris, Nightshift, H-MEM) and what wasn't (the Planner, the World Model).
- [`FAILURES.md`](FAILURES.md) lists the failure modes we found while building, and which of them are still open.
- [`examples/`](examples/) holds four live sample inputs and outputs (`palace ask --json`) and the H-MEM trust-ledger
  trace they produced. [`.env.example`](.env.example) lists every setting, with placeholder values only.

| Sponsor | Where it sits in Palace | Status |
|---|---|---|
| **Zetaris** | The source of record: the organisation's decisions, tickets and ledgers, queried over Zetaris REST next to the personal memory | **working** (adapter, query templates, live tests against our Zetaris) |
| **Meterless** | The H-MEM memory layer (provenance, confidence, supersession, trust ledger) in every turn; **Nightshift** as the primary AI provider | H-MEM **working** (conformance vectors green); Nightshift provider **working**; World Model not built |
| **NVIDIA** | Nemotron answers each turn: Nemotron 3.5 Lightning and Nemotron 3 Ultra via Nightshift's NVIDIA provider, or Nemotron 3 Nano / Super / Ultra via Nebius Token Factory | **working** on both |
| **Cursor** | Optional since HackOS's 22 Oct change. The window's code was written with Claude Code, not Cursor | not used |

**Grounded in Zetaris.** Every fact in an answer comes from a cited Zetaris record or a cited memory, so each answer
traces back to the data it rests on. Palace does no web search. If the optional web search on the roadmap (item 5) is
added, its results will be context only, never the cited source of a fact.

**How the sponsors run.**
- **Zetaris** runs locally, from the participant Docker bundle on our own hardware: a separate machine on the home
  network, which Palace reaches over Zetaris REST (design §3). It was installed and checked before the window. The
  five demo tables are loaded as the Lightning database `PALACE_DEMO` (`demo/zetaris/load_zetaris.py`), and
  `tests/test_zetaris_live.py` checks the templates against them on the real engine.
- **Meterless Nightshift** 1.2.3 runs in a Windows 10 VM on another local machine. Its OpenAI-compatible API answers
  from the dev machine: `GET /v1/models` lists the `meterless/*` routes, and a call without the runtime token gets 401.
  NVIDIA is connected in Nightshift's Providers tab (the key lives in Nightshift, never in Palace), and Palace calls
  Nightshift as its provider.
- Both will be running for the demo recording and during judging. Between development sessions their machines sleep
  to save power.

**Known limitations.**
- On a fresh Windows 10, Nightshift 1.2.3's `meterlessd.exe` won't start without the Microsoft Visual C++ runtime
  (`VCRUNTIME140.dll`), which its installer doesn't include. It exits with 0xC0000135. Installing Microsoft's
  `vc_redist.x64.exe` first fixes it.
- Through Nightshift's NVIDIA provider, Nemotron 3 Super 120B returns NVIDIA 404 ("function not found for account")
  for our key, so Palace's `super` tier pins Nemotron 3 Ultra. The `meterless/fast` and `meterless/deep` lanes
  routed to Ultra in 13–14 s, against 1.6 s for Ultra requested directly, so Palace pins model ids rather than lanes.
- Nemotron's reasoning sometimes arrives inline (a `…</think>` tail) through Nightshift. Palace strips it before
  showing the answer.

[`metadata.json`](metadata.json) holds the same information in machine-readable form. Its statuses are updated
with each commit.

## License

AGPL-3.0-or-later © 2026 Jeffrey Pine Hein. See [LICENSE](LICENSE). Built for [TechEMPOWER](https://techempower.org).

Source: <https://github.com/jphein/palace> (a running server links it at `/version`). This repository's history starts
from a squashed snapshot on 2026-09-27; development before that happened in a private repository, which is not published.
