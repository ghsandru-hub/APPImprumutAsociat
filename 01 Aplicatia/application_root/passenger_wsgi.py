from __future__ import annotations

import os
import sys
import traceback
from pathlib import Path

APP_PATH = Path("/home/aiallro/loancopilot.privat/app")
LOG_PATH = Path("/home/aiallro/loancopilot.privat/logs/passenger_startup_error.log")

if str(APP_PATH) not in sys.path:
    sys.path.insert(0, str(APP_PATH))

os.environ.setdefault("LOANCOPILOT_HOME", "/home/aiallro")
os.environ.setdefault("LOANCOPILOT_PUBLIC_ROOT", "/home/aiallro/loancopilot.aiall.ro")
os.environ.setdefault("LOANCOPILOT_PRIVATE_ROOT", "/home/aiallro/loancopilot.privat")
os.environ.setdefault("LOANCOPILOT_DB_ROOT", "/home/aiallro/loancopilot.privat/dbsqlite")
os.environ.setdefault("LOANCOPILOT_DOCUMENT_ROOT", "/home/aiallro/loancopilot.privat/documente")
os.environ.setdefault("LOANCOPILOT_TEMPLATE_ROOT", "/home/aiallro/loancopilot.privat/sabloane")
os.environ.setdefault("LOANCOPILOT_COOKIE_SECURE", "1")
os.environ.setdefault("LOANCOPILOT_TRUST_PROXY", "1")
os.environ.setdefault("PYTHONUNBUFFERED", "1")

try:
    from wsgi import application  # noqa: E402,F401
except Exception:
    try:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with LOG_PATH.open("a", encoding="utf-8") as handle:
            handle.write("\n=== Passenger startup failure ===\n")
            handle.write(f"sys.executable: {sys.executable}\n")
            handle.write(f"sys.version: {sys.version}\n")
            handle.write(f"sys.argv: {sys.argv!r}\n")
            handle.write(f"sys.path: {sys.path!r}\n")
            handle.write(traceback.format_exc())
    finally:
        raise
