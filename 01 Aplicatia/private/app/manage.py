#!/usr/bin/env python3
from __future__ import annotations

import argparse
import getpass
import os
import shutil
import sqlite3
from pathlib import Path

from loancopilot import create_app
from loancopilot.config import (
    AUTH_DB_PATH,
    DB_ROOT,
    DOCUMENT_ROOT,
    TENANT_DB_ROOT,
    ensure_directories,
)
from loancopilot.db import (
    auth_connect,
    copy_standard_templates_to_company,
    create_tenant_database,
    ensure_tenant_schema,
    init_auth_db,
    register_company,
    safe_filename,
    sync_tenant_company,
    tenant_database_status,
)
from loancopilot.security import hash_password, validate_password

APP_DIR = Path(__file__).resolve().parent
SEED_DB = DB_ROOT / "seed" / "mtm_18235662.sqlite"


def create_or_update_admin(email: str, display_name: str, password: str) -> int:
    validate_password(password)
    email = email.strip().lower()
    with auth_connect() as con:
        row = con.execute("SELECT id FROM users WHERE email=? COLLATE NOCASE", (email,)).fetchone()
        if row:
            con.execute(
                "UPDATE users SET display_name=?,password_hash=?,active=1,is_superadmin=1,updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (display_name, hash_password(password), row["id"]),
            )
            user_id = int(row["id"])
        else:
            cur = con.execute(
                "INSERT INTO users(email,display_name,password_hash,active,is_superadmin) VALUES(?,?,?,1,1)",
                (email, display_name, hash_password(password)),
            )
            user_id = int(cur.lastrowid)
        con.commit()
    return user_id


def seed_mtm() -> int:
    slug = "mtm-izolatii-constructii"
    db_filename = "mtm_18235662.sqlite"
    ensure_directories()
    target = TENANT_DB_ROOT / db_filename
    with auth_connect() as con:
        existing = con.execute("SELECT id FROM companies WHERE slug=?", (slug,)).fetchone()
        if existing:
            company_id = int(existing["id"])
        else:
            company_id = register_company(
                con,
                slug=slug,
                name="MTM IZOLAȚII CONSTRUCȚII SRL",
                cui="18235662",
                reg_com="J2005021485405",
                address="București, sector 6, str. Preciziei nr. 13C",
                administrator="Trif Marius-Constantin",
                db_filename=db_filename,
                documents_subdir=slug,
            )
            con.commit()
    if not target.exists():
        if not SEED_DB.exists():
            raise FileNotFoundError(f"Seed MTM lipsă: {SEED_DB}")
        create_tenant_database(
            target,
            seed_path=SEED_DB,
            company_data={
                "name": "MTM IZOLAȚII CONSTRUCȚII SRL",
                "cui": "18235662",
                "reg_com": "J2005021485405",
                "address": "București, sector 6, str. Preciziei nr. 13C",
                "administrator": "Trif Marius-Constantin",
            },
        )
    else:
        ensure_tenant_schema(target)
        sync_tenant_company(
            target,
            {
                "name": "MTM IZOLAȚII CONSTRUCȚII SRL",
                "cui": "18235662",
                "reg_com": "J2005021485405",
                "address": "București, sector 6, str. Preciziei nr. 13C",
                "administrator": "Trif Marius-Constantin",
            },
        )
    docs_target = DOCUMENT_ROOT / slug
    docs_target.mkdir(parents=True, exist_ok=True)
    copy_standard_templates_to_company(docs_target)
    return company_id


def command_init(args):
    ensure_directories()
    init_auth_db()
    company_id = seed_mtm() if not args.no_mtm else None
    email = args.admin_email or os.getenv("LOANCOPILOT_ADMIN_EMAIL") or input("Email administrator sistem: ").strip()
    display_name = args.admin_name or os.getenv("LOANCOPILOT_ADMIN_NAME") or "Administrator LoanCopilot"
    password = args.admin_password or os.getenv("LOANCOPILOT_ADMIN_PASSWORD")
    if not password:
        password = getpass.getpass("Parolă administrator (min. 12 caractere, literă + cifră): ")
        confirm = getpass.getpass("Confirmați parola: ")
        if password != confirm:
            raise SystemExit("Parolele nu coincid.")
    user_id = create_or_update_admin(email, display_name, password)
    if company_id:
        with auth_connect() as con:
            con.execute(
                "INSERT INTO user_companies(user_id,company_id,role) VALUES(?,?,'ADMIN') ON CONFLICT(user_id,company_id) DO UPDATE SET role='ADMIN'",
                (user_id, company_id),
            )
            con.commit()
    print(f"Inițializare finalizată. Auth DB: {AUTH_DB_PATH}")
    print(f"Administrator: {email}")
    if company_id:
        print("Compania MTM și baza sa SQLite au fost activate.")


