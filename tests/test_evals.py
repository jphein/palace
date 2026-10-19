import io
import json
import urllib.request

import pytest

from palace.agent import run_turn
from palace.cli import main as cli_main
from palace.config import DEFAULT_MODELS, DEFAULT_PRICES, Config, ConfigError
from palace.evals import cited_ids, load_questions, run_eval
from palace.memory import DemoMemory
from palace.tokenfactory import Completion, TokenFactory


# --- the eval set ---------------------------------------------------------------------------
def test_questions_reference_real_seed_ids():
    seed = {json.loads(line)["id"] for line in open("demo/seed.jsonl")}
    qs = load_questions()
    assert len(qs) >= 20 and len({q["id"] for q in qs}) == len(qs)
    for q in qs:
        assert set(q["expect_ids"]) <= seed, q["id"]
        assert q["expect_tier"] in DEFAULT_MODELS
    assert any(not q["expect_ids"] for q in qs), "needs at least one should-abstain question"


def test_cited_ids():
    assert cited_ids("Hire in July [demo-013], reversed [demo-016, 2026-08-05].") == ["demo-013", "demo-016"]
    assert cited_ids("No memory covers that.") == []


# --- offline eval: recall and routing, no network -------------------------------------------
def test_offline_eval_scores_recall_and_routing():
    rep = run_eval(load_questions(), DemoMemory(), chat=None)
    s = rep["summary"]
    assert s["mode"] == "offline" and s["questions"] == len(rep["rows"])
    assert 0.0 <= s["recall_at_k"] <= 1.0 and 0.0 <= s["tier_accuracy"] <= 1.0
    assert s["recall_at_k"] >= 0.8          # BM25 over the seed finds the expected memories
    assert "citation_valid" not in s        # live-only metrics stay out of an offline run
    row = next(r for r in rep["rows"] if r["id"] == "q03")
    assert row["recalled"] and row["tier"] == "ultra"


def test_live_eval_flags_hallucinated_citations_and_missed_abstains():
    qs = [{"id": "a", "question": "When is the scam spotting class?", "expect_ids": ["demo-024"], "expect_tier": "nano"},
          {"id": "b", "question": "What is the Wi-Fi password at the hub?", "expect_ids": [], "expect_tier": "nano"}]
    answers = {"a": "November 7 at 10am [demo-024] [demo-999].", "b": "It's juniper123 [demo-001]."}

    def fake_chat(tier, msgs):
        key = "a" if "scam" in msgs[1]["content"].split("Question:")[1] else "b"
        return Completion(answers[key], "fake-nemotron", 100, 20, 0.5)

    rep = run_eval(qs, DemoMemory(), chat=fake_chat)
    a, b = rep["rows"]
    assert a["expected_cited"] and not a["citation_valid"] and a["invented_ids"] == ["demo-999"]
    assert b["should_abstain"] and not b["abstained"]
    s = rep["summary"]
    # b's [demo-001] was recalled ("hub"), so it's a valid citation, just not an abstention
    assert s["mode"] == "live" and s["citation_valid"] == 0.5 and s["abstain_accuracy"] == 0.0
    assert s["prompt_tokens"] == 200 and s["cost_usd"] > 0


# --- per-turn usage and cost -----------------------------------------------------------------
def test_turn_records_usage_latency_and_cost():
    def fake_chat(tier, msgs):
        return Completion("Saturdays 10-2 [demo-001].", "fake", 1_000_000, 1_000_000, 1.25)
    prices = {"nano": (1.0, 2.0), "super": (10.0, 20.0), "ultra": (100.0, 200.0)}
    turn = run_turn("When is the hub open?", DemoMemory(), fake_chat, prices=prices)
    assert turn.route.tier == "nano"
    assert turn.usage == {"prompt_tokens": 1_000_000, "completion_tokens": 1_000_000, "latency_s": 1.25}
    assert turn.cost_usd == pytest.approx(3.0)


def test_default_prices_rank_the_tiers_and_env_overrides_them():
    assert DEFAULT_PRICES["nano"] < DEFAULT_PRICES["super"] < DEFAULT_PRICES["ultra"]
    assert all(p_in > 0 and p_out > 0 for p_in, p_out in DEFAULT_PRICES.values())
    assert Config.from_env({"PALACE_PRICE_ULTRA": "2,6"}).prices["ultra"] == (2.0, 6.0)
    with pytest.raises(ConfigError):
        Config.from_env({"PALACE_PRICE_NANO": "cheap"})


def test_turn_cost_is_none_when_usage_unknown():
    turn = run_turn("When is the hub open?", DemoMemory(), lambda t, m: Completion("x", "fake", None, None, 0.1))
    assert turn.cost_usd is None


# --- model catalog check ---------------------------------------------------------------------
class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_list_models_reads_catalog(monkeypatch):
    seen = {}

    def fake_urlopen(req, timeout):
        seen["url"], seen["auth"] = req.full_url, req.get_header("Authorization")
        return _Resp(json.dumps({"data": [{"id": "nvidia/a"}, {"id": "nvidia/b"}]}).encode())

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    tf = TokenFactory(Config.from_env({"NEBIUS_API_KEY": "k"}))
    assert tf.list_models() == ["nvidia/a", "nvidia/b"]
    assert seen["url"].endswith("/v1/models") and seen["auth"] == "Bearer k"


def test_cli_models_fails_when_a_tier_id_is_missing(monkeypatch, capsys):
    monkeypatch.setenv("NEBIUS_API_KEY", "k")
    monkeypatch.delenv("PALACE_URL", raising=False)
    monkeypatch.setattr(TokenFactory, "list_models", lambda self: [DEFAULT_MODELS["nano"], DEFAULT_MODELS["super"]])
    assert cli_main(["models"]) == 1
    out = capsys.readouterr().out
    assert "ultra" in out and "MISSING" in out


def test_cli_eval_offline_writes_report(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("PALACE_URL", raising=False)
    out = tmp_path / "run.json"
    assert cli_main(["eval", "--out", str(out)]) == 0
    rep = json.loads(out.read_text())
    assert rep["summary"]["mode"] == "offline" and rep["rows"]
    assert "recall@k" in capsys.readouterr().out


def test_cited_ids_also_reads_lenticular_brackets():
    # the eval must still count a citation format it didn't normalise (so format drift isn't scored as "no citations")
    assert cited_ids("Run a SMART check【demo-008】 and [demo-012].") == ["demo-008", "demo-012"]
