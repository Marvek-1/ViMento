from __future__ import annotations

from paper_exposure_policy import (
    DEFAULT_POLICY_CONFIG,
    ExposurePolicy,
    compute_trend_score,
    config_hash,
    raw_state_for_observation,
)


def test_trend_score_counts_positive_observations_only() -> None:
    assert compute_trend_score(
        btc_return_6h=0.01, btc_return_24h=-0.01, basket_return_6h=0.02, basket_return_24h=0.0,
    ) == 2  # 24h basket return of exactly 0.0 is not > 0


def test_trend_score_treats_missing_observation_as_non_positive() -> None:
    """A None (insufficient history) observation must never count toward
    RISK_ON -- it can only ever push the score down, never fabricate a
    positive signal from missing data."""
    assert compute_trend_score(
        btc_return_6h=None, btc_return_24h=0.05, basket_return_6h=0.05, basket_return_24h=0.05,
    ) == 3


def test_raw_state_risk_off_on_stale_prices_regardless_of_trend() -> None:
    state, reason = raw_state_for_observation(
        stale_prices=True, accounting_ok=True, trend_score=4, volatility_percentile=0.1,
        config=DEFAULT_POLICY_CONFIG,
    )
    assert state == "RISK_OFF"
    assert "stale" in reason


def test_raw_state_risk_off_on_accounting_not_ok() -> None:
    state, _ = raw_state_for_observation(
        stale_prices=False, accounting_ok=False, trend_score=4, volatility_percentile=0.1,
        config=DEFAULT_POLICY_CONFIG,
    )
    assert state == "RISK_OFF"


def test_raw_state_thresholds_match_frozen_spec() -> None:
    common = dict(stale_prices=False, accounting_ok=True, config=DEFAULT_POLICY_CONFIG)
    assert raw_state_for_observation(trend_score=0, volatility_percentile=None, **common)[0] == "RISK_OFF"
    assert raw_state_for_observation(trend_score=1, volatility_percentile=None, **common)[0] == "RISK_OFF"
    assert raw_state_for_observation(trend_score=2, volatility_percentile=None, **common)[0] == "CAUTION"
    assert raw_state_for_observation(trend_score=3, volatility_percentile=None, **common)[0] == "RISK_ON"
    assert raw_state_for_observation(trend_score=4, volatility_percentile=None, **common)[0] == "RISK_ON"


def test_raw_state_high_vol_forces_caution_even_with_strong_trend() -> None:
    state, reason = raw_state_for_observation(
        stale_prices=False, accounting_ok=True, trend_score=4, volatility_percentile=0.97,
        config=DEFAULT_POLICY_CONFIG,
    )
    assert state == "CAUTION"
    assert "volatility_percentile" in reason


def test_raw_state_missing_vol_percentile_never_fabricates_caution() -> None:
    """No 30-day history available -> volatility_percentile is None -> the
    vol-based CAUTION branch must never fire, not silently default to 0 or 1."""
    state, _ = raw_state_for_observation(
        stale_prices=False, accounting_ok=True, trend_score=4, volatility_percentile=None,
        config=DEFAULT_POLICY_CONFIG,
    )
    assert state == "RISK_ON"


def test_policy_starts_at_risk_on_with_no_dwell_requirement() -> None:
    policy = ExposurePolicy()
    decision = policy.decide(
        timestamp="2026-01-01T00:00:00+00:00", stale_prices=False, accounting_ok=True,
        trend_score=4, volatility_percentile=0.1,
    )
    assert decision.state == "RISK_ON"
    assert decision.target_gross_exposure == 1.0


def test_policy_reduces_exposure_after_two_confirmations() -> None:
    policy = ExposurePolicy()
    t0 = "2026-01-01T00:00:00+00:00"
    policy.decide(timestamp=t0, stale_prices=False, accounting_ok=True, trend_score=4, volatility_percentile=0.1)

    d1 = policy.decide(timestamp="2026-01-01T02:00:00+00:00", stale_prices=False, accounting_ok=True, trend_score=0, volatility_percentile=0.1)
    assert d1.state == "RISK_ON"  # only 1 confirmation so far

    d2 = policy.decide(timestamp="2026-01-01T04:00:00+00:00", stale_prices=False, accounting_ok=True, trend_score=0, volatility_percentile=0.1)
    assert d2.state == "RISK_OFF"  # 2nd confirmation, dwell (>=60min since t0) satisfied
    assert d2.target_gross_exposure == 0.0


