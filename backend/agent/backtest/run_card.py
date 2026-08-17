"""Trust Layer run card generator for backtest runs."""

from __future__ import annotations

import ast
import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence


SCHEMA_VERSION = "0.1"
# Minimum trade count before a run's outcome is treated as statistically
# evaluable at all. A handful of trades is not a sample; it's an anecdote.
# This does not itself decide hypothesis_supported -- that requires an actual
# evidence gate (deflated Sharpe, benchmark comparison, etc.) that does not
# exist yet, so hypothesis_supported stays null regardless of trade count
# until that gate is implemented.
CONFIDENCE_GATE_MIN_TRADES = 200
BACKTEST_SUMMARY_KEYS = (
    "codes",
    "start_date",
    "end_date",
    "interval",
    "engine",
    "initial_cash",
    "source",
)


def write_run_card(
    run_dir: Path,
    config: Mapping[str, Any],
    metrics: Mapping[str, Any],
    *,
    data_sources: Sequence[str] | None = None,
    strategy_path: Path | None = None,
    warnings: Sequence[str] | None = None,
    data_source_provenance: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Write JSON and Markdown run cards for a backtest run.

    Args:
        run_dir: Directory where run_card.json and run_card.md are written.
        config: Full backtest configuration. Only a summary and hash are stored.
        metrics: Backtest metrics. Scalar values are stored; ``validation`` is
            stored separately when present.
        data_sources: Data sources used by the run.
        strategy_path: Optional strategy source file to hash for reproducibility.
        warnings: Optional warnings to include in the card.

    Returns:
        The run card payload written to ``run_card.json``.
    """
    run_dir = Path(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)

    config_file = run_dir / "config.json"
    reproducibility: dict[str, Any] = {
        "config_hash": _file_hash(config_file) if config_file.exists() else _json_hash(config),
    }
    if strategy_path is not None:
        strategy_file = Path(strategy_path)
        if strategy_file.exists() and strategy_file.is_file():
            reproducibility["strategy_hash"] = _file_hash(strategy_file)

    scalar_metrics = _scalar_metrics(metrics)
    provenance_valid = _provenance_valid(run_dir, strategy_path)
    has_trades = _has_trades(scalar_metrics)
    provenance_map = data_source_provenance if data_source_provenance is not None else config.get("_data_source_provenance")
    window_integrity = _window_integrity(provenance_map)
    statistically_evaluable = _statistically_evaluable(provenance_valid, scalar_metrics, window_integrity)
    hypothesis_supported = _hypothesis_supported(statistically_evaluable)

    card: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": _utc_now(),
        "run_dir": str(run_dir),
        "backtest": _backtest_summary(config),
        "reproducibility": reproducibility,
        "strategy_implementation_status": _strategy_implementation_status(strategy_path),
        "run_purpose": _run_purpose(strategy_path),
        # provenance_valid: artifacts/strategy exist and are non-scaffold (evidence is real, not fabricated).
        # has_trades: at least one trade occurred (lightweight descriptive flag, not a statistical claim).
        # statistically_evaluable: enough trades on a proven requested window to draw any conclusion at all.
        # hypothesis_supported: always null until a real evidence gate (deflated Sharpe, benchmark
        # comparison, etc.) is implemented -- trade count alone cannot certify support.
        "provenance_valid": provenance_valid,
        "has_trades": has_trades,
        "window_integrity": window_integrity,
        "statistically_evaluable": statistically_evaluable,
        "hypothesis_supported": hypothesis_supported,
        "data_sources": list(data_sources or []),
        "metrics": scalar_metrics,
        "warnings": list(warnings or []),
        "artifacts": _list_artifacts(run_dir),
    }
    if "validation" in metrics:
        card["validation"] = metrics["validation"]
    
    if provenance_map:
        card["data_source_provenance"] = provenance_map

    card = _json_safe(card)
    json_path = run_dir / "run_card.json"
    md_path = run_dir / "run_card.md"
    json_path.write_text(
        json.dumps(
            card,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            default=str,
            allow_nan=False,
        )
        + "\n",
        encoding="utf-8",
    )
    md_path.write_text(_render_markdown(card), encoding="utf-8")
    return card


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _json_hash(value: Mapping[str, Any]) -> str:
    payload = json.dumps(
        {key: val for key, val in value.items() if not str(key).startswith("_")},
        sort_keys=True,
        default=str,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _strategy_implementation_status(strategy_path: Path | None) -> str:
    if strategy_path is None:
        return "missing"
    strategy_file = Path(strategy_path)
    if not strategy_file.exists() or not strategy_file.is_file():
        return "missing"
    if _is_unimplemented_scaffold_signal_engine(strategy_file):
        return "scaffold"
    return "implemented"


def _run_purpose(strategy_path: Path | None) -> str:
    if _strategy_implementation_status(strategy_path) == "scaffold":
        return "smoke_only"
    return "hypothesis_test"


def _provenance_valid(run_dir: Path, strategy_path: Path | None) -> bool:
    """Whether the run's evidence chain is real: a non-scaffold strategy plus its artifacts.

    This says nothing about whether the metrics support the hypothesis — see
    ``_hypothesis_supported`` for that.
    """
    required = (
        run_dir / "config.json",
        run_dir / "artifacts" / "metrics.csv",
        run_dir / "artifacts" / "equity.csv",
    )
    return (
        _strategy_implementation_status(strategy_path) == "implemented"
        and all(path.exists() and path.is_file() for path in required)
    )


def _has_trades(scalar_metrics: Mapping[str, Any]) -> bool:
    """Lightweight descriptive flag: did at least one trade occur. Not a statistical claim."""
    trade_count = scalar_metrics.get("trade_count")
    return isinstance(trade_count, (int, float)) and trade_count > 0



def _window_integrity(data_source_provenance: Any) -> bool | None:
    """Whether delivered data proves the requested window was covered.

    Returns:
        True: every symbol has coverage_ok == True.
        False: provenance exists and at least one symbol is truncated/missing.
        None: no provenance was stamped, so window integrity is unproven.

    Unknown is not guilty, but unknown is also not evidence.
    """
    if not data_source_provenance:
        return None
    if not isinstance(data_source_provenance, Mapping):
        return None

    saw_symbol = False
    for record in data_source_provenance.values():
        saw_symbol = True
        if not isinstance(record, Mapping):
            return False
        if record.get("coverage_ok") is not True:
            return False

    return True if saw_symbol else None

def _statistically_evaluable(
    provenance_valid: bool,
    scalar_metrics: Mapping[str, Any],
    window_integrity: bool | None,
) -> bool:
    """Whether the run clears the minimum conditions for statistical evaluation.

    Evaluable means enough trades on the exact window the hypothesis named.
    Both False and None window_integrity block evaluation.
    """
    if not provenance_valid or window_integrity is not True:
        return False
    trade_count = scalar_metrics.get("trade_count")
    return isinstance(trade_count, (int, float)) and trade_count >= CONFIDENCE_GATE_MIN_TRADES

def _hypothesis_supported(statistically_evaluable: bool) -> bool | None:
    """Whether the hypothesis is supported by evidence.

    Always ``None`` for now: certifying support requires a real evidence gate
    (deflated Sharpe, benchmark comparison, out-of-sample consistency, etc.)
    that does not exist yet. ``statistically_evaluable`` alone -- trade count
    clearing a threshold -- is necessary but not sufficient, so this must not
    be derived from a naive sign check on sharpe/return.
    """
    return None


def _is_unimplemented_scaffold_signal_engine(signal_path: Path) -> bool:
    """Return True when ``signal_engine.py`` is still the flat scaffold stub."""
    try:
        source = signal_path.read_text(encoding="utf-8")
    except OSError:
        return False

    if (
        "Auto-scaffolded signal engine" not in source
        or "flat 0.0" not in source
        or "Implement your signal" not in source
    ):
        return False

    try:
        tree = ast.parse(source, filename=str(signal_path))
    except SyntaxError:
        return False

    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef) or node.name != "generate":
            continue
        for child in ast.walk(node):
            if not isinstance(child, ast.Assign) or len(child.targets) != 1:
                continue
            target = child.targets[0]
            if not (
                isinstance(target, ast.Subscript)
                and isinstance(target.value, ast.Name)
                and target.value.id == "signals"
                and isinstance(target.slice, ast.Name)
                and target.slice.id == "code"
            ):
                continue
            call = child.value
            if not isinstance(call, ast.Call):
                continue
            if not (
                isinstance(call.func, ast.Attribute)
                and call.func.attr == "Series"
                and isinstance(call.func.value, ast.Name)
                and call.func.value.id == "pd"
            ):
                continue
            first_arg = call.args[0] if call.args else None
            if not (
                isinstance(first_arg, ast.Constant)
                and isinstance(first_arg.value, (int, float))
                and float(first_arg.value) == 0.0
            ):
                continue
            if any(
                kw.arg == "index"
                and isinstance(kw.value, ast.Attribute)
                and kw.value.attr == "index"
                and isinstance(kw.value.value, ast.Name)
                and kw.value.value.id == "frame"
                for kw in call.keywords
            ):
                return True
    return False


def _backtest_summary(config: Mapping[str, Any]) -> dict[str, Any]:
    return {key: config.get(key) for key in BACKTEST_SUMMARY_KEYS if key in config}


def _scalar_metrics(metrics: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in metrics.items()
        if key != "validation" and _is_scalar(value)
    }


def _json_safe(value: Any) -> Any:
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return value


def _is_scalar(value: Any) -> bool:
    return value is None or isinstance(value, (str, int, float, bool))


def _list_artifacts(run_dir: Path) -> list[dict[str, Any]]:
    candidates: list[Path] = []
    for relative in (Path("config.json"), Path("code/signal_engine.py")):
        path = run_dir / relative
        if path.exists() and path.is_file():
            candidates.append(path)

    artifacts_dir = run_dir / "artifacts"
    if artifacts_dir.exists() and artifacts_dir.is_dir():
        candidates.extend(path for path in artifacts_dir.rglob("*") if path.is_file())

    artifacts = []
    for path in sorted(candidates, key=lambda item: item.relative_to(run_dir).as_posix()):
        artifacts.append(
            {
                "path": path.relative_to(run_dir).as_posix(),
                "size_bytes": path.stat().st_size,
                "sha256": _file_hash(path),
            }
        )
    return artifacts


def _render_markdown(card: Mapping[str, Any]) -> str:
    lines = [
        "# Backtest Run Card",
        "",
        f"Generated: {card['generated_at']}",
        f"Run directory: `{card['run_dir']}`",
        "",
        "## Backtest Summary",
    ]

    backtest = card.get("backtest", {})
    if backtest:
        lines.extend(f"- {key}: {value}" for key, value in backtest.items())
    else:
        lines.append("- No backtest summary fields provided.")

    lines.extend(["", "## Reproducibility"])
    reproducibility = card.get("reproducibility", {})
    lines.append(f"- config_hash: `{reproducibility.get('config_hash', '')}`")
    if "strategy_hash" in reproducibility:
        lines.append(f"- strategy_hash: `{reproducibility['strategy_hash']}`")

    lines.extend(["", "## Evidence Status"])
    lines.append(
        f"- strategy_implementation_status: {card.get('strategy_implementation_status', 'unknown')}"
    )
    lines.append(f"- provenance_valid: {card.get('provenance_valid', False)}")
    lines.append(f"- has_trades: {card.get('has_trades', False)}")
    lines.append(
        f"- statistically_evaluable: {card.get('statistically_evaluable', False)}"
    )
    lines.append(f"- hypothesis_supported: {card.get('hypothesis_supported')}")
    lines.append(f"- run_purpose: {card.get('run_purpose', 'unknown')}")

    lines.extend(["", "## Data Sources"])
    data_sources = card.get("data_sources", [])
    lines.extend(f"- {source}" for source in data_sources) if data_sources else lines.append("- None recorded.")

    lines.extend(["", "## Metrics"])
    metric_values = card.get("metrics", {})
    lines.extend(f"- {key}: {value}" for key, value in metric_values.items()) if metric_values else lines.append("- No scalar metrics recorded.")

    lines.extend(["", "## Validation"])
    if "validation" in card:
        validation = card["validation"]
        if isinstance(validation, Mapping):
            lines.extend(f"- {key}: {value}" for key, value in validation.items())
        else:
            lines.append(f"- {validation}")
    else:
        lines.append("- Not present.")

    warnings = card.get("warnings", [])
    if warnings:
        lines.extend(["", "## Warnings"])
        lines.extend(f"- {warning}" for warning in warnings)

    lines.extend(["", "## Artifacts"])
    artifacts = card.get("artifacts", [])
    if artifacts:
        lines.extend(
            f"- `{artifact['path']}` ({artifact['size_bytes']} bytes, sha256 `{artifact['sha256']}`)"
            for artifact in artifacts
        )
    else:
        lines.append("- None found.")

    return "\n".join(lines) + "\n"
