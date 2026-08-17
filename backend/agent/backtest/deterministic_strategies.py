"""Strategy bodies for the deterministic (non-LLM) governed backtest route.

The governed backtest endpoint executes ``backtest.runner`` directly with no
agent in the loop, which means no model is available to author
``code/signal_engine.py``. ``BUY_AND_HOLD_SOURCE`` is a concrete, hardcoded
equal-weight buy-and-hold engine used for that path. It is deliberately
different in wording/structure from the autopilot scaffold template so it is
never mistaken for an unimplemented stub by
``backtest.run_card._is_unimplemented_scaffold_signal_engine``.
"""

from __future__ import annotations

BUY_AND_HOLD_TEMPLATE = "equal_weight_buy_and_hold_baseline"

BUY_AND_HOLD_SOURCE = '''"""Deterministic equal-weight buy-and-hold engine.

Used by the governed backtest API route (no LLM in this path). Holds every
requested symbol at a constant 1/N portfolio weight for the full window.
"""

from __future__ import annotations

import pandas as pd


class SignalEngine:
    """Equal-weight buy-and-hold across every symbol in data_map."""

    def generate(self, data_map: dict[str, "pd.DataFrame"]) -> dict[str, "pd.Series"]:
        n = len(data_map)
        target_weight = 1.0 / n if n else 0.0
        return {
            code: pd.Series(target_weight, index=frame.index)
            for code, frame in data_map.items()
        }
'''
