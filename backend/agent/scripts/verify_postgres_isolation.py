#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path
from uuid import UUID

agent_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(agent_dir))

from paper_postgres import PaperPostgres, WorkerIdentity


def main() -> None:
    manifest = json.loads((agent_dir / "config" / "paper_accounts.json").read_text(encoding="utf-8"))
    stores: list[PaperPostgres] = []
    try:
        for row in manifest["accounts"]:
            identity = WorkerIdentity(
                account_id=UUID(row["account_id"]), strategy_id=row["strategy_id"],
                worker_id=row["worker_id"], timeframe=row["timeframe"],
                mode=row["mode"], leverage=int(row["leverage"]),
            )
            stores.append(PaperPostgres(identity, manifest["database_dsn"]))
            print(f"PASS  {identity.worker_id} database identity and writer lease")

        try:
            PaperPostgres(stores[0].identity, manifest["database_dsn"])
        except RuntimeError as exc:
            if "active owner" not in str(exc):
                raise
            print("PASS  duplicate worker ownership rejected")
        else:
            raise AssertionError("duplicate worker ownership was accepted")
    finally:
        for store in stores:
            store.close()


if __name__ == "__main__":
    main()