def command_create_company(args):
    init_auth_db()
    slug = safe_filename(args.slug or f"{args.name}-{args.cui}")
    db_filename = f"{slug}.sqlite"
    company_data = {
        "name": args.name.strip(),
        "cui": args.cui.strip(),
        "reg_com": (args.reg_com or "").strip(),
        "address": (args.address or "").strip(),
        "administrator": (args.administrator or "").strip(),
    }
    target = TENANT_DB_ROOT / db_filename
    docs_target = DOCUMENT_ROOT / slug
    company_id = None
    db_created = False
    docs_created = False
    try:
        with auth_connect() as con:
            con.execute("BEGIN IMMEDIATE")
            duplicate = con.execute(
                "SELECT id,name FROM companies WHERE slug=? OR db_filename=? OR cui=? COLLATE NOCASE",
                (slug, db_filename, company_data["cui"]),
            ).fetchone()
            if duplicate:
                raise ValueError(f"Compania există deja: {duplicate['name']} (id={duplicate['id']}).")
            company_id = register_company(
                con, slug=slug, name=company_data["name"], cui=company_data["cui"],
                reg_com=company_data["reg_com"], address=company_data["address"],
                administrator=company_data["administrator"], db_filename=db_filename,
                documents_subdir=slug,
            )
            create_tenant_database(target, company_data=company_data)
            db_created = True
            docs_existed = docs_target.exists()
            docs_target.mkdir(parents=True, exist_ok=True)
            docs_created = not docs_existed
            copied_templates = copy_standard_templates_to_company(docs_target)
            con.commit()
        status = tenant_database_status({"db_filename": db_filename})
        if not status["ok"]:
            raise RuntimeError(f"Baza nu a trecut verificarea: {status}")
    except Exception:
        if company_id is not None:
            with auth_connect() as cleanup_con:
                cleanup_con.execute("DELETE FROM companies WHERE id=?", (company_id,))
                cleanup_con.commit()
        if db_created:
            target.unlink(missing_ok=True)
        if docs_created:
            shutil.rmtree(docs_target, ignore_errors=True)
        raise
    print(
        f"Companie creată: id={company_id}, db={target}, "
        f"dimensiune={target.stat().st_size}, șabloane copiate={copied_templates}"
    )


def command_create_user(args):
    init_auth_db()
    password = args.password or getpass.getpass("Parolă inițială: ")
    validate_password(password)
    with auth_connect() as con:
        company = con.execute("SELECT id FROM companies WHERE slug=?", (args.company,)).fetchone()
        if not company:
            raise SystemExit("Compania nu există.")
        cur = con.execute(
            "INSERT INTO users(email,display_name,password_hash) VALUES(?,?,?)",
            (args.email.lower(), args.name, hash_password(password)),
        )
        con.execute("INSERT INTO user_companies(user_id,company_id,role) VALUES(?,?,?)", (cur.lastrowid, company["id"], args.role))
        con.commit()
    print("Utilizator creat.")


def command_reset_password(args):
    password = args.password or getpass.getpass("Parolă nouă: ")
    validate_password(password)
    with auth_connect() as con:
        row = con.execute("SELECT id FROM users WHERE email=? COLLATE NOCASE", (args.email,)).fetchone()
        if not row:
            raise SystemExit("Utilizatorul nu există.")
        con.execute("UPDATE users SET password_hash=?,password_changed_at=CURRENT_TIMESTAMP,updated_at=CURRENT_TIMESTAMP WHERE id=?", (hash_password(password), row["id"]))
        con.execute("UPDATE auth_sessions SET revoked_at=CURRENT_TIMESTAMP WHERE user_id=? AND revoked_at IS NULL", (row["id"],))
        con.commit()
    print("Parola a fost schimbată și sesiunile au fost revocate.")


def command_run(args):
    app = create_app()
    app.run(host=args.host, port=args.port, debug=args.debug)


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description="Administrare smartBIZ LoanCopilot")
    sub = root.add_subparsers(dest="command", required=True)
    p = sub.add_parser("init", help="Inițializează structura, administratorul și compania MTM")
    p.add_argument("--admin-email")
    p.add_argument("--admin-name")
    p.add_argument("--admin-password")
    p.add_argument("--no-mtm", action="store_true")
    p.set_defaults(func=command_init)
    p = sub.add_parser("create-company")
    p.add_argument("--name", required=True); p.add_argument("--cui", required=True); p.add_argument("--slug")
    p.add_argument("--reg-com", default=""); p.add_argument("--address", default=""); p.add_argument("--administrator", default="")
    p.set_defaults(func=command_create_company)
    p = sub.add_parser("create-user")
    p.add_argument("--email", required=True); p.add_argument("--name", required=True); p.add_argument("--company", required=True)
    p.add_argument("--role", choices=["ADMIN", "EDITOR", "VIEWER"], default="VIEWER"); p.add_argument("--password")
    p.set_defaults(func=command_create_user)
    p = sub.add_parser("reset-password")
    p.add_argument("--email", required=True); p.add_argument("--password")
    p.set_defaults(func=command_reset_password)
    p = sub.add_parser("run")
    p.add_argument("--host", default="127.0.0.1"); p.add_argument("--port", type=int, default=8091); p.add_argument("--debug", action="store_true")
    p.set_defaults(func=command_run)
    return root


if __name__ == "__main__":
    arguments = parser().parse_args()
    try:
        arguments.func(arguments)
    except (ValueError, sqlite3.IntegrityError, FileExistsError, FileNotFoundError) as exc:
        raise SystemExit(str(exc)) from exc
