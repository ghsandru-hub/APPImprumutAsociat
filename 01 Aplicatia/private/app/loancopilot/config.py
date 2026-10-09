from __future__ import annotations

import os
from pathlib import Path

APP_VERSION = "2.5.0"
DEFAULT_HOME = Path("/home/aiallro")
HOME = Path(os.getenv("LOANCOPILOT_HOME", DEFAULT_HOME))
PUBLIC_ROOT = Path(os.getenv("LOANCOPILOT_PUBLIC_ROOT", HOME / "loancopilot.aiall.ro"))
PRIVATE_ROOT = Path(os.getenv("LOANCOPILOT_PRIVATE_ROOT", HOME / "loancopilot.privat"))
DB_ROOT = Path(os.getenv("LOANCOPILOT_DB_ROOT", PRIVATE_ROOT / "dbsqlite"))
TENANT_DB_ROOT = DB_ROOT / "companies"
DOCUMENT_ROOT = Path(os.getenv("LOANCOPILOT_DOCUMENT_ROOT", PRIVATE_ROOT / "documente"))
TEMPLATE_ROOT = Path(os.getenv("LOANCOPILOT_TEMPLATE_ROOT", PRIVATE_ROOT / "sabloane"))
BACKUP_ROOT = PRIVATE_ROOT / "backup"
LOG_ROOT = PRIVATE_ROOT / "logs"
SECRET_ROOT = PRIVATE_ROOT / "secrets"
AUTH_DB_PATH = DB_ROOT / "loancopilot_auth.sqlite"
APP_SECRET_PATH = SECRET_ROOT / "app_secret.key"
FERNET_KEY_PATH = SECRET_ROOT / "fernet.key"

SESSION_COOKIE = "loancopilot_session"
PREAUTH_COOKIE = "loancopilot_preauth"
SESSION_HOURS = int(os.getenv("LOANCOPILOT_SESSION_HOURS", "12"))
TRUST_PROXY = os.getenv("LOANCOPILOT_TRUST_PROXY", "1") == "1"
COOKIE_SECURE = os.getenv("LOANCOPILOT_COOKIE_SECURE", "1") == "1"
MAX_CONTENT_LENGTH = 25 * 1024 * 1024
PDF_CONVERSION_TIMEOUT = int(os.getenv("LOANCOPILOT_PDF_CONVERSION_TIMEOUT", "120"))
LIBREOFFICE_BINARY = os.getenv("LOANCOPILOT_LIBREOFFICE", "").strip()

BNR_RATE_URLS = (
    "https://www.bnr.ro/2482-politica-monetara",
    "https://www.bnr.ro/1970-rata-dobanzii-de-politica-monetara",
)


def ensure_directories() -> None:
    for path in (DB_ROOT, TENANT_DB_ROOT, DOCUMENT_ROOT, TEMPLATE_ROOT, BACKUP_ROOT, LOG_ROOT, SECRET_ROOT):
        path.mkdir(parents=True, exist_ok=True)
