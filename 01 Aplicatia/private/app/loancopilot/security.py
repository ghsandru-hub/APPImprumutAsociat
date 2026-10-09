from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import struct
import time
from urllib.parse import quote
import secrets
from pathlib import Path
from typing import Iterable

from cryptography.fernet import Fernet

from .config import APP_SECRET_PATH, FERNET_KEY_PATH, ensure_directories

PASSWORD_MIN_LENGTH = 12
SCRYPT_N = 2**15
SCRYPT_R = 8
SCRYPT_P = 1


def _read_or_create(path: Path, size: int, *, fernet: bool = False) -> bytes:
    ensure_directories()
    if path.exists():
        return path.read_bytes().strip()
    value = Fernet.generate_key() if fernet else secrets.token_bytes(size)
    path.write_bytes(value)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return value


def app_secret() -> bytes:
    return _read_or_create(APP_SECRET_PATH, 48)


def fernet() -> Fernet:
    return Fernet(_read_or_create(FERNET_KEY_PATH, 32, fernet=True))


def validate_password(password: str) -> None:
    if len(password or "") < PASSWORD_MIN_LENGTH:
        raise ValueError(f"Parola trebuie să aibă minimum {PASSWORD_MIN_LENGTH} caractere.")
    if not re.search(r"[A-Za-zĂÂÎȘȚăâîșț]", password) or not re.search(r"\d", password):
        raise ValueError("Parola trebuie să conțină cel puțin o literă și o cifră.")


def hash_password(password: str) -> str:
    validate_password(password)
    salt = secrets.token_bytes(16)
    derived = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P, dklen=32, maxmem=64 * 1024 * 1024)
    return "scrypt${}${}${}${}${}".format(
        SCRYPT_N,
        SCRYPT_R,
        SCRYPT_P,
        base64.urlsafe_b64encode(salt).decode("ascii"),
        base64.urlsafe_b64encode(derived).decode("ascii"),
    )


def verify_password(password: str, encoded: str) -> bool:
    try:
        kind, n, r, p, salt_b64, hash_b64 = encoded.split("$", 5)
        if kind != "scrypt":
            return False
        salt = base64.urlsafe_b64decode(salt_b64.encode("ascii"))
        expected = base64.urlsafe_b64decode(hash_b64.encode("ascii"))
        actual = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=int(n), r=int(r), p=int(p), dklen=len(expected), maxmem=64 * 1024 * 1024)
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False


def random_token(size: int = 32) -> str:
    return secrets.token_urlsafe(size)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def stable_hmac(value: str) -> str:
    return hmac.new(app_secret(), value.encode("utf-8"), hashlib.sha256).hexdigest()


def encrypt_text(value: str) -> str:
    return fernet().encrypt(value.encode("utf-8")).decode("ascii")


def decrypt_text(value: str | None) -> str | None:
    if not value:
        return None
    return fernet().decrypt(value.encode("ascii")).decode("utf-8")


def create_totp_secret() -> str:
    return base64.b32encode(secrets.token_bytes(20)).decode("ascii").rstrip("=")


def _totp_at(secret: str, counter: int, digits: int = 6) -> str:
    padding = "=" * ((8 - len(secret) % 8) % 8)
    key = base64.b32decode((secret + padding).upper().encode("ascii"))
    digest = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    value = (struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF) % (10 ** digits)
    return f"{value:0{digits}d}"


def verify_totp(secret: str, code: str) -> bool:
    normalized = re.sub(r"\s+", "", code or "")
    if not re.fullmatch(r"\d{6}", normalized):
        return False
    current = int(time.time()) // 30
    return any(hmac.compare_digest(_totp_at(secret, current + delta), normalized) for delta in (-1, 0, 1))


def provisioning_uri(secret: str, email: str) -> str:
    issuer = "smartBIZ LoanCopilot"
    label = quote(f"{issuer}:{email}", safe="")
    return f"otpauth://totp/{label}?secret={secret}&issuer={quote(issuer, safe='')}&algorithm=SHA1&digits=6&period=30"


def generate_recovery_codes(count: int = 10) -> list[str]:
    return [f"{secrets.token_hex(4).upper()}-{secrets.token_hex(4).upper()}" for _ in range(count)]


def hash_recovery_code(code: str) -> str:
    normalized = re.sub(r"[^A-Fa-f0-9]", "", code or "").upper()
    return stable_hmac(f"recovery:{normalized}")


def hash_recovery_codes(codes: Iterable[str]) -> str:
    return json.dumps([hash_recovery_code(code) for code in codes])
