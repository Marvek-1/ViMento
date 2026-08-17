#!/usr/bin/env python3
"""Vibe-Trading repair utility: install, sync, and status for IdimIkang ingestion."""
from __future__ import annotations

import json
import os
import shutil
import sqlite3
import subprocess
import sys
import urllib.request
from pathlib import Path
from urllib.error import HTTPError, URLError

REPO = Path("/home/idona/MoStar/_apps/financial/Vibe-Trading-main/Vibe-Trading-main")
AGENT = REPO / "agent"
DATA_DIR = AGENT / "data"
JOURNAL_DB = DATA_DIR / "vibe_signal_journal.sqlite3"
ENV_FILE = AGENT / ".env"
API_PORT = 8000
API_BASE = f"http://127.0.0.1:{API_PORT}"
SYNC_ENDPOINT = f"{API_BASE}/data-sources/idimikang/sync"
EVENTS_ENDPOINT = f"{API_BASE}/data-sources/idimikang/events"

SYSTEMD_DIR = Path.home() / ".config" / "systemd" / "user"
API_SERVICE = SYSTEMD_DIR / "vibe-trading-api.service"
SYNC_SERVICE = SYSTEMD_DIR / "vibe-trading-sync.service"
SYNC_TIMER = SYSTEMD_DIR / "vibe-trading-sync.timer"


def _run(cmd: list[str], check: bool = True) -> subprocess.CompletedProcess:
    print("$", " ".join(cmd))
    return subprocess.run(cmd, capture_output=True, text=True, check=check)


def _api_url() -> str:
    # Prefer the v2 name, fall back to the alias
    env = _read_env()
    return env.get("IDIMIKANG_API_URL") or env.get("IDIM_API_URL") or "http://127.0.0.1:41050/api"


def _read_env() -> dict[str, str]:
    out: dict[str, str] = {}
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                out[k.strip()] = v.strip()
    return out


def _ensure_env() -> None:
    """Back up .env and set the required keys without enabling trading."""
    if ENV_FILE.exists():
        shutil.copy(ENV_FILE, ENV_FILE.with_suffix(".env.repair-backup"))
    lines = ENV_FILE.read_text().splitlines() if ENV_FILE.exists() else []
    keys = {k.split("=")[0].strip() for k in lines if "=" in k and not k.strip().startswith("#")}
    additions = []
    if "IDIMIKANG_API_URL" not in keys:
        additions.append("IDIMIKANG_API_URL=http://127.0.0.1:41050/api")
    if "IDIM_API_URL" not in keys:
        additions.append("IDIM_API_URL=http://127.0.0.1:41050")
    if "TRADING_MODE" not in keys:
        additions.append("TRADING_MODE=paper")
    if "ALLOW_AUTO_EXECUTION" not in keys:
        additions.append("ALLOW_AUTO_EXECUTION=false")
    if "REQUIRE_MANUAL_APPROVAL" not in keys:
        additions.append("REQUIRE_MANUAL_APPROVAL=true")
    if "MAX_POSITION_USD" not in keys:
        additions.append("MAX_POSITION_USD=5")
    if "MAX_DAILY_LOSS_USD" not in keys:
        additions.append("MAX_DAILY_LOSS_USD=5")
    if additions:
        with open(ENV_FILE, "a") as f:
            f.write("\n# --- appended by vibe_repair.py ---\n")
            for a in additions:
                f.write(a + "\n")


