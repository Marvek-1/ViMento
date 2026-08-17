from __future__ import annotations

import json
import urllib.error

import paper_session


class _Response:
    def __init__(self, payload):
        self._body = json.dumps(payload).encode()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return self._body


def test_gate_price_parser_maps_paper_symbols(monkeypatch):
    payload = [
        {"contract": "BTC_USDT", "last": "64250.5"},
        {"contract": "ETH_USDT", "last": "3210.25"},
    ]
    monkeypatch.setattr(paper_session.urllib.request, "urlopen", lambda *a, **k: _Response(payload))

    assert paper_session._fetch_last_prices_gate(["BTC-USDT", "ETH-USDT"]) == {
        "BTC-USDT": 64250.5,
        "ETH-USDT": 3210.25,
    }


def test_market_data_falls_through_unreachable_hosts(monkeypatch, capsys):
    def unreachable(_symbols):
        raise urllib.error.URLError("network timeout")

    monkeypatch.setattr(paper_session, "_fetch_last_prices_okx", unreachable)
    monkeypatch.setattr(paper_session, "_fetch_last_prices_binance", unreachable)
    monkeypatch.setattr(paper_session, "_fetch_last_prices_bybit", unreachable)
    monkeypatch.setattr(
        paper_session,
        "_fetch_last_prices_gate",
        lambda symbols: {symbol: 100.0 for symbol in symbols},
    )

    assert paper_session.fetch_last_prices(["BTC-USDT"]) == {"BTC-USDT": 100.0}
    events = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert [(event["from"], event["to"]) for event in events] == [
        ("okx", "binance"),
        ("binance", "bybit"),
        ("bybit", "gate"),
    ]


def test_okx_success_records_source_okx(monkeypatch):
    monkeypatch.setattr(paper_session, "_fetch_last_prices_okx", lambda symbols: {s: 1.0 for s in symbols})
    result = paper_session.fetch_last_prices_with_source(["BTC-USDT"])
    assert result.source == "okx"
    assert result.prices == {"BTC-USDT": 1.0}


def test_okx_unreachable_binance_success_records_source_binance(monkeypatch):
    def unreachable(_symbols):
        raise urllib.error.URLError("network timeout")

    monkeypatch.setattr(paper_session, "_fetch_last_prices_okx", unreachable)
    monkeypatch.setattr(paper_session, "_fetch_last_prices_binance", lambda symbols: {s: 2.0 for s in symbols})
    result = paper_session.fetch_last_prices_with_source(["BTC-USDT"])
    assert result.source == "binance"
    assert result.prices == {"BTC-USDT": 2.0}


def test_okx_and_binance_unreachable_bybit_success_records_source_bybit(monkeypatch):
    def unreachable(_symbols):
        raise urllib.error.URLError("network timeout")

    monkeypatch.setattr(paper_session, "_fetch_last_prices_okx", unreachable)
    monkeypatch.setattr(paper_session, "_fetch_last_prices_binance", unreachable)
    monkeypatch.setattr(paper_session, "_fetch_last_prices_bybit", lambda symbols: {s: 3.0 for s in symbols})
    result = paper_session.fetch_last_prices_with_source(["BTC-USDT"])
    assert result.source == "bybit"
    assert result.prices == {"BTC-USDT": 3.0}


def test_fetch_last_prices_drops_provenance_but_matches_with_source(monkeypatch):
    monkeypatch.setattr(paper_session, "_fetch_last_prices_okx", lambda symbols: {s: 5.0 for s in symbols})
    assert paper_session.fetch_last_prices(["ETH-USDT"]) == \
        paper_session.fetch_last_prices_with_source(["ETH-USDT"]).prices


def test_invalid_okx_snapshot_falls_back_without_mislabeling(monkeypatch):
    monkeypatch.setattr(paper_session, "_fetch_last_prices_okx", lambda symbols: {symbols[0]: 0.0})
    monkeypatch.setattr(paper_session, "_fetch_last_prices_binance", lambda symbols: {s: 7.0 for s in symbols})
    result = paper_session.fetch_last_prices_with_source(["BTC-USDT"])
    assert result.source == "binance"
    assert result.prices == {"BTC-USDT": 7.0}
