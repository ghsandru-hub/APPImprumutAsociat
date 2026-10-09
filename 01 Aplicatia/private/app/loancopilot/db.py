from __future__ import annotations

import os
import shutil
import sqlite3
import unicodedata
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from .config import AUTH_DB_PATH, DOCUMENT_ROOT, TEMPLATE_ROOT, TENANT_DB_ROOT, ensure_directories

AUTH_SCHEMA = """
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS companies(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    slug TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    cui TEXT NOT NULL,
    reg_com TEXT,
    address TEXT,
    administrator TEXT,
    db_filename TEXT NOT NULL UNIQUE,
    documents_subdir TEXT NOT NULL UNIQUE,
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS users(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT NOT NULL UNIQUE COLLATE NOCASE,
    display_name TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1,
    is_superadmin INTEGER NOT NULL DEFAULT 0,
    totp_enabled INTEGER NOT NULL DEFAULT 0,
    totp_secret_enc TEXT,
    totp_pending_secret_enc TEXT,
    recovery_hashes TEXT,
    password_changed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_login_at TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS user_companies(
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    company_id INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    role TEXT NOT NULL CHECK(role IN ('ADMIN','EDITOR','VIEWER')),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY(user_id, company_id)
);
CREATE TABLE IF NOT EXISTS auth_sessions(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    token_hash TEXT NOT NULL UNIQUE,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    current_company_id INTEGER REFERENCES companies(id),
    csrf_token TEXT NOT NULL,
    ip_hash TEXT,
    user_agent_hash TEXT,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    revoked_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_auth_sessions_user ON auth_sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_auth_sessions_expiry ON auth_sessions(expires_at);
CREATE TABLE IF NOT EXISTS auth_challenges(
    token_hash TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    ip_hash TEXT,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS login_attempts(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    identity_hash TEXT NOT NULL,
    ip_hash TEXT NOT NULL,
    attempted_at TEXT NOT NULL,
    success INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_login_attempts_lookup ON login_attempts(identity_hash, ip_hash, attempted_at);
CREATE TABLE IF NOT EXISTS security_audit(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_time TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    user_id INTEGER,
    company_id INTEGER,
    action TEXT NOT NULL,
    ip_hash TEXT,
    details TEXT
);
CREATE TABLE IF NOT EXISTS system_settings(
    key TEXT PRIMARY KEY,
    value TEXT
);
"""

