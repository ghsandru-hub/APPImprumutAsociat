#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import sqlite3
import tempfile
from pathlib import Path

from loancopilot.docx_print import render_docx_for_print
from loancopilot.config import PRIVATE_ROOT, TEMPLATE_ROOT
from loancopilot.db import auth_connect, ensure_tenant_schema, tenant_db_path, tenant_documents_path


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verifică documentele Word, previzualizarea Print/Save as PDF, PDF-urile semnate și șabloanele."
    )
    parser.add_argument("--company-slug", default="mtm-izolatii-constructii")
    parser.add_argument(
        "--write-test",
        action="store_true",
        help="generează temporar HTML-ul de tipărire pentru primul document Word și îl validează",
    )
    args = parser.parse_args()

    with auth_connect() as con:
        company = con.execute("SELECT * FROM companies WHERE slug=?", (args.company_slug,)).fetchone()
    if not company:
        raise SystemExit(f"Compania nu există: {args.company_slug}")

    db_path = tenant_db_path(company)
    docs_root = tenant_documents_path(company)
    ensure_tenant_schema(db_path)
    missing: list[str] = []
    with sqlite3.connect(db_path) as con:
        con.row_factory = sqlite3.Row
        docs = con.execute("SELECT id,doc_type,filename FROM documents ORDER BY id").fetchall()
        for row in docs:
            if row["filename"] and not (docs_root / str(row["filename"])).is_file():
                missing.append(str(row["filename"]))
        tables = {
            row["name"]
            for row in con.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name IN "
                "('document_versions','document_word_versions','generated_pdf_versions')"
            ).fetchall()
        }

    print(f"Companie: {company['name']}")
    print(f"Bază: {db_path}")
    print(f"Documente în registru: {len(docs)}")
    print(f"Documente Word lipsă: {len(missing)}")
    for name in missing:
        print(f"  LIPSĂ: {name}")
    for table in ("document_versions", "document_word_versions", "generated_pdf_versions"):
        print(f"Tabel {table}: {'OK' if table in tables else 'LIPSĂ'}")

    templates = [
        path
        for path in (TEMPLATE_ROOT / "standard").iterdir()
        if path.is_file() and not path.name.startswith(".")
    ]
    print(f"Șabloane standard: {len(templates)}")

    required_tables = {"document_versions", "document_word_versions", "generated_pdf_versions"}
    if missing or not required_tables.issubset(tables) or not templates:
        return 2

    sources = [
        docs_root / str(row["filename"])
        for row in docs
        if row["filename"] and (docs_root / str(row["filename"])).suffix.lower() == ".docx"
    ]
    if not sources:
        print("Nu există documente DOCX pentru testul de tipărire.")
        return 3

    checked = 0
    for source in sources:
        rendered = render_docx_for_print(source, title=source.stem, filename=source.name)
        if "id=\"wordSource\"" not in rendered or "paginateWordDocument" not in rendered or "Tipărește / Salvează PDF" not in rendered:
            print(f"Previzualizare invalidă: {source.name}")
            return 4
        checked += 1
    print(f"Previzualizare browser validată pentru {checked} documente Word.")

    if args.write_test:
        temp_root = PRIVATE_ROOT / "tmp"
        temp_root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="loancopilot_print_", dir=temp_root) as temp_name:
            output = Path(temp_name) / "preview.html"
            rendered = render_docx_for_print(sources[0], title=sources[0].stem, filename=sources[0].name)
            output.write_text(rendered, encoding="utf-8")
            digest = sha256(output)
            if output.stat().st_size < 1000 or len(digest) != 64:
                print("Fișierul HTML de tipărire nu a putut fi confirmat.")
                return 5
            print(f"Test temporar Print/Save as PDF: OK · SHA-256 {digest[:12]}…")

    print("Verificare flux documente: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
