import json

import pytest

from palace.agent import build_prompt, run_turn
from palace.cli import main as cli_main
from palace.config import Config, ConfigError
from palace.memory import DemoMemory
from palace.router import route


# --- the real-palace guard ------------------------------------------------------------------
# Fictional names only. No real host is named anywhere in this repo; real ones live in gitignored files.
NO_FILES: tuple = ()


@pytest.fixture(autouse=True)
def no_dns(monkeypatch):
    """Guard tests are hermetic: no real DNS. Tests that need resolution install their own table."""
    monkeypatch.setattr("palace.config._resolve", lambda host: set())


def test_public_name_that_resolves_to_a_private_address_is_refused(monkeypatch):
    table = {"palace.example.com": {"10.9.8.7"}, "demo.example.com": {"8.8.8.8"}, "loop.example.com": {"127.0.0.1"}}
    monkeypatch.setattr("palace.config._resolve", lambda host: table.get(host, set()))
    with pytest.raises(ConfigError, match="resolves to a private address"):
        Config.from_env({"PALACE_URL": "https://palace.example.com"}, host_files=NO_FILES)
    assert Config.from_env({"PALACE_URL": "https://demo.example.com"}, host_files=NO_FILES).palace_url
    assert Config.from_env({"PALACE_URL": "https://loop.example.com"}, host_files=NO_FILES).palace_url
    assert Config.from_env({"PALACE_URL": "https://palace.example.com", "PALACE_ALLOW_HOSTS": "palace.example.com"},
                           host_files=NO_FILES).palace_url


def test_cli_network_error_is_clean(monkeypatch, capsys):
    monkeypatch.setenv("PALACE_URL", "http://127.0.0.1:9")   # discard port: connection refused
    assert cli_main(["ask", "anything", "--dry-run"]) == 3
    assert "network error" in capsys.readouterr().err


@pytest.mark.parametrize("url", [
    "http://example-palace.lan:8085", "http://EXAMPLE-PALACE.LAN:8085/", "http://mybox:8085",
    "http://nas.local", "http://pantry.home.arpa", "http://10.1.2.3:8085", "http://192.168.1.20",
    "http://172.16.0.9", "http://[fd00::1]:8085", "http://169.254.1.1", "http://palace.internal",
])
def test_refuses_lan_looking_hosts_by_default(url):
    with pytest.raises(ConfigError):
        Config.from_env({"PALACE_URL": url}, host_files=NO_FILES)


@pytest.mark.parametrize("url", ["http://127.0.0.1:8085", "http://localhost:8085", "http://[::1]:8085",
                                 "https://demo-palace.example.org"])
def test_loopback_and_public_demo_hosts_are_allowed(url):
    assert Config.from_env({"PALACE_URL": url}, host_files=NO_FILES).palace_url == url


def test_no_url_means_offline_demo():
    assert Config.from_env({}, host_files=NO_FILES).palace_url is None


def test_forbidden_hosts_from_env_cover_subdomains_only_on_a_dot():
    env = {"PALACE_FORBIDDEN_HOSTS": "Memory-Keep.example.com, other.example.net"}
    for url in ("https://memory-keep.example.com", "https://api.memory-keep.example.com/"):
        with pytest.raises(ConfigError, match="forbidden-hosts"):
            Config.from_env({**env, "PALACE_URL": url}, host_files=NO_FILES)
    assert Config.from_env({**env, "PALACE_URL": "https://notmemory-keep.example.com"}, host_files=NO_FILES)


def test_forbidden_hosts_from_files(tmp_path):
    f = tmp_path / "forbidden-hosts"
    f.write_text("# my real palaces\nmemory-keep.example.com   # the web name\n\n")
    with pytest.raises(ConfigError):
        Config.from_env({"PALACE_URL": "https://memory-keep.example.com"}, host_files=[f])
    # the default file locations: $XDG_CONFIG_HOME/palace/forbidden-hosts and PALACE_FORBIDDEN_HOSTS_FILE
    (tmp_path / "palace").mkdir()
    (tmp_path / "palace" / "forbidden-hosts").write_text("keep-a.example.com\n")
    extra = tmp_path / "extra"
    extra.write_text("keep-b.example.com\n")
    env = {"XDG_CONFIG_HOME": str(tmp_path), "PALACE_FORBIDDEN_HOSTS_FILE": str(extra)}
    for host in ("keep-a.example.com", "keep-b.example.com"):
        with pytest.raises(ConfigError):
            Config.from_env({**env, "PALACE_URL": f"https://{host}"})


