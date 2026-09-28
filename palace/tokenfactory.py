"""Minimal OpenAI-compatible chat client for Nebius Token Factory (stdlib only)."""
from __future__ import annotations

import json
import urllib.request
from dataclasses import dataclass

from .config import Config, ConfigError


@dataclass(frozen=True)
class Completion:
    text: str
    model: str
    prompt_tokens: int | None
    completion_tokens: int | None


class TokenFactory:
    def __init__(self, cfg: Config, timeout: float = 120.0):
        if not cfg.api_key:
            raise ConfigError("NEBIUS_API_KEY is not set (create it in the Token Factory console; store it in the vault).")
        self.cfg, self.timeout = cfg, timeout

    def chat(self, tier: str, messages: list[dict], max_tokens: int = 700, temperature: float = 0.3) -> Completion:
        model = self.cfg.models[tier]
        body = {"model": model, "messages": messages, "max_tokens": max_tokens, "temperature": temperature}
        req = urllib.request.Request(self.cfg.base_url.rstrip("/") + "/chat/completions", data=json.dumps(body).encode(),
                                     headers={"content-type": "application/json", "authorization": f"Bearer {self.cfg.api_key}"})
        with urllib.request.urlopen(req, timeout=self.timeout) as r:
            data = json.loads(r.read())
        usage = data.get("usage") or {}
        return Completion(data["choices"][0]["message"]["content"], data.get("model", model),
                          usage.get("prompt_tokens"), usage.get("completion_tokens"))
