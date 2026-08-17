"""Fixed backtest entrypoint: read config.json, select loader by source, import signal_engine, run engine.

Supports ``source="auto"`` to route codes to loaders by symbol format.
Supports ``interval`` for bar size (1m/5m/15m/30m/1H/4H/1D, default 1D).
Supports ``engine`` for backtest engine (daily/options, default daily).

Usage: ``python -m backtest.runner <run_dir>``
"""

import ast
import importlib.util
import inspect
import json
import logging
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd
from pydantic import BaseModel, ConfigDict, model_validator, field_validator

from dotenv import load_dotenv
load_dotenv()

from backtest.loaders.registry import (
    FALLBACK_CHAINS,
    LOADER_REGISTRY,
    VALID_SOURCES,
    get_loader_cls_with_fallback,
    resolve_loader,
)
from backtest.loaders.base import NoAvailableSourceError, validate_ohlc
from backtest.source_schema import CRYPTO_SOURCES, MARKET_TO_SOURCE
# Symbol classification lives in ``_market_hooks`` so runner.py and
# composite.py share a single source of truth (audit-2026-05-18 B1+C1+C2).
# ``_detect_market`` is also re-exported here for back-compat with
# ``agent/src/swarm/grounding.py`` and existing tests that import it
# from ``backtest.runner``.
from backtest.engines._market_hooks import (  # noqa: F401  (re-exported)
    _detect_market,
    _detect_submarket,
    _is_china_futures,
)

logger = logging.getLogger(__name__)

def _init_provenance(codes: List[str], requested_source: str) -> dict:
    return {
        code: {
            "requested_source": requested_source,
            "attempted_sources": [],
            "failed_sources": [],
            "successful_source": None,
            "bars": 0,
            "start": None,
            "end": None,
        } for code in codes
    }

def _record_fetch_error(provenance: dict, codes: List[str], source: str, error: Exception | str) -> None:
    error_msg = str(error) or type(error).__name__ if isinstance(error, Exception) else str(error)
    for code in codes:
        if code in provenance:
            if source not in provenance[code]["attempted_sources"]:
                provenance[code]["attempted_sources"].append(source)
            provenance[code]["failed_sources"].append({"source": source, "error": error_msg})

def _record_fetch_success(provenance: dict, source: str, result: dict, codes_attempted: List[str]) -> None:
    for code in codes_attempted:
        if code not in provenance:
            continue
        if source not in provenance[code]["attempted_sources"]:
            provenance[code]["attempted_sources"].append(source)
        
        df = result.get(code)
        if df is not None and not df.empty:
            provenance[code]["successful_source"] = source
            provenance[code]["bars"] = len(df)
            provenance[code]["start"] = df.index[0].strftime("%Y-%m-%d") if hasattr(df.index[0], "strftime") else str(df.index[0])
            provenance[code]["end"] = df.index[-1].strftime("%Y-%m-%d") if hasattr(df.index[-1], "strftime") else str(df.index[-1])
        else:
            provenance[code]["failed_sources"].append({"source": source, "error": "No data returned"})

_VALID_INTERVALS = {"1m", "5m", "15m", "30m", "1H", "4H", "1D"}
_VALID_ENGINES = {"daily", "options"}


