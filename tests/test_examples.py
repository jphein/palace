"""The committed live samples stay honest: every id an answer cites was actually sent to the model in that turn."""

import json
import re
from pathlib import Path

import pytest

EX = sorted((Path(__file__).resolve().parent.parent / "examples").glob("0*.json"))
CITE = re.compile(r"\[((?:demo-\d+)|(?:zetaris:q-[0-9a-f]{8}))")


def test_there_are_at_least_three_samples():
    assert len(EX) >= 3


@pytest.mark.parametrize("path", EX, ids=[p.name for p in EX])
def test_citations_were_sent(path):
    d = json.loads(path.read_text())
    sent = {e["id"] for e in d["egress"]} | {e["id"] for e in d["zetaris"]["egress"]}
    cited = set(CITE.findall(d["answer"]))
    assert cited, "a sample answer cites something"
    assert cited <= sent, f"cited but never sent: {cited - sent}"
    assert d["receipt_id"].startswith("rcpt_") and d["model"].startswith("nvidia/")
