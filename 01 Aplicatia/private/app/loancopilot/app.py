from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import shutil
import sqlite3
import zipfile
from xml.etree import ElementTree as ET
from datetime import date, datetime, timedelta, timezone
from functools import wraps
from pathlib import Path
from urllib.parse import urlparse

import qrcode
from flask import Flask, Response, abort, g, jsonify, make_response, redirect, render_template, request, send_file, url_for
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from werkzeug.exceptions import HTTPException
from werkzeug.utils import secure_filename

from . import business
from .anaf import AnafLookupError, lookup_company, normalize_cui
from .docx_print import render_docx_for_print
from .config import (
    APP_VERSION,
    BACKUP_ROOT,
    BNR_RATE_URLS,
    COOKIE_SECURE,
    TEMPLATE_ROOT,
    MAX_CONTENT_LENGTH,
    PREAUTH_COOKIE,
    SESSION_COOKIE,
    SESSION_HOURS,
    TRUST_PROXY,
    ensure_directories,
)
from .db import (
    auth_connect,
    copy_standard_templates_to_company,
    create_tenant_database,
    init_auth_db,
    register_company,
    repair_tenant_database,
    safe_filename,
    tenant_connect,
    tenant_database_status,
    tenant_db_path,
    tenant_documents_path,
    utcnow,
)
from .security import (
    app_secret,
    create_totp_secret,
    decrypt_text,
    encrypt_text,
    generate_recovery_codes,
    hash_password,
    hash_recovery_code,
    hash_recovery_codes,
    provisioning_uri,
    random_token,
    stable_hmac,
    token_hash,
    validate_password,
    verify_password,
    verify_totp,
)

ROLE_LEVEL = {"VIEWER": 10, "EDITOR": 20, "ADMIN": 30}

TEMPLATE_DESCRIPTIONS = {
    "00_Ghid_completare_sabloane.txt": "Instrucțiuni și lista câmpurilor de completat.",
    "01_Hotarare_AGA_contractare_imprumut_asociat.docx": "Aprobarea contractării împrumutului asociat.",
    "02_Contract_cadru_imprumut_asociat_fara_dobanda.docx": "Contract-cadru inițial, fără dobândă.",
    "03_Hotarare_AGA_prelungire_imprumut.docx": "Aprobarea prelungirii duratei împrumutului.",
    "04_Act_aditional_1_prelungire.docx": "Act adițional pentru prelungirea scadenței.",
    "05_Nota_explicativa_finantare_capital_lucru_si_gestiune_creante.docx": "Justificarea economică, financiar-contabilă și fiscală a finanțării.",
    "06_Proces_verbal_confirmare_sold_4551.docx": "Confirmarea și repartizarea soldului contului 4551.",
    "07_Hotarare_AGA_stabilire_dobanda_BNR.docx": "Aprobarea remunerării prin rata de referință BNR.",
    "08_Act_aditional_2_dobanda_BNR.docx": "Act adițional pentru dobânda variabilă BNR.",
    "09_Proces_verbal_reconciliere_sold.docx": "Reconcilierea soldurilor și a diferențelor de deschidere.",
    "10_Fisa_calcul_dobanda_si_nota_contabila.docx": "Calculul pe subperioade și propunerea de note contabile.",
    "11_Checklist_juridic_contabil_fiscal.docx": "Controlul dosarului contractual și fiscal.",
}
ALLOWED_TEMPLATE_EXTENSIONS = {".docx", ".xlsx", ".odt", ".txt", ".pdf"}
DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def validate_docx_file(path: Path) -> bool:
    try:
        with zipfile.ZipFile(path) as archive:
            names = set(archive.namelist())
            return "[Content_Types].xml" in names and "word/document.xml" in names
    except (OSError, zipfile.BadZipFile):
        return False


def utc_dt() -> datetime:
    return datetime.now(timezone.utc)


def parse_utc(value: str) -> datetime:
    return datetime.fromisoformat(value)


def client_ip() -> str:
    if TRUST_PROXY:
        forwarded = request.headers.get("X-Forwarded-For", "")
        if forwarded:
            return forwarded.split(",", 1)[0].strip()
    return request.remote_addr or "unknown"


def request_fingerprint() -> tuple[str, str]:
    ip_hash = stable_hmac(f"ip:{client_ip()}")
    ua_hash = stable_hmac(f"ua:{request.headers.get('User-Agent', '')[:500]}")
    return ip_hash, ua_hash


def json_error(message: str, status: int = 400):
    return jsonify(ok=False, error=message), status


def is_safe_source_url(value: str | None) -> bool:
    if not value:
        return True
    parsed = urlparse(value)
    return parsed.scheme == "https" and parsed.hostname in {"bnr.ro", "www.bnr.ro"}


def security_audit(action: str, *, user_id: int | None = None, company_id: int | None = None, details: str = "") -> None:
    ip_hash, _ = request_fingerprint()
    with auth_connect() as con:
        con.execute(
            "INSERT INTO security_audit(user_id,company_id,action,ip_hash,details) VALUES(?,?,?,?,?)",
            (user_id, company_id, action, ip_hash, details[:2000]),
        )
        con.commit()


def session_cookie(response, token: str, expires: datetime):
    response.set_cookie(
        SESSION_COOKIE,
        token,
        expires=expires,
        secure=COOKIE_SECURE,
        httponly=True,
        samesite="Lax",
        path="/",
    )
    return response


def clear_auth_cookies(response):
    response.delete_cookie(SESSION_COOKIE, path="/")
    response.delete_cookie(PREAUTH_COOKIE, path="/")
    return response


def company_memberships(con: sqlite3.Connection, user_id: int, is_superadmin: bool) -> list[sqlite3.Row]:
    if is_superadmin:
        return con.execute(
            """SELECT c.*, 'ADMIN' role FROM companies c WHERE c.active=1 ORDER BY c.name"""
        ).fetchall()
    return con.execute(
        """SELECT c.*,uc.role FROM user_companies uc JOIN companies c ON c.id=uc.company_id
           WHERE uc.user_id=? AND c.active=1 ORDER BY c.name""",
        (user_id,),
    ).fetchall()


def create_auth_session(user_id: int, *, preferred_company_id: int | None = None) -> tuple[str, datetime]:
    raw_token = random_token(40)
    csrf = random_token(24)
    now = utc_dt()
    expires = now + timedelta(hours=SESSION_HOURS)
    ip_hash, ua_hash = request_fingerprint()
    with auth_connect() as con:
        user = con.execute("SELECT * FROM users WHERE id=? AND active=1", (user_id,)).fetchone()
        if not user:
            raise ValueError("Utilizator inactiv.")
        memberships = company_memberships(con, user_id, bool(user["is_superadmin"]))
        company_ids = {int(row["id"]) for row in memberships}
        current_company_id = preferred_company_id if preferred_company_id in company_ids else (next(iter(company_ids), None))
        con.execute(
            """INSERT INTO auth_sessions(token_hash,user_id,current_company_id,csrf_token,ip_hash,user_agent_hash,
               created_at,expires_at,last_seen_at) VALUES(?,?,?,?,?,?,?,?,?)""",
            (token_hash(raw_token), user_id, current_company_id, csrf, ip_hash, ua_hash, now.isoformat(), expires.isoformat(), now.isoformat()),
        )
        con.execute("UPDATE users SET last_login_at=?,updated_at=? WHERE id=?", (now.isoformat(), now.isoformat(), user_id))
        con.commit()
    return raw_token, expires


def revoke_session(raw_token: str | None) -> None:
    if not raw_token:
        return
    with auth_connect() as con:
        con.execute("UPDATE auth_sessions SET revoked_at=? WHERE token_hash=? AND revoked_at IS NULL", (utcnow(), token_hash(raw_token)))
        con.commit()