def test_missing_host_files_are_ignored(tmp_path):
    assert Config.from_env({"PALACE_URL": "http://127.0.0.1:8085"}, host_files=[tmp_path / "nope"]).palace_url


def test_allow_list_opts_a_lan_demo_daemon_in_but_never_overrides_the_deny_list():
    ok = {"PALACE_URL": "http://demo-box.lan:8085", "PALACE_ALLOW_HOSTS": "demo-box.lan"}
    assert Config.from_env(ok, host_files=NO_FILES).palace_url
    with pytest.raises(ConfigError, match="forbidden-hosts"):
        Config.from_env({**ok, "PALACE_FORBIDDEN_HOSTS": "demo-box.lan"}, host_files=NO_FILES)


def test_url_without_host_is_refused():
    with pytest.raises(ConfigError):
        Config.from_env({"PALACE_URL": "not-a-url"}, host_files=NO_FILES)


# --- router ---------------------------------------------------------------------------------
def test_router_tiers():
    assert route("When is the next county report due?").tier == "nano"
    assert route("Should I hire the coordinator this fall? Weigh it against the budget.").tier == "ultra"
    assert route("Tell me about the hotspot lending program").tier == "super"
    assert route("Tell me everything", n_memories=20).tier == "ultra"


# --- demo memory ----------------------------------------------------------------------------
def test_demo_memory_recalls_with_citations():
    mem = DemoMemory()
    hits = mem.search("county report due", limit=3)
    assert hits and any("October 15" in h.text for h in hits)
    assert hits[0].cite().startswith("[demo-")


def test_demo_memory_finds_the_reversed_decision():
    ids = {h.id for h in DemoMemory().search("coordinator hire fall", limit=5)}
    assert {"demo-013", "demo-016"} <= ids   # the July decision and its August reversal


def test_demo_memory_write_then_recall():
    mem = DemoMemory()
    rid = mem.write("Ordered 10 refurbished Chromebooks for the winter classes.", wing="hub", room="decisions")
    assert rid in {h.id for h in mem.search("chromebooks winter")}


def test_seed_is_marked_synthetic():
    rows = [json.loads(line) for line in open("demo/seed.jsonl")]
    assert len(rows) >= 20 and all(r["id"].startswith("demo-") for r in rows)


# --- one turn -------------------------------------------------------------------------------
def test_dry_run_turn_records_egress_and_sends_nothing():
    turn = run_turn("What did I decide about the coordinator?", DemoMemory(), chat=None)
    assert turn.answer is None
    assert turn.egress and all(e["chars"] <= 600 for e in turn.egress)
    assert "Memories:" in turn.prompt[1]["content"]


def test_turn_with_fake_model_uses_routed_tier():
    seen = {}
    def fake_chat(tier, msgs):
        seen["tier"] = tier
        return "You planned to hire in July [demo-013], then reversed it in August [demo-016].", "fake-nemotron"
    turn = run_turn("Should I still plan on the coordinator hire? Weigh the budget.", DemoMemory(), fake_chat)
    assert seen["tier"] == "ultra" and "[demo-016]" in turn.answer and turn.model == "fake-nemotron"


def test_prompt_without_memories_says_so():
    assert "(no relevant memories found)" in build_prompt("anything", [])[1]["content"]


def test_cli_dry_run(capsys, monkeypatch):
    monkeypatch.delenv("PALACE_URL", raising=False)
    assert cli_main(["ask", "When is the scam spotting class?", "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "route: nano" in out and "demo-024" in out


def test_cli_without_api_key_fails_cleanly(capsys, monkeypatch):
    monkeypatch.delenv("NEBIUS_API_KEY", raising=False)
    monkeypatch.delenv("PALACE_URL", raising=False)
    assert cli_main(["ask", "hello"]) == 2
    assert "NEBIUS_API_KEY" in capsys.readouterr().err
