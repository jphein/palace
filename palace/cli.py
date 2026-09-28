"""palace ask "question" [--dry-run] [--json]  |  palace serve [--host H] [--port P]"""
from __future__ import annotations

import argparse
import json
import sys

from .agent import run_turn
from .config import Config, ConfigError
from .memory import open_memory


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="palace", description="Ask your palace (Nemotron on Nebius Token Factory).")
    sub = p.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("ask", help="ask a question")
    a.add_argument("question")
    a.add_argument("--dry-run", action="store_true", help="recall and route only; show what WOULD leave the house")
    a.add_argument("--json", action="store_true")
    w = sub.add_parser("serve", help="web chat with the 'what leaves the house' panel")
    w.add_argument("--host", default="127.0.0.1")
    w.add_argument("--port", type=int, default=8765)
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
        memory = open_memory(cfg)
        chat = None
        if not args.dry_run:
            from .tokenfactory import TokenFactory
            tf = TokenFactory(cfg)
            chat = lambda tier, msgs: (lambda c: (c.text, c.model))(tf.chat(tier, msgs))
        turn = run_turn(args.question, memory, chat)
    except ConfigError as e:
        print(f"palace: {e}", file=sys.stderr)
        return 2
    except OSError as e:  # URLError, timeouts, refused connections
        print(f"palace: network error: {getattr(e, 'reason', e)}", file=sys.stderr)
        return 3

    if args.json:
        print(json.dumps({"route": turn.route.__dict__, "egress": turn.egress, "answer": turn.answer, "model": turn.model,
                          "memories": [m.__dict__ for m in turn.memories]}, indent=2))
        return 0
    print(f"route: {turn.route.tier} ({turn.route.reason})")
    print("what leaves the house: " + (", ".join(f"{e['id']} ({e['chars']} chars)" for e in turn.egress) or "nothing"))
    for m in turn.memories:
        print(f"  {m.cite()} {m.wing}/{m.room}: {m.text[:100]}")
    if turn.answer:
        print("\n" + turn.answer)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