def test_policy_requires_four_confirmations_to_increase_exposure() -> None:
    policy = ExposurePolicy()
    t = "2026-01-01T00:00:00+00:00"
    # Force RISK_OFF immediately via stale prices, then two confirmations to lock it in.
    policy.decide(timestamp=t, stale_prices=True, accounting_ok=True, trend_score=0, volatility_percentile=None)
    policy.decide(timestamp="2026-01-01T02:00:00+00:00", stale_prices=True, accounting_ok=True, trend_score=0, volatility_percentile=None)
    d = policy.decide(timestamp="2026-01-01T04:00:00+00:00", stale_prices=True, accounting_ok=True, trend_score=0, volatility_percentile=None)
    assert d.state == "RISK_OFF"

    # Now trend recovers to RISK_ON-eligible; must take 4 confirmations, not 2.
    timestamps = [f"2026-01-0{i}T00:00:00+00:00" for i in range(2, 6)]
    states = []
    for ts in timestamps:
        d = policy.decide(timestamp=ts, stale_prices=False, accounting_ok=True, trend_score=4, volatility_percentile=0.1)
        states.append(d.state)
    assert states[:3] == ["RISK_OFF", "RISK_OFF", "RISK_OFF"]
    assert states[3] == "RISK_ON"


def test_policy_resets_confirmation_count_if_observation_flips_back() -> None:
    policy = ExposurePolicy()
    t = "2026-01-01T00:00:00+00:00"
    policy.decide(timestamp=t, stale_prices=False, accounting_ok=True, trend_score=4, volatility_percentile=0.1)
    policy.decide(timestamp="2026-01-01T02:00:00+00:00", stale_prices=False, accounting_ok=True, trend_score=0, volatility_percentile=0.1)  # 1st RISK_OFF confirmation
    # Flips back to RISK_ON-consistent observation -- must reset the pending count.
    policy.decide(timestamp="2026-01-01T03:00:00+00:00", stale_prices=False, accounting_ok=True, trend_score=4, volatility_percentile=0.1)
    d = policy.decide(timestamp="2026-01-01T05:00:00+00:00", stale_prices=False, accounting_ok=True, trend_score=0, volatility_percentile=0.1)
    assert d.state == "RISK_ON"  # only 1 confirmation again, not the carried-over 2nd


def test_policy_respects_minimum_dwell_even_with_enough_confirmations() -> None:
    policy = ExposurePolicy()
    t0 = "2026-01-01T00:00:00+00:00"
    policy.decide(timestamp=t0, stale_prices=False, accounting_ok=True, trend_score=4, volatility_percentile=0.1)
    # Two confirmations arrive within the 60-minute dwell window (10 and 20 min after t0).
    policy.decide(timestamp="2026-01-01T00:10:00+00:00", stale_prices=False, accounting_ok=True, trend_score=0, volatility_percentile=0.1)
    d = policy.decide(timestamp="2026-01-01T00:20:00+00:00", stale_prices=False, accounting_ok=True, trend_score=0, volatility_percentile=0.1)
    assert d.state == "RISK_ON"  # confirmations satisfied, but dwell (20min < 60min) is not


def test_decision_is_deterministic_for_identical_inputs() -> None:
    kwargs = dict(timestamp="2026-01-01T00:00:00+00:00", stale_prices=False, accounting_ok=True, trend_score=3, volatility_percentile=0.2)
    d1 = ExposurePolicy().decide(**kwargs)
    d2 = ExposurePolicy().decide(**kwargs)
    assert d1.to_dict() == d2.to_dict()


def test_config_hash_changes_when_config_changes() -> None:
    default_hash = config_hash(DEFAULT_POLICY_CONFIG)
    changed = dict(DEFAULT_POLICY_CONFIG)
    changed["trend_score_risk_off_max"] = 0
    assert config_hash(changed) != default_hash


def test_decision_serializes_full_provenance() -> None:
    policy = ExposurePolicy()
    d = policy.decide(
        timestamp="2026-01-01T00:00:00+00:00", stale_prices=False, accounting_ok=True,
        trend_score=3, volatility_percentile=0.4,
    )
    payload = d.to_dict()
    for key in ("timestamp", "state", "target_gross_exposure", "trend_score",
                "volatility_percentile", "confirmations", "reason", "policy_id", "config_hash"):
        assert key in payload
