import pytest

from positions_reconciliation import reconcile_positions, validate_position_snapshot


def test_three_same_symbol_legs_are_preserved():
    positions = [
        {"trade_id": "leg-1", "symbol": "BTCUSDT"},
        {"trade_id": "leg-2", "symbol": "BTCUSDT"},
        {"trade_id": "leg-3", "symbol": "BTCUSDT"},
    ]
    plan = reconcile_positions("grid-5x", positions, set())
    assert [p["trade_id"] for p in plan.upserts] == ["leg-1", "leg-2", "leg-3"]
    assert plan.deletes == ()


def test_only_closed_leg_is_deleted():
    positions = [
        {"trade_id": "leg-1", "symbol": "BTCUSDT"},
        {"trade_id": "leg-3", "symbol": "BTCUSDT"},
    ]
    plan = reconcile_positions("grid-5x", positions, {"leg-1", "leg-2", "leg-3"})
    assert plan.deletes == ("leg-2",)


def test_empty_snapshot_deletes_all_known_legs():
    plan = reconcile_positions("grid-5x", [], {"leg-1", "leg-2"})
    assert plan.upserts == ()
    assert plan.deletes == ("leg-1", "leg-2")


@pytest.mark.parametrize(
    "positions, message",
    [
        ([{"symbol": "BTCUSDT"}], "missing trade_id"),
        ([{"trade_id": "x"}, {"trade_id": "x"}], "duplicate trade_id"),
    ],
)
def test_invalid_snapshot_fails_before_persistence(positions, message):
    with pytest.raises(ValueError, match=message):
        validate_position_snapshot("grid-5x", positions)