class BacktestConfigSchema(BaseModel):
    """Validates backtest config.json before execution."""

    model_config = ConfigDict(extra="allow")

    codes: List[str]
    start_date: str
    end_date: str
    source: str = "auto"
    interval: str = "1D"
    engine: str = "daily"
    fundamental_fields: Optional[Dict[str, List[str]]] = None
    event_feeds: Optional[List[Dict[str, Any]]] = None

    @field_validator("codes")
    @classmethod
    def codes_not_empty(cls, v: List[str]) -> List[str]:
        if not v:
            raise ValueError("codes must be a non-empty list")
        if any(not c.strip() for c in v):
            raise ValueError("codes must not contain empty strings")
        return v

    @field_validator("start_date", "end_date")
    @classmethod
    def valid_date(cls, v: str) -> str:
        try:
            pd.Timestamp(v)
        except Exception:
            raise ValueError(f"invalid date format: {v!r} (expected YYYY-MM-DD)")
        return v

    @field_validator("interval")
    @classmethod
    def valid_interval(cls, v: str) -> str:
        if v not in _VALID_INTERVALS:
            raise ValueError(f"unsupported interval {v!r}, must be one of {_VALID_INTERVALS}")
        return v

    @field_validator("engine")
    @classmethod
    def valid_engine(cls, v: str) -> str:
        if v not in _VALID_ENGINES:
            raise ValueError(f"unsupported engine {v!r}, must be one of {_VALID_ENGINES}")
        return v

    @field_validator("source")
    @classmethod
    def valid_source(cls, v: str) -> str:
        if v not in VALID_SOURCES:
            raise ValueError(f"unsupported source {v!r}, must be one of {VALID_SOURCES}")
        return v

    @field_validator("fundamental_fields")
    @classmethod
    def valid_fundamental_fields(
        cls,
        v: Optional[Dict[str, List[str]]],
    ) -> Optional[Dict[str, List[str]]]:
        if v is None:
            return v
        for table, fields in v.items():
            if not table.strip():
                raise ValueError("fundamental_fields table names must be non-empty strings")
            if any(not field.strip() for field in fields):
                raise ValueError("fundamental_fields field names must be non-empty strings")
        return v

    @field_validator("event_feeds")
    @classmethod
    def valid_event_feeds(cls, v: Optional[List[Dict[str, Any]]]) -> Optional[List[Dict[str, Any]]]:
        if v is None:
            return v
        for entry in v:
            if not isinstance(entry, dict):
                raise ValueError(
                    "each event_feeds entry must be an object with name/route_template/event_type"
                )
            for key in ("name", "route_template", "event_type"):
                if not str(entry.get(key, "")).strip():
                    raise ValueError(f"event_feeds entry missing required field: {key}")
        return v

    @model_validator(mode="after")
    def start_before_end(self) -> "BacktestConfigSchema":
        if pd.Timestamp(self.start_date) > pd.Timestamp(self.end_date):
            raise ValueError(
                f"start_date ({self.start_date}) must be <= end_date ({self.end_date})"
            )
        return self


def _load_module_from_file(file_path: Path, module_name: str):
    """Load a Python module from a file path via importlib.

    Args:
        file_path: Path to the ``.py`` file.
        module_name: Logical module name.

    Returns:
        Loaded module object.
    """
    _validate_signal_engine_source(file_path)
    spec = importlib.util.spec_from_file_location(module_name, file_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def _is_literal_node(node: ast.AST) -> bool:
    """Return whether an AST node is made only from literal values."""
    if isinstance(node, ast.Constant):
        return True
    if isinstance(node, (ast.Tuple, ast.List, ast.Set)):
        return all(_is_literal_node(item) for item in node.elts)
    if isinstance(node, ast.Dict):
        return all(
            (key is None or _is_literal_node(key)) and _is_literal_node(value)
            for key, value in zip(node.keys, node.values)
        )
    return False


def _is_safe_constant_assignment(node: ast.AST) -> bool:
    """Return whether a top-level assignment is literal-only."""
    if isinstance(node, ast.Assign):
        return _is_literal_node(node.value)
    if isinstance(node, ast.AnnAssign):
        return node.value is None or _is_literal_node(node.value)
    return False


def _is_safe_reference(node: ast.AST | None) -> bool:
    """Return whether an annotation/base expression cannot call code."""
    if node is None:
        return True
    if isinstance(node, (ast.Name, ast.Attribute, ast.Constant)):
        return True
    if isinstance(node, ast.Subscript):
        return _is_safe_reference(node.value) and _is_safe_reference(node.slice)
    if isinstance(node, ast.Tuple):
        return all(_is_safe_reference(item) for item in node.elts)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
        return _is_safe_reference(node.left) and _is_safe_reference(node.right)
    return False


def _validate_function_def(node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
    """Reject import-time execution in function definitions."""
    if node.decorator_list:
        raise ValueError(f"Decorators are not allowed on function {node.name!r}")
    for default in [*node.args.defaults, *[d for d in node.args.kw_defaults if d]]:
        if not _is_literal_node(default):
            raise ValueError(f"Non-literal default is not allowed on function {node.name!r}")
    annotations = [node.returns]
    annotations.extend(arg.annotation for arg in node.args.posonlyargs)
    annotations.extend(arg.annotation for arg in node.args.args)
    annotations.extend(arg.annotation for arg in node.args.kwonlyargs)
    annotations.append(node.args.vararg.annotation if node.args.vararg else None)
    annotations.append(node.args.kwarg.annotation if node.args.kwarg else None)
    for annotation in annotations:
        if not _is_safe_reference(annotation):
            raise ValueError(f"Unsafe annotation is not allowed on function {node.name!r}")


def _validate_class_body(node: ast.ClassDef) -> None:
    """Reject import-time execution inside class bodies."""
    if node.decorator_list:
        raise ValueError(f"Decorators are not allowed on class {node.name!r}")
    for base in node.bases:
        if not _is_safe_reference(base):
            raise ValueError(f"Unsafe base class is not allowed on class {node.name!r}")
    if node.keywords:
        raise ValueError(f"Class keywords are not allowed on class {node.name!r}")
    for child in node.body:
        if isinstance(child, ast.Expr) and isinstance(child.value, ast.Constant):
            continue
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
            _validate_function_def(child)
            continue
        if _is_safe_constant_assignment(child):
            continue
        if isinstance(child, ast.Pass):
            continue
        raise ValueError(
            f"Executable class-level statement {type(child).__name__} is not allowed"
        )


def _validate_signal_engine_source(file_path: Path) -> None:
    """Reject import-time executable statements before loading signal_engine.py."""
    try:
        tree = ast.parse(file_path.read_text(encoding="utf-8"), filename=str(file_path))
    except SyntaxError as exc:
        raise ValueError(f"Invalid signal_engine.py syntax: {exc}") from exc

    for node in tree.body:
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant):
            continue
        if isinstance(node, ast.ImportFrom) and node.module == "signal_engine":
            raise ValueError(
                "Circular import: 'from signal_engine import ...' imports the file from itself. "
                "Remove this import — SignalEngine is defined in this same file."
            )
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            continue
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            _validate_function_def(node)
            continue
        if isinstance(node, ast.ClassDef):
            _validate_class_body(node)
            continue
        if _is_safe_constant_assignment(node):
            continue
        raise ValueError(
            f"Executable top-level statement {type(node).__name__} is not allowed"
        )


def _validate_signal_engine_class(engine_cls) -> None:
    """Pre-flight check: SignalEngine can be instantiated with no args and has generate()."""
    sig = inspect.signature(engine_cls.__init__)
    required = [
        p.name for p in sig.parameters.values()
        if p.name != "self" and p.default is inspect.Parameter.empty
        and p.kind not in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD)
    ]
    if required:
        raise ValueError(
            f"SignalEngine.__init__() has required arguments {required}. "
            "All parameters must have default values so the runner can call SignalEngine()."
        )
    if not callable(getattr(engine_cls, "generate", None)):
        raise ValueError(
            "SignalEngine must have a callable 'generate' method. "
            "Expected: def generate(self, data_map: Dict[str, pd.DataFrame]) -> Dict[str, pd.Series]"
        )


