"""Security regression tests for run_dir-based file tools."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import pytest

from src.tools.backtest_tool import run_backtest
from src.tools.edit_file_tool import EditFileTool
from src.tools.read_file_tool import ReadFileTool
from src.tools.signal_engine_contract import canonicalization_pass
from src.tools.write_file_tool import WriteFileTool
from src.tools.path_utils import allowed_write_roots, resolve_safe_path


def _body(raw: str) -> dict:
    """Parse a JSON tool response."""
    return json.loads(raw)


def test_write_file_rejects_unconfigured_absolute_run_dir(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("VIBE_TRADING_ALLOWED_RUN_ROOTS", raising=False)

    body = _body(WriteFileTool().execute(
        path="code/signal_engine.py",
        content="print('nope')",
        run_dir=str(tmp_path),
    ))

    assert body["status"] == "error"
    assert "outside allowed run roots" in body["error"]
    assert not (tmp_path / "code" / "signal_engine.py").exists()


def test_read_and_edit_file_accept_configured_run_root(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("VIBE_TRADING_ALLOWED_RUN_ROOTS", str(tmp_path))
    target = tmp_path / "run" / "notes.md"
    target.parent.mkdir(parents=True)
    target.write_text("alpha beta", encoding="utf-8")

    read_body = _body(ReadFileTool().execute(path="notes.md", run_dir=str(target.parent)))
    edit_body = _body(EditFileTool().execute(
        path="notes.md",
        old_text="beta",
        new_text="gamma",
        run_dir=str(target.parent),
    ))

    assert read_body["status"] == "ok"
    assert "alpha beta" in read_body["content"]
    assert edit_body["status"] == "ok"
    assert target.read_text(encoding="utf-8") == "alpha gamma"


def test_backtest_rejects_unconfigured_absolute_run_dir(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("VIBE_TRADING_ALLOWED_RUN_ROOTS", raising=False)
    (tmp_path / "code").mkdir()
    (tmp_path / "config.json").write_text('{"source":"auto","codes":["AAPL"]}', encoding="utf-8")
    (tmp_path / "code" / "signal_engine.py").write_text(
        "class SignalEngine:\n    def generate(self, data_map):\n        return {}\n",
        encoding="utf-8",
    )

    body = _body(run_backtest(str(tmp_path)))

    assert body["status"] == "error"
    assert "outside allowed run roots" in body["error"]


def test_tilde_expansion_resolves_to_mock_home(tmp_path: Path, monkeypatch) -> None:
    # Mock user home directory
    mock_home = tmp_path / "home_user"
    mock_home.mkdir()
    monkeypatch.setenv("HOME", str(mock_home))
    monkeypatch.setenv("USERPROFILE", str(mock_home))

    # Configure mock home as allowed write root
    monkeypatch.setenv("VIBE_TRADING_ALLOWED_WRITE_ROOTS", str(mock_home / ".vibe-trading"))
    allowed_write = allowed_write_roots()
    assert any(p.is_relative_to(mock_home) for p in allowed_write)

    # Resolve safe path using tilde
    resolved = resolve_safe_path("~/.vibe-trading/scripts/strat.py", None, allowed_write, purpose="write")
    assert resolved == mock_home / ".vibe-trading" / "scripts" / "strat.py"


def test_read_write_separation_prevent_cross_escalation(tmp_path: Path, monkeypatch) -> None:
    read_only_dir = tmp_path / "read_only"
    write_only_dir = tmp_path / "write_only"
    read_only_dir.mkdir()
    write_only_dir.mkdir()

    # Configure separate environment variables
    monkeypatch.setenv("VIBE_TRADING_ALLOWED_FILE_ROOTS", str(read_only_dir))
    monkeypatch.setenv("VIBE_TRADING_ALLOWED_WRITE_ROOTS", str(write_only_dir))

    # Setup read-only file
    ro_file = read_only_dir / "conf.json"
    ro_file.write_text('{"key": "val"}', encoding="utf-8")

    # 1. Read should succeed on read-only root
    read_res = _body(ReadFileTool().execute(path=str(ro_file)))
    assert read_res["status"] == "ok"
    assert "val" in read_res["content"]

    # 2. Write/Edit should FAIL on read-only root (write isolation)
    write_res = _body(WriteFileTool().execute(path=str(ro_file), content="poison"))
    assert write_res["status"] == "error"
    assert "run_dir is required" in write_res["error"] or "escapes" in write_res["error"]
    assert ro_file.read_text(encoding="utf-8") == '{"key": "val"}' # Intact

    # 3. Write should succeed on write-only root
    wo_file = write_only_dir / "output.txt"
    write_ok = _body(WriteFileTool().execute(path=str(wo_file), content="success_write"))
    assert write_ok["status"] == "ok"
    assert wo_file.read_text(encoding="utf-8") == "success_write"


def test_resolve_safe_path_run_dir_escapes_fallback(tmp_path: Path, monkeypatch) -> None:
    run_dir = tmp_path / "runs" / "run_1"
    run_dir.mkdir(parents=True)
    extra_write_dir = tmp_path / "extra_write"
    extra_write_dir.mkdir()

    monkeypatch.setenv("VIBE_TRADING_ALLOWED_RUN_ROOTS", str(tmp_path / "runs"))
    monkeypatch.setenv("VIBE_TRADING_ALLOWED_WRITE_ROOTS", str(extra_write_dir))

    # 1. Inside run_dir -> resolves to run_dir
    resolved_1 = resolve_safe_path("script.py", str(run_dir), allowed_write_roots(), purpose="write")
    assert resolved_1 == run_dir / "script.py"

    # 2. Escapes run_dir but inside extra_write -> resolves to extra_write (fallback)
    resolved_2 = resolve_safe_path(str(extra_write_dir / "tool.py"), str(run_dir), allowed_write_roots(), purpose="write")
    assert resolved_2 == extra_write_dir / "tool.py"

    # 3. Escapes run_dir and not in extra_write -> raises ValueError
    with pytest.raises(ValueError) as excinfo:
        resolve_safe_path("/etc/passwd", str(run_dir), allowed_write_roots(), purpose="write")
    assert "escapes run_dir" in str(excinfo.value)


def test_write_signal_engine_returns_contract_receipt(tmp_path: Path, monkeypatch) -> None:
    run_dir = tmp_path / "runs" / "run_1"
    (run_dir / "code").mkdir(parents=True)
    (run_dir / "config.json").write_text(
        '{"codes":["000300.SH"],"source":"auto","start_date":"2024-01-01","end_date":"2024-03-01"}',
        encoding="utf-8",
    )
    monkeypatch.setenv("VIBE_TRADING_ALLOWED_RUN_ROOTS", str(tmp_path / "runs"))

    content = """
