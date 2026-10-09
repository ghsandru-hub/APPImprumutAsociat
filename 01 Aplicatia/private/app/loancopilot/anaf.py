from __future__ import annotations

import fcntl
import json
import os
import socket
import time
from dataclasses import dataclass
from datetime import date, datetime
from http.client import HTTPResponse
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .config import ANAF_API_URL, ANAF_RETRIES, ANAF_TIMEOUT, APP_VERSION, PRIVATE_ROOT


ANAF_RATE_LIMIT_FILE = PRIVATE_ROOT / "tmp" / "anaf_v9_rate_limit.lock"
ANAF_MIN_REQUEST_INTERVAL = 1.05


def _wait_for_request_slot() -> None:
    """Serializează cererile între procese și păstrează intervalul public ANAF."""
    ANAF_RATE_LIMIT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with ANAF_RATE_LIMIT_FILE.open("a+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            handle.seek(0)
            raw = handle.read().strip()
            try:
                last_request_at = float(raw) if raw else 0.0
            except ValueError:
                last_request_at = 0.0
            wait_seconds = ANAF_MIN_REQUEST_INTERVAL - (time.time() - last_request_at)
            if wait_seconds > 0:
                time.sleep(wait_seconds)
            now = time.time()
            handle.seek(0)
            handle.truncate()
            handle.write(f"{now:.6f}")
            handle.flush()
            os.fsync(handle.fileno())
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


class AnafLookupError(RuntimeError):
    """Raised when the ANAF service cannot return a usable company record."""


@dataclass(frozen=True)
class AnafLookupResult:
    cui: str
    queried_date: str
    name: str
    reg_com: str
    address: str
    fiscal_address: str
    registration_status: str
    registration_date: str
    caen_code: str
    vat_registered: bool
    vat_on_collection: bool
    inactive: bool
    split_vat: bool
    e_invoice: bool
    tax_authority: str
    legal_form: str
    organisation_form: str
    ownership_form: str
    iban: str
    source_url: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "cui": self.cui,
            "queried_date": self.queried_date,
            "name": self.name,
            "reg_com": self.reg_com,
            "address": self.address,
            "fiscal_address": self.fiscal_address,
            "registration_status": self.registration_status,
            "registration_date": self.registration_date,
            "caen_code": self.caen_code,
            "vat_registered": self.vat_registered,
            "vat_on_collection": self.vat_on_collection,
            "inactive": self.inactive,
            "split_vat": self.split_vat,
            "e_invoice": self.e_invoice,
            "tax_authority": self.tax_authority,
            "legal_form": self.legal_form,
            "organisation_form": self.organisation_form,
            "ownership_form": self.ownership_form,
            "iban": self.iban,
            "source_url": self.source_url,
        }


def normalize_cui(value: str | int) -> str:
    raw = str(value or "").strip().upper()
    if raw.startswith("RO"):
        raw = raw[2:]
    digits = "".join(ch for ch in raw if ch.isdigit())
    if not digits:
        raise ValueError("Introduceți un CUI numeric.")
    if len(digits) < 2 or len(digits) > 10:
        raise ValueError("CUI-ul trebuie să conțină între 2 și 10 cifre.")
    return digits


def normalize_query_date(value: str | None) -> str:
    raw = (value or "").strip()
    if not raw:
        return date.today().isoformat()
    try:
        parsed = datetime.strptime(raw, "%Y-%m-%d").date()
    except ValueError as exc:
        raise ValueError("Data interogării trebuie să fie în format AAAA-LL-ZZ.") from exc
    if parsed > date.today():
        raise ValueError("Data interogării ANAF nu poate fi în viitor.")
    return parsed.isoformat()


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    return _clean(value).lower() in {"1", "true", "da", "yes"}


def _social_address(data: dict[str, Any]) -> str:
    if not isinstance(data, dict):
        return ""
    pieces: list[str] = []
    country = _clean(data.get("stara"))
    county = _clean(data.get("sdenumire_Judet"))
    locality = _clean(data.get("sdenumire_Localitate"))
    street = _clean(data.get("sdenumire_Strada"))
    number = _clean(data.get("snumar_Strada"))
    details = _clean(data.get("sdetalii_Adresa"))
    postal = _clean(data.get("scod_Postal"))

    if country and country.upper() not in {"ROMANIA", "ROMÂNIA"}:
        pieces.append(country)
    if county:
        county_upper = county.upper()
        pieces.append(county if "BUCURE" in county_upper or county_upper.startswith("MUNICIPIUL") else f"JUD. {county}")
    if locality:
        pieces.append(locality)
    if street:
        pieces.append(street)
    if number:
        pieces.append(f"NR. {number}")
    if details:
        pieces.append(details)
    if postal:
        pieces.append(f"COD POȘTAL {postal}")
    return ", ".join(pieces)