# --- Market detection ---
# ``_MARKET_PATTERNS``, ``_detect_market``, ``_is_china_futures``,
# ``_detect_submarket`` are imported from ``_market_hooks`` above and
# re-exported here for back-compat (swarm/grounding.py, tests).

# Back-compat alias for tests/importers that still read this from runner.py.
_MARKET_TO_SOURCE = MARKET_TO_SOURCE


def _detect_source(code: str) -> str:
    """Infer legacy source name from symbol (back-compat for metrics/engine).

    Args:
        code: Ticker / symbol string.

    Returns:
        Source name from the canonical market-to-source schema.
    """
    market = _detect_market(code)
    return MARKET_TO_SOURCE.get(market, "binance")


def _group_codes_by_market(codes: List[str]) -> Dict[str, List[str]]:
    """Group symbols by detected market type.

    Args:
        codes: List of symbol strings.

    Returns:
        Mapping market_type -> list of codes.
    """
    groups: Dict[str, List[str]] = {}
    for code in codes:
        market = _detect_market(code)
        groups.setdefault(market, []).append(code)
    return groups


def _group_codes_by_source(codes: List[str]) -> Dict[str, List[str]]:
    """Group symbols by inferred source (back-compat).

    Args:
        codes: List of symbol strings.

    Returns:
        Mapping source -> list of codes.
    """
    groups: Dict[str, List[str]] = {}
    for code in codes:
        src = _detect_source(code)
        groups.setdefault(src, []).append(code)
    return groups


def _get_loader(source: str):
    """Return a DataLoader class for a source name, with fallback.

    Args:
        source: Source name.

    Returns:
        DataLoader class.
    """
    try:
        return get_loader_cls_with_fallback(source)
    except NoAvailableSourceError:
        raise


def _normalize_codes(codes: List[str], source: str) -> List[str]:
    """Normalize symbol strings for a source.

    Args:
        codes: Raw code list.
        source: Data source.

    Returns:
        Normalized codes.
    """
    if source in CRYPTO_SOURCES:
        return [c.replace("/", "-").upper() for c in codes]
    return codes


