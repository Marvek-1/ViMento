from datetime import datetime, timedelta, timezone
import pytest
from futures_paper_engine import FuturesPaperEngine, RiskConfig

@pytest.mark.parametrize("price_key", ["BTCUSDT", "btcusdt", "BTC-USDT", "BTC/USDT", "BTC_USDT"])
def test_process_all_normalizes_price_keys(tmp_path, price_key):
    engine = FuturesPaperEngine(tmp_path, initial_balance=1000)
    pos = engine.open_position("BTCUSDT", "long", price=100, risk=RiskConfig(margin=50, leverage=10, max_hold_minutes=1))
    engine.state.positions[pos.trade_id].entry_time = (datetime.now(timezone.utc) - timedelta(minutes=2)).isoformat()
    closed = engine.process_all({price_key: 100})
    assert len(closed) == 1
    assert closed[0].exit_reason == "max_hold"

def test_stored_symbol_is_normalized_before_lookup(tmp_path):
    engine = FuturesPaperEngine(tmp_path, initial_balance=1000)
    pos = engine.open_position("BTC-USDT", "long", price=100, risk=RiskConfig(margin=50, leverage=10, max_hold_minutes=1))
    engine.state.positions[pos.trade_id].entry_time = (datetime.now(timezone.utc) - timedelta(minutes=2)).isoformat()
    assert len(engine.process_all({"BTCUSDT": 100})) == 1