def parse_v9_response(payload: Any, expected_cui: str, queried_date: str) -> AnafLookupResult:
    if not isinstance(payload, dict):
        raise AnafLookupError("ANAF a returnat un răspuns JSON cu structură neașteptată.")

    found = payload.get("found")
    if found is None and isinstance(payload.get("data"), dict):
        found = payload["data"].get("found")
    if not isinstance(found, list):
        found = []

    match: dict[str, Any] | None = None
    for item in found:
        if not isinstance(item, dict):
            continue
        general = item.get("date_generale") or item.get("dateGenerale") or {}
        if not isinstance(general, dict):
            continue
        try:
            item_cui = normalize_cui(general.get("cui") or expected_cui)
        except ValueError:
            continue
        if item_cui == expected_cui:
            match = item
            break

    if match is None:
        not_found = payload.get("notFound") or payload.get("not_found") or []
        if isinstance(not_found, list):
            normalized_not_found = []
            for value in not_found:
                try:
                    normalized_not_found.append(normalize_cui(value))
                except ValueError:
                    continue
            if expected_cui in normalized_not_found:
                raise AnafLookupError(f"CUI {expected_cui} nu a fost găsit în serviciul ANAF pentru data {queried_date}.")
        message = _clean(payload.get("message") or payload.get("error"))
        raise AnafLookupError(message or f"ANAF nu a returnat date pentru CUI {expected_cui}.")

    general = match.get("date_generale") or match.get("dateGenerale") or {}
    vat = match.get("inregistrare_scop_Tva") or match.get("inregistrare_scop_tva") or {}
    vat_collection = match.get("inregistrare_RTVAI") or match.get("inregistrare_rtvai") or {}
    inactive = match.get("stare_inactiv") or {}
    split_vat = match.get("inregistrare_SplitTVA") or match.get("inregistrare_split_tva") or {}
    social = match.get("adresa_sediu_social") or {}

    fiscal_address = _clean(general.get("adresa"))
    social_address = _social_address(social)
    preferred_address = social_address or fiscal_address

    return AnafLookupResult(
        cui=normalize_cui(general.get("cui") or expected_cui),
        queried_date=_clean(general.get("data")) or queried_date,
        name=_clean(general.get("denumire")),
        reg_com=_clean(general.get("nrRegCom") or general.get("nr_reg_com")),
        address=preferred_address,
        fiscal_address=fiscal_address,
        registration_status=_clean(general.get("stare_inregistrare")),
        registration_date=_clean(general.get("data_inregistrare")),
        caen_code=_clean(general.get("cod_CAEN") or general.get("cod_caen")),
        vat_registered=_as_bool(vat.get("scpTVA")),
        vat_on_collection=_as_bool(vat_collection.get("statusTvaIncasare")),
        inactive=_as_bool(inactive.get("statusInactivi")),
        split_vat=_as_bool(split_vat.get("statusSplitTVA")),
        e_invoice=_as_bool(general.get("statusRO_e_Factura")),
        tax_authority=_clean(general.get("organFiscalCompetent")),
        legal_form=_clean(general.get("forma_juridica")),
        organisation_form=_clean(general.get("forma_organizare")),
        ownership_form=_clean(general.get("forma_de_proprietate")),
        iban=_clean(general.get("iban")),
        source_url=ANAF_API_URL,
    )


def _read_response(response: HTTPResponse) -> Any:
    charset = response.headers.get_content_charset() or "utf-8"
    raw = response.read().decode(charset, errors="replace").lstrip("\ufeff").strip()
    if not raw:
        raise AnafLookupError("ANAF a returnat un răspuns gol.")
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        excerpt = " ".join(raw[:300].split())
        raise AnafLookupError(f"ANAF nu a returnat JSON valid: {excerpt}") from exc


def lookup_company(cui: str | int, query_date: str | None = None) -> AnafLookupResult:
    normalized_cui = normalize_cui(cui)
    normalized_date = normalize_query_date(query_date)
    body = json.dumps(
        [{"cui": int(normalized_cui), "data": normalized_date}],
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")

    last_error: Exception | None = None
    for attempt in range(max(1, ANAF_RETRIES)):
        request = Request(
            ANAF_API_URL,
            data=body,
            method="POST",
            headers={
                "Content-Type": "application/json; charset=utf-8",
                "Accept": "application/json",
                "User-Agent": f"LoanCopilot/{APP_VERSION}",
                "Cache-Control": "no-cache",
            },
        )
        try:
            _wait_for_request_slot()
            with urlopen(request, timeout=ANAF_TIMEOUT) as response:
                parsed = _read_response(response)
                return parse_v9_response(parsed, normalized_cui, normalized_date)
        except HTTPError as exc:
            last_error = exc
            response_text = ""
            try:
                response_text = exc.read().decode("utf-8", errors="replace")
            except Exception:
                pass
            if exc.code in {429, 500, 502, 503, 504} and attempt + 1 < max(1, ANAF_RETRIES):
                time.sleep(max(1.0, float(attempt + 1)))
                continue
            excerpt = " ".join(response_text[:250].split())
            suffix = f" · {excerpt}" if excerpt else ""
            raise AnafLookupError(f"Serviciul ANAF a răspuns HTTP {exc.code}{suffix}") from exc
        except (URLError, socket.timeout, TimeoutError) as exc:
            last_error = exc
            if attempt + 1 < max(1, ANAF_RETRIES):
                time.sleep(max(1.0, float(attempt + 1)))
                continue
            reason = getattr(exc, "reason", exc)
            raise AnafLookupError(f"Nu s-a putut comunica cu serviciul ANAF: {reason}") from exc
        except AnafLookupError:
            raise
        except Exception as exc:
            last_error = exc
            raise AnafLookupError(f"Interogarea ANAF a eșuat: {type(exc).__name__}: {exc}") from exc

    raise AnafLookupError(f"Interogarea ANAF a eșuat: {last_error}")
