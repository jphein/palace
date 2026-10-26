"""Keep the offline suite offline: a developer's live provider settings must not leak into tests that read os.environ
(found 2026-10-26, when METERLESS_BASE_URL in the shell turned two CLI tests onto the Nightshift provider)."""

import os

import pytest

SCRUB = ("METERLESS_", "ZETARIS_", "NEBIUS_", "PALACE_PROVIDER", "PALACE_TRUST_LEDGER", "PALACE_URL", "PALACE_MODEL_")
LIVE = {"test_zetaris_live.py"}   # these read the live ZETARIS_* on purpose


@pytest.fixture(autouse=True)
def _offline_env(request, monkeypatch):
    if request.node.path.name in LIVE:
        return
    for k in list(os.environ):
        if k.startswith(SCRUB):
            monkeypatch.delenv(k)