EMPTY_TENANT_SCHEMA = """
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS company(id INTEGER PRIMARY KEY,name TEXT NOT NULL,cui TEXT NOT NULL,reg_com TEXT,address TEXT,administrator TEXT,updated_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS associates(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT NOT NULL,share_pct REAL NOT NULL DEFAULT 0,cnp TEXT,id_doc TEXT,address TEXT,email TEXT,iban TEXT,active INTEGER NOT NULL DEFAULT 1,created_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS loans(id INTEGER PRIMARY KEY AUTOINCREMENT,contract_no TEXT NOT NULL UNIQUE,contract_date TEXT NOT NULL,original_contract_date TEXT NOT NULL,interest_start_date TEXT,associate_id INTEGER NOT NULL REFERENCES associates(id),principal REAL NOT NULL DEFAULT 0,interest_rate REAL NOT NULL DEFAULT 0,maturity_date TEXT,calculation_basis TEXT DEFAULT 'ACTUAL_365',recognition_frequency TEXT DEFAULT 'QUARTERLY',interest_due_rule TEXT DEFAULT 'ON_REQUEST',status TEXT NOT NULL DEFAULT 'ACTIVE',notes TEXT,created_at TEXT DEFAULT CURRENT_TIMESTAMP,interest_rate_mode TEXT DEFAULT 'BNR_REFERENCE',interest_rate_source TEXT);
CREATE TABLE IF NOT EXISTS transactions(id INTEGER PRIMARY KEY AUTOINCREMENT,loan_id INTEGER NOT NULL REFERENCES loans(id) ON DELETE CASCADE,accrual_id INTEGER,txn_date TEXT NOT NULL,txn_type TEXT NOT NULL,amount REAL NOT NULL CHECK(amount>=0),tax_withheld REAL NOT NULL DEFAULT 0,payment_method TEXT DEFAULT 'ACCOUNTING',reference TEXT,notes TEXT,source_order INTEGER,created_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS interest_accruals(id INTEGER PRIMARY KEY AUTOINCREMENT,loan_id INTEGER NOT NULL REFERENCES loans(id) ON DELETE CASCADE,period_start TEXT NOT NULL,period_end TEXT NOT NULL,opening_balance REAL NOT NULL,principal_advances REAL NOT NULL DEFAULT 0,principal_repayments REAL NOT NULL DEFAULT 0,closing_balance REAL NOT NULL,days INTEGER NOT NULL,calculated_amount REAL NOT NULL,recognized_amount REAL NOT NULL DEFAULT 0,recognized_date TEXT,status TEXT NOT NULL DEFAULT 'CALCULATED',notes TEXT,UNIQUE(loan_id,period_start,period_end));
CREATE TABLE IF NOT EXISTS bnr_reference_rates(id INTEGER PRIMARY KEY AUTOINCREMENT,effective_date TEXT NOT NULL UNIQUE,rate REAL NOT NULL CHECK(rate>=0),rate_name TEXT NOT NULL DEFAULT 'Rata dobânzii de politică monetară',source_url TEXT,source_document TEXT,fetched_at TEXT DEFAULT CURRENT_TIMESTAMP,entry_mode TEXT NOT NULL DEFAULT 'BNR_AUTO',notes TEXT);
CREATE TABLE IF NOT EXISTS interest_segments(id INTEGER PRIMARY KEY AUTOINCREMENT,accrual_id INTEGER NOT NULL REFERENCES interest_accruals(id) ON DELETE CASCADE,bnr_rate_id INTEGER REFERENCES bnr_reference_rates(id),segment_start TEXT NOT NULL,segment_end TEXT NOT NULL,days INTEGER NOT NULL,rate REAL NOT NULL,balance_days REAL NOT NULL,calculated_amount REAL NOT NULL);
CREATE TABLE IF NOT EXISTS documents(id INTEGER PRIMARY KEY AUTOINCREMENT,doc_type TEXT NOT NULL,doc_no TEXT,doc_date TEXT,associate_id INTEGER REFERENCES associates(id),loan_id INTEGER REFERENCES loans(id),filename TEXT,status TEXT DEFAULT 'SIGNED',notes TEXT);
CREATE TABLE IF NOT EXISTS document_versions(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    version_no INTEGER NOT NULL,
    version_type TEXT NOT NULL DEFAULT 'SIGNED_PDF' CHECK(version_type IN ('SIGNED_PDF')),
    stored_path TEXT NOT NULL,
    original_filename TEXT NOT NULL,
    mime_type TEXT NOT NULL DEFAULT 'application/pdf',
    size_bytes INTEGER NOT NULL DEFAULT 0 CHECK(size_bytes>=0),
    sha256 TEXT NOT NULL,
    notes TEXT,
    uploaded_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    uploaded_by TEXT,
    UNIQUE(document_id,version_no),
    UNIQUE(document_id,sha256)
);
CREATE INDEX IF NOT EXISTS idx_document_versions_document ON document_versions(document_id,version_no DESC);
CREATE TABLE IF NOT EXISTS document_word_versions(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    version_no INTEGER NOT NULL,
    stored_path TEXT NOT NULL,
    original_filename TEXT NOT NULL,
    mime_type TEXT NOT NULL DEFAULT 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    size_bytes INTEGER NOT NULL DEFAULT 0 CHECK(size_bytes>=0),
    sha256 TEXT NOT NULL,
    notes TEXT,
    is_current INTEGER NOT NULL DEFAULT 0,
    uploaded_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    uploaded_by TEXT,
    UNIQUE(document_id,version_no),
    UNIQUE(document_id,sha256)
);
CREATE INDEX IF NOT EXISTS idx_document_word_versions_document ON document_word_versions(document_id,version_no DESC);
CREATE UNIQUE INDEX IF NOT EXISTS idx_document_word_versions_current ON document_word_versions(document_id) WHERE is_current=1;
CREATE TABLE IF NOT EXISTS generated_pdf_versions(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    word_version_id INTEGER REFERENCES document_word_versions(id) ON DELETE SET NULL,
    version_no INTEGER NOT NULL,
    stored_path TEXT NOT NULL,
    original_filename TEXT NOT NULL,
    mime_type TEXT NOT NULL DEFAULT 'application/pdf',
    size_bytes INTEGER NOT NULL DEFAULT 0 CHECK(size_bytes>=0),
    sha256 TEXT NOT NULL,
    generated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    generated_by TEXT,
    notes TEXT,
    UNIQUE(document_id,version_no),
    UNIQUE(document_id,sha256)
);
CREATE INDEX IF NOT EXISTS idx_generated_pdf_versions_document ON generated_pdf_versions(document_id,version_no DESC);
INSERT OR IGNORE INTO bnr_reference_rates(effective_date,rate,rate_name,source_url,source_document,entry_mode,notes) VALUES('2024-08-08',6.50,'Rata dobânzii de politică monetară','https://www.bnr.ro/2482-politica-monetara','Pagina oficială BNR – rata dobânzii de politică monetară','BNR_SEED','Rată istorică inițială; actualizați registrul din aplicație.');
CREATE TABLE IF NOT EXISTS audit_log(id INTEGER PRIMARY KEY AUTOINCREMENT,event_time TEXT DEFAULT CURRENT_TIMESTAMP,action TEXT,entity TEXT,entity_id INTEGER,details TEXT,user_email TEXT);
CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY,value TEXT);
CREATE VIEW IF NOT EXISTS loan_balances AS SELECT l.id loan_id,l.contract_no,COALESCE(SUM(CASE WHEN t.txn_type IN ('ADVANCE','OPENING_BALANCE') THEN t.amount ELSE 0 END),0) funded,COALESCE(SUM(CASE WHEN t.txn_type='REPAYMENT' THEN t.amount ELSE 0 END),0) repaid,COALESCE(SUM(CASE WHEN t.txn_type IN ('ADVANCE','OPENING_BALANCE') THEN t.amount WHEN t.txn_type='REPAYMENT' THEN -t.amount ELSE 0 END),0) balance FROM loans l LEFT JOIN transactions t ON t.loan_id=l.id GROUP BY l.id;
"""


