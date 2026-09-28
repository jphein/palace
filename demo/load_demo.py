"""Load the synthetic seed into a throwaway palace-daemon:  python demo/load_demo.py http://127.0.0.1:8085"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from palace.config import Config  # noqa: E402
from palace.memory import DaemonMemory  # noqa: E402


def main(url: str) -> int:
    cfg = Config.from_env({"PALACE_URL": url})   # raises on a real-palace host
    mem = DaemonMemory(cfg)
    seed = Path(__file__).with_name("seed.jsonl")
    n = 0
    for line in seed.read_text().splitlines():
        row = json.loads(line)
        mem.write(f"[{row['date']}] {row['text']}", wing=f"demo-{row['wing']}", room=row["room"])
        n += 1
    print(f"loaded {n} synthetic drawers into {url} (wings demo-*)")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__)
        raise SystemExit(2)
    raise SystemExit(main(sys.argv[1]))
