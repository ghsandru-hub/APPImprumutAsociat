#!/usr/bin/env python3
from __future__ import annotations

import ast
import compileall
import re
import sys
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / "app"
PACKAGE_ROOT = ROOT.parent


class IdCollector(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.ids: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        for key, value in attrs:
            if key == "id" and value:
                self.ids.append(value)


def fail(message: str) -> None:
    raise RuntimeError(message)


def check_python() -> None:
    if not compileall.compile_dir(APP_ROOT, quiet=1, force=True):
        fail("Compilarea Python a eșuat.")

    unused: list[str] = []
    for path in APP_ROOT.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        imports: list[tuple[str, int]] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for item in node.names:
                    imports.append((item.asname or item.name.split(".", 1)[0], node.lineno))
            elif isinstance(node, ast.ImportFrom):
                for item in node.names:
                    if item.name != "*":
                        imports.append((item.asname or item.name, node.lineno))
        used = {
            node.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load)
        }
        for name, line in imports:
            if name != "annotations" and name not in used:
                unused.append(f"{path.relative_to(APP_ROOT)}:{line}: import neutilizat {name}")
    if unused:
        fail("Importuri neutilizate:\n" + "\n".join(unused))


def check_templates() -> None:
    templates = APP_ROOT / "loancopilot" / "templates"
    for filename in ("app.html", "admin.html"):
        path = templates / filename
        source = path.read_text(encoding="utf-8")
        if "<style" in source.lower():
            fail(f"{filename} conține CSS inline.")
        inline_scripts = re.findall(r"<script(?![^>]*\bsrc=)[^>]*>", source, flags=re.I)
        if inline_scripts:
            fail(f"{filename} conține JavaScript inline.")
        if "name=\"viewport\"" not in source:
            fail(f"{filename} nu conține meta viewport.")

        collector = IdCollector()
        collector.feed(source)
        duplicates = sorted({item for item in collector.ids if collector.ids.count(item) > 1})
        if duplicates:
            fail(f"ID-uri duplicate în {filename}: {', '.join(duplicates)}")

    app_html = (templates / "app.html").read_text(encoding="utf-8")
    if "app.css" not in app_html or "app.js" not in app_html:
        fail("app.html nu folosește asset-urile separate app.css și app.js.")
    for required_id in ("interestStartBody", "loanEditModal", "loanEditInterestStartDate"):
        if f'id="{required_id}"' not in app_html:
            fail(f"Controlul obligatoriu {required_id} lipsește din app.html.")


def check_removed_legacy() -> None:
    forbidden = {
        "imp.load_source": "loader Passenger recursiv",
        "os.execl": "reexec Passenger",
        "LOANCOPILOT_LIBREOFFICE": "configurație LibreOffice abandonată",
        "libreoffice_binary": "convertor LibreOffice abandonat",
        "convert_docx_to_pdf": "convertor server Word-PDF abandonat",
    }
    text_files = [
        *APP_ROOT.rglob("*.py"),
        *APP_ROOT.rglob("*.html"),
        *APP_ROOT.rglob("*.js"),
        *APP_ROOT.rglob("*.css"),
        PACKAGE_ROOT / "application_root" / "passenger_wsgi.py",
    ]
    for path in text_files:
        if not path.is_file():
            continue
        source = path.read_text(encoding="utf-8", errors="replace")
        for token, label in forbidden.items():
            if token in source:
                fail(f"Cod legacy detectat ({label}) în {path}.")

    app_js = (APP_ROOT / "loancopilot" / "static" / "app.js").read_text(encoding="utf-8")
    if re.search(r"companyMeta[^\n]{0,250}sold 4551", app_js):
        fail("Metadatele operaționale au rămas în header.")


def main() -> int:
    check_python()
    check_templates()
    check_removed_legacy()
    print("AUDIT COD OK: Python, template-uri, asset-uri, header mobil și cod legacy.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"AUDIT COD EROARE: {exc}", file=sys.stderr)
        raise SystemExit(1)
