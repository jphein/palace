"""Minimal OpenAI-compatible chat client for Nebius Token Factory (stdlib only)."""
from __future__ import annotations

import json
import time
import urllib.request
from dataclasses import dataclass

from .config import Config, ConfigError


@dataclass(frozen=True)
class Completion:
    text: str
    model: str
    prompt_tokens: int | None
    completion_tokens: int | None
    latency_s: float | None = None
    receipt_id: str | None = None    # the provider's own record of the call (Meterless compute receipt)
    provider: str = "tokenfactory"


class TokenFactory:
    name = "tokenfactory"

    def __init__(self, cfg: Config, timeout: float = 120.0):
        if not cfg.api_key:
            raise ConfigError("NEBIUS_API_KEY is not set (create it in the Token Factory console; store it in the vault).")
        self.cfg, self.timeout = cfg, timeout

    def _req(self, path: str, body: dict | None = None) -> dict:
        req = urllib.request.Request(self.cfg.base_url.rstrip("/") + path,
                                     data=None if body is None else json.dumps(body).encode(),
                                     headers={"content-type": "application/json", "authorization": f"Bearer {self.cfg.api_key}"})
        with urllib.request.urlopen(req, timeout=self.timeout) as r:
            return json.loads(r.read())

    def chat(self, tier: str, messages: list[dict], max_tokens: int = 700, temperature: float = 0.3) -> Completion:
        model = self.cfg.models[tier]
        t0 = time.monotonic()
        data = self._req("/chat/completions", {"model": model, "messages": messages, "max_tokens": max_tokens,
                                               "temperature": temperature})
        usage = data.get("usage") or {}
        return Completion(data["choices"][0]["message"]["content"], data.get("model", model),
                          usage.get("prompt_tokens"), usage.get("completion_tokens"), round(time.monotonic() - t0, 3))

    def list_models(self) -> list[str]:
        """Model ids in the live catalog (GET /models)."""
        return [m["id"] for m in self._req("/models").get("data", [])]
