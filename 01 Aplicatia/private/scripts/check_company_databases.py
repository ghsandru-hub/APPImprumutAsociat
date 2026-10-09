#!/usr/bin/env python3
from __future__ import annotations

import argparse

from loancopilot.config import DB_ROOT, DOCUMENT_ROOT, PRIVATE_ROOT, TENANT_DB_ROOT
from loancopilot.db import (
    auth_connect,
    copy_standard_templates_to_company,
    repair_tenant_database,
    tenant_database_status,
    tenant_documents_path,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verifică bazele SQLite fizic separate ale companiilor LoanCopilot."
    )
    parser.add_argument(
        "--repair-missing",
        action="store_true",
        help="Creează bazele lipsă. Nu suprascrie baze existente.",
    )
    parser.add_argument(
        "--repair",
        action="store_true",
        help=(
            "Creează bazele lipsă și completează schema/rândul companiei în bazele valide, "
            "dar incomplete. Nu rescrie o bază SQLite coruptă."
        ),
    )
    args = parser.parse_args()

    print(f"PRIVATE_ROOT={PRIVATE_ROOT}")
    print(f"DB_ROOT={DB_ROOT}")
    print(f"TENANT_DB_ROOT={TENANT_DB_ROOT}")
    print(f"DOCUMENT_ROOT={DOCUMENT_ROOT}")

    with auth_connect() as con:
        companies = con.execute("SELECT * FROM companies ORDER BY id").fetchall()

    if not companies:
        print("Nu există companii în baza centrală de autentificare.")
        return 0

    failures = 0
    for company in companies:
        status = tenant_database_status(company)
        actions: list[str] = []

        may_repair_existing = (
            status["exists"]
            and str(status["integrity"]).lower() == "ok"
            and not status["ok"]
        )
        should_repair = (
            (not status["exists"] and (args.repair_missing or args.repair))
            or (may_repair_existing and args.repair)
        )

        if should_repair:
            was_missing = not status["exists"]
            status = repair_tenant_database(company)
            actions.append("CREATĂ" if was_missing else "SCHEMĂ COMPLETATĂ")

        docs = tenant_documents_path(company)
        if args.repair or args.repair_missing:
            docs.mkdir(parents=True, exist_ok=True)
            copied = copy_standard_templates_to_company(docs)
            if copied:
                actions.append(f"ȘABLOANE COPIATE={copied}")

        label = "OK" if status["ok"] else "EROARE"
        action_text = f"; {'; '.join(actions)}" if actions else ""
        print(
            f"[{label}] id={company['id']} · {company['name']} · "
            f"{status['path']} · {status['size_bytes']} bytes · "
            f"integrity={status['integrity']}{action_text}"
        )
        if status["missing_tables"]:
            print("  Tabele lipsă:", ", ".join(status["missing_tables"]))
        if status["error"]:
            print("  Eroare:", status["error"])
        if status["exists"] and str(status["integrity"]).lower() != "ok":
            print("  Baza pare coruptă; nu a fost suprascrisă automat. Restaurați un backup.")
        if not status["ok"]:
            failures += 1

    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
