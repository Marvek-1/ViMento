"""Shared fixtures and sys.path setup for all tests."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Ensure agent/ is on sys.path so imports like `backtest.*` and `src.*` work.
AGENT_DIR = Path(__file__).resolve().parent.parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))


@pytest.fixture(autouse=True)
def _disable_loader_cache_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep local .env cache settings from changing mocked loader tests."""
    monkeypatch.delenv("VIBE_TRADING_DATA_CACHE", raising=False)
    monkeypatch.delenv("VIBE_TRADING_DATA_CACHE_ROOT", raising=False)