def _is_replaced_legacy_source_request(source: str, codes: List[str]) -> bool:
    """Return whether a generated config should be normalized to auto routing.

    Older generated configs pinned ``source`` to providers that are no longer
    part of the canonical source schema. Normalize those requests to registry
    fallback instead of trying to construct that provider directly.
    """
    if source != "tushare":
        return False
    if not codes:
        return False
    return bool({_detect_market(code) for code in codes})


def _instantiate_if_available(source: str):
    """Return an available loader instance for ``source``, or ``None``."""
    loader_cls = LOADER_REGISTRY.get(source)
    if loader_cls is None:
        return None
    try:
        loader = loader_cls()
    except Exception as exc:  # noqa: BLE001 - unavailable provider, try fallback
        logger.debug("loader %s failed to construct: %s", source, exc)
        return None
    try:
        if not loader.is_available():
            return None
    except Exception as exc:  # noqa: BLE001 - unavailable provider, try fallback
        logger.debug("loader %s availability check failed: %s", source, exc)
        return None
    return loader


def _fetch_with_loader(loader, codes: List[str], config: dict, interval: str) -> tuple[dict, List[str]]:
    """Fetch through one loader and return ``(data_map, normalized_codes)``."""
    source = getattr(loader, "name", "unknown")
    normalized_codes = _normalize_codes(codes, source)
    fields = config.get("extra_fields") if source == "binance" else None
    data_map = loader.fetch(
        normalized_codes,
        config.get("start_date", ""),
        config.get("end_date", ""),
        fields=fields,
        interval=interval,
    )
    return data_map, normalized_codes


def _fallback_loader_names_for_codes(codes: List[str]) -> list[str]:
    """Return ordered unique fallback source names for the requested symbols."""
    names: list[str] = []
    for market in _group_codes_by_market(codes):
        for name in FALLBACK_CHAINS.get(market, []):
            if name not in names:
                names.append(name)
    return names


def _fetch_single_source(
    codes: List[str],
    config: dict,
    requested_source: str,
    interval: str,
) -> tuple[dict, str, Any, List[str]]:
    """Fetch data for an explicit source, degrading through market fallback.

    Returns:
        ``(data_map, effective_source, loader, normalized_codes)``.
    """
    source = requested_source
    if _is_replaced_legacy_source_request(source, codes):
        logger.info(
            "source=%s is a replaced legacy OHLCV source; using registry fallback",
            source,
        )
        source = "auto"

    if "_data_source_provenance" not in config:
        config["_data_source_provenance"] = _init_provenance(codes, source)
    provenance = config["_data_source_provenance"]

    if source == "auto":
        data_map, effective_sources = _fetch_auto(codes, config, interval)
        effective_source = effective_sources[0] if len(effective_sources) == 1 else "auto"
        return data_map, effective_source, _AutoLoader(data_map, name=effective_source), codes

    try:
        primary_cls = _get_loader(source)
        primary = primary_cls()
    except Exception as exc:  # noqa: BLE001 - continue with market fallback
        logger.warning("source=%s unavailable: %s", source, exc)
        _record_fetch_error(provenance, codes, source, exc)
        primary = None

    candidates: list[Any] = []
    if primary is not None:
        candidates.append(primary)
    for name in _fallback_loader_names_for_codes(codes):
        if name == source:
            continue
        loader = _instantiate_if_available(name)
        if loader is not None and getattr(loader, "name", None) not in {
            getattr(candidate, "name", None) for candidate in candidates
        }:
            candidates.append(loader)

    last_error: Exception | None = None
    for loader in candidates:
        effective_source = getattr(loader, "name", source)
        try:
            data_map, normalized_codes = _fetch_with_loader(loader, codes, config, interval)
        except Exception as exc:  # noqa: BLE001 - provider failed, try next
            logger.warning("source=%s fetch failed: %s", effective_source, exc)
            _record_fetch_error(provenance, codes, effective_source, exc)
            last_error = exc
            continue
        
        _record_fetch_success(provenance, effective_source, data_map, codes)
        if data_map:
            _stamp_fetch_coverage(provenance, effective_source, data_map, codes, config, interval)
            if not _market_coverage_ok(provenance, codes):
                reason = _coverage_failure_reason(provenance, codes)
                logger.warning("source=%s rejected: %s", effective_source, reason)
                _record_truncated_fetch(provenance, codes, effective_source, reason)
                continue
            if effective_source != requested_source:
                logger.info("Runtime fallback: %s -> %s", requested_source, effective_source)
            return data_map, effective_source, loader, normalized_codes
        logger.warning("source=%s returned no data", effective_source)

    if last_error is not None:
        logger.debug("last loader fetch error", exc_info=last_error)
    return {}, source, _AutoLoader({}, name=source), codes


