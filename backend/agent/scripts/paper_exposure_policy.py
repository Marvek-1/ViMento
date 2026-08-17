"""Portfolio-level exposure governor: RISK_ON / CAUTION / RISK_OFF gating on
trend and volatility, applied as a scalar on top of the existing equal-
weight rebalance target.

This is a new, freestanding candidate proposed to address one specific,
verified finding (see reports/profit_recovery/): the repaired equal-weight
strategy runs at ~100% gross exposure to an 8-symbol crypto basket at all
times, so a falling basket produces a falling book regardless of how well
the rebalance layer itself performs. It does NOT continue, resume, or reuse
any prior "adaptive allocator" run -- no such run exists in this repo, and
none of its cited failure modes or thresholds are real; every threshold
here is a new, frozen-for-testing proposal, not a validated repo
convention.

Design constraints (frozen for the offline experiment -- do not tune
against the six short v2 sessions used only for mechanical verification):
- No shorts, no leverage, no synthetic hedges.
- Long-only sleeve blend: target_gross_exposure in {0.0, 0.5, 1.0}.
- A decision at timestamp T must use only price/accounting information
  timestamped <= T -- no lookahead.
- Hysteresis: exposure reductions confirm faster (2 checks) than exposure
  increases (4 checks), with a minimum dwell per state, so the governor
  does not pay repeated fees oscillating around a boundary.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Literal, Optional

State = Literal["RISK_ON", "CAUTION", "RISK_OFF"]

EXPOSURE_BY_STATE: dict[State, float] = {"RISK_ON": 1.0, "CAUTION": 0.5, "RISK_OFF": 0.0}
_STATE_RANK: dict[State, int] = {"RISK_OFF": 0, "CAUTION": 1, "RISK_ON": 2}

DEFAULT_POLICY_CONFIG: dict[str, Any] = {
    "policy_id": "exposure_governor_v1",
    "trend_score_risk_off_max": 1,       # trend_score <= this -> RISK_OFF
    "trend_score_caution": 2,            # trend_score == this -> CAUTION
    "vol_percentile_caution_min": 0.95,  # trailing vol percentile >= this -> CAUTION
    "reduce_confirmations": 2,           # consecutive checks to move to LOWER exposure
    "increase_confirmations": 4,         # consecutive checks to move to HIGHER exposure
    "min_dwell_minutes": 60,
}


def config_hash(config: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(config, sort_keys=True).encode("utf-8")).hexdigest()[:16]


@dataclass(frozen=True)
class ExposureDecision:
    timestamp: str
    state: State
    target_gross_exposure: float
    trend_score: int
    volatility_percentile: Optional[float]
    confirmations: int
    reason: str
    policy_id: str
    config_hash: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def compute_trend_score(
    *,
    btc_return_6h: Optional[float],
    btc_return_24h: Optional[float],
    basket_return_6h: Optional[float],
    basket_return_24h: Optional[float],
) -> int:
    """+1 for each of the four trend observations that is positive. A
    missing (None) observation -- not enough history yet -- scores 0, not a
    fabricated sign; it can only ever push the score toward RISK_OFF/CAUTION,
    never toward a false RISK_ON."""
    score = 0
    for value in (btc_return_6h, btc_return_24h, basket_return_6h, basket_return_24h):
        if value is not None and value > 0:
            score += 1
    return score


def raw_state_for_observation(
    *,
    stale_prices: bool,
    accounting_ok: bool,
    trend_score: int,
    volatility_percentile: Optional[float],
    config: dict[str, Any],
) -> tuple[State, str]:
    """The frozen state machine, evaluated on a single observation.
    Hysteresis/dwell is applied separately by ExposurePolicy."""
    if stale_prices or not accounting_ok:
        return "RISK_OFF", "stale_prices_or_accounting_not_ok"
    if trend_score <= config["trend_score_risk_off_max"]:
        return "RISK_OFF", f"trend_score={trend_score}<={config['trend_score_risk_off_max']}"
    if trend_score == config["trend_score_caution"]:
        return "CAUTION", f"trend_score=={config['trend_score_caution']}"
    if volatility_percentile is not None and volatility_percentile >= config["vol_percentile_caution_min"]:
        return "CAUTION", f"volatility_percentile={volatility_percentile:.3f}>={config['vol_percentile_caution_min']}"
    return "RISK_ON", f"trend_score={trend_score}>{config['trend_score_caution']}_and_vol_below_caution_threshold"


def _parse_iso(value: str) -> datetime:
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


class ExposurePolicy:
    """Stateful hysteresis/dwell wrapper around raw_state_for_observation.

    One instance per session/replay -- state (current exposure state,
    pending-confirmation count, dwell clock) is not safe to share across
    independent replays.
    """

    def __init__(self, config: Optional[dict[str, Any]] = None):
        self.config = dict(DEFAULT_POLICY_CONFIG)
        if config:
            self.config.update(config)
        self._config_hash = config_hash(self.config)
        self.current_state: State = "RISK_ON"
        self._pending_state: Optional[State] = None
        self._pending_count = 0
        self._state_entered_at: Optional[datetime] = None
        self.history: list[ExposureDecision] = []

    def decide(
        self,
        *,
        timestamp: str,
        stale_prices: bool,
        accounting_ok: bool,
        trend_score: int,
        volatility_percentile: Optional[float],
    ) -> ExposureDecision:
        raw_state, raw_reason = raw_state_for_observation(
            stale_prices=stale_prices,
            accounting_ok=accounting_ok,
            trend_score=trend_score,
            volatility_percentile=volatility_percentile,
            config=self.config,
        )
        now = _parse_iso(timestamp)
        reason = raw_reason

        if raw_state == self.current_state:
            self._pending_state = None
            self._pending_count = 0
        else:
            if self._pending_state == raw_state:
                self._pending_count += 1
            else:
                self._pending_state = raw_state
                self._pending_count = 1

            moving_lower = _STATE_RANK[raw_state] < _STATE_RANK[self.current_state]
            required = self.config["reduce_confirmations"] if moving_lower else self.config["increase_confirmations"]
            dwell_ok = (
                self._state_entered_at is None
                or (now - self._state_entered_at) >= timedelta(minutes=self.config["min_dwell_minutes"])
            )
            if self._pending_count >= required and dwell_ok:
                self.current_state = raw_state
                self._state_entered_at = now
                self._pending_state = None
                self._pending_count = 0
                reason = f"{raw_reason}; confirmed after {required} checks"
            else:
                reason = f"{raw_reason}; pending ({self._pending_count}/{required} confirmations, dwell_ok={dwell_ok})"

        if self._state_entered_at is None:
            self._state_entered_at = now

        decision = ExposureDecision(
            timestamp=timestamp,
            state=self.current_state,
            target_gross_exposure=EXPOSURE_BY_STATE[self.current_state],
            trend_score=trend_score,
            volatility_percentile=volatility_percentile,
            confirmations=self._pending_count,
            reason=reason,
            policy_id=self.config["policy_id"],
            config_hash=self._config_hash,
        )
        self.history.append(decision)
        return decision