from __future__ import annotations

import pandas as pd


class SignalEngine:
    def generate(self, data_map):
        signals = {}
        for code, frame in data_map.items():
            signals[code] = pd.Series(0.0, index=frame.index)
        return signals
""".lstrip()

    body = _body(
        WriteFileTool().execute(
            path="code/signal_engine.py",
            content=content,
            run_dir=str(run_dir),
        )
    )

    expected_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()

    assert body["status"] == "ok"
    assert body["contract_receipt"]["status"] == "ok"
    assert body["contract_receipt"]["contract_valid"] is True
    assert body["contract_receipt"]["codes"] == ["000300.SH"]
    assert body["contract_receipt"]["output_keys"] == ["000300.SH"]
    assert body["contract_receipt"]["signal_engine_sha256"] == expected_hash
    assert body["sha256"] == expected_hash
    assert (run_dir / "code" / "signal_engine.py").read_text(encoding="utf-8") == content


def test_write_signal_engine_rejects_wrong_symbol_contract_without_writing(
    tmp_path: Path,
    monkeypatch,
) -> None:
    run_dir = tmp_path / "runs" / "run_1"
    (run_dir / "code").mkdir(parents=True)
    (run_dir / "config.json").write_text(
        '{"codes":["000300.SH"],"source":"auto","start_date":"2024-01-01","end_date":"2024-03-01"}',
        encoding="utf-8",
    )
    monkeypatch.setenv("VIBE_TRADING_ALLOWED_RUN_ROOTS", str(tmp_path / "runs"))

    content = """
