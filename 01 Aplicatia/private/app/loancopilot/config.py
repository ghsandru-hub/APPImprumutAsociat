from __future__ import annotations

import os
from pathlib import Path

APP_VERSION = "2.6.1"
DEFAULT_HOME = Path("/home/aiallro")
HOME = Path(os.getenv("LOANCOPILOT_HOME", DEFAULT_HOME)).expanduser()
PUBLIC_ROOT = Path(os.getenv("LOANCOPILOT_PUBLIC_ROOT", HOME / "loancopilot.aiall.ro")).expanduser()
PRIVATE_ROOT = Path(os.getenv("LOANCOPILOT_PRIVATE_ROOT", HOME / "loancopilot.privat")).expanduser()


def _private_child(env_name: str, default_subdir: str) -> Path:
    """Keep persistent data inside PRIVATE_ROOT even when an old cPanel variable is wrong."""
    private_root = PRIVATE_ROOT.resolve()
    raw_value = (os.getenv(env_name) or "").strip()
    candidate = Path(raw_value).expanduser() if raw_value else private_root / default_subdir
    resolved = candidate.resolve()
    if resolved != private_root and private_root not in resolved.parents:
        return private_root / default_subdir
    return resolved


# LoanCopilot's deployment contract requires all persistent data to remain private.
DB_ROOT = _private_child("LOANCOPILOT_DB_ROOT", "dbsqlite")
TENANT_DB_ROOT = DB_ROOT / "companies"
DOCUMENT_ROOT = _private_child("LOANCOPILOT_DOCUMENT_ROOT", "documente")
TEMPLATE_ROOT = _private_child("LOANCOPILOT_TEMPLATE_ROOT", "sabloane")
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

ANAF_API_URL = os.getenv(
    "LOANCOPILOT_ANAF_API_URL",
    "https://webservicesp.anaf.ro/api/PlatitorTvaRest/v9/tva",
).strip()
ANAF_TIMEOUT = int(os.getenv("LOANCOPILOT_ANAF_TIMEOUT", "20"))
ANAF_RETRIES = max(1, min(3, int(os.getenv("LOANCOPILOT_ANAF_RETRIES", "2"))))

BNR_RATE_URLS = (
    "https://www.bnr.ro/1970-rata-dobanzii-de-politica-monetara",
    "https://www.bnr.ro/1936-piete-financiare",
    "https://www.bnr.ro/2482-politica-monetara",
    "https://www.bnr.ro/Rata-dobanzii-de-politica-monetara-1744-Mobile.aspx",
    "https://www.bnr.ro/Rata-dobanzii-de-politica-monetara-1744.aspx",
)


def ensure_directories() -> None:
    for path in (
        DB_ROOT,
        TENANT_DB_ROOT,
        DOCUMENT_ROOT,
        TEMPLATE_ROOT,
        BACKUP_ROOT,
        LOG_ROOT,
        SECRET_ROOT,
        PRIVATE_ROOT / "tmp",
    ):
        path.mkdir(parents=True, exist_ok=True)
