"""Backtest tool source-default regression tests."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from src.tools import backtest_tool


def test_run_backtest_accepts_missing_source_as_auto(tmp_path: Path, monkeypatch) -> None:
    run_dir = tmp_path / "run"
    (run_dir / "code").mkdir(parents=True)
    (run_dir / "config.json").write_text(
        json.dumps(
            {
                "codes": ["BTC-USDT"],
                "start_date": "2025-01-01",
                "end_date": "2025-01-31",
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "code" / "signal_engine.py").write_text(
        "class SignalEngine:\n"
        "    def generate(self, data_map):\n"
        "        return {}\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("VIBE_TRADING_ALLOWED_RUN_ROOTS", str(tmp_path))

    progress_messages: list[str] = []
    monkeypatch.setattr(
        backtest_tool,
        "emit_progress",
        lambda _stage, *, message: progress_messages.append(message),
    )

    class FakeRunner:
        def __init__(self, timeout: int) -> None:
            self.timeout = timeout

        def execute(self, *args, **kwargs):
            return SimpleNamespace(success=True, exit_code=0, stdout="", stderr="", artifacts={})

    monkeypatch.setattr(backtest_tool, "Runner", FakeRunner)

    body = json.loads(backtest_tool.run_backtest(str(run_dir)))

    assert body["status"] == "ok"
    assert "running backtest engine (source=auto)" in progress_messages