from __future__ import annotations

import pandas as pd


class SignalEngine:
    def generate(self, data_map):
        frame = next(iter(data_map.values()))
        return {"BTC-USDT": pd.Series(0.0, index=frame.index)}
""".lstrip()

    body = _body(
        WriteFileTool().execute(
            path="code/signal_engine.py",
            content=content,
            run_dir=str(run_dir),
        )
    )

    assert body["status"] == "error"
    assert "output keys must match config codes" in body["error"]
    assert body["contract_receipt"]["status"] == "error"
    assert not (run_dir / "code" / "signal_engine.py").exists()


def test_edit_signal_engine_returns_contract_hash_matching_write_receipt(
    tmp_path: Path,
    monkeypatch,
) -> None:
    run_dir = tmp_path / "runs" / "run_1"
    signal_path = run_dir / "code" / "signal_engine.py"
    signal_path.parent.mkdir(parents=True)
    (run_dir / "config.json").write_text(
        '{"codes":["000300.SH"],"source":"auto","start_date":"2024-01-01","end_date":"2024-03-01"}',
        encoding="utf-8",
    )
    monkeypatch.setenv("VIBE_TRADING_ALLOWED_RUN_ROOTS", str(tmp_path / "runs"))

    content = """
from __future__ import annotations

import pandas as pd


class SignalEngine:
    def generate(self, data_map):
        signals = {}
        for code, frame in data_map.items():
            signals[code] = pd.Series(0.0, index=frame.index)
        return signals
""".lstrip()
    signal_path.write_text(content, encoding="utf-8")

    old_text = "signals[code] = pd.Series(0.0, index=frame.index)"
    new_text = "signals[code] = pd.Series(1.0, index=frame.index)"
    expected_content = content.replace(old_text, new_text, 1)
    expected_hash = hashlib.sha256(expected_content.encode("utf-8")).hexdigest()

    body = _body(
        EditFileTool().execute(
            path="code/signal_engine.py",
            old_text=old_text,
            new_text=new_text,
            run_dir=str(run_dir),
        )
    )

    assert body["status"] == "ok"
    assert body["contract_receipt"]["status"] == "ok"
    assert body["contract_receipt"]["contract_valid"] is True
    assert body["contract_receipt"]["signal_engine_sha256"] == expected_hash
    assert body["sha256"] == expected_hash
    assert signal_path.read_text(encoding="utf-8") == expected_content


def test_edit_signal_engine_rejects_invalid_contract_and_preserves_file(
    tmp_path: Path,
    monkeypatch,
) -> None:
    run_dir = tmp_path / "runs" / "run_1"
    signal_path = run_dir / "code" / "signal_engine.py"
    signal_path.parent.mkdir(parents=True)
    (run_dir / "config.json").write_text(
        '{"codes":["000300.SH"],"source":"auto","start_date":"2024-01-01","end_date":"2024-03-01"}',
        encoding="utf-8",
    )
    monkeypatch.setenv("VIBE_TRADING_ALLOWED_RUN_ROOTS", str(tmp_path / "runs"))

    content = """
from __future__ import annotations

import pandas as pd


class SignalEngine:
    def generate(self, data_map):
        signals = {}
        for code, frame in data_map.items():
            signals[code] = pd.Series(0.0, index=frame.index)
        return signals