def create_app() -> Flask:
    ensure_directories()
    init_auth_db()
    # Aplică migrațiile de schemă separat fiecărei baze deja înregistrate.
    from .db import ensure_tenant_schema
    with auth_connect() as migration_con:
        for company_row in migration_con.execute("SELECT * FROM companies WHERE active=1").fetchall():
            path = tenant_db_path(company_row)
            if path.exists():
                ensure_tenant_schema(path)
    app = Flask(__name__, template_folder="templates", static_folder="static")
    app.config.update(
        MAX_CONTENT_LENGTH=MAX_CONTENT_LENGTH,
        JSON_AS_ASCII=False,
        SECRET_KEY=app_secret(),
    )
    preauth_serializer = URLSafeTimedSerializer(app_secret(), salt="loancopilot-preauth")

    @app.before_request
    def load_identity():
        g.user = None
        g.auth_session = None
        g.company = None
        g.role = None
        raw = request.cookies.get(SESSION_COOKIE)
        if not raw:
            return None
        now = utc_dt()
        with auth_connect() as con:
            row = con.execute(
                """SELECT s.*,u.email,u.display_name,u.active,u.is_superadmin,u.totp_enabled
                   FROM auth_sessions s JOIN users u ON u.id=s.user_id
                   WHERE s.token_hash=? AND s.revoked_at IS NULL""",
                (token_hash(raw),),
            ).fetchone()
            if not row or not row["active"] or parse_utc(row["expires_at"]) <= now:
                return None
            ip_hash, ua_hash = request_fingerprint()
            if row["user_agent_hash"] and row["user_agent_hash"] != ua_hash:
                con.execute("UPDATE auth_sessions SET revoked_at=? WHERE id=?", (now.isoformat(), row["id"]))
                con.commit()
                return None
            g.auth_session = dict(row)
            g.user = {
                "id": row["user_id"],
                "email": row["email"],
                "display_name": row["display_name"],
                "is_superadmin": bool(row["is_superadmin"]),
                "totp_enabled": bool(row["totp_enabled"]),
            }
            memberships = company_memberships(con, int(row["user_id"]), bool(row["is_superadmin"]))
            membership_by_id = {int(item["id"]): item for item in memberships}
            current_id = row["current_company_id"]
            if current_id not in membership_by_id and memberships:
                current_id = memberships[0]["id"]
                con.execute("UPDATE auth_sessions SET current_company_id=? WHERE id=?", (current_id, row["id"]))
            if current_id in membership_by_id:
                g.company = dict(membership_by_id[current_id])
                g.role = "ADMIN" if g.user["is_superadmin"] else membership_by_id[current_id]["role"]
            last_seen = parse_utc(row["last_seen_at"])
            if now - last_seen > timedelta(minutes=5):
                con.execute("UPDATE auth_sessions SET last_seen_at=? WHERE id=?", (now.isoformat(), row["id"]))
            con.commit()
        return None

    @app.before_request
    def csrf_guard():
        if request.method in {"POST", "PUT", "PATCH", "DELETE"} and request.path.startswith("/api/"):
            if not g.user:
                return json_error("Autentificare necesară.", 401)
            supplied = request.headers.get("X-CSRF-Token", "")
            expected = g.auth_session["csrf_token"]
            if not supplied or not secrets_compare(supplied, expected):
                return json_error("Token CSRF invalid. Reîncărcați pagina.", 403)
        return None

    @app.after_request
    def security_headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
            "script-src 'self' 'unsafe-inline'; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
        )
        if request.is_secure or request.headers.get("X-Forwarded-Proto") == "https":
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        if request.path.startswith("/api/") or request.path in {"/login", "/two-factor", "/profile/security"}:
            response.headers["Cache-Control"] = "no-store"
        return response

    def auth_required(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if not g.user:
                if request.path.startswith("/api/"):
                    return json_error("Autentificare necesară.", 401)
                return redirect(url_for("login", next=request.full_path))
            return view(*args, **kwargs)
        return wrapped

    def company_required(view):
        @wraps(view)
        @auth_required
        def wrapped(*args, **kwargs):
            if not g.company:
                if request.path.startswith("/api/"):
                    return json_error("Utilizatorul nu are acces la nicio companie.", 403)
                return render_template("no_company.html", user=g.user), 403
            return view(*args, **kwargs)
        return wrapped

    def role_required(min_role: str):
        def decorator(view):
            @wraps(view)
            @company_required
            def wrapped(*args, **kwargs):
                if ROLE_LEVEL.get(g.role or "", 0) < ROLE_LEVEL[min_role]:
                    return json_error("Nu aveți drepturi pentru această operațiune.", 403)
                return view(*args, **kwargs)
            return wrapped
        return decorator

    def tenant():
        return tenant_connect(g.company)

    def payload() -> dict:
        return request.get_json(silent=True) or {}

    def normalize_company_updates(data: dict, *, allow_active: bool) -> dict:
        values = {
            "name": str(data.get("name") or "").strip(),
            "cui": str(data.get("cui") or "").strip(),
            "reg_com": str(data.get("reg_com") or "").strip(),
            "address": str(data.get("address") or "").strip(),
            "administrator": str(data.get("administrator") or "").strip(),
        }
        if not values["name"]:
            raise ValueError("Denumirea companiei este obligatorie.")
        if not values["cui"]:
            raise ValueError("CUI-ul companiei este obligatoriu.")
        limits = {"name": 250, "cui": 40, "reg_com": 80, "address": 1000, "administrator": 250}
        for field, limit in limits.items():
            if len(values[field]) > limit:
                raise ValueError(f"Câmpul {field} depășește limita de {limit} caractere.")
        if allow_active and "active" in data:
            raw_active = data.get("active")
            if isinstance(raw_active, str):
                values["active"] = 0 if raw_active.strip().lower() in {"0", "false", "nu", "off", ""} else 1
            else:
                values["active"] = 1 if bool(raw_active) else 0
        return values

    def update_company_records(company_id: int, data: dict, *, allow_active: bool) -> dict:
        updates = normalize_company_updates(data, allow_active=allow_active)
        with auth_connect() as auth_con:
            company_row = auth_con.execute("SELECT * FROM companies WHERE id=?", (company_id,)).fetchone()
            if not company_row:
                raise LookupError("Compania nu există.")
            tenant_path = tenant_db_path(company_row)
            if not tenant_path.is_file():
                raise FileNotFoundError(f"Baza SQLite a companiei lipsește: {tenant_path.name}")
            set_clause = ",".join(f"{field}=?" for field in updates)
            auth_con.execute(
                f"UPDATE companies SET {set_clause},updated_at=? WHERE id=?",
                [*updates.values(), utcnow(), company_id],
            )
            with tenant_connect(company_row) as tenant_con:
                tenant_values = {key: value for key, value in updates.items() if key != "active"}
                tenant_con.execute(
                    """INSERT INTO company(id,name,cui,reg_com,address,administrator,updated_at)
                       VALUES(1,?,?,?,?,?,?)
                       ON CONFLICT(id) DO UPDATE SET
                         name=excluded.name,cui=excluded.cui,reg_com=excluded.reg_com,
                         address=excluded.address,administrator=excluded.administrator,
                         updated_at=excluded.updated_at""",
                    (
                        tenant_values["name"], tenant_values["cui"], tenant_values["reg_com"],
                        tenant_values["address"], tenant_values["administrator"], utcnow(),
                    ),
                )
                business.audit(
                    tenant_con,
                    "UPDATE",
                    "company",
                    entity_id=1,
                    details=json.dumps(updates, ensure_ascii=False),
                    user_email=g.user["email"],
                )
                tenant_con.commit()
            auth_con.commit()
            updated = auth_con.execute("SELECT * FROM companies WHERE id=?", (company_id,)).fetchone()
        security_audit(
            "COMPANY_UPDATED",
            user_id=g.user["id"],
            company_id=company_id,
            details=json.dumps(updates, ensure_ascii=False),
        )
        return dict(updated)

    def company_with_storage(company_row) -> dict:
        item = dict(company_row)
        status = tenant_database_status(company_row)
        docs_path = tenant_documents_path(company_row)
        templates_path = docs_path / "sabloane"
        item.update(
            db_exists=bool(status["exists"]),
            db_ok=bool(status["ok"]),
            db_integrity=status["integrity"],
            db_size_bytes=int(status["size_bytes"]),
            db_missing_tables=status["missing_tables"],
            db_error=status["error"],
            db_path=status["path"],
            documents_exists=docs_path.is_dir(),
            documents_path=str(docs_path),
            company_template_count=(
                sum(1 for entry in templates_path.iterdir() if entry.is_file())
                if templates_path.is_dir() else 0
            ),
        )
        return item

    @app.get("/health")
    def health():
        return jsonify(ok=True, app="LoanCopilot", version=APP_VERSION)

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if g.user:
            return redirect(url_for("index"))
        error = None
        if request.method == "POST":
            email = (request.form.get("email") or "").strip().lower()
            password = request.form.get("password") or ""
            ip_hash, _ = request_fingerprint()
            identity_hash = stable_hmac(f"login:{email}")
            cutoff = (utc_dt() - timedelta(minutes=15)).isoformat()
            with auth_connect() as con:
                failures = con.execute(
                    "SELECT COUNT(*) FROM login_attempts WHERE identity_hash=? AND ip_hash=? AND attempted_at>=? AND success=0",
                    (identity_hash, ip_hash, cutoff),
                ).fetchone()[0]
                if failures >= 8:
                    error = "Prea multe încercări. Reîncercați după 15 minute."
                else:
                    user = con.execute("SELECT * FROM users WHERE email=? COLLATE NOCASE", (email,)).fetchone()
                    valid = bool(user and user["active"] and verify_password(password, user["password_hash"]))
                    con.execute(
                        "INSERT INTO login_attempts(identity_hash,ip_hash,attempted_at,success) VALUES(?,?,?,?)",
                        (identity_hash, ip_hash, utcnow(), int(valid)),
                    )
                    con.execute("DELETE FROM login_attempts WHERE attempted_at<?", ((utc_dt() - timedelta(days=2)).isoformat(),))
                    con.commit()
                    if not valid:
                        error = "Email sau parolă incorectă."
                    elif user["totp_enabled"]:
                        challenge_raw = random_token(32)
                        expires = utc_dt() + timedelta(minutes=5)
                        con.execute(
                            "INSERT INTO auth_challenges(token_hash,user_id,ip_hash,created_at,expires_at) VALUES(?,?,?,?,?)",
                            (token_hash(challenge_raw), user["id"], ip_hash, utcnow(), expires.isoformat()),
                        )
                        con.commit()
                        signed = preauth_serializer.dumps(challenge_raw)
                        response = redirect(url_for("two_factor"))
                        response.set_cookie(PREAUTH_COOKIE, signed, max_age=300, secure=COOKIE_SECURE, httponly=True, samesite="Strict", path="/")
                        security_audit("LOGIN_PASSWORD_OK_2FA_PENDING", user_id=user["id"])
                        return response
                    else:
                        raw, expires = create_auth_session(int(user["id"]))
                        response = redirect(url_for("index"))
                        session_cookie(response, raw, expires)
                        security_audit("LOGIN_SUCCESS", user_id=user["id"])
                        return response
            if error:
                security_audit("LOGIN_FAILED", details=f"identity={identity_hash[:12]}")
        return render_template("login.html", error=error, version=APP_VERSION)

    @app.route("/two-factor", methods=["GET", "POST"])
    def two_factor():
        signed = request.cookies.get(PREAUTH_COOKIE)
        if not signed:
            return redirect(url_for("login"))
        try:
            challenge_raw = preauth_serializer.loads(signed, max_age=300)
        except (BadSignature, SignatureExpired):
            response = redirect(url_for("login"))
            response.delete_cookie(PREAUTH_COOKIE, path="/")
            return response
        error = None
        with auth_connect() as con:
            challenge = con.execute(
                """SELECT ch.*,u.email,u.totp_secret_enc,u.recovery_hashes,u.active
                   FROM auth_challenges ch JOIN users u ON u.id=ch.user_id WHERE ch.token_hash=?""",
                (token_hash(challenge_raw),),
            ).fetchone()
            if not challenge or not challenge["active"] or parse_utc(challenge["expires_at"]) <= utc_dt():
                error = "Sesiunea de verificare a expirat."
            elif request.method == "POST":
                code = request.form.get("code") or ""
                secret = decrypt_text(challenge["totp_secret_enc"])
                valid = bool(secret and verify_totp(secret, code))
                recovery_hashes = json.loads(challenge["recovery_hashes"] or "[]")
                recovery_hash = hash_recovery_code(code)
                used_recovery = recovery_hash in recovery_hashes
                if used_recovery:
                    valid = True
                    recovery_hashes.remove(recovery_hash)
                    con.execute("UPDATE users SET recovery_hashes=? WHERE id=?", (json.dumps(recovery_hashes), challenge["user_id"]))
                if valid:
                    con.execute("DELETE FROM auth_challenges WHERE token_hash=?", (token_hash(challenge_raw),))
                    con.commit()
                    raw, expires = create_auth_session(int(challenge["user_id"]))
                    response = redirect(url_for("index"))
                    session_cookie(response, raw, expires)
                    response.delete_cookie(PREAUTH_COOKIE, path="/")
                    security_audit("LOGIN_2FA_SUCCESS", user_id=challenge["user_id"], details="recovery_code" if used_recovery else "totp")
                    return response
                error = "Codul de autentificare este invalid."
                security_audit("LOGIN_2FA_FAILED", user_id=challenge["user_id"])
        return render_template("two_factor.html", error=error)

    @app.post("/logout")
    @auth_required
    def logout():
        raw = request.cookies.get(SESSION_COOKIE)
        security_audit("LOGOUT", user_id=g.user["id"], company_id=g.company["id"] if g.company else None)
        revoke_session(raw)
        response = redirect(url_for("login"))
        return clear_auth_cookies(response)

    @app.get("/")
    @company_required
    def index():
        with auth_connect() as con:
            memberships = [dict(row) for row in company_memberships(con, g.user["id"], g.user["is_superadmin"])]
        return render_template(
            "app.html",
            user=g.user,
            company=g.company,
            role=g.role,
            companies=memberships,
            csrf_token=g.auth_session["csrf_token"],
            version=APP_VERSION,
        )

    @app.get("/profile/security")
    @auth_required
    def profile_security():
        return render_template("security.html", user=g.user, csrf_token=g.auth_session["csrf_token"], version=APP_VERSION)

    @app.get("/admin")
    @auth_required
    def admin_page():
        if not g.user["is_superadmin"] and g.role != "ADMIN":
            abort(403)
        return render_template("admin.html", user=g.user, company=g.company, csrf_token=g.auth_session["csrf_token"], version=APP_VERSION)

    @app.get("/api/auth/me")
    @auth_required
    def api_me():
        with auth_connect() as con:
            memberships = [dict(row) for row in company_memberships(con, g.user["id"], g.user["is_superadmin"])]
        return jsonify(ok=True, user=g.user, company=g.company, role=g.role, companies=memberships, csrf_token=g.auth_session["csrf_token"])

    @app.post("/api/anaf/company-lookup")
    @auth_required
    def api_anaf_company_lookup():
        if not (g.user["is_superadmin"] or g.role == "ADMIN"):
            return json_error("Doar administratorii pot prelua datele unei companii din ANAF.", 403)
        data = payload()
        try:
            cui = normalize_cui(data.get("cui"))
            result = lookup_company(cui, data.get("data"))
        except ValueError as exc:
            return json_error(str(exc), 400)
        except AnafLookupError as exc:
            app.logger.warning("ANAF lookup failed for CUI %s: %s", data.get("cui"), exc)
            return json_error(str(exc), 502)
        except Exception as exc:
            app.logger.exception("Unexpected ANAF lookup failure")
            return json_error(f"Interogarea ANAF a eșuat: {type(exc).__name__}: {exc}", 500)
        item = result.as_dict()
        security_audit(
            "ANAF_COMPANY_LOOKUP",
            user_id=g.user["id"],
            company_id=g.company["id"] if g.company else None,
            details=json.dumps(
                {
                    "cui": item["cui"],
                    "queried_date": item["queried_date"],
                    "name": item["name"],
                    "registration_status": item["registration_status"],
                    "vat_registered": item["vat_registered"],
                    "inactive": item["inactive"],
                },
                ensure_ascii=False,
            ),
        )
        return jsonify(ok=True, item=item)

    @app.post("/api/auth/company")
    @auth_required
    def api_switch_company():
        company_id = int(payload().get("company_id") or 0)
        with auth_connect() as con:
            allowed = {int(row["id"]) for row in company_memberships(con, g.user["id"], g.user["is_superadmin"])}
            if company_id not in allowed:
                return json_error("Nu aveți acces la compania selectată.", 403)
            con.execute("UPDATE auth_sessions SET current_company_id=? WHERE id=?", (company_id, g.auth_session["id"]))
            con.commit()
        security_audit("SWITCH_COMPANY", user_id=g.user["id"], company_id=company_id)
        return jsonify(ok=True)

    @app.post("/api/profile/password")
    @auth_required
    def api_change_password():
        data = payload()
        current_password = data.get("current_password") or ""
        new_password = data.get("new_password") or ""
        validate_password(new_password)
        with auth_connect() as con:
            user = con.execute("SELECT * FROM users WHERE id=?", (g.user["id"],)).fetchone()
            if not verify_password(current_password, user["password_hash"]):
                return json_error("Parola curentă este incorectă.", 400)
            con.execute(
                "UPDATE users SET password_hash=?,password_changed_at=?,updated_at=? WHERE id=?",
                (hash_password(new_password), utcnow(), utcnow(), g.user["id"]),
            )
            con.execute("UPDATE auth_sessions SET revoked_at=? WHERE user_id=? AND id<>?", (utcnow(), g.user["id"], g.auth_session["id"]))
            con.commit()
        security_audit("PASSWORD_CHANGED", user_id=g.user["id"])
        return jsonify(ok=True)

    @app.post("/api/profile/2fa/start")
    @auth_required
    def api_2fa_start():
        password = payload().get("password") or ""
        with auth_connect() as con:
            user = con.execute("SELECT * FROM users WHERE id=?", (g.user["id"],)).fetchone()
            if not verify_password(password, user["password_hash"]):
                return json_error("Parola este incorectă.", 400)
            secret = create_totp_secret()
            con.execute("UPDATE users SET totp_pending_secret_enc=?,updated_at=? WHERE id=?", (encrypt_text(secret), utcnow(), g.user["id"]))
            con.commit()
        uri = provisioning_uri(secret, g.user["email"])
        image = qrcode.make(uri)
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        qr = "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")
        return jsonify(ok=True, secret=secret, provisioning_uri=uri, qr=qr)

    @app.post("/api/profile/2fa/confirm")
    @auth_required
    def api_2fa_confirm():
        code = payload().get("code") or ""
        with auth_connect() as con:
            user = con.execute("SELECT * FROM users WHERE id=?", (g.user["id"],)).fetchone()
            secret = decrypt_text(user["totp_pending_secret_enc"])
            if not secret or not verify_totp(secret, code):
                return json_error("Cod TOTP invalid.", 400)
            recovery_codes = generate_recovery_codes()
            con.execute(
                """UPDATE users SET totp_enabled=1,totp_secret_enc=?,totp_pending_secret_enc=NULL,
                   recovery_hashes=?,updated_at=? WHERE id=?""",
                (encrypt_text(secret), hash_recovery_codes(recovery_codes), utcnow(), g.user["id"]),
            )
            con.commit()
        security_audit("2FA_ENABLED", user_id=g.user["id"])
        return jsonify(ok=True, recovery_codes=recovery_codes)

    @app.post("/api/profile/2fa/disable")
    @auth_required
    def api_2fa_disable():
        data = payload()
        with auth_connect() as con:
            user = con.execute("SELECT * FROM users WHERE id=?", (g.user["id"],)).fetchone()
            secret = decrypt_text(user["totp_secret_enc"])
            if not verify_password(data.get("password") or "", user["password_hash"]):
                return json_error("Parola este incorectă.", 400)
            if not secret or not verify_totp(secret, data.get("code") or ""):
                return json_error("Codul TOTP este invalid.", 400)
            con.execute(
                "UPDATE users SET totp_enabled=0,totp_secret_enc=NULL,totp_pending_secret_enc=NULL,recovery_hashes=NULL,updated_at=? WHERE id=?",
                (utcnow(), g.user["id"]),
            )
            con.commit()
        security_audit("2FA_DISABLED", user_id=g.user["id"])
        return jsonify(ok=True)

    # ----- Business API, isolated by selected company -----
    @app.get("/api/dashboard")
    @company_required
    def api_dashboard():
        with tenant() as con:
            return jsonify(ok=True, **business.dashboard(con))

    @app.get("/api/company")
    @company_required
    def api_company():
        with tenant() as con:
            row = con.execute("SELECT * FROM company LIMIT 1").fetchone()
        item = dict(row) if row else {"name": g.company["name"], "cui": g.company["cui"]}
        storage = tenant_database_status(g.company)
        item.update(
            db_filename=g.company["db_filename"],
            db_path=storage["path"],
            db_exists=bool(storage["exists"]),
            db_ok=bool(storage["ok"]),
            db_integrity=storage["integrity"],
            db_size_bytes=int(storage["size_bytes"]),
            db_missing_tables=storage["missing_tables"],
            db_error=storage["error"],
            documents_subdir=g.company["documents_subdir"],
        )
        return jsonify(ok=True, item=item)

    @app.patch("/api/company")
    @role_required("ADMIN")
    def api_update_current_company():
        try:
            item = update_company_records(int(g.company["id"]), payload(), allow_active=False)
        except ValueError as exc:
            return json_error(str(exc), 400)
        except LookupError as exc:
            return json_error(str(exc), 404)
        return jsonify(ok=True, item=item)

    @app.get("/api/associates")
    @company_required
    def api_associates():
        with tenant() as con:
            rows = con.execute("SELECT * FROM associates ORDER BY name").fetchall()
            return jsonify(ok=True, items=business.rows_to_dicts(rows))

    @app.post("/api/associates")
    @role_required("EDITOR")
    def api_create_associate():
        data = payload()
        name = (data.get("name") or "").strip()
        if not name:
            return json_error("Numele asociatului / creditorului este obligatoriu.")
        try:
            share_pct = float(data.get("share_pct") or 0)
        except (TypeError, ValueError):
            return json_error("Cota trebuie să fie numerică.")
        if share_pct < 0 or share_pct > 100:
            return json_error("Cota trebuie să fie între 0 și 100%.")
        values = {
            "name": name,
            "share_pct": share_pct,
            "cnp": (data.get("cnp") or "").strip() or None,
            "id_doc": (data.get("id_doc") or "").strip() or None,
            "address": (data.get("address") or "").strip() or None,
            "email": (data.get("email") or "").strip() or None,
            "iban": (data.get("iban") or "").strip() or None,
            "active": 1,
        }
        with tenant() as con:
            cursor = con.execute(
                """INSERT INTO associates(name,share_pct,cnp,id_doc,address,email,iban,active)
                   VALUES(?,?,?,?,?,?,?,?)""",
                tuple(values[key] for key in ("name","share_pct","cnp","id_doc","address","email","iban","active")),
            )
            item_id = int(cursor.lastrowid)
            business.audit(
                con,
                "CREATE",
                "associates",
                entity_id=item_id,
                details=json.dumps(values, ensure_ascii=False),
                user_email=g.user["email"],
            )
            con.commit()
            row = con.execute("SELECT * FROM associates WHERE id=?", (item_id,)).fetchone()
        return jsonify(ok=True, item=dict(row)), 201

    @app.patch("/api/associates/<int:item_id>")
    @role_required("EDITOR")
    def api_update_associate(item_id: int):
        allowed = {"name", "share_pct", "cnp", "id_doc", "address", "email", "iban", "active"}
        data = {key: value for key, value in payload().items() if key in allowed}
        if not data:
            return json_error("Nu există câmpuri de actualizat.")
        with tenant() as con:
            con.execute(f"UPDATE associates SET {','.join(f'{key}=?' for key in data)} WHERE id=?", [*data.values(), item_id])
            business.audit(con, "UPDATE", "associates", entity_id=item_id, details=json.dumps(data, ensure_ascii=False), user_email=g.user["email"])
            con.commit()
        return jsonify(ok=True)

    @app.get("/api/loans")
    @company_required
    def api_loans():
        with tenant() as con:
            rows = con.execute(
                """SELECT l.*,a.name associate_name,b.funded AS funded_principal,b.repaid,b.balance,
                          COALESCE((SELECT SUM(calculated_amount) FROM interest_accruals ia WHERE ia.loan_id=l.id),0) interest_calculated,
                          COALESCE((SELECT SUM(recognized_amount) FROM interest_accruals ia WHERE ia.loan_id=l.id),0) interest_recognized,
                          COALESCE((SELECT SUM(amount) FROM transactions t WHERE t.loan_id=l.id AND t.txn_type='INTEREST_PAYMENT'),0) interest_paid
                   FROM loans l JOIN associates a ON a.id=l.associate_id JOIN loan_balances b ON b.loan_id=l.id
                   ORDER BY l.contract_date,l.id"""
            ).fetchall()
            return jsonify(ok=True, items=business.rows_to_dicts(rows))

    @app.post("/api/loans")
    @role_required("EDITOR")
    def api_create_loan():
        data = payload()
        required = ["contract_no", "contract_date", "associate_id", "principal"]
        missing = [key for key in required if data.get(key) in (None, "")]
        if missing:
            return json_error("Lipsesc: " + ", ".join(missing))
        with tenant() as con:
            cur = con.execute(
                """INSERT INTO loans(contract_no,original_contract_date,contract_date,interest_start_date,associate_id,
                   principal,interest_rate,maturity_date,calculation_basis,recognition_frequency,interest_due_rule,status,
                   notes,interest_rate_mode,interest_rate_source) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (data["contract_no"], data.get("original_contract_date") or data["contract_date"], data["contract_date"],
                 data.get("interest_start_date") or None, int(data["associate_id"]), float(data["principal"]),
                 float(data.get("interest_rate") or 0), data.get("maturity_date"), data.get("calculation_basis") or "ACTUAL_365",
                 data.get("recognition_frequency") or "QUARTERLY", data.get("interest_due_rule") or "ON_REQUEST",
                 data.get("status") or "ACTIVE", data.get("notes"), data.get("interest_rate_mode") or "BNR_REFERENCE",
                 data.get("interest_rate_source") or "Rata dobânzii de politică monetară BNR"),
            )
            con.execute(
                "INSERT INTO transactions(loan_id,txn_date,txn_type,amount,payment_method,reference) VALUES(?,?,'OPENING_BALANCE',?,'ACCOUNTING','Sold inițial')",
                (cur.lastrowid, data.get("original_contract_date") or data["contract_date"], float(data["principal"])),
            )
            business.audit(con, "CREATE", "loans", entity_id=cur.lastrowid, details=data["contract_no"], user_email=g.user["email"])
            con.commit()
        return jsonify(ok=True, id=cur.lastrowid)

    @app.patch("/api/loans/<int:item_id>")
    @role_required("EDITOR")
    def api_update_loan(item_id: int):
        allowed = {
            "original_contract_date",
            "contract_date",
            "interest_start_date",
            "interest_rate",
            "maturity_date",
            "status",
            "notes",
            "interest_rate_mode",
            "interest_rate_source",
        }
        incoming = payload()
        data = {key: incoming[key] for key in incoming if key in allowed}
        if not data:
            return json_error("Nu există câmpuri de actualizat.")

        date_fields = {"original_contract_date", "contract_date", "interest_start_date", "maturity_date"}
        for field in date_fields.intersection(data):
            value = str(data[field] or "").strip()
            if not value:
                if field in {"original_contract_date", "contract_date"}:
                    return json_error(f"Câmpul {field} este obligatoriu.")
                data[field] = None
                continue
            try:
                date.fromisoformat(value)
            except ValueError:
                return json_error(f"Data din câmpul {field} nu este validă.")
            data[field] = value

        if "status" in data:
            data["status"] = str(data["status"] or "").strip().upper()
            if data["status"] not in {"ACTIVE", "SUSPENDED", "CLOSED"}:
                return json_error("Statusul contractului nu este valid.")
        if "notes" in data:
            data["notes"] = str(data["notes"] or "").strip() or None

        with tenant() as con:
            current = con.execute("SELECT * FROM loans WHERE id=?", (item_id,)).fetchone()
            if not current:
                return json_error("Contract inexistent.", 404)

            merged = dict(current)
            merged.update(data)
            signed_date = date.fromisoformat(merged["original_contract_date"])
            effective_date = date.fromisoformat(merged["contract_date"])
            interest_start = date.fromisoformat(merged["interest_start_date"]) if merged.get("interest_start_date") else None
            maturity_date = date.fromisoformat(merged["maturity_date"]) if merged.get("maturity_date") else None

            if signed_date > effective_date:
                return json_error("Data semnării nu poate fi ulterioară datei de la care contractul produce efecte.")
            if interest_start and interest_start < effective_date:
                return json_error("Data de început a dobânzii nu poate fi anterioară datei efectelor contractului.")
            if maturity_date and maturity_date < effective_date:
                return json_error("Scadența nu poate fi anterioară datei efectelor contractului.")
            if interest_start and maturity_date and interest_start > maturity_date:
                return json_error("Data de început a dobânzii nu poate fi ulterioară scadenței.")

            recognized = con.execute(
                """SELECT COUNT(*) AS count,MIN(period_start) AS first_start,MAX(period_end) AS last_end
                   FROM interest_accruals WHERE loan_id=? AND status='RECOGNIZED'""",
                (item_id,),
            ).fetchone()
            recognized_count = int(recognized["count"] or 0)
            if recognized_count:
                first_recognized = date.fromisoformat(recognized["first_start"])
                last_recognized = date.fromisoformat(recognized["last_end"])
                if interest_start is None or interest_start > first_recognized:
                    return json_error(
                        "Există dobândă recunoscută contabil începând cu "
                        f"{recognized['first_start']}. Data de început nu poate fi eliminată sau mutată după această perioadă."
                    )
                if maturity_date and maturity_date < last_recognized:
                    return json_error(
                        "Există dobândă recunoscută contabil până la "
                        f"{recognized['last_end']}. Scadența nu poate fi mutată înaintea acestei date."
                    )

            recalculation_fields = {"interest_start_date", "maturity_date", "status"}
            needs_recalculation = any(merged.get(field) != current[field] for field in recalculation_fields if field in data)
            deleted_preliminary = 0
            recalculated_periods = 0

            con.execute(
                f"UPDATE loans SET {','.join(f'{key}=?' for key in data)} WHERE id=?",
                [*data.values(), item_id],
            )
            if needs_recalculation:
                deleted_preliminary = int(
                    con.execute(
                        "SELECT COUNT(*) FROM interest_accruals WHERE loan_id=? AND status='CALCULATED'",
                        (item_id,),
                    ).fetchone()[0]
                )
                con.execute(
                    "DELETE FROM interest_accruals WHERE loan_id=? AND status='CALCULATED'",
                    (item_id,),
                )
                recalculated_periods = business.recalculate_loan(con, item_id)

            business.audit(
                con,
                "UPDATE",
                "loans",
                entity_id=item_id,
                details=json.dumps(
                    {
                        "changes": data,
                        "deleted_preliminary": deleted_preliminary,
                        "recalculated_periods": recalculated_periods,
                        "recognized_preserved": recognized_count,
                    },
                    ensure_ascii=False,
                ),
                user_email=g.user["email"],
            )
            con.commit()
        return jsonify(
            ok=True,
            deleted_preliminary=deleted_preliminary,
            recalculated_periods=recalculated_periods,
            recognized_preserved=recognized_count,
        )

    @app.get("/api/transactions")
    @company_required
    def api_transactions():
        clauses = ["t.txn_type<>'OPENING_BALANCE'"]
        params: list = []
        if request.args.get("loan_id"):
            clauses.append("t.loan_id=?")
            params.append(int(request.args["loan_id"]))
        if request.args.get("type"):
            clauses.append("t.txn_type=?")
            params.append(request.args["type"])
        with tenant() as con:
            rows = con.execute(
                f"""SELECT t.*,l.contract_no,a.name associate_name FROM transactions t
                   JOIN loans l ON l.id=t.loan_id JOIN associates a ON a.id=l.associate_id
                   WHERE {' AND '.join(clauses)} ORDER BY t.txn_date DESC,t.id DESC""",
                params,
            ).fetchall()
            return jsonify(ok=True, items=business.rows_to_dicts(rows))

    @app.post("/api/transactions")
    @role_required("EDITOR")
    def api_create_transaction():
        data = payload()
        if data.get("txn_type") not in {"ADVANCE", "REPAYMENT", "INTEREST_PAYMENT"}:
            return json_error("Tip de operațiune neacceptat.")
        amount = float(data.get("amount") or 0)
        if amount <= 0:
            return json_error("Suma trebuie să fie mai mare decât zero.")
        with tenant() as con:
            if not con.execute("SELECT 1 FROM loans WHERE id=?", (int(data["loan_id"]),)).fetchone():
                return json_error("Contract inexistent.", 404)
            cur = con.execute(
                """INSERT INTO transactions(loan_id,accrual_id,txn_date,txn_type,amount,tax_withheld,payment_method,reference,notes)
                   VALUES(?,?,?,?,?,?,?,?,?)""",
                (int(data["loan_id"]), data.get("accrual_id") or None, data["txn_date"], data["txn_type"], amount,
                 float(data.get("tax_withheld") or 0), data.get("payment_method") or "BANK", data.get("reference"), data.get("notes")),
            )
            business.audit(con, "CREATE", "transactions", entity_id=cur.lastrowid, details=f"{data['txn_type']} {amount:.2f}", user_email=g.user["email"])
            con.commit()
        return jsonify(ok=True, id=cur.lastrowid)

    @app.delete("/api/transactions/<int:item_id>")
    @role_required("EDITOR")
    def api_delete_transaction(item_id: int):
        with tenant() as con:
            row = con.execute("SELECT * FROM transactions WHERE id=?", (item_id,)).fetchone()
            if not row:
                return json_error("Operațiune inexistentă.", 404)
            con.execute("DELETE FROM transactions WHERE id=?", (item_id,))
            business.audit(con, "DELETE", "transactions", entity_id=item_id, details=f"{row['txn_type']} {row['amount']}", user_email=g.user["email"])
            con.commit()
        return jsonify(ok=True)

    @app.get("/api/interest")
    @company_required
    def api_interest():
        params: list = []
        where = ""
        if request.args.get("loan_id"):
            where = "WHERE ia.loan_id=?"
            params.append(int(request.args["loan_id"]))
        with tenant() as con:
            rows = con.execute(
                f"""SELECT ia.*,l.contract_no,a.name associate_name,
                    COALESCE((SELECT SUM(t.amount) FROM transactions t WHERE t.accrual_id=ia.id AND t.txn_type='INTEREST_PAYMENT'),0) paid_amount,
                    COALESCE((SELECT GROUP_CONCAT(printf('%.2f%% · %d zile',s.rate,s.days),' | ') FROM interest_segments s WHERE s.accrual_id=ia.id),'') rate_summary
                    FROM interest_accruals ia JOIN loans l ON l.id=ia.loan_id JOIN associates a ON a.id=l.associate_id
                    {where} ORDER BY ia.period_start DESC,ia.loan_id""",
                params,
            ).fetchall()
            return jsonify(ok=True, items=business.rows_to_dicts(rows))

    @app.get("/api/interest/segments/<int:item_id>")
    @company_required
    def api_interest_segments(item_id: int):
        with tenant() as con:
            accrual = con.execute(
                """SELECT ia.*,l.contract_no,a.name associate_name FROM interest_accruals ia
                   JOIN loans l ON l.id=ia.loan_id JOIN associates a ON a.id=l.associate_id WHERE ia.id=?""",
                (item_id,),
            ).fetchone()
            if not accrual:
                return json_error("Calcul inexistent.", 404)
            rows = con.execute(
                """SELECT s.*,r.effective_date rate_effective_date,r.source_url,r.source_document
                   FROM interest_segments s LEFT JOIN bnr_reference_rates r ON r.id=s.bnr_rate_id
                   WHERE s.accrual_id=? ORDER BY s.segment_start""",
                (item_id,),
            ).fetchall()
            return jsonify(ok=True, accrual=dict(accrual), items=business.rows_to_dicts(rows))

    @app.post("/api/interest/recalculate")
    @role_required("EDITOR")
    def api_recalculate_interest():
        data = payload()
        cutoff = date.fromisoformat(data["cutoff"]) if data.get("cutoff") else None
        with tenant() as con:
            count = business.recalculate_all(con, user_email=g.user["email"], cutoff=cutoff)
        return jsonify(ok=True, periods=count)

    @app.post("/api/interest/recognize")
    @role_required("EDITOR")
    def api_recognize_interest():
        data = payload()
        with tenant() as con:
            row = con.execute("SELECT * FROM interest_accruals WHERE id=?", (int(data["id"]),)).fetchone()
            if not row:
                return json_error("Calcul inexistent.", 404)
            amount = round(float(data.get("recognized_amount", row["calculated_amount"])), 2)
            con.execute(
                "UPDATE interest_accruals SET recognized_amount=?,recognized_date=?,status='RECOGNIZED' WHERE id=?",
                (amount, data.get("recognized_date") or row["period_end"], row["id"]),
            )
            business.audit(con, "RECOGNIZE", "interest_accruals", entity_id=row["id"], details=f"{amount:.2f}", user_email=g.user["email"])
            con.commit()
        return jsonify(ok=True)

    @app.get("/api/bnr-rates")
    @company_required
    def api_bnr_rates():
        with tenant() as con:
            rows = con.execute("SELECT * FROM bnr_reference_rates ORDER BY effective_date DESC,id DESC").fetchall()
            return jsonify(ok=True, items=business.rows_to_dicts(rows))

    @app.post("/api/bnr-rates/update")
    @role_required("EDITOR")
    def api_update_bnr_rate():
        try:
            item = business.fetch_current_bnr_rate()
        except Exception as exc:
            app.logger.exception("Actualizarea automată BNR a eșuat")
            message = str(exc).strip() or "Sursa BNR nu a putut fi accesată."
            return json_error(message[:1800], 502)
        with tenant() as con:
            con.execute(
                """INSERT INTO bnr_reference_rates(effective_date,rate,rate_name,source_url,source_document,fetched_at,entry_mode,notes)
                   VALUES(?,?,?,?,?,CURRENT_TIMESTAMP,?,?) ON CONFLICT(effective_date) DO UPDATE SET rate=excluded.rate,
                   rate_name=excluded.rate_name,source_url=excluded.source_url,source_document=excluded.source_document,
                   fetched_at=CURRENT_TIMESTAMP,entry_mode=excluded.entry_mode,notes=excluded.notes""",
                (item["effective_date"], item["rate"], item["rate_name"], item["source_url"], item["source_document"], item["entry_mode"], item["notes"]),
            )
            business.audit(con, "BNR_UPDATE", "bnr_reference_rates", details=f"{item['effective_date']} · {item['rate']:.2f}%", user_email=g.user["email"])
            periods = business.recalculate_all(con, user_email=g.user["email"])
        return jsonify(ok=True, item=item, periods=periods)

    @app.post("/api/bnr-rates")
    @role_required("EDITOR")
    def api_create_bnr_rate():
        data = payload()
        rate = round(float(data.get("rate") or 0), 4)
        if not 0 <= rate <= 30:
            return json_error("Rata trebuie să fie între 0% și 30%.")
        if not is_safe_source_url(data.get("source_url")):
            return json_error("Sursa manuală trebuie să fie o adresă HTTPS oficială bnr.ro.")
        with tenant() as con:
            con.execute(
                """INSERT INTO bnr_reference_rates(effective_date,rate,rate_name,source_url,source_document,fetched_at,entry_mode,notes)
                   VALUES(?,?,?,?,?,CURRENT_TIMESTAMP,'MANUAL',?) ON CONFLICT(effective_date) DO UPDATE SET rate=excluded.rate,
                   source_url=excluded.source_url,source_document=excluded.source_document,fetched_at=CURRENT_TIMESTAMP,
                   entry_mode='MANUAL',notes=excluded.notes""",
                (data["effective_date"], rate, "Rata dobânzii de politică monetară", data.get("source_url") or BNR_RATE_URLS[0],
                 data.get("source_document") or "Înregistrare verificată manual", data.get("notes") or "Rată introdusă manual."),
            )
            business.audit(con, "CREATE", "bnr_reference_rates", details=f"{data['effective_date']} · {rate:.2f}%", user_email=g.user["email"])
            periods = business.recalculate_all(con, user_email=g.user["email"])
        return jsonify(ok=True, periods=periods)

    @app.delete("/api/bnr-rates/<int:item_id>")
    @role_required("EDITOR")
    def api_delete_bnr_rate(item_id: int):
        with tenant() as con:
            if con.execute("SELECT COUNT(*) FROM bnr_reference_rates").fetchone()[0] <= 1:
                return json_error("Trebuie păstrată cel puțin o rată BNR.")
            if con.execute("SELECT COUNT(*) FROM interest_segments WHERE bnr_rate_id=?", (item_id,)).fetchone()[0]:
                return json_error("Rata este folosită în calcule. Înregistrați corecția pe aceeași dată.")
            row = con.execute("SELECT * FROM bnr_reference_rates WHERE id=?", (item_id,)).fetchone()
            if not row:
                return json_error("Rată inexistentă.", 404)
            con.execute("DELETE FROM bnr_reference_rates WHERE id=?", (item_id,))
            business.audit(con, "DELETE", "bnr_reference_rates", entity_id=item_id, details=row["effective_date"], user_email=g.user["email"])
            con.commit()
        return jsonify(ok=True)

    def resolve_company_document_path(relative_path: str) -> Path:
        root = tenant_documents_path(g.company).resolve()
        candidate = (root / relative_path).resolve()
        if candidate == root or root not in candidate.parents:
            abort(404)
        return candidate

    def resolve_template_path(relative_path: str) -> Path:
        root = TEMPLATE_ROOT.resolve()
        candidate = (root / relative_path).resolve()
        if candidate == root or root not in candidate.parents:
            abort(404)
        return candidate

    def template_metadata() -> dict[str, dict]:
        path = TEMPLATE_ROOT / "custom" / ".metadata.json"
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            return value if isinstance(value, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}

    def save_template_metadata(value: dict[str, dict]) -> None:
        folder = TEMPLATE_ROOT / "custom"
        folder.mkdir(parents=True, exist_ok=True)
        temp = folder / ".metadata.json.tmp"
        temp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temp, folder / ".metadata.json")

    @app.get("/api/templates")
    @auth_required
    def api_templates():
        items = []
        root = TEMPLATE_ROOT.resolve()
        metadata = template_metadata()
        for category in ("standard", "custom"):
            folder = root / category
            if not folder.is_dir():
                continue
            for path in sorted(folder.rglob("*")):
                if not path.is_file() or path.name.startswith(".") or path.suffix.lower() not in ALLOWED_TEMPLATE_EXTENSIONS:
                    continue
                stat = path.stat()
                items.append({
                    "path": path.relative_to(root).as_posix(),
                    "filename": path.name,
                    "category": category.upper(),
                    "extension": path.suffix.lower().lstrip(".").upper(),
                    "size_bytes": stat.st_size,
                    "modified_at": datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds"),
                    "description": (metadata.get(path.name, {}).get("description") if category == "custom" else None) or TEMPLATE_DESCRIPTIONS.get(path.name, "Șablon editabil al utilizatorului." if category == "custom" else "Șablon editabil standard."),
                    "uploaded_by": metadata.get(path.name, {}).get("uploaded_by") if category == "custom" else None,
                })
        return jsonify(ok=True, items=items)

    @app.get("/templates/<path:filename>/download")
    @auth_required
    def download_template(filename: str):
        path = resolve_template_path(filename)
        if not path.is_file() or path.suffix.lower() not in ALLOWED_TEMPLATE_EXTENSIONS:
            abort(404)
        return send_file(path, as_attachment=True, download_name=path.name)

    @app.post("/api/templates/upload")
    @role_required("EDITOR")
    def upload_template():
        upload = request.files.get("file")
        description = (request.form.get("description") or "").strip()
        if upload is None or not upload.filename:
            return json_error("Selectați fișierul șablon.")
        original_filename = Path(upload.filename).name
        extension = Path(original_filename).suffix.lower()
        if extension not in ALLOWED_TEMPLATE_EXTENSIONS:
            return json_error("Format neacceptat. Sunt permise DOCX, XLSX, ODT, TXT și PDF.")
        normalized = secure_filename(original_filename) or f"sablon{extension}"
        custom_dir = TEMPLATE_ROOT / "custom"
        custom_dir.mkdir(parents=True, exist_ok=True)
        temp_path = custom_dir / f".upload_{os.getpid()}_{datetime.now().timestamp():.6f}.tmp"
        try:
            upload.save(temp_path)
            size_bytes = temp_path.stat().st_size
            if size_bytes == 0:
                return json_error("Fișierul este gol.")
            if extension == ".docx" and not validate_docx_file(temp_path):
                return json_error("Fișierul selectat nu este un document Word DOCX valid.")
            if extension == ".pdf" and temp_path.read_bytes()[:5] != b"%PDF-":
                return json_error("Fișierul selectat nu este un PDF valid.")
            digest = hashlib.sha256(temp_path.read_bytes()).hexdigest()
            for existing in custom_dir.iterdir():
                if existing.is_file() and not existing.name.startswith(".") and hashlib.sha256(existing.read_bytes()).hexdigest() == digest:
                    return json_error(f"Acest șablon este deja încărcat ca {existing.name}.")
            destination = custom_dir / normalized
            if destination.exists():
                destination = custom_dir / f"{destination.stem}_{datetime.now():%Y%m%d_%H%M%S}{destination.suffix}"
            os.replace(temp_path, destination)
            metadata = template_metadata()
            metadata[destination.name] = {
                "description": description or "Șablon editabil încărcat de utilizator.",
                "uploaded_by": g.user["email"],
                "uploaded_at": utcnow(),
                "sha256": digest,
            }
            save_template_metadata(metadata)
            security_audit("UPLOAD_TEMPLATE", user_id=g.user["id"], company_id=g.company["id"] if g.company else None, details=f"file={destination.name}; sha256={digest}")
            return jsonify(ok=True, filename=destination.name, size_bytes=size_bytes, sha256=digest)
        finally:
            temp_path.unlink(missing_ok=True)

    @app.post("/api/templates/<path:filename>/copy-to-company")
    @role_required("EDITOR")
    def copy_template_to_company(filename: str):
        source = resolve_template_path(filename)
        if not source.is_file() or source.suffix.lower() not in ALLOWED_TEMPLATE_EXTENSIONS:
            return json_error("Șablon inexistent.", 404)
        destination_dir = tenant_documents_path(g.company) / "sabloane"
        destination_dir.mkdir(parents=True, exist_ok=True)
        destination = destination_dir / source.name
        source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
        if destination.exists():
            destination_hash = hashlib.sha256(destination.read_bytes()).hexdigest()
            if destination_hash == source_hash:
                return jsonify(ok=True, copied=False, filename=destination.name, relative_path=destination.relative_to(tenant_documents_path(g.company)).as_posix())
            destination = destination_dir / f"{source.stem}_{datetime.now():%Y%m%d_%H%M%S}{source.suffix}"
        shutil.copy2(source, destination)
        relative_path = destination.relative_to(tenant_documents_path(g.company)).as_posix()
        with tenant() as con:
            business.audit(con, "COPY_TEMPLATE", "templates", details=f"source={filename}; target={relative_path}", user_email=g.user["email"])
            con.commit()
        return jsonify(ok=True, copied=True, filename=destination.name, relative_path=relative_path)

    @app.get("/api/documents")
    @company_required
    def api_documents():
        with tenant() as con:
            rows = con.execute(
                """SELECT d.*,a.name associate_name,l.contract_no,
                          (SELECT COUNT(*) FROM document_versions v WHERE v.document_id=d.id AND v.version_type='SIGNED_PDF') signed_count,
                          (SELECT v.id FROM document_versions v WHERE v.document_id=d.id AND v.version_type='SIGNED_PDF' ORDER BY v.version_no DESC LIMIT 1) latest_signed_id,
                          (SELECT v.original_filename FROM document_versions v WHERE v.document_id=d.id AND v.version_type='SIGNED_PDF' ORDER BY v.version_no DESC LIMIT 1) latest_signed_filename,
                          (SELECT v.version_no FROM document_versions v WHERE v.document_id=d.id AND v.version_type='SIGNED_PDF' ORDER BY v.version_no DESC LIMIT 1) latest_signed_version_no,
                          (SELECT v.uploaded_at FROM document_versions v WHERE v.document_id=d.id AND v.version_type='SIGNED_PDF' ORDER BY v.version_no DESC LIMIT 1) latest_signed_uploaded_at,
                          (SELECT COUNT(*) FROM document_word_versions w WHERE w.document_id=d.id) word_version_count,
                          (SELECT COUNT(*) FROM generated_pdf_versions p WHERE p.document_id=d.id) generated_pdf_count,
                          (SELECT p.id FROM generated_pdf_versions p WHERE p.document_id=d.id ORDER BY p.version_no DESC LIMIT 1) latest_generated_pdf_id,
                          (SELECT p.version_no FROM generated_pdf_versions p WHERE p.document_id=d.id ORDER BY p.version_no DESC LIMIT 1) latest_generated_pdf_version_no,
                          (SELECT p.generated_at FROM generated_pdf_versions p WHERE p.document_id=d.id ORDER BY p.version_no DESC LIMIT 1) latest_generated_pdf_at
                   FROM documents d
                   LEFT JOIN associates a ON a.id=d.associate_id
                   LEFT JOIN loans l ON l.id=d.loan_id
                   ORDER BY d.doc_date DESC,d.id DESC"""
            ).fetchall()
            return jsonify(ok=True, items=business.rows_to_dicts(rows))

    @app.post("/api/documents")
    @role_required("EDITOR")
    def api_create_document():
        data = payload()
        if not data.get("doc_type"):
            return json_error("Tipul documentului este obligatoriu.")
        filename = Path(data.get("filename") or "").name or None
        with tenant() as con:
            cur = con.execute(
                """INSERT INTO documents(doc_type,doc_no,doc_date,associate_id,loan_id,filename,status,notes)
                   VALUES(?,?,?,?,?,?,?,?)""",
                (data["doc_type"], data.get("doc_no"), data.get("doc_date"), data.get("associate_id") or None,
                 data.get("loan_id") or None, filename, data.get("status") or "READY_FOR_SIGNATURE", data.get("notes")),
            )
            business.audit(con, "CREATE", "documents", entity_id=cur.lastrowid, details=data["doc_type"], user_email=g.user["email"])
            con.commit()
        return jsonify(ok=True, id=cur.lastrowid)

    @app.delete("/api/documents/<int:item_id>")
    @role_required("EDITOR")
    def api_delete_document(item_id: int):
        with tenant() as con:
            counts = con.execute(
                """SELECT
                       (SELECT COUNT(*) FROM document_versions WHERE document_id=?) signed_count,
                       (SELECT COUNT(*) FROM document_word_versions WHERE document_id=?) word_count,
                       (SELECT COUNT(*) FROM generated_pdf_versions WHERE document_id=?) generated_count
                   """,
                (item_id, item_id, item_id),
            ).fetchone()
            if counts and (int(counts["signed_count"]) or int(counts["word_count"]) or int(counts["generated_count"])):
                return json_error(
                    "Documentul are istoric de versiuni Word/PDF. Pentru protejarea trasabilității, registrul nu poate fi șters."
                )
            document = con.execute("SELECT id FROM documents WHERE id=?", (item_id,)).fetchone()
            if not document:
                return json_error("Document inexistent.", 404)
            con.execute("DELETE FROM documents WHERE id=?", (item_id,))
            business.audit(con, "DELETE", "documents", entity_id=item_id, details="Ștergere registru; fișierul original nu este eliminat", user_email=g.user["email"])
            con.commit()
        return jsonify(ok=True)

    @app.get("/documents/<int:item_id>/download")
    @company_required
    def download_document(item_id: int):
        with tenant() as con:
            row = con.execute("SELECT filename FROM documents WHERE id=?", (item_id,)).fetchone()
        if not row or not row["filename"]:
            abort(404)
        relative_path = str(row["filename"])
        path = resolve_company_document_path(relative_path)
        if not path.is_file():
            abort(404)
        return send_file(path, as_attachment=True, download_name=Path(relative_path).name, mimetype=DOCX_MIME if path.suffix.lower()==".docx" else None)

    @app.post("/api/documents/<int:item_id>/word-version")
    @role_required("EDITOR")
    def replace_document_word(item_id: int):
        upload = request.files.get("file")
        notes = (request.form.get("notes") or "").strip()
        if upload is None or not upload.filename:
            return json_error("Selectați documentul Word formatat.")
        original_filename = Path(upload.filename).name
        normalized_filename = secure_filename(original_filename) or "document.docx"
        if not normalized_filename.lower().endswith(".docx"):
            return json_error("Este permis exclusiv formatul Word DOCX.")

        root = tenant_documents_path(g.company)
        word_dir = (root / "word" / f"{item_id:06d}").resolve()
        if root.resolve() not in word_dir.parents:
            return json_error("Calea de stocare este invalidă.")
        word_dir.mkdir(parents=True, exist_ok=True)
        temp_path = word_dir / f".upload_{os.getpid()}_{datetime.now().timestamp():.6f}.tmp"
        created_paths: list[Path] = []
        try:
            upload.save(temp_path)
            if temp_path.stat().st_size == 0 or not validate_docx_file(temp_path):
                return json_error("Fișierul selectat nu este un document Word DOCX valid.")
            digest = hashlib.sha256(temp_path.read_bytes()).hexdigest()
            with tenant() as con:
                document = con.execute("SELECT * FROM documents WHERE id=?", (item_id,)).fetchone()
                if not document:
                    return json_error("Document inexistent.", 404)
                duplicate = con.execute("SELECT version_no FROM document_word_versions WHERE document_id=? AND sha256=?", (item_id, digest)).fetchone()
                if duplicate:
                    return json_error(f"Acest document Word este deja înregistrat ca versiunea {duplicate['version_no']}.")

                con.execute("BEGIN IMMEDIATE")
                max_version = int(con.execute("SELECT COALESCE(MAX(version_no),0) FROM document_word_versions WHERE document_id=?", (item_id,)).fetchone()[0])
                current_relative = document["filename"]
                current_path = resolve_company_document_path(current_relative) if current_relative else None
                if max_version == 0 and current_path and current_path.is_file():
                    old_digest = hashlib.sha256(current_path.read_bytes()).hexdigest()
                    if old_digest == digest:
                        return json_error("Fișierul încărcat este identic cu documentul Word curent.")
                    old_name = Path(current_relative).name
                    old_stored = word_dir / f"v001_{secure_filename(old_name) or 'document_initial.docx'}"
                    shutil.copy2(current_path, old_stored)
                    created_paths.append(old_stored)
                    con.execute(
                        """INSERT INTO document_word_versions(document_id,version_no,stored_path,original_filename,mime_type,size_bytes,sha256,notes,is_current,uploaded_by)
                           VALUES(?,1,?,?,?,?,?,?,0,?)""",
                        (item_id, old_stored.relative_to(root).as_posix(), old_name, DOCX_MIME, old_stored.stat().st_size, old_digest, "Versiunea Word existentă înainte de prima înlocuire.", g.user["email"]),
                    )
                    max_version = 1

                version_no = max_version + 1
                stored_path = word_dir / f"v{version_no:03d}_{normalized_filename}"
                os.replace(temp_path, stored_path)
                created_paths.append(stored_path)
                relative_path = stored_path.relative_to(root).as_posix()
                con.execute("UPDATE document_word_versions SET is_current=0 WHERE document_id=?", (item_id,))
                cur = con.execute(
                    """INSERT INTO document_word_versions(document_id,version_no,stored_path,original_filename,mime_type,size_bytes,sha256,notes,is_current,uploaded_by)
                       VALUES(?,?,?,?,?,?,?,?,1,?)""",
                    (item_id, version_no, relative_path, original_filename, DOCX_MIME, stored_path.stat().st_size, digest, notes, g.user["email"]),
                )
                con.execute("UPDATE documents SET filename=?,status='READY_FOR_SIGNATURE' WHERE id=?", (relative_path, item_id))
                business.audit(con, "REPLACE_WORD", "document_word_versions", entity_id=cur.lastrowid, details=f"document={item_id}; version={version_no}; file={original_filename}; sha256={digest}", user_email=g.user["email"])
                con.commit()
            return jsonify(ok=True, id=cur.lastrowid, version_no=version_no, filename=original_filename, sha256=digest)
        except Exception:
            for created in created_paths:
                created.unlink(missing_ok=True)
            raise
        finally:
            temp_path.unlink(missing_ok=True)

    @app.get("/documents/<int:item_id>/word/<int:version_id>/download")
    @company_required
    def download_word_version(item_id: int, version_id: int):
        with tenant() as con:
            row = con.execute("SELECT stored_path,original_filename FROM document_word_versions WHERE id=? AND document_id=?", (version_id, item_id)).fetchone()
        if not row:
            abort(404)
        path = resolve_company_document_path(row["stored_path"])
        if not path.is_file():
            abort(404)
        return send_file(path, as_attachment=True, download_name=Path(row["original_filename"]).name, mimetype=DOCX_MIME)

    def render_word_print_response(*, item_id: int, source: Path, display_name: str, title: str, download_url: str):
        if not source.is_file() or source.suffix.lower() != ".docx":
            abort(404)
        try:
            rendered = render_docx_for_print(
                source,
                title=title,
                filename=display_name,
                download_url=download_url,
                auto_print=request.args.get("auto") == "1",
            )
        except (OSError, zipfile.BadZipFile, ET.ParseError, ValueError) as exc:
            app.logger.exception("DOCX print rendering failed for document %s", item_id)
            abort(500, description=f"Documentul Word nu a putut fi pregătit pentru tipărire: {exc}")
        response = make_response(rendered)
        response.mimetype = "text/html"
        response.headers["Cache-Control"] = "private, no-store"
        return response

    @app.get("/documents/<int:item_id>/word-print")
    @company_required
    def print_document_word(item_id: int):
        with tenant() as con:
            document = con.execute("SELECT id,doc_type,doc_no,filename FROM documents WHERE id=?", (item_id,)).fetchone()
        if not document or not document["filename"]:
            abort(404)
        source = resolve_company_document_path(document["filename"])
        display_name = Path(document["filename"]).name
        title = f"{document['doc_type']} {document['doc_no'] or ''}".strip()
        return render_word_print_response(
            item_id=item_id,
            source=source,
            display_name=display_name,
            title=title,
            download_url=url_for("download_document", item_id=item_id),
        )

    @app.get("/documents/<int:item_id>/word/<int:version_id>/print")
    @company_required
    def print_word_version(item_id: int, version_id: int):
        with tenant() as con:
            row = con.execute(
                """SELECT w.stored_path,w.original_filename,w.version_no,d.doc_type,d.doc_no
                   FROM document_word_versions w JOIN documents d ON d.id=w.document_id
                   WHERE w.id=? AND w.document_id=?""",
                (version_id, item_id),
            ).fetchone()
        if not row:
            abort(404)
        source = resolve_company_document_path(row["stored_path"])
        title = f"{row['doc_type']} {row['doc_no'] or ''} · Word v{row['version_no']}".strip()
        return render_word_print_response(
            item_id=item_id,
            source=source,
            display_name=Path(row["original_filename"]).name,
            title=title,
            download_url=url_for("download_word_version", item_id=item_id, version_id=version_id),
        )

    @app.post("/api/documents/<int:item_id>/generate-pdf")
    @role_required("EDITOR")
    def generate_document_pdf(item_id: int):
        """Open the current DOCX in the browser print view.

        LoanCopilot intentionally avoids a server-side Office dependency. The user
        saves the browser print output as PDF and can then archive or upload the
        signed version through the existing versioned PDF endpoints.
        """
        with tenant() as con:
            document = con.execute("SELECT * FROM documents WHERE id=?", (item_id,)).fetchone()
        if not document or not document["filename"]:
            return json_error("Documentul Word nu este atașat.", 404)

        source = resolve_company_document_path(document["filename"])
        if not source.is_file() or source.suffix.lower() != ".docx":
            return json_error("Sursa curentă nu este un document Word DOCX.")

        return jsonify(
            ok=True,
            mode="browser_print",
            print_url=url_for("print_document_word", item_id=item_id, auto=1),
            message="Documentul a fost pregătit pentru Print / Save as PDF în browser.",
        )

    @app.post("/api/documents/<int:item_id>/generated-versions")
    @role_required("EDITOR")
    def upload_generated_pdf(item_id: int):
        upload = request.files.get("file")
        notes = (request.form.get("notes") or "").strip()
        if upload is None or not upload.filename:
            return json_error("Selectați PDF-ul salvat din dialogul Print / Save as PDF.")
        original_filename = Path(upload.filename).name
        normalized_filename = secure_filename(original_filename) or "document_generat.pdf"
        if not normalized_filename.lower().endswith(".pdf"):
            return json_error("Este permis exclusiv formatul PDF.")

        root = tenant_documents_path(g.company)
        pdf_dir = (root / "generate" / f"{item_id:06d}").resolve()
        if root.resolve() not in pdf_dir.parents:
            return json_error("Calea de stocare este invalidă.")
        pdf_dir.mkdir(parents=True, exist_ok=True)
        temp_path = pdf_dir / f".upload_{os.getpid()}_{datetime.now().timestamp():.6f}.tmp"
        try:
            upload.save(temp_path)
            if temp_path.stat().st_size <= 5 or temp_path.read_bytes()[:5] != b"%PDF-":
                return json_error("Fișierul selectat nu este un PDF valid.")
            digest = hashlib.sha256(temp_path.read_bytes()).hexdigest()
            with tenant() as con:
                document = con.execute("SELECT id,filename FROM documents WHERE id=?", (item_id,)).fetchone()
                if not document:
                    return json_error("Document inexistent.", 404)
                duplicate = con.execute(
                    "SELECT id,version_no FROM generated_pdf_versions WHERE document_id=? AND sha256=?",
                    (item_id, digest),
                ).fetchone()
                if duplicate:
                    return jsonify(ok=True, id=duplicate["id"], version_no=duplicate["version_no"], reused=True)
                current_word = con.execute(
                    "SELECT id FROM document_word_versions WHERE document_id=? AND is_current=1",
                    (item_id,),
                ).fetchone()
                con.execute("BEGIN IMMEDIATE")
                version_no = int(con.execute(
                    "SELECT COALESCE(MAX(version_no),0)+1 FROM generated_pdf_versions WHERE document_id=?",
                    (item_id,),
                ).fetchone()[0])
                destination = pdf_dir / f"v{version_no:03d}_{normalized_filename}"
                shutil.move(str(temp_path), destination)
                relative_path = destination.relative_to(root).as_posix()
                cur = con.execute(
                    """INSERT INTO generated_pdf_versions(
                           document_id,word_version_id,version_no,stored_path,original_filename,
                           mime_type,size_bytes,sha256,generated_by,notes)
                       VALUES(?,?,?,?,?,'application/pdf',?,?,?,?)""",
                    (
                        item_id, current_word["id"] if current_word else None, version_no, relative_path,
                        original_filename, destination.stat().st_size, digest, g.user["email"],
                        notes or "PDF salvat prin Print / Save as PDF și încărcat în aplicație.",
                    ),
                )
                business.audit(
                    con, "UPLOAD_GENERATED_PDF", "generated_pdf_versions", entity_id=cur.lastrowid,
                    details=f"document={item_id}; version={version_no}; file={original_filename}; sha256={digest}",
                    user_email=g.user["email"],
                )
                con.commit()
            return jsonify(ok=True, id=cur.lastrowid, version_no=version_no, reused=False)
        finally:
            temp_path.unlink(missing_ok=True)

    @app.get("/documents/<int:item_id>/generated/<int:version_id>/view")
    @company_required
    def view_generated_pdf(item_id: int, version_id: int):
        with tenant() as con:
            row = con.execute("SELECT stored_path,original_filename FROM generated_pdf_versions WHERE id=? AND document_id=?", (version_id, item_id)).fetchone()
        if not row:
            abort(404)
        path = resolve_company_document_path(row["stored_path"])
        if not path.is_file():
            abort(404)
        response = send_file(path, as_attachment=False, download_name=Path(row["original_filename"]).name, mimetype="application/pdf")
        response.headers["Content-Disposition"] = f'inline; filename="{Path(row["original_filename"]).name}"'
        return response

    @app.get("/documents/<int:item_id>/generated/<int:version_id>/download")
    @company_required
    def download_generated_pdf(item_id: int, version_id: int):
        with tenant() as con:
            row = con.execute("SELECT stored_path,original_filename FROM generated_pdf_versions WHERE id=? AND document_id=?", (version_id, item_id)).fetchone()
        if not row:
            abort(404)
        path = resolve_company_document_path(row["stored_path"])
        if not path.is_file():
            abort(404)
        return send_file(path, as_attachment=True, download_name=Path(row["original_filename"]).name, mimetype="application/pdf")

    @app.get("/api/documents/<int:item_id>/history")
    @company_required
    def document_history(item_id: int):
        with tenant() as con:
            document = con.execute("SELECT id,doc_type,doc_no,filename,status FROM documents WHERE id=?", (item_id,)).fetchone()
            if not document:
                return json_error("Document inexistent.", 404)
            word_items = con.execute("SELECT * FROM document_word_versions WHERE document_id=? ORDER BY version_no DESC", (item_id,)).fetchall()
            generated_items = con.execute("SELECT * FROM generated_pdf_versions WHERE document_id=? ORDER BY version_no DESC", (item_id,)).fetchall()
            signed_items = con.execute("SELECT * FROM document_versions WHERE document_id=? AND version_type='SIGNED_PDF' ORDER BY version_no DESC", (item_id,)).fetchall()
        return jsonify(ok=True, document=dict(document), word_items=business.rows_to_dicts(word_items), generated_items=business.rows_to_dicts(generated_items), signed_items=business.rows_to_dicts(signed_items))

    @app.get("/document-files/<path:filename>/download")
    @company_required
    def download_document_by_filename(filename: str):
        safe_relative = Path(filename).name
        path = resolve_company_document_path(safe_relative)
        if not path.is_file():
            abort(404)
        return send_file(path, as_attachment=True, download_name=safe_relative)

    @app.get("/api/documents/<int:item_id>/versions")
    @company_required
    def api_document_versions(item_id: int):
        with tenant() as con:
            document = con.execute(
                """SELECT d.*,a.name associate_name,l.contract_no
                   FROM documents d
                   LEFT JOIN associates a ON a.id=d.associate_id
                   LEFT JOIN loans l ON l.id=d.loan_id
                   WHERE d.id=?""",
                (item_id,),
            ).fetchone()
            if not document:
                return json_error("Document inexistent.", 404)
            versions = con.execute(
                """SELECT id,document_id,version_no,version_type,original_filename,mime_type,
                          size_bytes,sha256,notes,uploaded_at,uploaded_by
                   FROM document_versions WHERE document_id=? ORDER BY version_no DESC""",
                (item_id,),
            ).fetchall()
        return jsonify(ok=True, document=dict(document), items=business.rows_to_dicts(versions))

    @app.post("/api/documents/<int:item_id>/signed-versions")
    @role_required("EDITOR")
    def api_upload_signed_document(item_id: int):
        upload = request.files.get("file")
        notes = (request.form.get("notes") or "").strip()
        if upload is None or not upload.filename:
            return json_error("Selectați fișierul PDF semnat.")

        original_filename = Path(upload.filename).name
        normalized_filename = secure_filename(original_filename) or "document_semnat.pdf"
        if not normalized_filename.lower().endswith(".pdf"):
            return json_error("Este permis exclusiv formatul PDF.")

        signature = upload.stream.read(5)
        upload.stream.seek(0)
        if signature != b"%PDF-":
            return json_error("Fișierul selectat nu este un PDF valid.")

        root = tenant_documents_path(g.company)
        signed_dir = (root / "semnate" / f"{item_id:06d}").resolve()
        if root.resolve() not in signed_dir.parents:
            return json_error("Calea de stocare este invalidă.", 400)
        signed_dir.mkdir(parents=True, exist_ok=True)

        temp_path = signed_dir / f".upload_{os.getpid()}_{datetime.now().timestamp():.6f}.tmp"
        final_path = None
        try:
            upload.save(temp_path)
            size_bytes = temp_path.stat().st_size
            if size_bytes <= 5:
                return json_error("Fișierul PDF este gol sau incomplet.")
            digest = hashlib.sha256(temp_path.read_bytes()).hexdigest()

            with tenant() as con:
                document = con.execute("SELECT id,doc_type,doc_no FROM documents WHERE id=?", (item_id,)).fetchone()
                if not document:
                    return json_error("Document inexistent.", 404)
                duplicate = con.execute(
                    "SELECT id,version_no FROM document_versions WHERE document_id=? AND sha256=?",
                    (item_id, digest),
                ).fetchone()
                if duplicate:
                    return json_error(f"Acest PDF este deja încărcat ca versiunea {duplicate['version_no']}.")

                con.execute("BEGIN IMMEDIATE")
                version_no = int(con.execute(
                    "SELECT COALESCE(MAX(version_no),0)+1 FROM document_versions WHERE document_id=?",
                    (item_id,),
                ).fetchone()[0])
                stored_name = f"v{version_no:03d}_{normalized_filename}"
                final_path = signed_dir / stored_name
                os.replace(temp_path, final_path)
                stored_path = final_path.relative_to(root).as_posix()
                cur = con.execute(
                    """INSERT INTO document_versions(
                           document_id,version_no,version_type,stored_path,original_filename,
                           mime_type,size_bytes,sha256,notes,uploaded_by
                       ) VALUES(?,?,'SIGNED_PDF',?,?,?,?,?,?,?)""",
                    (item_id, version_no, stored_path, original_filename, "application/pdf", size_bytes, digest, notes, g.user["email"]),
                )
                con.execute("UPDATE documents SET status='SIGNED' WHERE id=?", (item_id,))
                business.audit(
                    con,
                    "UPLOAD_SIGNED_PDF",
                    "document_versions",
                    entity_id=cur.lastrowid,
                    details=f"document={item_id}; version={version_no}; file={original_filename}; sha256={digest}",
                    user_email=g.user["email"],
                )
                con.commit()
            return jsonify(ok=True, id=cur.lastrowid, version_no=version_no, filename=original_filename, size_bytes=size_bytes)
        except sqlite3.IntegrityError:
            if final_path and final_path.exists():
                final_path.unlink(missing_ok=True)
            raise
        except Exception:
            if final_path and final_path.exists():
                final_path.unlink(missing_ok=True)
            raise
        finally:
            temp_path.unlink(missing_ok=True)

    @app.get("/documents/<int:item_id>/signed/<int:version_id>/download")
    @company_required
    def download_signed_document(item_id: int, version_id: int):
        with tenant() as con:
            row = con.execute(
                """SELECT stored_path,original_filename,mime_type
                   FROM document_versions WHERE id=? AND document_id=?""",
                (version_id, item_id),
            ).fetchone()
        if not row:
            abort(404)
        path = resolve_company_document_path(row["stored_path"])
        if not path.is_file():
            abort(404)
        return send_file(
            path,
            as_attachment=True,
            download_name=Path(row["original_filename"]).name,
            mimetype=row["mime_type"] or "application/pdf",
        )

    @app.delete("/api/documents/<int:item_id>/signed-versions/<int:version_id>")
    @role_required("EDITOR")
    def api_delete_signed_document(item_id: int, version_id: int):
        with tenant() as con:
            row = con.execute(
                "SELECT * FROM document_versions WHERE id=? AND document_id=?",
                (version_id, item_id),
            ).fetchone()
            if not row:
                return json_error("Versiune semnată inexistentă.", 404)
            path = resolve_company_document_path(row["stored_path"])
            con.execute("DELETE FROM document_versions WHERE id=?", (version_id,))
            remaining = int(con.execute("SELECT COUNT(*) FROM document_versions WHERE document_id=?", (item_id,)).fetchone()[0])
            if remaining == 0:
                con.execute("UPDATE documents SET status='READY_FOR_SIGNATURE' WHERE id=?", (item_id,))
            business.audit(
                con,
                "DELETE_SIGNED_PDF",
                "document_versions",
                entity_id=version_id,
                details=f"document={item_id}; version={row['version_no']}; file={row['original_filename']}",
                user_email=g.user["email"],
            )
            con.commit()
        path.unlink(missing_ok=True)
        return jsonify(ok=True)

    @app.get("/api/audit")
    @company_required
    def api_audit():
        with tenant() as con:
            rows = con.execute("SELECT * FROM audit_log ORDER BY event_time DESC,id DESC LIMIT 500").fetchall()
            return jsonify(ok=True, items=business.rows_to_dicts(rows))

    @app.get("/api/export")
    @company_required
    def api_export():
        dataset = request.args.get("dataset", "loans")
        with tenant() as con:
            raw, filename = business.csv_export(con, dataset)
        return Response(raw, headers={"Content-Disposition": f'attachment; filename="{filename}"'}, content_type="text/csv; charset=utf-8")

    @app.get("/api/backup")
    @role_required("ADMIN")
    def api_backup():
        source_path = tenant_db_path(g.company)
        backup_dir = BACKUP_ROOT / g.company["slug"]
        backup_dir.mkdir(parents=True, exist_ok=True)
        target = backup_dir / f"{g.company['slug']}_{datetime.now():%Y%m%d_%H%M%S}.sqlite"
        with sqlite3.connect(source_path) as source, sqlite3.connect(target) as destination:
            source.backup(destination)
        security_audit("TENANT_BACKUP", user_id=g.user["id"], company_id=g.company["id"], details=target.name)
        return jsonify(ok=True, filename=target.name)

    # ----- Administration -----
    def admin_access() -> bool:
        return bool(g.user and (g.user["is_superadmin"] or g.role == "ADMIN"))

    @app.get("/api/admin/data")
    @auth_required
    def api_admin_data():
        if not admin_access():
            return json_error("Acces interzis.", 403)
        with auth_connect() as con:
            if g.user["is_superadmin"]:
                companies = [company_with_storage(row) for row in con.execute("SELECT * FROM companies ORDER BY name")]
                users = [dict(row) for row in con.execute("SELECT id,email,display_name,active,is_superadmin,totp_enabled,last_login_at,created_at FROM users ORDER BY display_name")]
                memberships = [dict(row) for row in con.execute("SELECT uc.*,u.email,c.name company_name FROM user_companies uc JOIN users u ON u.id=uc.user_id JOIN companies c ON c.id=uc.company_id ORDER BY c.name,u.email")]
            else:
                companies = [company_with_storage(con.execute("SELECT * FROM companies WHERE id=?", (g.company["id"],)).fetchone())]
                users = [dict(row) for row in con.execute(
                    """SELECT u.id,u.email,u.display_name,u.active,u.is_superadmin,u.totp_enabled,u.last_login_at,u.created_at
                       FROM users u JOIN user_companies uc ON uc.user_id=u.id WHERE uc.company_id=? ORDER BY u.display_name""",
                    (g.company["id"],),
                )]
                memberships = [dict(row) for row in con.execute(
                    """SELECT uc.*,u.email,c.name company_name FROM user_companies uc JOIN users u ON u.id=uc.user_id
                       JOIN companies c ON c.id=uc.company_id WHERE uc.company_id=? ORDER BY u.email""",
                    (g.company["id"],),
                )]
        return jsonify(ok=True, companies=companies, users=users, memberships=memberships)

    @app.post("/api/admin/companies")
    @auth_required
    def api_admin_create_company():
        if not g.user["is_superadmin"]:
            return json_error("Doar administratorul sistem poate crea o companie.", 403)
        try:
            data = normalize_company_updates(payload(), allow_active=False)
        except ValueError as exc:
            return json_error(str(exc), 400)
        requested_slug = str((request.get_json(silent=True) or {}).get("slug") or "").strip()
        slug = safe_filename(requested_slug or f"{data['name']}-{data['cui']}")
        db_filename = f"{slug}.sqlite"
        company_record = {**data, "slug": slug, "db_filename": db_filename, "documents_subdir": slug}
        target_db = tenant_db_path(company_record)
        docs = tenant_documents_path(company_record)
        company_id = None
        copied_templates = 0
        db_created = False
        docs_created = False
        try:
            with auth_connect() as con:
                con.execute("BEGIN IMMEDIATE")
                duplicate = con.execute(
                    "SELECT id,name,slug,cui FROM companies WHERE slug=? OR db_filename=? OR cui=? COLLATE NOCASE",
                    (slug, db_filename, data["cui"]),
                ).fetchone()
                if duplicate:
                    raise ValueError(
                        f"Există deja compania '{duplicate['name']}' cu slug/CUI incompatibil "
                        f"({duplicate['slug']} / {duplicate['cui']})."
                    )
                if target_db.exists():
                    raise FileExistsError(
                        f"Fișierul bazei există deja fără înregistrare în aplicație: {target_db}. "
                        "Redenumiți slug-ul sau verificați fișierul orfan."
                    )
                company_id = register_company(
                    con,
                    slug=slug,
                    name=data["name"],
                    cui=data["cui"],
                    reg_com=data["reg_com"],
                    address=data["address"],
                    administrator=data["administrator"],
                    db_filename=db_filename,
                    documents_subdir=slug,
                )
                create_tenant_database(target_db, company_data=data)
                db_created = True
                docs_existed = docs.exists()
                docs.mkdir(parents=True, exist_ok=True)
                docs_created = not docs_existed
                copied_templates = copy_standard_templates_to_company(docs)
                con.execute(
                    "INSERT INTO user_companies(user_id,company_id,role) VALUES(?,?,'ADMIN') "
                    "ON CONFLICT(user_id,company_id) DO UPDATE SET role='ADMIN'",
                    (g.user["id"], company_id),
                )
                con.commit()
            status = tenant_database_status(company_record)
            if not status["ok"]:
                raise RuntimeError(
                    "Baza a fost creată, dar verificarea finală a eșuat: "
                    + (status["error"] or status["integrity"] or ", ".join(status["missing_tables"]))
                )
        except (ValueError, FileExistsError) as exc:
            if company_id is not None:
                with auth_connect() as cleanup_con:
                    cleanup_con.execute("DELETE FROM companies WHERE id=?", (company_id,))
                    cleanup_con.commit()
            if db_created:
                target_db.unlink(missing_ok=True)
            if docs_created:
                shutil.rmtree(docs, ignore_errors=True)
            return json_error(str(exc), 400)
        except Exception as exc:
            if company_id is not None:
                with auth_connect() as cleanup_con:
                    cleanup_con.execute("DELETE FROM companies WHERE id=?", (company_id,))
                    cleanup_con.commit()
            if db_created:
                target_db.unlink(missing_ok=True)
            if docs_created:
                shutil.rmtree(docs, ignore_errors=True)
            app.logger.exception("Company provisioning failed")
            return json_error(
                f"Crearea companiei a eșuat la baza SQLite: {type(exc).__name__}: {exc}",
                500,
            )
        security_audit(
            "COMPANY_CREATED",
            user_id=g.user["id"],
            company_id=company_id,
            details=f"{data['name']}; db={target_db}; templates={copied_templates}",
        )
        return jsonify(
            ok=True,
            id=company_id,
            slug=slug,
            db_created=True,
            db_filename=db_filename,
            db_path=str(target_db),
            db_size_bytes=target_db.stat().st_size,
            templates_copied=copied_templates,
        )


    @app.patch("/api/admin/companies/<int:company_id>")
    @auth_required
    def api_admin_update_company(company_id: int):
        if not admin_access():
            return json_error("Acces interzis.", 403)
        if not g.user["is_superadmin"] and (not g.company or company_id != int(g.company["id"])):
            return json_error("Puteți edita numai compania activă.", 403)
        try:
            item = update_company_records(company_id, payload(), allow_active=bool(g.user["is_superadmin"]))
        except ValueError as exc:
            return json_error(str(exc), 400)
        except LookupError as exc:
            return json_error(str(exc), 404)
        return jsonify(ok=True, item=item)

    @app.post("/api/admin/companies/<int:company_id>/storage/repair")
    @auth_required
    def api_admin_repair_company_storage(company_id: int):
        if not g.user["is_superadmin"]:
            return json_error("Doar administratorul sistem poate repara stocarea unei companii.", 403)
        with auth_connect() as con:
            company_row = con.execute("SELECT * FROM companies WHERE id=?", (company_id,)).fetchone()
            if not company_row:
                return json_error("Compania nu există.", 404)
        try:
            status = repair_tenant_database(company_row)
            docs_path = tenant_documents_path(company_row)
            docs_path.mkdir(parents=True, exist_ok=True)
            copied_templates = copy_standard_templates_to_company(docs_path)
        except Exception as exc:
            app.logger.exception("Company storage repair failed")
            return json_error(f"Repararea bazei a eșuat: {type(exc).__name__}: {exc}", 500)
        security_audit(
            "COMPANY_STORAGE_REPAIRED",
            user_id=g.user["id"],
            company_id=company_id,
            details=f"created={status.get('created')}; db={status['path']}; templates={copied_templates}",
        )
        return jsonify(ok=True, storage=status, templates_copied=copied_templates)

    @app.post("/api/admin/users")
    @auth_required
    def api_admin_create_user():
        if not admin_access():
            return json_error("Acces interzis.", 403)
        data = payload()
        validate_password(data.get("password") or "")
        email = (data.get("email") or "").strip().lower()
        role = data.get("role") or "VIEWER"
        if role not in ROLE_LEVEL:
            return json_error("Rol invalid.")
        company_id = int(data.get("company_id") or (g.company["id"] if g.company else 0))
        if not g.user["is_superadmin"] and company_id != g.company["id"]:
            return json_error("Nu puteți acorda acces la altă companie.", 403)
        with auth_connect() as con:
            existing = con.execute("SELECT * FROM users WHERE email=? COLLATE NOCASE", (email,)).fetchone()
            if existing:
                user_id = int(existing["id"])
            else:
                cur = con.execute(
                    "INSERT INTO users(email,display_name,password_hash,is_superadmin) VALUES(?,?,?,0)",
                    (email, data.get("display_name") or email, hash_password(data["password"])),
                )
                user_id = int(cur.lastrowid)
            con.execute(
                "INSERT INTO user_companies(user_id,company_id,role) VALUES(?,?,?) ON CONFLICT(user_id,company_id) DO UPDATE SET role=excluded.role",
                (user_id, company_id, role),
            )
            con.commit()
        security_audit("USER_CREATED_OR_ASSIGNED", user_id=g.user["id"], company_id=company_id, details=email)
        return jsonify(ok=True, id=user_id)

    @app.post("/api/admin/memberships")
    @auth_required
    def api_admin_membership():
        if not admin_access():
            return json_error("Acces interzis.", 403)
        data = payload()
        user_id = int(data["user_id"])
        company_id = int(data.get("company_id") or g.company["id"])
        role = data["role"]
        if role not in ROLE_LEVEL:
            return json_error("Rol invalid.")
        if not g.user["is_superadmin"] and company_id != g.company["id"]:
            return json_error("Acces interzis.", 403)
        with auth_connect() as con:
            con.execute(
                "INSERT INTO user_companies(user_id,company_id,role) VALUES(?,?,?) ON CONFLICT(user_id,company_id) DO UPDATE SET role=excluded.role",
                (user_id, company_id, role),
            )
            con.commit()
        return jsonify(ok=True)

    @app.patch("/api/admin/users/<int:user_id>")
    @auth_required
    def api_admin_update_user(user_id: int):
        if not admin_access():
            return json_error("Acces interzis.", 403)
        data = payload()
        allowed = {"display_name", "active"} if g.user["is_superadmin"] else {"display_name"}
        updates = {key: value for key, value in data.items() if key in allowed}
        if not updates:
            return json_error("Nu există câmpuri de actualizat.")
        if not g.user["is_superadmin"]:
            with auth_connect() as con:
                access = con.execute("SELECT 1 FROM user_companies WHERE user_id=? AND company_id=?", (user_id, g.company["id"])).fetchone()
                if not access:
                    return json_error("Acces interzis.", 403)
        with auth_connect() as con:
            con.execute(f"UPDATE users SET {','.join(f'{key}=?' for key in updates)},updated_at=? WHERE id=?", [*updates.values(), utcnow(), user_id])
            if updates.get("active") in {0, False}:
                con.execute("UPDATE auth_sessions SET revoked_at=? WHERE user_id=? AND revoked_at IS NULL", (utcnow(), user_id))
            con.commit()
        return jsonify(ok=True)

    @app.errorhandler(sqlite3.IntegrityError)
    def handle_integrity(exc):
        if request.path.startswith("/api/"):
            return json_error(f"Date duplicate sau nevalide: {exc}", 400)
        return "Date duplicate sau nevalide", 400

    @app.errorhandler(413)
    def too_large(_exc):
        return json_error("Fișierul depășește limita de 25 MB.", 413)

    @app.errorhandler(HTTPException)
    def http_error(exc):
        if request.path.startswith("/api/"):
            return json_error(exc.description or "Eroare HTTP.", exc.code or 500)
        return render_template("error.html", message=exc.description or "Eroare HTTP."), exc.code or 500

    @app.errorhandler(Exception)
    def unhandled(exc):
        app.logger.exception("Unhandled error")
        if request.path.startswith("/api/"):
            return json_error("A apărut o eroare internă. Evenimentul a fost înregistrat.", 500)
        return render_template("error.html", message="A apărut o eroare internă."), 500

    return app


def secrets_compare(left: str, right: str) -> bool:
    import hmac
    return hmac.compare_digest(left.encode("utf-8"), right.encode("utf-8"))
