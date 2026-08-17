from __future__ import annotations

import futures_paper_engine as engine


def test_okx_funding_rate_and_history(monkeypatch):
    calls = []

    def fake(url, params=None):
        calls.append((url, params))
        if url.endswith("funding-rate-history"):
            return {"data": [{"fundingRate": "0.0002"}, {"fundingRate": "-0.0001"}]}
        return {"data": [{"fundingRate": "0.0003"}]}

    monkeypatch.setattr(engine, "_public_json", fake)
    assert engine.fetch_funding_rate("BTC-USDT", source="okx") == 0.0003
    assert engine.fetch_funding_history("BTC-USDT", 20, source="okx") == [0.0002, -0.0001]
    assert all(call[1]["instId"] == "BTC-USDT-SWAP" for call in calls)


def test_bybit_funding_uses_linear_symbol(monkeypatch):
    def fake(url, params=None):
        assert params["category"] == "linear"
        assert params["symbol"] == "ETHUSDT"
        if url.endswith("history"):
            return {"result": {"list": [{"fundingRate": "0.0004"}]}}
        return {"result": {"list": [{"fundingRate": "0.0005"}]}}

    monkeypatch.setattr(engine, "_public_json", fake)
    assert engine.fetch_funding_rate("ETH-USDT", source="bybit") == 0.0005
    assert engine.fetch_funding_history("ETH-USDT", 10, source="bybit") == [0.0004]


def test_gate_funding_uses_contract_symbol(monkeypatch):
    def fake(url, params=None):
        if url.endswith("BTC_USDT"):
            return {"funding_rate": "0.0006"}
        assert params["contract"] == "BTC_USDT"
        return [{"r": "0.0007"}]

    monkeypatch.setattr(engine, "_public_json", fake)
    assert engine.fetch_funding_rate("BTC-USDT", source="gate") == 0.0006
    assert engine.fetch_funding_history("BTC-USDT", 10, source="gate") == [0.0007]


def test_binance_funding_remains_supported(monkeypatch):
    def fake(path, params=None, timeout=15):
        assert params["symbol"] == "BTCUSDT"
        if path.endswith("fundingRate"):
            return [{"fundingRate": "0.0008"}]
        return {"lastFundingRate": "0.0009"}

    monkeypatch.setattr(engine, "request_json", fake)
    assert engine.fetch_funding_rate("BTC-USDT", source="binance") == 0.0009
    assert engine.fetch_funding_history("BTC-USDT", 10, source="binance") == [0.0008]
