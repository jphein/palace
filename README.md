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
python3 -m pytest -q                                   # 56 tests, offline
python3 -m palace ask "When is the next county report due?" --dry-run
python3 -m palace eval                                 # offline: recall@k + router tier accuracy
NEBIUS_API_KEY=... python3 -m palace models            # check the tier ids against the live catalog
NEBIUS_API_KEY=... python3 -m palace ask "Should I still plan on hiring a coordinator?"
NEBIUS_API_KEY=... python3 -m palace eval --live       # also: citation validity, abstention, tokens, cost
python3 -m palace serve                                # web chat on http://127.0.0.1:8765/
```

**Web chat.** `palace serve` opens a chat page with a **"What leaves the house"** panel: for every answer it shows the Nemotron tier and why it was chosen, the memories recalled (with ids and dates), how many characters of memory left, and the exact messages sent to Token Factory. Citations in an answer are clickable and highlight the memory they came from. Without `NEBIUS_API_KEY` the page runs in **preview** mode: recall and routing run, and the panel shows what *would* be sent, but nothing is. Light and dark themes; no JavaScript dependencies; binds to `127.0.0.1` unless you pass `--host`.

| Env | Meaning |
|---|---|
| `NEBIUS_API_KEY` | Token Factory API key |
| `NEBIUS_BASE_URL` | OpenAI-compatible base URL (default `https://api.tokenfactory.nebius.com/v1/`, verified live) |
| `PALACE_MODEL_NANO/SUPER/ULTRA` | Model ids per tier (defaults verified in the live catalog 2026-10-19; `palace models` re-checks) |
| `PALACE_PRICE_NANO/SUPER/ULTRA` | `"input,output"` USD per 1M tokens, for the per-answer cost (defaults in `config.py`) |
| `PALACE_URL`, `PALACE_API_KEY` | A **demo** palace-daemon; omit to use the offline synthetic palace |
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

Status: that output is the target. Recall, citations and the egress record work today. The Zetaris queries and the
source-of-record judgement are what this window builds.

This `public` branch is also the Open Agent Hackathon entry. The window opened on 22 Oct 2026 at 00:00 UTC.
- **Everything committed before that is pre-existing**: recall, the keyword router, the egress log, the web chat
  and the Token Factory client.
- **Declared pre-window prep**, written on 2026-10-19 and committed in the window's first commit:
  [`docs/open-agent-design.md`](docs/open-agent-design.md) and the synthetic dataset in [`demo/zetaris/`](demo/zetaris/).
- The design's §1 table lists, line by line, what is pre-existing and what is built in the window.

| Sponsor | Where it sits in Palace | Status |
|---|---|---|
| **Zetaris** | The source of record: the organisation's decisions, tickets and ledgers, queried over Zetaris REST next to the personal memory | planned (window work) |
| **Meterless** | The H-MEM memory layer (provenance, confidence, supersession) and the World Model event log; **Nightshift** as the primary AI provider | planned (window work) |
| **NVIDIA** | Nemotron 3 Nano / Super / Ultra answers each turn, via Nightshift lanes and Nebius Token Factory | Token Factory is pre-existing; Nightshift lanes are planned |
| **Cursor** | The development environment for the window's code; prompts and session logs go in `docs/cursor-evidence/` | setting up |

**How the sponsors run.**
- **Zetaris** runs locally, from the participant Docker bundle on our own hardware: a separate machine on the home
  network, which Palace reaches over Zetaris REST (design §3). It was installed and checked before the window.
- **Meterless Nightshift** will run in a Windows VM on another local machine, reached over its OpenAI-compatible API.
  The VM is being set up.
- Both will be running for the demo recording and during judging. Between development sessions their machines sleep
  to save power.

[`metadata.json`](metadata.json) holds the same information in machine-readable form. Its statuses are updated
with each commit.

## License

AGPL-3.0-or-later © 2026 Jeffrey Pine Hein. See [LICENSE](LICENSE). Built for [TechEMPOWER](https://techempower.org).

Source: <https://github.com/jphein/palace> (a running server links it at `/version`). This repository's history starts
from a squashed snapshot on 2026-09-27; development before that happened in a private repository, which is not published.
