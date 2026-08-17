"""CMC placeholder loader.

``cmc`` is a canonical source name used by the generated source schema for
fund-style instruments. There is no configured CMC OHLCV backend yet, so this
loader intentionally reports unavailable and lets registry fallback continue
to the next fund provider.
"""

from __future__ import annotations

from typing import Dict, List, Optional

import pandas as pd

from backtest.loaders.registry import register


@register
class DataLoader:
    """Unavailable CMC hook that degrades through the fund fallback chain."""

    name = "cmc"
    markets = {"fund"}
    requires_auth = False

    def is_available(self) -> bool:
        return False

    def fetch(
        self,
        codes: List[str],
        start_date: str,
        end_date: str,
        *,
        interval: str = "1D",
        fields: Optional[List[str]] = None,
    ) -> Dict[str, pd.DataFrame]:
        return {}