# --- Main entry ---

def main(run_dir: Path) -> None:
    """Load config, fetch data, run the selected backtest engine.

    With ``source="auto"``, routes each code through the appropriate loader.

    Args:
        run_dir: Run directory containing ``config.json`` and ``code/signal_engine.py``.
            The path is validated against the allowed run roots
            (``VIBE_TRADING_ALLOWED_RUN_ROOTS`` plus the defaults) before any
            file is read so an arbitrary filesystem location cannot be used
            to source ``code/signal_engine.py``.
    """
    # Guard the CLI entry point with the same root whitelist the MCP
    # ``backtest`` tool already uses (src/tools/backtest_tool.py:23). Without
    # this, ``python -m backtest.runner /tmp/attacker_path`` would happily
    # import ``signal_engine.py`` from anywhere on disk; the AST scrubber
    # below blocks executable top-level statements but a method body still
    # runs on instantiation. See ``safe_run_dir`` for the policy.
    from src.tools.path_utils import safe_run_dir
    try:
        run_dir = safe_run_dir(str(run_dir))
    except ValueError as exc:
        print(json.dumps({"error": str(exc)}))
        sys.exit(1)

    config_path = run_dir / "config.json"
    if not config_path.exists():
        print(json.dumps({"error": "config.json not found"}))
        sys.exit(1)

    raw_config = json.loads(config_path.read_text(encoding="utf-8"))
    if str(raw_config.get("source", "")).lower() == "tushare":
        raw_config["source"] = "auto"

    # Validate config schema
    try:
        BacktestConfigSchema(**raw_config)
    except Exception as exc:
        errors = str(exc)
        print(json.dumps({"error": f"Invalid config: {errors}"}))
        sys.exit(1)

    config = raw_config
    source = config.get("source", "auto")
    codes = config.get("codes", [])

    # Load signal engine
    signal_path = run_dir / "code" / "signal_engine.py"
    if not signal_path.exists():
        print(json.dumps({"error": "code/signal_engine.py not found"}))
        sys.exit(1)

    # Refuse to execute a strategy body that is still byte-identical to the
    # scaffold. A smoke body is not a hypothesis; see write_receipt.py.
    from write_receipt import (
        assert_not_scaffold,
        detect_silencer_patterns,
        ScaffoldNeverReplacedError,
        STRATEGY_PROVENANCE_FILENAME,
    )

    try:
        signal_engine_sha256 = assert_not_scaffold(run_dir)
    except ScaffoldNeverReplacedError as exc:
        print(json.dumps({"error": str(exc)}))
        sys.exit(1)

    # Lint, not a gate: real code that catches a schema mismatch and
    # degrades to NaN instead of surfacing it survives this far (hash
    # differs from scaffold, no exception escapes) — flag it in the run
    # card so it can't pass as robustness unnoticed.
    strategy_lint_warnings = detect_silencer_patterns(signal_path.read_text(encoding="utf-8"))

    try:
        signal_module = _load_module_from_file(signal_path, "signal_engine")
    except ValueError as exc:
        # Source-level AST validation (circular self-import, unsafe imports,
        # decorators, top-level statements) raises ValueError. Surface it as a
        # clean JSON envelope instead of a raw traceback so the agent gets an
        # actionable message.
        print(json.dumps({"error": f"SignalEngine source error: {exc}"}))
        sys.exit(1)
    engine_cls: Any | None = getattr(signal_module, "SignalEngine", None)
    if engine_cls is None:
        print(json.dumps({"error": "SignalEngine class not found in signal_engine.py"}))
        sys.exit(1)
    try:
        _validate_signal_engine_class(engine_cls)
    except ValueError as exc:
        print(json.dumps({"error": f"SignalEngine interface error: {exc}"}))
        sys.exit(1)

    # Data: auto split vs single loader
    interval = config.get("interval", "1D")

    data_map, effective_source, loader, effective_codes = _fetch_single_source(
        codes,
        config,
        source,
        interval,
    )
    codes = effective_codes
    config["codes"] = codes
    config["_requested_source"] = source
    config["source"] = effective_source

    if data_map and len(data_map) < len(codes):
        missing = set(codes) - set(data_map.keys())
        logger.warning(
            "source=%s returned data for %d/%d symbols; missing: %s",
            effective_source, len(data_map), len(codes), missing,
        )

    # Loader-boundary OHLC sanity for every source, centralized at the one
    # point all fetch paths converge (auto / single / runtime fallback).
    data_map = _sanitize_data_map(data_map)
    if not data_map:
        try:
            from backtest.run_card import write_run_card
            write_run_card(run_dir, config, {"status": "error", "error": "No data fetched"})
        except Exception:
            pass
        print(json.dumps({"error": "No data fetched"}))
        sys.exit(1)

    if effective_source == "auto":
        config["_run_card_effective_sources"] = sorted(_group_codes_by_source(codes))
    else:
        config["_run_card_effective_sources"] = [effective_source]

    # Engine
    engine_type = config.get("engine", "daily")
    signal_engine = engine_cls()

    # Annualization bars
    primary_source = _detect_primary_source(codes, effective_source)
    from backtest.metrics import calc_bars_per_year
    # Cross-market: use calendar-day annualization (bars_per_year=None)
    market_types = {_detect_market(c) for c in codes}
    if len(market_types) > 1:
        bars_per_year = None
    else:
        bars_per_year = calc_bars_per_year(interval, primary_source)

    # Auto mode: wrap preloaded data in a dummy loader
    if effective_source == "auto":
        loader = _AutoLoader(data_map)
    if engine_type == "options":
        from backtest.engines.options_portfolio import run_options_backtest
        run_options_backtest(config, loader, signal_engine, run_dir, bars_per_year=bars_per_year or 252)
    else:
        market_engine = _create_market_engine(primary_source, config, codes)
        market_engine.run_backtest(config, loader, signal_engine, run_dir, bars_per_year=bars_per_year or 252)

    # Stamp the strategy body's proven hash into the run card. write_run_card()
    # (called inside the engine above) has no visibility into assert_not_scaffold's
    # result, so the card is patched here once it's on disk.
    run_card_path = run_dir / "run_card.json"
    if run_card_path.exists():
        try:
            card = json.loads(run_card_path.read_text(encoding="utf-8"))
            card["signal_engine_sha256"] = signal_engine_sha256
            card["strategy_lint_warnings"] = strategy_lint_warnings
            provenance_marker = signal_path.parent / STRATEGY_PROVENANCE_FILENAME
            if provenance_marker.exists():
                try:
                    card["strategy_provenance"] = json.loads(provenance_marker.read_text(encoding="utf-8"))
                except (json.JSONDecodeError, OSError):
                    pass
            run_card_path.write_text(
                json.dumps(card, ensure_ascii=False, indent=2, sort_keys=True, default=str) + "\n",
                encoding="utf-8",
            )
        except (json.JSONDecodeError, OSError):
            pass


