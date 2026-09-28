"""Configuration from the environment. Nothing here is secret by default; keys come from env only."""
from __future__ import annotations

import ipaddress
import os
import socket
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

# The real-palace guard. This project runs against a SYNTHETIC demo palace only, so it refuses:
#   1. any host on an explicit deny-list (none ship in the source; see forbidden_hosts_from below), and
#   2. anything that looks like a home/LAN server: private or link-local IPs, single-label names ("mybox"),
#      LAN suffixes (.lan, .local, .home.arpa, ...), and any name that RESOLVES to a private address
#      (a public domain pointed at a home server), unless the host is listed in PALACE_ALLOW_HOSTS.
# Loopback (localhost, 127.0.0.0/8, ::1) is allowed: that is where the throwaway demo daemon runs.
# The explicit deny-list always wins, even over PALACE_ALLOW_HOSTS.
LAN_SUFFIXES = (".lan", ".local", ".localdomain", ".home", ".home.arpa", ".internal", ".intranet", ".corp")
REPO_HOSTS_FILE = Path(__file__).resolve().parent.parent / ".forbidden-hosts"   # gitignored


def _split(v: str) -> set[str]:
    return {h.strip().lower().rstrip(".") for h in v.replace("\n", ",").split(",") if h.strip()}


def _read_hosts(path: Path) -> set[str]:
    try:
        lines = path.read_text().splitlines()
    except OSError:
        return set()
    return {ln.split("#", 1)[0].strip().lower().rstrip(".") for ln in lines} - {""}


def forbidden_hosts_from(env: Mapping[str, str], host_files: Iterable[Path] | None = None) -> frozenset[str]:
    """PALACE_FORBIDDEN_HOSTS (comma-separated) plus one host per line from, by default: the repo's gitignored
    .forbidden-hosts, $XDG_CONFIG_HOME/palace/forbidden-hosts, and PALACE_FORBIDDEN_HOSTS_FILE."""
    if host_files is None:
        xdg = Path(env.get("XDG_CONFIG_HOME") or Path.home() / ".config")
        host_files = [REPO_HOSTS_FILE, xdg / "palace" / "forbidden-hosts"]
        if env.get("PALACE_FORBIDDEN_HOSTS_FILE"):
            host_files.append(Path(env["PALACE_FORBIDDEN_HOSTS_FILE"]))
    out = _split(env.get("PALACE_FORBIDDEN_HOSTS", ""))
    for f in host_files:
        out |= _read_hosts(Path(f))
    return frozenset(out)


def _matches(host: str, names: frozenset[str]) -> bool:
    return host in names or any(host.endswith("." + h) for h in names)


def _resolve(host: str) -> set[str]:
    """The addresses a name resolves to; empty if it doesn't resolve (then no connection can be made anyway)."""
    try:
        return {ai[4][0] for ai in socket.getaddrinfo(host, None)}
    except (OSError, UnicodeError):
        return set()


def _private(addr: str) -> bool:
    try:
        ip = ipaddress.ip_address(addr.split("%", 1)[0])
    except ValueError:
        return False
    return not ip.is_loopback and (ip.is_private or ip.is_link_local)


def lan_reason(host: str, resolve=None) -> str | None:
    """Why a host looks like a home/LAN server, or None. Loopback is never LAN here."""
    if host == "localhost" or host.endswith(".localhost"):
        return None
    try:
        ip = ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        if "." not in host:
            return "a single-label (LAN) hostname"
        if host.endswith(LAN_SUFFIXES):
            return "a LAN domain"
        addrs = (resolve or _resolve)(host)
        priv = sorted(a for a in addrs if _private(a))
        return f"a name that resolves to a private address ({priv[0]})" if priv else None
    if ip.is_loopback:
        return None
    if ip.is_private or ip.is_link_local:
        return "a private-network address"
    return None


# TODO(verify in the Token Factory console): exact base URL and model ids. The API is
# OpenAI-compatible; these defaults are placeholders to be confirmed before the first real call.
DEFAULT_BASE_URL = "https://api.tokenfactory.nebius.com/v1/"
DEFAULT_MODELS = {
    "nano": "nvidia/nemotron-3-nano",    # fast, everyday calls
    "super": "nvidia/nemotron-3-super",  # default
    "ultra": "nvidia/nemotron-3-ultra",  # serious reasoning, used sparingly
}


class ConfigError(RuntimeError):
    pass


@dataclass(frozen=True)
class Config:
    api_key: str | None
    base_url: str
    models: dict[str, str]
    palace_url: str | None          # None -> offline demo memory (demo/seed.jsonl)
    palace_api_key: str | None
    forbidden_hosts: frozenset[str] = field(default_factory=frozenset)
    allowed_hosts: frozenset[str] = field(default_factory=frozenset)

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None, host_files: Iterable[Path] | None = None) -> "Config":
        e = os.environ if env is None else env
        cfg = cls(
            api_key=e.get("NEBIUS_API_KEY") or None,
            base_url=e.get("NEBIUS_BASE_URL", DEFAULT_BASE_URL),
            models={tier: e.get(f"PALACE_MODEL_{tier.upper()}", default) for tier, default in DEFAULT_MODELS.items()},
            palace_url=e.get("PALACE_URL") or None,
            palace_api_key=e.get("PALACE_API_KEY") or None,
            forbidden_hosts=forbidden_hosts_from(e, host_files),
            allowed_hosts=frozenset(_split(e.get("PALACE_ALLOW_HOSTS", ""))),
        )
        cfg.check_palace_url()
        return cfg

    def check_palace_url(self) -> None:
        """Refuse any palace URL that points at a real personal palace (see the guard notes at the top)."""
        if not self.palace_url:
            return
        host = (urlparse(self.palace_url).hostname or "").lower().rstrip(".")
        if not host:
            raise ConfigError(f"PALACE_URL {self.palace_url!r} has no host.")
        hint = "This project only runs against a synthetic demo palace (see demo/README.md)."
        if _matches(host, self.forbidden_hosts):
            raise ConfigError(f"PALACE_URL host {host!r} is on the forbidden-hosts list: it serves a real personal "
                              f"palace. {hint}")
        why = lan_reason(host)
        if why and not _matches(host, self.allowed_hosts):
            raise ConfigError(f"PALACE_URL host {host!r} is {why}, which usually means a real home palace. {hint} "
                              "If it really is a throwaway demo daemon, add it to PALACE_ALLOW_HOSTS.")