def utcnow() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def configure_connection(con: sqlite3.Connection) -> sqlite3.Connection:
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    con.execute("PRAGMA busy_timeout=5000")
    try:
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("PRAGMA synchronous=NORMAL")
    except sqlite3.OperationalError:
        pass
    return con


def auth_connect() -> sqlite3.Connection:
    ensure_directories()
    return configure_connection(sqlite3.connect(AUTH_DB_PATH, timeout=10))


def init_auth_db() -> None:
    with auth_connect() as con:
        con.executescript(AUTH_SCHEMA)
        con.execute("INSERT OR IGNORE INTO system_settings(key,value) VALUES('schema_version','2')")
        con.commit()


def safe_filename(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", str(value or ""))
    ascii_value = normalized.encode("ascii", "ignore").decode("ascii")
    allowed = "abcdefghijklmnopqrstuvwxyz0123456789-_"
    cleaned = "".join(ch for ch in ascii_value.lower().replace(" ", "-") if ch in allowed)
    while "--" in cleaned:
        cleaned = cleaned.replace("--", "-")
    return cleaned.strip("-") or "company"


def tenant_db_path(company_row) -> Path:
    path = (TENANT_DB_ROOT / company_row["db_filename"]).resolve()
    root = TENANT_DB_ROOT.resolve()
    if root not in path.parents:
        raise ValueError("Calea bazei companiei este invalidă.")
    return path


def tenant_documents_path(company_row) -> Path:
    path = (DOCUMENT_ROOT / company_row["documents_subdir"]).resolve()
    root = DOCUMENT_ROOT.resolve()
    if path != root and root not in path.parents:
        raise ValueError("Calea documentelor companiei este invalidă.")
    return path



def copy_standard_templates_to_company(company_documents_path: Path) -> int:
    """Copy missing standard templates into a company-local sabloane folder."""
    source = TEMPLATE_ROOT / "standard"
    destination = company_documents_path / "sabloane"
    destination.mkdir(parents=True, exist_ok=True)
    if not source.is_dir():
        return 0
    copied = 0
    for item in sorted(source.iterdir()):
        if not item.is_file() or item.name.startswith("."):
            continue
        target = destination / item.name
        if target.exists():
            continue
        shutil.copy2(item, target)
        copied += 1
    return copied

def tenant_connect(company_row) -> sqlite3.Connection:
    path = tenant_db_path(company_row)
    if not path.exists():
        raise FileNotFoundError(f"Baza companiei lipsește: {path.name}")
    return configure_connection(sqlite3.connect(path, timeout=10))


def ensure_tenant_schema(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with configure_connection(sqlite3.connect(path, timeout=10)) as con:
        # The schema is idempotent, so missing tables from interrupted provisioning are restored.
        con.executescript(EMPTY_TENANT_SCHEMA)
        columns = {row["name"] for row in con.execute("PRAGMA table_info(audit_log)")}
        if "user_email" not in columns:
            con.execute("ALTER TABLE audit_log ADD COLUMN user_email TEXT")
        con.executescript(
            """
            CREATE TABLE IF NOT EXISTS document_versions(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
                version_no INTEGER NOT NULL,
                version_type TEXT NOT NULL DEFAULT 'SIGNED_PDF' CHECK(version_type IN ('SIGNED_PDF')),
                stored_path TEXT NOT NULL,
                original_filename TEXT NOT NULL,
                mime_type TEXT NOT NULL DEFAULT 'application/pdf',
                size_bytes INTEGER NOT NULL DEFAULT 0 CHECK(size_bytes>=0),
                sha256 TEXT NOT NULL,
                notes TEXT,
                uploaded_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                uploaded_by TEXT,
                UNIQUE(document_id,version_no),
                UNIQUE(document_id,sha256)
            );
            CREATE INDEX IF NOT EXISTS idx_document_versions_document
                ON document_versions(document_id,version_no DESC);
            CREATE TABLE IF NOT EXISTS document_word_versions(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
                version_no INTEGER NOT NULL,
                stored_path TEXT NOT NULL,
                original_filename TEXT NOT NULL,
                mime_type TEXT NOT NULL DEFAULT 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
                size_bytes INTEGER NOT NULL DEFAULT 0 CHECK(size_bytes>=0),
                sha256 TEXT NOT NULL,
                notes TEXT,
                is_current INTEGER NOT NULL DEFAULT 0,
                uploaded_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                uploaded_by TEXT,
                UNIQUE(document_id,version_no),
                UNIQUE(document_id,sha256)
            );
            CREATE INDEX IF NOT EXISTS idx_document_word_versions_document
                ON document_word_versions(document_id,version_no DESC);
            CREATE UNIQUE INDEX IF NOT EXISTS idx_document_word_versions_current
                ON document_word_versions(document_id) WHERE is_current=1;
            CREATE TABLE IF NOT EXISTS generated_pdf_versions(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
                word_version_id INTEGER REFERENCES document_word_versions(id) ON DELETE SET NULL,
                version_no INTEGER NOT NULL,
                stored_path TEXT NOT NULL,
                original_filename TEXT NOT NULL,
                mime_type TEXT NOT NULL DEFAULT 'application/pdf',
                size_bytes INTEGER NOT NULL DEFAULT 0 CHECK(size_bytes>=0),
                sha256 TEXT NOT NULL,
                generated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                generated_by TEXT,
                notes TEXT,
                UNIQUE(document_id,version_no),
                UNIQUE(document_id,sha256)
            );
            CREATE INDEX IF NOT EXISTS idx_generated_pdf_versions_document
                ON generated_pdf_versions(document_id,version_no DESC);
            """
        )
        con.execute("INSERT OR REPLACE INTO settings(key,value) VALUES('schema_version','4')")
        con.commit()


def sync_tenant_company(path: Path, company_data: dict) -> None:
    ensure_tenant_schema(path)
    with configure_connection(sqlite3.connect(path, timeout=10)) as con:
        con.execute(
            """INSERT INTO company(id,name,cui,reg_com,address,administrator,updated_at)
               VALUES(1,?,?,?,?,?,?)
               ON CONFLICT(id) DO UPDATE SET
                 name=excluded.name,cui=excluded.cui,reg_com=excluded.reg_com,
                 address=excluded.address,administrator=excluded.administrator,
                 updated_at=excluded.updated_at""",
            (
                str(company_data.get("name") or "").strip(),
                str(company_data.get("cui") or "").strip(),
                str(company_data.get("reg_com") or "").strip(),
                str(company_data.get("address") or "").strip(),
                str(company_data.get("administrator") or "").strip(),
                utcnow(),
            ),
        )
        con.commit()


REQUIRED_TENANT_TABLES = {
    "company", "associates", "loans", "transactions", "interest_accruals",
    "bnr_reference_rates", "interest_segments", "documents", "document_versions",
    "document_word_versions", "generated_pdf_versions", "audit_log", "settings",
}


def tenant_database_status(company_row) -> dict:
    path = tenant_db_path(company_row)
    result = {
        "path": str(path),
        "filename": path.name,
        "exists": path.is_file(),
        "size_bytes": path.stat().st_size if path.is_file() else 0,
        "ok": False,
        "integrity": "MISSING" if not path.is_file() else "UNKNOWN",
        "missing_tables": [],
        "company_row": False,
        "error": "",
    }
    if not path.is_file():
        return result
    try:
        with sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=10) as con:
            integrity_row = con.execute("PRAGMA quick_check").fetchone()
            result["integrity"] = str(integrity_row[0] if integrity_row else "UNKNOWN")
            tables = {row[0] for row in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            result["missing_tables"] = sorted(REQUIRED_TENANT_TABLES - tables)
            if "company" in tables:
                result["company_row"] = bool(con.execute("SELECT 1 FROM company WHERE id=1").fetchone())
            result["ok"] = (
                result["integrity"].lower() == "ok"
                and not result["missing_tables"]
                and result["company_row"]
            )
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
    return result


def create_tenant_database(
    target: Path,
    *,
    seed_path: Path | None = None,
    company_data: dict | None = None,
) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        raise FileExistsError(target)
    temp_target = target.with_name(f".{target.name}.{uuid.uuid4().hex}.creating")
    try:
        if seed_path:
            shutil.copy2(seed_path, temp_target)
        else:
            sqlite3.connect(temp_target).close()
        ensure_tenant_schema(temp_target)
        if company_data:
            sync_tenant_company(temp_target, company_data)
        # Provisioning helpers use WAL in normal runtime. Before the atomic rename,
        # merge the WAL into the database, close that connection, then switch back
        # to a single-file journal. Fetching the PRAGMA result releases its cursor.
        with sqlite3.connect(temp_target, timeout=10, isolation_level=None) as con:
            checkpoint = con.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
            if checkpoint and int(checkpoint[0]) != 0:
                raise sqlite3.OperationalError(f"Checkpoint WAL ocupat: {checkpoint}")
        with sqlite3.connect(temp_target, timeout=10, isolation_level=None) as con:
            check = con.execute("PRAGMA quick_check").fetchone()
            if not check or str(check[0]).lower() != "ok":
                raise sqlite3.DatabaseError(f"PRAGMA quick_check: {check[0] if check else 'fără rezultat'}")
        for sidecar in (Path(str(temp_target) + "-wal"), Path(str(temp_target) + "-shm")):
            sidecar.unlink(missing_ok=True)
        os.chmod(temp_target, 0o600)
        os.replace(temp_target, target)
    except Exception:
        temp_target.unlink(missing_ok=True)
        Path(str(temp_target) + "-wal").unlink(missing_ok=True)
        Path(str(temp_target) + "-shm").unlink(missing_ok=True)
        raise


def repair_tenant_database(company_row) -> dict:
    path = tenant_db_path(company_row)
    company_data = dict(company_row)
    created = False
    if not path.exists():
        create_tenant_database(path, company_data=company_data)
        created = True
    else:
        ensure_tenant_schema(path)
        sync_tenant_company(path, company_data)
        os.chmod(path, 0o600)
    status = tenant_database_status(company_row)
    status["created"] = created
    return status


def register_company(con: sqlite3.Connection, *, slug: str, name: str, cui: str, reg_com: str = "", address: str = "", administrator: str = "", db_filename: str | None = None, documents_subdir: str | None = None) -> int:
    slug = safe_filename(slug)
    db_filename = db_filename or f"{slug}.sqlite"
    documents_subdir = documents_subdir or slug
    cur = con.execute(
        """INSERT INTO companies(slug,name,cui,reg_com,address,administrator,db_filename,documents_subdir)
           VALUES(?,?,?,?,?,?,?,?)""",
        (slug, name, cui, reg_com, address, administrator, db_filename, documents_subdir),
    )
    return int(cur.lastrowid)


@contextmanager
def transaction(con: sqlite3.Connection):
    try:
        yield con
        con.commit()
    except Exception:
        con.rollback()
        raise