def _create_market_engine(source: str, config: dict, codes: List[str]):
    """Create the appropriate market engine based on data source and market type.

    Routing priority:
      1. Detect market type from symbol patterns (futures, forex, etc.)
      2. Fall back to source-based routing (okx->crypto, akshare->china_a, etc.)

    Args:
        source: Data source (binance/bybit/cmc/akshare/yfinance/akshare/cctx).
        config: Backtest configuration.
        codes: Instrument codes.

    Returns:
        BaseEngine subclass instance.
    """
    # Detect dominant market type from codes
    markets = {_detect_market(c) for c in codes} if codes else set()

    # Cross-market -> CompositeEngine
    if len(markets) > 1:
        from backtest.engines.composite import CompositeEngine
        return CompositeEngine(config, codes)

    # Futures routing (Wave 2)
    if "futures" in markets:
        # Distinguish China vs global futures by exchange suffix
        if any(_is_china_futures(c) for c in codes):
            from backtest.engines.china_futures import ChinaFuturesEngine
            return ChinaFuturesEngine(config)
        from backtest.engines.global_futures import GlobalFuturesEngine
        return GlobalFuturesEngine(config)

    # Forex routing (Wave 2)
    if "forex" in markets:
        from backtest.engines.forex import ForexEngine
        return ForexEngine(config)

    if "a_share" in markets:
        from backtest.engines.china_a import ChinaAEngine
        return ChinaAEngine(config)

    if markets & {"us_equity", "hk_equity"}:
        from backtest.engines.global_equity import GlobalEquityEngine
        market = _detect_submarket(codes)
        return GlobalEquityEngine(config, market=market)

    if "crypto" in markets:
        from backtest.engines.crypto import CryptoEngine
        return CryptoEngine(config)

    # Original routing (Wave 1)
    if source in ("binance", "bybit", "cmc", "akshare", "okx", "ccxt"):
        from backtest.engines.crypto import CryptoEngine
        return CryptoEngine(config)
    elif source in ("binance", "bybit", "cmc", "akshare", "okx", "ccxt"):
        if markets & {"us_equity", "hk_equity"}:
            from backtest.engines.global_equity import GlobalEquityEngine
            market = _detect_submarket(codes)
            return GlobalEquityEngine(config, market=market)
        from backtest.engines.china_a import ChinaAEngine
        return ChinaAEngine(config)
    elif source == "yfinance":
        from backtest.engines.global_equity import GlobalEquityEngine
        market = _detect_submarket(codes)
        return GlobalEquityEngine(config, market=market)
    else:
        from backtest.engines.crypto import CryptoEngine
        return CryptoEngine(config)


