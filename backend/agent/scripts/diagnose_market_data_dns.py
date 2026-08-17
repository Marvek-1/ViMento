#!/usr/bin/env python3
"""Read-only market-data connectivity probe.

Tests DNS resolution and public Binance HTTP access through:
1. socket.getaddrinfo
2. urllib
3. requests, when installed
4. ccxt public ping and ticker paths, when installed

No credentials are loaded and no orders are submitted.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import socket
import sys
import time
import urllib.request
from datetime import datetime, timezone
from typing import Any, Callable


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def attempt(operation: Callable[[], Any]) -> dict[str, Any]:
    started = time.monotonic()

    try:
        value = operation()
        return {
            "ok": True,
            "elapsed_ms": round((time.monotonic() - started) * 1000, 2),
            "value": value,
        }
    except Exception as exc:
        return {
            "ok": False,
            "elapsed_ms": round((time.monotonic() - started) * 1000, 2),
            "error_type": type(exc).__name__,
            "error": str(exc),
        }


def resolve(host: str, port: int) -> list[str]:
    addresses = socket.getaddrinfo(
        host,
        port,
        family=socket.AF_UNSPEC,
        type=socket.SOCK_STREAM,
    )
    return sorted({entry[4][0] for entry in addresses})


def urllib_ping(url: str, timeout: float) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "vibe-trading-connectivity-probe/1"},
    )

    with urllib.request.urlopen(request, timeout=timeout) as response:
        return {
            "status": response.status,
            "final_url": response.geturl(),
        }


def build_requests_probe(
    url: str,
    timeout: float,
) -> tuple[bool, Callable[[], dict[str, Any]] | None]:
    try:
        import requests
    except ImportError:
        return False, None

    session = requests.Session()

    def probe() -> dict[str, Any]:
        response = session.get(url, timeout=(timeout, timeout))
        return {
            "status": response.status_code,
            "final_url": response.url,
        }

    return True, probe


def build_ccxt_probes(
    symbol: str,
    timeout_ms: int,
) -> tuple[
    bool,
    Callable[[], Any] | None,
    Callable[[], Any] | None,
]:
    try:
        import ccxt
    except ImportError:
        return False, None, None

    exchange = ccxt.binance(
        {
            "enableRateLimit": True,
            "timeout": timeout_ms,
        }
    )

    def ping() -> Any:
        return exchange.public_get_ping()

    def ticker() -> dict[str, Any]:
        result = exchange.fetch_ticker(symbol)
        return {
            "symbol": result.get("symbol"),
            "last": result.get("last"),
            "timestamp": result.get("timestamp"),
        }

    return True, ping, ticker


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--context", default="unspecified")
    parser.add_argument("--host", default="api.binance.com")
    parser.add_argument(
        "--url",
        default="https://api.binance.com/api/v3/ping",
    )
    parser.add_argument("--symbol", default="BTC/USDT")
    parser.add_argument("--iterations", type=int, default=20)
    parser.add_argument("--interval", type=float, default=5.0)
    parser.add_argument("--timeout", type=float, default=10.0)
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    requests_available, requests_probe = build_requests_probe(
        args.url,
        args.timeout,
    )
    ccxt_available, ccxt_ping, ccxt_ticker = build_ccxt_probes(
        args.symbol,
        int(args.timeout * 1000),
    )

    successes = {
        "dns": 0,
        "urllib": 0,
        "requests": 0,
        "ccxt_ping": 0,
        "ccxt_ticker": 0,
    }

    metadata = {
        "event": "probe_start",
        "timestamp": utc_now(),
        "context": args.context,
        "python": sys.executable,
        "python_version": platform.python_version(),
        "platform": platform.platform(),
        "pid": os.getpid(),
        "host": args.host,
        "url": args.url,
        "symbol": args.symbol,
        "requests_available": requests_available,
        "ccxt_available": ccxt_available,
        "proxy_variables_present": {
            name: name in os.environ
            for name in (
                "HTTP_PROXY",
                "HTTPS_PROXY",
                "ALL_PROXY",
                "NO_PROXY",
                "http_proxy",
                "https_proxy",
                "all_proxy",
                "no_proxy",
            )
        },
    }
    print(json.dumps(metadata, sort_keys=True), flush=True)

    for iteration in range(1, args.iterations + 1):
        record: dict[str, Any] = {
            "event": "probe_iteration",
            "timestamp": utc_now(),
            "context": args.context,
            "iteration": iteration,
        }

        record["dns"] = attempt(lambda: resolve(args.host, 443))
        record["urllib"] = attempt(
            lambda: urllib_ping(args.url, args.timeout)
        )

        if requests_probe is not None:
            record["requests"] = attempt(requests_probe)
        else:
            record["requests"] = {"skipped": "requests not installed"}

        if ccxt_ping is not None and ccxt_ticker is not None:
            record["ccxt_ping"] = attempt(ccxt_ping)
            record["ccxt_ticker"] = attempt(ccxt_ticker)
        else:
            record["ccxt_ping"] = {"skipped": "ccxt not installed"}
            record["ccxt_ticker"] = {"skipped": "ccxt not installed"}

        for key in successes:
            if record.get(key, {}).get("ok") is True:
                successes[key] += 1

        print(json.dumps(record, sort_keys=True), flush=True)

        if iteration < args.iterations:
            time.sleep(args.interval)

    summary = {
        "event": "probe_summary",
        "timestamp": utc_now(),
        "context": args.context,
        "iterations": args.iterations,
        "successes": successes,
    }
    print(json.dumps(summary, sort_keys=True), flush=True)

    if successes["dns"] == 0:
        return 2
    if successes["urllib"] == 0:
        return 3
    if ccxt_available and successes["ccxt_ticker"] == 0:
        return 4
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
