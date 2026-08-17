"""Regression tests for optional per-exchange ccxt authentication.

OHLCV is a public endpoint on every exchange ccxt talks to, so
``get_market_data`` works with zero credentials by design. This is a
best-effort enhancement only: when a COMPLETE credential set exists for the
active exchange (key + secret, plus passphrase for OKX), ccxt gets an
authenticated session; otherwise it's the same unauthenticated public
session as before. A partial set (e.g. a key with no secret) must never be
handed to ccxt half-formed.
"""

from __future__ import annotations

import ccxt

from backtest.loaders.ccxt_loader import DataLoader, _exchange_credentials


class _FakeExchange:
    def __init__(self, config):
        self.config = config


def _clear_all_credential_env(monkeypatch):
    for name in (
        "BINANCE_API_KEY", "BINANCE_API_SECRET",
        "BYBIT_API_KEY", "BYBIT_API_SECRET",
        "GATEIO_API_KEY", "GATEIO_API_SECRET",
        "OKX_API_KEY", "OKX_API_SECRET", "OKX_PASSWORD",
    ):
        monkeypatch.delenv(name, raising=False)


def test_no_credentials_yields_empty_config(monkeypatch):
    _clear_all_credential_env(monkeypatch)
    assert _exchange_credentials("binance") == {}


def test_partial_credentials_are_not_used(monkeypatch):
    """A key with no secret must not be passed to ccxt half-formed."""
    _clear_all_credential_env(monkeypatch)
    monkeypatch.setenv("BINANCE_API_KEY", "some-key")
    assert _exchange_credentials("binance") == {}


def test_complete_key_secret_pair_is_used(monkeypatch):
    _clear_all_credential_env(monkeypatch)
    monkeypatch.setenv("BYBIT_API_KEY", "bybit-key")
    monkeypatch.setenv("BYBIT_API_SECRET", "bybit-secret")
    assert _exchange_credentials("bybit") == {
        "apiKey": "bybit-key",
        "secret": "bybit-secret",
    }


def test_okx_needs_only_key_and_secret_no_passphrase(monkeypatch):
    """OKX intentionally omits the passphrase ccxt's private endpoints would
    need — public OHLCV never signs a request, so key + secret is enough."""
    _clear_all_credential_env(monkeypatch)
    monkeypatch.setenv("OKX_API_KEY", "okx-key")
    monkeypatch.setenv("OKX_API_SECRET", "okx-secret")
    assert _exchange_credentials("okx") == {
        "apiKey": "okx-key",
        "secret": "okx-secret",
    }


def test_unknown_exchange_yields_empty_config(monkeypatch):
    _clear_all_credential_env(monkeypatch)
    assert _exchange_credentials("some_random_exchange") == {}


def test_get_exchange_passes_complete_credentials_through(monkeypatch):
    _clear_all_credential_env(monkeypatch)
    monkeypatch.setenv("CCXT_EXCHANGE", "gate")
    monkeypatch.setenv("GATEIO_API_KEY", "gate-key")
    monkeypatch.setenv("GATEIO_API_SECRET", "gate-secret")
    monkeypatch.setattr(ccxt, "gate", _FakeExchange, raising=False)

    exchange = DataLoader()._get_exchange()

    assert exchange.config["apiKey"] == "gate-key"
    assert exchange.config["secret"] == "gate-secret"


def test_get_exchange_stays_unauthenticated_without_full_credentials(monkeypatch):
    """Regression for the default/common case: no or partial credentials
    must produce the same public, unauthenticated config as before this
    feature existed."""
    _clear_all_credential_env(monkeypatch)
    monkeypatch.setenv("CCXT_EXCHANGE", "binance")
    monkeypatch.setattr(ccxt, "binance", _FakeExchange)

    exchange = DataLoader()._get_exchange()

    assert "apiKey" not in exchange.config
    assert "secret" not in exchange.config