def _detect_primary_source(codes: List[str], source: str) -> str:
    """Pick primary source for annualization (e.g. bars per year).

    Args:
        codes: All symbols.
        source: Config ``source`` field.

    Returns:
        Dominant source name.
    """
    if source != "auto":
        return source
    groups = _group_codes_by_source(codes)
    if len(groups) == 1:
        return list(groups.keys())[0]
    # Mixed: use the source with the most symbols
    return max(groups, key=lambda s: len(groups[s]))


# ---------------------------------------------------------------------------
# Data window coverage receipts
# ---------------------------------------------------------------------------

from backtest.coverage import (  # shared with benchmark.py
    COVERAGE_FLOOR,
    coverage_receipt_for_frame,
    expected_bar_count,
    interval_to_timedelta,
)

# Backward-compatible aliases for older tests/imports.
_interval_to_timedelta = interval_to_timedelta
_expected_bar_count = expected_bar_count
_coverage_receipt_for_frame = coverage_receipt_for_frame


def _stamp_fetch_coverage(
    provenance: dict,
    source: str,
    data_map: dict,
    codes: list[str],
    config: dict,
    interval: str,
) -> None:
    """Stamp requested/delivered window coverage per symbol."""
    requested_start = str(config.get("start_date", ""))
    requested_end = str(config.get("end_date", ""))

    for code in codes:
        rec = provenance.setdefault(
            code,
            {
                "requested_source": config.get("source", "auto"),
                "attempted_sources": [],
                "failed_sources": [],
                "successful_source": None,
                "bars": 0,
            },
        )
        receipt = _coverage_receipt_for_frame(
            data_map.get(code),
            requested_start=requested_start,
            requested_end=requested_end,
            interval=interval,
        )
        rec.update(receipt)
        rec["bars"] = receipt["delivered_bars"]
        if not receipt["coverage_ok"] and rec.get("successful_source") == source:
            # Source returned bars, but not the requested window. It is not a true success.
            rec["successful_source"] = None


def _market_coverage_ok(provenance: dict, codes: list[str]) -> bool:
    """True only when every requested symbol has acceptable window coverage."""
    return all(bool(provenance.get(code, {}).get("coverage_ok")) for code in codes)


def _coverage_failure_reason(provenance: dict, codes: list[str]) -> str:
    """Compact reason for treating a non-empty fetch as failed/truncated."""
    parts = []
    for code in codes:
        rec = provenance.get(code, {})
        if rec.get("coverage_ok"):
            continue
        reason = rec.get("window_integrity_error") or "coverage_not_ok"
        parts.append(f"{code}: {reason}")
    return "truncated window; " + " | ".join(parts[:5])


def _record_truncated_fetch(provenance: dict, codes: list[str], source: str, reason: str) -> None:
    """Record a successful-but-wrong-window fetch as a degraded failure."""
    for code in codes:
        rec = provenance.setdefault(
            code,
            {
                "requested_source": "auto",
                "attempted_sources": [],
                "failed_sources": [],
                "successful_source": None,
                "bars": 0,
            },
        )
        attempted = rec.setdefault("attempted_sources", [])
        if source not in attempted:
            attempted.append(source)
        failures = rec.setdefault("failed_sources", [])
        failures.append({"source": source, "error": reason, "kind": "truncated"})
        if rec.get("successful_source") == source and not rec.get("coverage_ok"):
            rec["successful_source"] = None


