#!/usr/bin/env python3
from __future__ import annotations

import shutil
import sqlite3
import tempfile
from datetime import date
from pathlib import Path

from loancopilot import business
from loancopilot.config import PRIVATE_ROOT


def main() -> int:
    seed = PRIVATE_ROOT / "dbsqlite" / "seed" / "mtm_18235662.sqlite"
    if not seed.is_file():
        raise FileNotFoundError(f"Seed MTM lipsă: {seed}")

    with tempfile.TemporaryDirectory(prefix="loancopilot_interest_") as temp_dir:
        test_db = Path(temp_dir) / "test.sqlite"
        shutil.copy2(seed, test_db)
        with sqlite3.connect(test_db) as con:
            con.row_factory = sqlite3.Row
            con.execute("PRAGMA foreign_keys=ON")
            recognized_before = int(
                con.execute("SELECT COUNT(*) FROM interest_accruals WHERE status='RECOGNIZED'").fetchone()[0]
            )
            periods = business.recalculate_loan(con, 1, cutoff=date(2026, 6, 30))
            con.commit()
            recognized_after = int(
                con.execute("SELECT COUNT(*) FROM interest_accruals WHERE status='RECOGNIZED'").fetchone()[0]
            )
            loan = con.execute(
                "SELECT contract_no,interest_start_date FROM loans WHERE id=1"
            ).fetchone()

        assert loan is not None
        assert loan["interest_start_date"] == "2026-01-01"
        assert periods == 2
        assert recognized_before == recognized_after

    print(
        "INTEREST START OK: câmp existent, recalculare pe contract funcțională, "
        f"{recognized_after} perioade recunoscute păstrate."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
