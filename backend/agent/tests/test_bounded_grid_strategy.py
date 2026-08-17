from __future__ import annotations

import pytest

from bounded_grid_strategy import BoundedGridConfig, BoundedGridStrategy, config_hash


def _config(**overrides) -> BoundedGridConfig:
    base = dict(
        symbol="BTC-USDT", leverage=5, margin_per_level=10.0, max_total_notional=150.0,
        levels_per_side=3, max_open_levels=3, grid_spacing_bps=25.0,
        take_profit_bps=30.0, stop_loss_bps=90.0,
    )
    base.update(overrides)
    return BoundedGridConfig(**base)


def test_config_rejects_notional_cap_below_max_levels():
    with pytest.raises(ValueError):
        BoundedGridStrategy(_config(max_total_notional=100.0))  # 3 x 10 x 5x = 150 > 100


def test_first_tick_sets_center_and_opens_nothing_at_center():
    strategy = BoundedGridStrategy(_config())
    intents = strategy.on_price_tick(100.0, open_trade_ids=set())
    assert strategy.center_price == 100.0
    assert intents == []


def test_price_drop_through_lower_level_opens_long():
    strategy = BoundedGridStrategy(_config())
    strategy.on_price_tick(100.0, open_trade_ids=set())
    # level 1 long trigger = 100 * (1 - 0.0025) = 99.75
    intents = strategy.on_price_tick(99.70, open_trade_ids=set())
    assert len(intents) == 1
    assert intents[0].action == "OPEN_LONG"
    assert intents[0].level_id == "long:1"


def test_price_rise_through_upper_level_opens_short():
    strategy = BoundedGridStrategy(_config())
    strategy.on_price_tick(100.0, open_trade_ids=set())
    intents = strategy.on_price_tick(100.30, open_trade_ids=set())
    assert len(intents) == 1
    assert intents[0].action == "OPEN_SHORT"
    assert intents[0].level_id == "short:1"


def test_occupied_level_does_not_refire_until_closed():
    strategy = BoundedGridStrategy(_config())
    strategy.on_price_tick(100.0, open_trade_ids=set())
    intents = strategy.on_price_tick(99.70, open_trade_ids=set())
    strategy.mark_level_filled(intents[0].level_id, "trade-1")

    # Price stays past the trigger -- level 1 must not fire a second time
    # while its position is still open (no martingale / no re-entry stacking).
    again = strategy.on_price_tick(99.60, open_trade_ids={"trade-1"})
    assert all(i.level_id != "long:1" for i in again)


def test_level_frees_and_can_refire_after_position_closes():
    strategy = BoundedGridStrategy(_config())
    strategy.on_price_tick(100.0, open_trade_ids=set())
    intents = strategy.on_price_tick(99.70, open_trade_ids=set())
    strategy.mark_level_filled(intents[0].level_id, "trade-1")

    # Engine no longer reports trade-1 as open (TP/SL closed it) -- and since
    # the strategy is flat again, it re-centers before evaluating levels.
    intents_after_close = strategy.on_price_tick(99.70, open_trade_ids=set())
    assert strategy.center_price == 99.70
    assert intents_after_close == []  # exactly at the new center, no level crossed yet


def test_max_open_levels_caps_total_regardless_of_side_mix():
    strategy = BoundedGridStrategy(_config(max_open_levels=2))
    strategy.on_price_tick(100.0, open_trade_ids=set())
    # Crash straight through all three long levels in one tick.
    intents = strategy.on_price_tick(90.0, open_trade_ids=set())
    assert len(intents) == 2  # capped at max_open_levels, not levels_per_side


def test_max_total_notional_caps_new_entries():
    # BoundedGridConfig.validate() already refuses a config where
    # max_open_levels x level_notional exceeds max_total_notional, so the two
    # caps can never actually disagree at construction time -- this proves
    # the runtime notional accounting in on_price_tick still holds exactly at
    # that boundary rather than silently overshooting it by float error.
    strategy = BoundedGridStrategy(_config(max_total_notional=150.0, max_open_levels=3))
    strategy.on_price_tick(100.0, open_trade_ids=set())
    intents = strategy.on_price_tick(90.0, open_trade_ids=set())
    assert len(intents) == 3
    assert sum(i.margin * strategy.config.leverage for i in intents) == pytest.approx(150.0)


def test_fixed_margin_per_level_no_martingale():
    strategy = BoundedGridStrategy(_config())
    strategy.on_price_tick(100.0, open_trade_ids=set())
    intents = strategy.on_price_tick(90.0, open_trade_ids=set())
    assert all(i.margin == 10.0 for i in intents)


def test_state_round_trips_through_export_restore():
    strategy = BoundedGridStrategy(_config())
    strategy.on_price_tick(100.0, open_trade_ids=set())
    intents = strategy.on_price_tick(99.70, open_trade_ids=set())
    strategy.mark_level_filled(intents[0].level_id, "trade-1")

    restored = BoundedGridStrategy(_config())
    restored.restore_state(strategy.export_state())
    assert restored.center_price == strategy.center_price
    assert restored.occupied == strategy.occupied


def test_restore_state_rejects_config_drift():
    strategy = BoundedGridStrategy(_config())
    strategy.on_price_tick(100.0, open_trade_ids=set())
    state = strategy.export_state()

    drifted = BoundedGridStrategy(_config(grid_spacing_bps=50.0))
    with pytest.raises(ValueError):
        drifted.restore_state(state)


def test_config_hash_changes_with_config():
    a = config_hash(_config())
    b = config_hash(_config(grid_spacing_bps=50.0))
    assert a != b


def test_invalid_mark_price_raises():
    strategy = BoundedGridStrategy(_config())
    with pytest.raises(ValueError):
        strategy.on_price_tick(0.0, open_trade_ids=set())
    with pytest.raises(ValueError):
        strategy.on_price_tick(-5.0, open_trade_ids=set())