def _fetch_auto(codes: List[str], config: dict, interval: str = "1D") -> tuple[dict, list[str]]:
    """Auto mode: route each market group through fallback chain.

    A provider is accepted only if it returns data for the requested window.
    A non-empty but truncated fetch is recorded as ``kind=truncated`` and the
    next source is tried. Silent window truncation is a coverage silencer.
    """
    market_groups = _group_codes_by_market(codes)
    merged = {}
    effective_sources: list[str] = []
    start_date = config.get("start_date", "")
    end_date = config.get("end_date", "")

    if "_data_source_provenance" not in config:
        config["_data_source_provenance"] = _init_provenance(codes, "auto")
    provenance = config["_data_source_provenance"]

    for market, market_codes in market_groups.items():
        candidates = []

        # Prefer the explicit source queue. This lets us witness each attempted
        # source instead of accepting the first registry provider blindly.
        for name in FALLBACK_CHAINS.get(market, []):
            loader = _instantiate_if_available(name)
            if loader is None:
                _record_fetch_error(provenance, market_codes, name, "Loader unavailable")
                continue
            if getattr(loader, "name", name) not in {getattr(c, "name", None) for c in candidates}:
                candidates.append(loader)

        # Registry fallback if the chain is empty/unavailable.
        if not candidates:
            try:
                loader = resolve_loader(market)
                candidates.append(loader)
            except NoAvailableSourceError as exc:
                legacy_src = MARKET_TO_SOURCE.get(market, "binance")
                logger.warning("Fallback chain failed for %s: %s — trying %s", market, exc, legacy_src)
                _record_fetch_error(provenance, market_codes, market, exc)
                loader = _instantiate_if_available(legacy_src)
                if loader is not None:
                    candidates.append(loader)

        result = {}
        src_name = None

        for loader in candidates:
            src_name = getattr(loader, "name", "unknown")
            normalized_codes = _normalize_codes(market_codes, src_name)
            fields = config.get("extra_fields") if src_name == "binance" else None

            try:
                result = loader.fetch(
                    normalized_codes,
                    start_date,
                    end_date,
                    fields=fields,
                    interval=interval,
                )
            except Exception as exc:  # noqa: BLE001 - provider failed, try next
                logger.warning("source=%s fetch failed for %s: %s", src_name, market, exc)
                _record_fetch_error(provenance, market_codes, src_name, exc)
                result = {}
                continue

            if not result:
                logger.warning("source=%s returned no data for %s", src_name, market)
                _record_fetch_error(provenance, market_codes, src_name, "returned no data")
                continue

            _record_fetch_success(provenance, src_name, result, market_codes)
            _stamp_fetch_coverage(provenance, src_name, result, market_codes, config, interval)

            if _market_coverage_ok(provenance, market_codes):
                break

            reason = _coverage_failure_reason(provenance, market_codes)
            logger.warning("source=%s rejected for %s: %s", src_name, market, reason)
            _record_truncated_fetch(provenance, market_codes, src_name, reason)
            result = {}
            src_name = None

        if result and src_name is not None:
            merged.update(result)
            if src_name not in effective_sources:
                effective_sources.append(src_name)

    return merged, effective_sources

def _sanitize_data_map(data_map: dict) -> dict:
    """Drop structurally-invalid OHLC bars from every fetched frame.

    Each loader only drops NaN rows, so a bar that violates the OHLC
    invariants (``high < low``, a non-positive price, or a high/low that fails
    to bracket open/close) can still reach the backtest and surface as NaN/inf
    metrics. Applying :func:`validate_ohlc` here — the single point every
    fetched map converges through — guards every source uniformly (``auto``,
    single-source, runtime fallback, and any future loader), so the per-loader
    checks no longer have to be added one at a time.

    Args:
        data_map: ``code -> DataFrame`` map as returned by a loader fetch.

    Returns:
        The same mapping with each frame's invalid bars removed.
    """
    return {code: validate_ohlc(frame) for code, frame in data_map.items()}


class _AutoLoader:
    """Dummy loader for auto mode: returns pre-fetched data maps.

    Carries ``name`` (the actual resolved provider, e.g. ``"tencent"``) so a
    caller reading ``loader.name`` after an auto/fallback resolution sees
    which source really served the data, not just the literal string
    ``"auto"`` the request was made with.
    """

    def __init__(self, data_map: dict, name: str = "auto"):
        self._data = data_map
        self.name = name

    def fetch(self, codes, start_date, end_date, fields=None, interval="1D"):
        """Return preloaded rows for requested codes."""
        return {c: df for c, df in self._data.items() if c in codes}


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python -m backtest.runner <run_dir>")
        sys.exit(1)
    main(Path(sys.argv[1]))