def _init_journal() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(JOURNAL_DB)
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS emitted (
            signal_id TEXT PRIMARY KEY NOT NULL,
            symbol TEXT NOT NULL,
            side TEXT NOT NULL,
            score REAL,
            timestamp TEXT NOT NULL,
            regime TEXT,
            signal_family TEXT,
            raw_json TEXT NOT NULL,
            inserted_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS resolved (
            signal_id TEXT PRIMARY KEY NOT NULL,
            symbol TEXT NOT NULL,
            side TEXT NOT NULL,
            outcome TEXT NOT NULL,
            r_multiple REAL,
            resolved_at TEXT NOT NULL,
            raw_json TEXT NOT NULL,
            inserted_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS coverage (
            metric TEXT PRIMARY KEY NOT NULL,
            value INTEGER NOT NULL,
            updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE TRIGGER IF NOT EXISTS prevent_emitted_update
            BEFORE UPDATE ON emitted
        BEGIN
            SELECT CASE WHEN 1 THEN RAISE(ABORT, 'emitted is append-only') END;
        END;
        CREATE TRIGGER IF NOT EXISTS prevent_emitted_delete
            BEFORE DELETE ON emitted
        BEGIN
            SELECT CASE WHEN 1 THEN RAISE(ABORT, 'emitted is append-only') END;
        END;
        CREATE TRIGGER IF NOT EXISTS prevent_resolved_update
            BEFORE UPDATE ON resolved
        BEGIN
            SELECT CASE WHEN 1 THEN RAISE(ABORT, 'resolved is append-only') END;
        END;
        CREATE TRIGGER IF NOT EXISTS prevent_resolved_delete
            BEFORE DELETE ON resolved
        BEGIN
            SELECT CASE WHEN 1 THEN RAISE(ABORT, 'resolved is append-only') END;
        END;
        """
    )
    conn.commit()
    conn.close()


def _systemd_unit(service: Path, content: str) -> None:
    SYSTEMD_DIR.mkdir(parents=True, exist_ok=True)
    service.write_text(content)


def _install_systemd() -> None:
    api = """[Unit]
Description=Vibe-Trading API server
After=network.target

[Service]
Type=simple
WorkingDirectory=/home/idona/MoStar/_apps/financial/Vibe-Trading-main/Vibe-Trading-main/agent
ExecStart=/home/idona/MoStar/_apps/financial/Vibe-Trading-main/Vibe-Trading-main/.venv/bin/uvicorn api_server:app --host 127.0.0.1 --port 8000
Restart=always
RestartSec=10

[Install]
WantedBy=default.target
"""
    sync = """[Unit]
Description=Vibe-Trading IdimIkang sync
After=vibe-trading-api.service

[Service]
Type=oneshot
WorkingDirectory=/home/idona/MoStar/_apps/financial/Vibe-Trading-main/Vibe-Trading-main/agent
ExecStart=/home/idona/MoStar/_apps/financial/Vibe-Trading-main/Vibe-Trading-main/.venv/bin/python /home/idona/MoStar/_apps/financial/Vibe-Trading-main/Vibe-Trading-main/agent/vibe_repair.py sync
"""
    timer = """[Unit]
Description=Vibe-Trading IdimIkang sync timer

[Timer]
OnBootSec=1m
OnUnitActiveSec=5m

[Install]
WantedBy=timers.target
"""
    _systemd_unit(API_SERVICE, api)
    _systemd_unit(SYNC_SERVICE, sync)
    _systemd_unit(SYNC_TIMER, timer)
    _run(["loginctl", "enable-linger", os.environ.get("USER", "idona")], check=False)
    _run(["systemctl", "--user", "daemon-reload"])
    _run(["systemctl", "--user", "enable", "--now", "vibe-trading-api.service"])
    _run(["systemctl", "--user", "enable", "--now", "vibe-trading-sync.timer"])


def _api_request(method: str, url: str, data: bytes | None = None, timeout: int = 30) -> bytes:
    req = urllib.request.Request(url, data=data, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read()
    except HTTPError as e:
        return e.read()
    except URLError as e:
        raise RuntimeError(f"{url}: {e}")


def _sync_store() -> dict:
    """Call the Vibe API sync endpoint to populate the IdimIkang store."""
    body = _api_request("POST", SYNC_ENDPOINT, data=b"{}")
    return json.loads(body)


def _fetch_api_signals() -> list[dict]:
    """Fetch raw signals from the IdimIkang API."""
    url = _api_url()
    body = _api_request("GET", url + "/signals")
    data = json.loads(body)
    return data.get("signals", data if isinstance(data, list) else [])


def _journal_signals(signals: list[dict]) -> tuple[int, int]:
    """Insert raw signals into the append-only journal, separating emitted/resolved."""
    conn = sqlite3.connect(JOURNAL_DB)
    cur = conn.cursor()
    emitted = 0
    resolved = 0
    for s in signals:
        sid = s.get("signal_id") or s.get("id")
        if not sid:
            continue
        raw = json.dumps(s, sort_keys=True, default=str)
        cur.execute(
            "INSERT OR IGNORE INTO emitted (signal_id, symbol, side, score, timestamp, regime, signal_family, raw_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                sid,
                (s.get("pair") or s.get("symbol") or "").upper(),
                (s.get("side") or "").upper(),
                s.get("score"),
                s.get("ts") or s.get("timestamp") or s.get("created_at"),
                s.get("regime"),
                s.get("signal_family"),
                raw,
            ),
        )
        if cur.rowcount:
            emitted += 1
        if s.get("outcome"):
            cur.execute(
                "INSERT OR IGNORE INTO resolved (signal_id, symbol, side, outcome, r_multiple, resolved_at, raw_json) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    sid,
                    (s.get("pair") or s.get("symbol") or "").upper(),
                    (s.get("side") or "").upper(),
                    s.get("outcome"),
                    s.get("r_multiple"),
                    s.get("updated_at") or s.get("ts"),
                    raw,
                ),
            )
            if cur.rowcount:
                resolved += 1
    # coverage counters
    cur.execute("INSERT OR REPLACE INTO coverage (metric, value, updated_at) VALUES ('emitted', ?, datetime('now'))", (cur.execute("SELECT COUNT(*) FROM emitted").fetchone()[0],))
    cur.execute("INSERT OR REPLACE INTO coverage (metric, value, updated_at) VALUES ('resolved', ?, datetime('now'))", (cur.execute("SELECT COUNT(*) FROM resolved").fetchone()[0],))
    conn.commit()
    conn.close()
    return emitted, resolved


def _ensure_api_running() -> None:
    """Start the API if it is not up."""
    try:
        urllib.request.urlopen(f"{API_BASE}/data-sources/idimikang/status", timeout=2)
    except Exception:
        _run(["systemctl", "--user", "start", "vibe-trading-api.service"])


def cmd_install() -> int:
    _ensure_env()
    _init_journal()
    _install_systemd()
    print("Install complete. Run `python3 agent/vibe_repair.py status` to verify.")
    return cmd_status()


def cmd_sync() -> int:
    _ensure_api_running()
    try:
        store_result = _sync_store()
    except Exception as e:
        print("Store sync failed:", e)
        store_result = {}
    signals = _fetch_api_signals()
    emitted, resolved = _journal_signals(signals)
    print(json.dumps({
        "store_sync": store_result,
        "api_signals": len(signals),
        "journal_emitted": emitted,
        "journal_resolved": resolved,
    }, indent=2, default=str))
    return 0


def cmd_status() -> int:
    api = _run(["systemctl", "--user", "is-active", "vibe-trading-api.service"], check=False)
    timer = _run(["systemctl", "--user", "is-active", "vibe-trading-sync.timer"], check=False)
    env = _read_env()
    observer = env.get("TRADING_MODE", "") == "paper" or env.get("ALLOW_AUTO_EXECUTION", "") != "true"
    execution_allowed = env.get("ALLOW_AUTO_EXECUTION", "").lower() == "true"
    store_count = 0
    try:
        import sqlite3
        home = Path.home()
        db = home / ".vibe-trading" / "idimikang.db"
        if db.exists():
            conn = sqlite3.connect(db)
            store_count = conn.execute("SELECT COUNT(*) FROM idimikang_events").fetchone()[0]
            conn.close()
    except Exception as e:
        print("store count error:", e)
    journal_counts = {}
    if JOURNAL_DB.exists():
        conn = sqlite3.connect(JOURNAL_DB)
        journal_counts["emitted"] = conn.execute("SELECT COUNT(*) FROM emitted").fetchone()[0]
        journal_counts["resolved"] = conn.execute("SELECT COUNT(*) FROM resolved").fetchone()[0]
        conn.close()
    print(f"vibe-trading-api.service: {api.stdout.strip() or 'inactive'}")
    print(f"vibe-trading-sync.timer: {timer.stdout.strip() or 'inactive'}")
    print(f"observer_only: {observer}")
    print(f"execution_allowed: {execution_allowed}")
    print(f"store.event_count: {store_count}")
    print(f"journal.emitted_signals: {journal_counts.get('emitted', 0)}")
    print(f"journal.resolved_signals: {journal_counts.get('resolved', 0)}")
    return 0 if api.stdout.strip() == "active" and store_count > 0 else 1


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: vibe_repair.py install|sync|status")
        return 1
    cmd = sys.argv[1]
    if cmd == "install":
        return cmd_install()
    if cmd == "sync":
        return cmd_sync()
    if cmd == "status":
        return cmd_status()
    print("unknown command:", cmd)
    return 1


if __name__ == "__main__":
    sys.exit(main())
