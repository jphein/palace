"""palace ask "question" [--dry-run] [--json]  |  palace serve [--host H] [--port P]  |  palace models
palace eval [--live] [--out PATH]"""
from __future__ import annotations

import argparse
import datetime
import os
import json
import sys
from pathlib import Path

from .agent import run_turn
from .config import Config, ConfigError
from .memory import open_memory


def _client(cfg: Config):
    if cfg.provider == "meterless":
        from .providers.meterless import Nightshift
        return Nightshift(cfg)
    from .tokenfactory import TokenFactory
    return TokenFactory(cfg)


def cmd_ask(cfg: Config, args) -> int:
    from .adapters.zetaris import Unreachable, ZetarisOffline, open_zetaris
    memory = open_memory(cfg)
    chat = None if args.dry_run else _client(cfg).chat
    try:
        org = open_zetaris()
    except ZetarisOffline as e:
        org = Unreachable(e)
    turn = run_turn(args.question, memory, chat, prices=cfg.prices, org=org,
                    ledger_path=os.environ.get("PALACE_TRUST_LEDGER") or None)
    if args.json:
        print(json.dumps({"route": turn.route.__dict__, "egress": turn.egress, "answer": turn.answer, "model": turn.model,
                          "usage": turn.usage, "cost_usd": turn.cost_usd, "provider": turn.provider,
                          "receipt_id": turn.receipt_id, "hmem": {**(turn.hmem or {}), "superseded": turn.superseded},
                          "memories": [m.__dict__ for m in turn.memories],
                          "zetaris": {"status": turn.org_status, "plan": [s.__dict__ for s in turn.plan],
                                      "egress": turn.record_egress,
                                      "records": [rs.__dict__ for rs in turn.records]}}, indent=2))
        return 0
    print(f"route: {turn.route.tier} ({turn.route.reason})")
    sent = [f"{e['id']} ({e['chars']} chars)" for e in turn.egress]
    sent += [f"{e['id']} ({e['rows']} rows, {e['chars']} chars)" for e in turn.record_egress]
    print("what leaves the house: " + (", ".join(sent) or "nothing"))
    for m in turn.memories:
        sup = f" (superseded by {turn.superseded[m.id]})" if m.id in turn.superseded else ""
        print(f"  {m.cite()} {m.wing}/{m.room}{sup}: {m.text[:100]}")
    if turn.hmem:
        print(f"h-mem: {turn.hmem['retrievalReason']}; ledger {turn.hmem['ledger']}")
    if turn.org_status:
        print(f"zetaris: {turn.org_status}")
    for step, rs in zip(turn.plan, turn.records):
        print(f"  {rs.cite()} {step.template}({', '.join(f'{k}={v!r}' for k, v in step.params.items())}) -> "
              f"{rs.row_count} rows in {rs.latency_ms} ms: {' | '.join(rs.columns)} = "
              + "; ".join(" | ".join(r) for r in rs.rows[:3]))
    if turn.answer:
        print("\n" + turn.answer)
        u = turn.usage or {}
        via = "Meterless Nightshift" if turn.provider == "meterless" else "Token Factory"
        print(f"\n{turn.model} via {via} · {u.get('prompt_tokens')} in / {u.get('completion_tokens')} out · "
              f"{u.get('latency_s')} s" + (f" · ${turn.cost_usd:.6f}" if turn.cost_usd is not None else "")
              + (f" · receipt {turn.receipt_id}" if turn.receipt_id else ""))
    return 0


def cmd_models(cfg: Config, args) -> int:
    """Check each configured tier id against the live catalog of the active provider."""
    client = _client(cfg)
    if cfg.provider == "meterless":
        print(f"Meterless Nightshift at {cfg.model_host}: {client.status()}")
    live = set(client.list_models())
    nemotron = sorted(m for m in live if "nemotron" in m.lower())
    ok = True
    for tier, model in cfg.active_models.items():
        found = model in live
        ok &= found
        print(f"{tier:5}  {model}  {'ok' if found else 'MISSING'}")
    print(f"\n{len(live)} models in the catalog; Nemotron: " + (", ".join(nemotron) or "none"))
    return 0 if ok else 1


def cmd_eval(cfg: Config, args) -> int:
    from .evals import load_questions, run_eval
    chat = _client(cfg).chat if args.live else None
    rep = run_eval(load_questions(), open_memory(cfg), chat, k=args.k, prices=cfg.prices)
    s = rep["summary"]
    s["at"] = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
    out = Path(args.out) if args.out else Path("evals/runs") / f"{s['at'][:19].replace(':', '')}-{s['mode']}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(rep, indent=2) + "\n")
    print(f"{s['mode']} eval, {s['questions']} questions: recall@k {s['recall_at_k']} · tier accuracy {s['tier_accuracy']}"
          f" · tiers {s['tiers']}")
    if args.live:
        print(f"citation valid {s['citation_valid']} · expected cited {s['expected_cited']} · abstain {s['abstain_accuracy']}"
              f" · {s['prompt_tokens']}+{s['completion_tokens']} tokens · ${s['cost_usd']} · {s['latency_s']} s")
    for r in rep["rows"]:
        if r["tier_ok"] is False or r["recalled"] is False or r.get("citation_valid") is False:
            print(f"  miss {r['id']}: tier {r['tier']} (want {r['expect_tier']}), recalled {r['recalled']}"
                  + (f", invented {r['invented_ids']}" if r.get("invented_ids") else ""))
    print(f"report: {out}")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="palace", description="Ask your palace (Nemotron via Meterless Nightshift or "
                                                           "Nebius Token Factory).")
    sub = p.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("ask", help="ask a question")
    a.add_argument("question")
    a.add_argument("--dry-run", action="store_true", help="recall and route only; show what WOULD leave the house")
    a.add_argument("--json", action="store_true")
    w = sub.add_parser("serve", help="web chat with the 'what leaves the house' panel")
    w.add_argument("--host", default="127.0.0.1")
    w.add_argument("--port", type=int, default=8765)
    sub.add_parser("models", help="check the configured Nemotron ids against the active provider's live catalog")
    e = sub.add_parser("eval", help="score recall and routing (and, with --live, citations) on evals/questions.jsonl")
    e.add_argument("--live", action="store_true", help="also call Nemotron and score the answers")
    e.add_argument("--k", type=int, default=8)
    e.add_argument("--out", help="report path (default evals/runs/<utc>-<mode>.json)")
    args = p.parse_args(argv)

    if args.cmd == "serve":
        from .web import serve
        try:
            serve(args.host, args.port)
        except ConfigError as e:
            print(f"palace: {e}", file=sys.stderr)
            return 2
        return 0

    try:
        cfg = Config.from_env()
        return {"ask": cmd_ask, "models": cmd_models, "eval": cmd_eval}[args.cmd](cfg, args)
    except ConfigError as e:
        print(f"palace: {e}", file=sys.stderr)
        return 2
    except RuntimeError as e:  # ZetarisError: a refused login or query (an outage is reported in the turn)
        print(f"palace: {e}", file=sys.stderr)
        return 4
    except OSError as e:  # URLError, timeouts, refused connections
        print(f"palace: network error: {getattr(e, 'reason', e)}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