""".lstrip()
    signal_path.write_text(content, encoding="utf-8")

    body = _body(
        EditFileTool().execute(
            path="code/signal_engine.py",
            old_text="signals[code]",
            new_text="signals['BTC-USDT']",
            run_dir=str(run_dir),
        )
    )

    assert body["status"] == "error"
    assert "output keys must match config codes" in body["error"]
    assert body["contract_receipt"]["status"] == "error"
    assert signal_path.read_text(encoding="utf-8") == content


def test_write_file_rejects_scaffold_hash_marker(tmp_path: Path, monkeypatch) -> None:
    run_dir = tmp_path / "runs" / "run_1"
    (run_dir / "code").mkdir(parents=True)
    monkeypatch.setenv("VIBE_TRADING_ALLOWED_RUN_ROOTS", str(tmp_path / "runs"))

    body = _body(
        WriteFileTool().execute(
            path="code/.scaffold.sha256",
            content='{"scaffold_sha256": "forged"}',
            run_dir=str(run_dir),
        )
    )

    assert body["status"] == "error"
    assert "trust-marker file" in body["error"]
    assert not (run_dir / "code" / ".scaffold.sha256").exists()


def test_write_file_rejects_strategy_provenance_marker(tmp_path: Path, monkeypatch) -> None:
    """An agent must not be able to self-declare its own body verified.

    Without this check, an agent could write a real (matching) hash into
    .strategy_provenance.json next to a signal_engine.py it authored itself,
    and assert_not_scaffold() would return a bare verified hash instead of
    'unverified:' — forged provenance indistinguishable from the real thing.
    """
    run_dir = tmp_path / "runs" / "run_1"
    (run_dir / "code").mkdir(parents=True)
    monkeypatch.setenv("VIBE_TRADING_ALLOWED_RUN_ROOTS", str(tmp_path / "runs"))

    body = _body(
        WriteFileTool().execute(
            path="code/.strategy_provenance.json",
            content='{"scaffold_status": "not_scaffold", "sha256": "forged"}',
            run_dir=str(run_dir),
        )
    )

    assert body["status"] == "error"
    assert "trust-marker file" in body["error"]
    assert not (run_dir / "code" / ".strategy_provenance.json").exists()


def test_edit_file_rejects_trust_marker_tamper(tmp_path: Path, monkeypatch) -> None:
    """edit_file must refuse trust markers too, not just write_file.

    Rejecting only write_file would leave a tamper path open: an agent could
    edit_file an *existing* marker (written by a trusted code path) to match
    a body it forged afterward.
    """
    run_dir = tmp_path / "runs" / "run_1"
    (run_dir / "code").mkdir(parents=True)
    marker = run_dir / "code" / ".strategy_provenance.json"
    marker.write_text('{"scaffold_status": "not_scaffold", "sha256": "real"}', encoding="utf-8")
    monkeypatch.setenv("VIBE_TRADING_ALLOWED_RUN_ROOTS", str(tmp_path / "runs"))

    body = _body(
        EditFileTool().execute(
            path="code/.strategy_provenance.json",
            old_text="real",
            new_text="forged",
            run_dir=str(run_dir),
        )
    )

    assert body["status"] == "error"
    assert "trust-marker file" in body["error"]
    assert marker.read_text(encoding="utf-8") == '{"scaffold_status": "not_scaffold", "sha256": "real"}'


def test_trusted_code_paths_still_write_markers_directly(tmp_path: Path) -> None:
    """The gate blocks agent *tool calls*, not the trusted receipt module itself."""
    import write_receipt as wr

    run_dir = tmp_path / "run"
    engine = run_dir / "code" / "signal_engine.py"
    wr.receipted_write(engine, "class SignalEngine:\n    pass\n")

    wr.record_scaffold_hash(run_dir)
    assert (run_dir / "code" / wr.SCAFFOLD_HASH_FILENAME).exists()

    wr.mark_deterministic_baseline(run_dir, template="t", generated_by="test")
    assert (run_dir / "code" / wr.STRATEGY_PROVENANCE_FILENAME).exists()


def test_missing_contract_hash_blocks_canonicalization() -> None:
    proof = {
        "candidate_hash": "abc",
        "governed_hash": "abc",
        "write_receipt_hash": "abc",
        "contract_receipt_hash": None,
    }

    assert canonicalization_pass(proof) is False


def test_hash_mismatch_between_contract_and_write_blocks_success() -> None:
    proof = {
        "candidate_hash": "abc",
        "governed_hash": "abc",
        "write_receipt_hash": "abc",
        "contract_receipt_hash": "def",
    }

    assert canonicalization_pass(proof) is False
