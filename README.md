# Palace

**A private, always-on personal AI with a real long-term memory, running on NVIDIA Nemotron via Nebius Token Factory.**

Ask it what you decided, what you promised, or what happened last time, and it answers with dated citations from your own archive. Your memory stays on your server; only the few snippets needed for each answer go to the model, and a "what leaves the house" log shows exactly which ones.

> Status: **skeleton** for the Nebius x NVIDIA Global AI Hackathon (Personal AI track). Recall, routing, the egress log, the CLI, the web chat and the tests work offline today. The live Token Factory call is wired but not yet run (needs an API key), and the Hermes Agent persona and public deploy are on the roadmap below.

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
python3 -m pytest -q                                   # 53 tests, offline
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
| `PALACE_MODEL_NANO/SUPER/ULTRA` | Model ids per tier (defaults are candidates; `palace models` checks them against the live catalog) |
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

## Roadmap to submission (Oct 30, 2026)
1. Confirm the Nemotron 3 Nano/Super/Ultra ids with `palace models`; make the first real call and a live eval run.
2. Hermes Agent persona: expose `recall`, `remember` and `brief_me` as Hermes tools that call this turn loop.
3. Optional: re-embed the demo wing with an NVIDIA embedding model on Token Factory; compare latency and quality.
4. ~~Web chat with the "what leaves the house" panel (dark/light)~~ (done: `palace serve`); public demo on the synthetic palace.
5. Optional Tavily web-search tool.
6. Demo video (≤3 min) naming Token Factory and Nemotron; README feedback section.

## License

AGPL-3.0-or-later © 2026 Jeffrey Pine Hein. See [LICENSE](LICENSE). Built for [TechEMPOWER](https://techempower.org).
