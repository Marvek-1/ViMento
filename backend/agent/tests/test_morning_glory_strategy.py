from morning_glory_strategy import decide, funding_zscore


def test_zscore_requires_history():
    assert funding_zscore([0.0001] * 5, 0.0002, 120) is None


def test_negative_extreme_opens_long():
    assert decide(-2.0, False, 1.5, 0.5).action == "OPEN_LONG"


def test_positive_extreme_opens_short():
    assert decide(2.0, False, 1.5, 0.5).action == "OPEN_SHORT"


def test_mean_reversion_closes_position():
    assert decide(0.25, True, 1.5, 0.5).action == "CLOSE"
