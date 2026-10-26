"""Meterless Nightshift as Palace's AI provider (docs/open-agent-design.md §4b). Stdlib only.

Nightshift is a local OpenAI-compatible runtime; its Providers tab holds the NVIDIA key, so Palace never sees it.
Palace sends the runtime token, `meterless-app: palace` on every request and `meterless-scope: user` on chat,
and pins one explicit NVIDIA Nemotron id per tier: the `meterless/*` lanes may route anywhere, and the award
evidence must show Nemotron served the answer. Each answer keeps Nightshift's compute receipt id, and the
response's own `model` field (what actually ran) is what Palace reports.

Status follows Meterless's provider contract: 401/403 -> "unauthorized", 200 with meterless/* routes ->
"online", anything else -> "offline". `/healthz` only says the process is up, so it is never used here.
"""
from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.request

from ..config import Config, ConfigError
from ..tokenfactory import Completion

APP_ID = "palace"
TIMEOUT = 180.0     # a lane may load a model first
# Nemotron reasoning text sometimes arrives inline: a whole <think>…</think> block, or only its tail ending in
# </think> (measured on Nemotron 3 Ultra through Nightshift, 2026-10-24 and 10-26).
_THINK_BLOCK = re.compile(r"<think>.*?</think>", re.S)


def strip_think(text: str) -> str:
    text = _THINK_BLOCK.sub("", text or "")
    if "</think>" in text:
        text = text.rsplit("</think>", 1)[1]
    return text.strip()


def normalise_base_url(url: str) -> str:
    """'host:8088', 'http://host:8088/', '…/v1/' and '…/v1/v1' all become 'http://host:8088/v1'."""
    url = url.strip().rstrip("/")
    if "://" not in url:
        url = "http://" + url
    while url.endswith("/v1/v1"):
        url = url[:-3]
    return url if url.endswith("/v1") else url + "/v1"


class Nightshift:
    name = "meterless"

    def __init__(self, cfg: Config, timeout: float = TIMEOUT):
        if not cfg.meterless_url:
            raise ConfigError("METERLESS_BASE_URL is not set (Nightshift's runtime URL, normally http://127.0.0.1:8088/v1).")
        if not cfg.meterless_key or cfg.meterless_key == "rt-local":
            raise ConfigError("METERLESS_API_KEY is not set (Nightshift's runtime token; 'rt-local' is a placeholder).")
        self.cfg, self.timeout = cfg, timeout

    def _req(self, path: str, body: dict | None = None) -> dict:
        headers = {"content-type": "application/json", "authorization": f"Bearer {self.cfg.meterless_key}",
                   "meterless-app": APP_ID}
        if body is not None:
            headers["meterless-scope"] = "user"
        req = urllib.request.Request(self.cfg.meterless_url + path, headers=headers,
                                     data=None if body is None else json.dumps(body).encode())
        with urllib.request.urlopen(req, timeout=self.timeout) as r:
            return json.loads(r.read())

    def chat(self, tier: str, messages: list[dict], max_tokens: int = 1500, temperature: float = 0.3) -> Completion:
        # Reasoning models spend completion tokens on thinking first, so the cap is higher than Token Factory's.
        model = self.cfg.meterless_models[tier]
        t0 = time.monotonic()
        data = self._req("/chat/completions", {"model": model, "messages": messages, "max_tokens": max_tokens,
                                               "temperature": temperature})
        usage = data.get("usage") or {}
        receipt = (data.get("meterless") or {}).get("receipt_id")
        return Completion(strip_think(data["choices"][0]["message"]["content"]), data.get("model", model),
                          usage.get("prompt_tokens"), usage.get("completion_tokens"), round(time.monotonic() - t0, 3),
                          receipt_id=receipt, provider=self.name)

    def list_models(self) -> list[str]:
        return [m["id"] for m in self._req("/models").get("data", [])]

    def status(self) -> str:
        try:
            ids = self.list_models()
        except urllib.error.HTTPError as e:
            return "unauthorized" if e.code in (401, 403) else "offline"
        except (OSError, ValueError):
            return "offline"
        return "online" if any(i.startswith("meterless/") for i in ids) else "offline"
