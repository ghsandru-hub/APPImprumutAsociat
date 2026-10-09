from __future__ import annotations

import csv
import io
import re
import shutil
import sqlite3
import subprocess
from datetime import date, timedelta
from html import unescape
from urllib.request import Request, urlopen

from .config import APP_VERSION, BNR_RATE_URLS

MONTHS_RO = {
    "ian": 1, "ianuarie": 1, "feb": 2, "februarie": 2, "mar": 3, "martie": 3,
    "apr": 4, "aprilie": 4, "mai": 5, "iun": 6, "iunie": 6, "iul": 7, "iulie": 7,
    "aug": 8, "august": 8, "sep": 9, "sept": 9, "septembrie": 9, "oct": 10, "octombrie": 10,
    "nov": 11, "noiembrie": 11, "dec": 12, "decembrie": 12,
}


def rows_to_dicts(rows):
    return [dict(row) for row in rows]


def parse_date(value: str) -> date:
    return date.fromisoformat(value)


def quarter_end_for(day: date) -> date:
    if day.month <= 3:
        return date(day.year, 3, 31)
    if day.month <= 6:
        return date(day.year, 6, 30)
    if day.month <= 9:
        return date(day.year, 9, 30)
    return date(day.year, 12, 31)


def iter_completed_quarters(start: date, end: date, include_partial_end: bool = False):
    current = start
    while current <= end:
        q_end = quarter_end_for(current)
        if q_end <= end:
            yield current, q_end
            current = q_end + timedelta(days=1)
            continue
        if include_partial_end:
            yield current, end
        break


def signed_principal_delta(txn_type: str, amount: float) -> float:
    if txn_type in {"ADVANCE", "OPENING_BALANCE"}:
        return amount
    if txn_type == "REPAYMENT":
        return -amount
    return 0.0


def balance_at(con: sqlite3.Connection, loan_id: int, day: date) -> float:
    rows = con.execute(
        "SELECT txn_type,amount FROM transactions WHERE loan_id=? AND txn_date<=? ORDER BY txn_date,id",
        (loan_id, day.isoformat()),
    ).fetchall()
    return round(sum(signed_principal_delta(row["txn_type"], float(row["amount"])) for row in rows), 2)


def audit(con: sqlite3.Connection, action: str, entity: str, *, entity_id: int | None = None, details: str = "", user_email: str = "") -> None:
    con.execute(
        "INSERT INTO audit_log(action,entity,entity_id,details,user_email) VALUES(?,?,?,?,?)",
        (action, entity, entity_id, details, user_email),
    )


def normalize_html_text(raw_html: str, *, include_scripts: bool = False) -> str:
    """Transformă HTML-ul BNR într-un text stabil pentru parsare."""
    text = raw_html
    if not include_scripts:
        text = re.sub(r"(?is)<script.*?</script>", " ", text)
    text = re.sub(r"(?is)<style.*?</style>", " ", text)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    text = unescape(text)
    text = re.sub(
        r"\\u([0-9a-fA-F]{4})",
        lambda match: chr(int(match.group(1), 16)),
        text,
    )
    text = text.replace(r"\/", "/").replace("\xa0", " ")
    return re.sub(r"\s+", " ", text).strip()


RO_DATE_PATTERN = (
    r"(?:\d{1,2}[./-]\d{1,2}[./-]\d{4}"
    r"|\d{1,2}\s+[A-Za-zăâîșțşţĂÂÎȘȚŞŢ]{3,15}\.?\s*\d{4})"
)


def parse_ro_date(text: str) -> str | None:
    value = re.sub(r"\s+", " ", text.strip())
    numeric = re.fullmatch(r"(\d{1,2})[./-](\d{1,2})[./-](\d{4})", value)
    try:
        if numeric:
            return date(int(numeric.group(3)), int(numeric.group(2)), int(numeric.group(1))).isoformat()
        match = re.fullmatch(
            r"(\d{1,2})\s+([A-Za-zăâîșțşţĂÂÎȘȚŞŢ]+)\.?\s*(\d{4})",
            value,
        )
        if not match:
            return None
        day = int(match.group(1))
        month_token = (
            match.group(2)
            .lower()
            .replace("ş", "ș")
            .replace("ţ", "ț")
            .rstrip(".")
        )
        month = MONTHS_RO.get(month_token) or MONTHS_RO.get(month_token[:3])
        if not month:
            return None
        return date(int(match.group(3)), month, day).isoformat()
    except ValueError:
        return None


def _rate_from_window(text: str, start: int, end: int) -> float | None:
    """Extrage prima rată plauzibilă imediat după o dată."""
    window = text[start:end]
    candidates: list[tuple[int, int, float]] = []
    for match in re.finditer(
        r"(?<!\d)(\d{1,2}(?:[,.]\d{1,4})?)(?!\d)\s*(%|p\.?\s*a\.?|la\s+sută)?",
        window,
        flags=re.I,
    ):
        token = match.group(1)
        value = float(token.replace(",", "."))
        if not 0 <= value <= 30:
            continue
        quality = 0 if ("," in token or "." in token or match.group(2)) else 1
        candidates.append((quality, match.start(), value))
    if not candidates:
        return None
    candidates.sort(key=lambda item: (item[0], item[1]))
    return candidates[0][2]


def _records_after_table_marker(text: str) -> list[tuple[str, float]]:
    lower = text.casefold()
    markers = []
    for marker_pattern in (
        r"valabile\s+din\s*:",
        r"valabil[ăa]\s+din\s*:",
        r"ratele?\s+dobânzilor\s+bnr[^.]{0,120}valabil[ăe]\s+din\s*:",
    ):
        markers.extend(match.end() for match in re.finditer(marker_pattern, lower, flags=re.I))
    records: list[tuple[str, float]] = []
    for marker in markers:
        section = text[marker: marker + 20000]
        date_matches = list(re.finditer(RO_DATE_PATTERN, section, flags=re.I))
        for index, date_match in enumerate(date_matches):
            effective_date = parse_ro_date(date_match.group(0))
            if not effective_date:
                continue
            next_date_start = date_matches[index + 1].start() if index + 1 < len(date_matches) else len(section)
            window_end = min(next_date_start, date_match.end() + 220)
            rate = _rate_from_window(section, date_match.end(), window_end)
            if rate is not None:
                records.append((effective_date, rate))
    return records


def _direct_policy_rate(text: str) -> tuple[str, float] | None:
    """Parsează cardul curent: denumire → Valabilă din → dată → rată."""
    pattern = re.compile(
        rf"rata\s+dobânzii\s+de\s+politică\s+monetară"
        rf".{{0,260}}?valabil[ăa]\s+din\s+({RO_DATE_PATTERN})"
        rf".{{0,180}}?([0-9]{{1,2}}(?:[,.][0-9]{{1,4}})?)\s*(?:%|p\.?\s*a\.?|la\s+sută)",
        flags=re.I,
    )
    match = pattern.search(text)
    if not match:
        return None
    effective_date = parse_ro_date(match.group(1))
    if not effective_date:
        return None
    return effective_date, float(match.group(2).replace(",", "."))


def _generic_historical_records(text: str) -> list[tuple[str, float]]:
    """Fallback pentru tabelul vechi BNR, inclusiv variantele Mobile.aspx."""
    lower = text.casefold()
    header_positions = [
        match.end()
        for match in re.finditer(r"rata\s+dobânzii\s+de\s+politică\s+monetară", lower, flags=re.I)
    ]
    records: list[tuple[str, float]] = []
    for header_end in header_positions[:8]:
        section = text[header_end: header_end + 15000]
        date_matches = list(re.finditer(RO_DATE_PATTERN, section, flags=re.I))
        for index, date_match in enumerate(date_matches):
            before = section[max(0, date_match.start() - 120): date_match.start()].casefold()
            if "ședinț" in before or "sedint" in before:
                continue
            effective_date = parse_ro_date(date_match.group(0))
            if not effective_date:
                continue
            next_date_start = date_matches[index + 1].start() if index + 1 < len(date_matches) else len(section)
            window_end = min(next_date_start, date_match.end() + 180)
            rate = _rate_from_window(section, date_match.end(), window_end)
            if rate is not None:
                records.append((effective_date, rate))
    return records


def parse_bnr_rate_page(raw_html: str, source_url: str) -> dict:
    attempts = [
        normalize_html_text(raw_html, include_scripts=False),
        normalize_html_text(raw_html, include_scripts=True),
    ]

    # Prioritate 1: cardul curent, care leagă explicit denumirea ratei de data
    # aplicării și de valoare.
    for text in attempts:
        direct = _direct_policy_rate(text)
        if direct and 0 <= direct[1] <= 30:
            effective_date, rate = direct
            break
    else:
        # Prioritate 2: tabelul oficial după marcajul „Valabile din”.
        table_records: list[tuple[str, float]] = []
        for text in attempts:
            table_records.extend(_records_after_table_marker(text))
        table_valid = {
            (effective_date, round(rate, 4))
            for effective_date, rate in table_records
            if 0 <= rate <= 30
        }
        if table_valid:
            effective_date, rate = max(table_valid, key=lambda item: item[0])
        else:
            # Prioritate 3: structura istorică veche/Mobile.aspx.
            fallback_records: list[tuple[str, float]] = []
            for text in attempts:
                fallback_records.extend(_generic_historical_records(text))
            fallback_valid = {
                (effective_date, round(rate, 4))
                for effective_date, rate in fallback_records
                if 0 <= rate <= 30
            }
            if not fallback_valid:
                raise ValueError(
                    "Pagina BNR a fost accesată, dar tabelul/cardul cu rata și data de "
                    "intrare în vigoare nu a putut fi identificat automat."
                )
            effective_date, rate = max(fallback_valid, key=lambda item: item[0])
    return {
        "effective_date": effective_date,
        "rate": round(rate, 4),
        "rate_name": "Rata dobânzii de politică monetară",
        "source_url": source_url,
        "source_document": "Pagina oficială BNR – rata dobânzii de politică monetară",
        "entry_mode": "BNR_AUTO",
        "notes": "Preluare automată din sursa oficială BNR; parser card/tabel cu fallback.",
    }


def _decode_response_body(body: bytes, charset: str | None = None) -> str:
    for encoding in (charset, "utf-8", "cp1250", "iso-8859-2"):
        if not encoding:
            continue
        try:
            return body.decode(encoding)
        except (LookupError, UnicodeDecodeError):
            continue
    return body.decode("utf-8", "replace")


def _fetch_url_urllib(url: str) -> str:
    req = Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36 "
                f"LoanCopilot/{APP_VERSION}"
            ),
            "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
            "Accept-Language": "ro-RO,ro;q=0.9,en;q=0.6",
            "Accept-Encoding": "identity",
            "Cache-Control": "no-cache",
        },
    )
    with urlopen(req, timeout=25) as response:
        body = response.read(5 * 1024 * 1024 + 1)
        if len(body) > 5 * 1024 * 1024:
            raise ValueError("Răspunsul BNR depășește limita de 5 MB.")
        charset = response.headers.get_content_charset()
    return _decode_response_body(body, charset)


def _fetch_url_curl(url: str) -> str:
    curl = shutil.which("curl")
    if not curl:
        raise RuntimeError("curl nu este disponibil pe server pentru metoda de rezervă.")
    completed = subprocess.run(
        [
            curl,
            "--fail", "--silent", "--show-error", "--location",
            "--max-time", "30", "--connect-timeout", "10", "--compressed",
            "--user-agent", f"Mozilla/5.0 LoanCopilot/{APP_VERSION}",
            "--header", "Accept-Language: ro-RO,ro;q=0.9,en;q=0.6",
            url,
        ],
        capture_output=True,
        timeout=35,
        check=False,
    )
    if completed.returncode != 0:
        detail = completed.stderr.decode("utf-8", "replace").strip()
        raise RuntimeError(detail or f"curl s-a încheiat cu codul {completed.returncode}.")
    if len(completed.stdout) > 5 * 1024 * 1024:
        raise ValueError("Răspunsul BNR depășește limita de 5 MB.")
    return _decode_response_body(completed.stdout)


def fetch_current_bnr_rate() -> dict:
    errors = []
    for url in BNR_RATE_URLS:
        for method_name, fetcher in (("urllib", _fetch_url_urllib), ("curl", _fetch_url_curl)):
            try:
                raw = fetcher(url)
                return parse_bnr_rate_page(raw, url)
            except Exception as exc:
                errors.append(f"{method_name} {url}: {type(exc).__name__}: {exc}")
    detail = " | ".join(errors[-10:])
    raise RuntimeError(
        "Actualizarea automată BNR nu a reușit. Au fost încercate paginile "
        "oficiale prin urllib și curl. Detalii: " + detail
    )

def rate_row_for_day(con: sqlite3.Connection, day: date) -> sqlite3.Row:
    row = con.execute(
        "SELECT * FROM bnr_reference_rates WHERE effective_date<=? ORDER BY effective_date DESC,id DESC LIMIT 1",
        (day.isoformat(),),
    ).fetchone()
    if not row:
        raise ValueError(f"Nu există rată BNR înregistrată pentru data {day.isoformat()}.")
    return row


def calculate_period(con: sqlite3.Connection, loan: sqlite3.Row, start: date, end: date) -> dict:
    opening = balance_at(con, loan["id"], start - timedelta(days=1))
    advances = float(con.execute(
        "SELECT COALESCE(SUM(amount),0) FROM transactions WHERE loan_id=? AND txn_type='ADVANCE' AND txn_date BETWEEN ? AND ?",
        (loan["id"], start.isoformat(), end.isoformat()),
    ).fetchone()[0])
    repayments = float(con.execute(
        "SELECT COALESCE(SUM(amount),0) FROM transactions WHERE loan_id=? AND txn_type='REPAYMENT' AND txn_date BETWEEN ? AND ?",
        (loan["id"], start.isoformat(), end.isoformat()),
    ).fetchone()[0])
    segments: list[dict] = []
    cursor = start
    total_unrounded = 0.0
    while cursor <= end:
        balance = max(0.0, balance_at(con, loan["id"], cursor))
        rate_row = rate_row_for_day(con, cursor)
        rate = float(rate_row["rate"])
        daily = balance * rate / 100.0 / 365.0
        total_unrounded += daily
        if segments and segments[-1]["bnr_rate_id"] == rate_row["id"]:
            segment = segments[-1]
            segment["segment_end"] = cursor.isoformat()
            segment["days"] += 1
            segment["balance_days"] += balance
            segment["unrounded"] += daily
        else:
            segments.append({
                "bnr_rate_id": rate_row["id"],
                "segment_start": cursor.isoformat(),
                "segment_end": cursor.isoformat(),
                "days": 1,
                "rate": rate,
                "balance_days": balance,
                "unrounded": daily,
            })
        cursor += timedelta(days=1)
    for segment in segments:
        segment["calculated_amount"] = round(segment.pop("unrounded"), 2)
        segment["balance_days"] = round(segment["balance_days"], 2)
    amount = round(total_unrounded, 2)
    if segments:
        difference = round(amount - sum(float(item["calculated_amount"]) for item in segments), 2)
        if difference:
            segments[-1]["calculated_amount"] = round(float(segments[-1]["calculated_amount"]) + difference, 2)
    return {
        "period_start": start.isoformat(),
        "period_end": end.isoformat(),
        "opening_balance": round(opening, 2),
        "principal_advances": round(advances, 2),
        "principal_repayments": round(repayments, 2),
        "closing_balance": balance_at(con, loan["id"], end),
        "days": (end - start).days + 1,
        "calculated_amount": amount,
        "rate_summary": " | ".join(f"{item['rate']:.2f}%: {item['days']} zile" for item in segments),
        "segments": segments,
    }


def recalculate_loan(
    con: sqlite3.Connection,
    loan_id: int,
    *,
    sync_recognized: bool = False,
    cutoff: date | None = None,
) -> int:
    loan = con.execute("SELECT * FROM loans WHERE id=?", (loan_id,)).fetchone()
    if not loan or loan["status"] == "CLOSED" or not loan["interest_start_date"]:
        return 0

    start = parse_date(loan["interest_start_date"])
    maturity = parse_date(loan["maturity_date"]) if loan["maturity_date"] else (cutoff or date.today())
    effective_cutoff = min(cutoff or date.today(), maturity)
    count = 0

    for period_start, period_end in iter_completed_quarters(start, effective_cutoff, include_partial_end=False):
        calc = calculate_period(con, loan, period_start, period_end)
        existing = con.execute(
            "SELECT id,status,recognized_amount FROM interest_accruals WHERE loan_id=? AND period_start=? AND period_end=?",
            (loan["id"], calc["period_start"], calc["period_end"]),
        ).fetchone()
        notes = f"Rată BNR variabilă · Actual/365 · {calc['rate_summary']}."
        if existing:
            recognized = (
                calc["calculated_amount"]
                if sync_recognized and existing["status"] == "RECOGNIZED"
                else existing["recognized_amount"]
            )
            con.execute(
                """UPDATE interest_accruals SET opening_balance=?,principal_advances=?,principal_repayments=?,
                   closing_balance=?,days=?,calculated_amount=?,recognized_amount=?,notes=? WHERE id=?""",
                (calc["opening_balance"], calc["principal_advances"], calc["principal_repayments"], calc["closing_balance"],
                 calc["days"], calc["calculated_amount"], recognized, notes, existing["id"]),
            )
            accrual_id = existing["id"]
        else:
            cur = con.execute(
                """INSERT INTO interest_accruals(loan_id,period_start,period_end,opening_balance,principal_advances,
                   principal_repayments,closing_balance,days,calculated_amount,recognized_amount,status,notes)
                   VALUES(?,?,?,?,?,?,?,?,?,0,'CALCULATED',?)""",
                (loan["id"], calc["period_start"], calc["period_end"], calc["opening_balance"], calc["principal_advances"],
                 calc["principal_repayments"], calc["closing_balance"], calc["days"], calc["calculated_amount"], notes),
            )
            accrual_id = cur.lastrowid
        con.execute("DELETE FROM interest_segments WHERE accrual_id=?", (accrual_id,))
        con.executemany(
            """INSERT INTO interest_segments(accrual_id,bnr_rate_id,segment_start,segment_end,days,rate,balance_days,calculated_amount)
               VALUES(?,?,?,?,?,?,?,?)""",
            [(accrual_id, item["bnr_rate_id"], item["segment_start"], item["segment_end"], item["days"], item["rate"],
              item["balance_days"], item["calculated_amount"]) for item in calc["segments"]],
        )
        count += 1
    return count


def recalculate_all(con: sqlite3.Connection, *, user_email: str = "system", sync_recognized: bool = False, cutoff: date | None = None) -> int:
    loan_ids = [
        int(row["id"])
        for row in con.execute("SELECT id FROM loans WHERE status<>'CLOSED' ORDER BY id").fetchall()
    ]
    count = sum(
        recalculate_loan(con, loan_id, sync_recognized=sync_recognized, cutoff=cutoff)
        for loan_id in loan_ids
    )
    latest = con.execute("SELECT rate FROM bnr_reference_rates ORDER BY effective_date DESC,id DESC LIMIT 1").fetchone()
    if latest:
        con.execute("UPDATE loans SET interest_rate=? WHERE interest_rate_mode='BNR_REFERENCE'", (latest["rate"],))
    audit(con, "RECALCULATE", "interest_accruals", details=f"Recalculate {count} perioade pe subperioade BNR", user_email=user_email)
    con.commit()
    return count


def dashboard(con: sqlite3.Connection) -> dict:
    company_row = con.execute("SELECT * FROM company LIMIT 1").fetchone()
    company = dict(company_row) if company_row else {}
    loans = rows_to_dicts(con.execute(
        """SELECT l.id,l.contract_no,l.original_contract_date,l.contract_date,l.interest_start_date,l.interest_rate,
                  l.interest_rate_mode,l.maturity_date,l.status,a.name associate_name,b.funded AS principal,b.repaid,b.balance,
                  COALESCE((SELECT SUM(calculated_amount) FROM interest_accruals ia WHERE ia.loan_id=l.id),0) interest_calculated,
                  COALESCE((SELECT SUM(recognized_amount) FROM interest_accruals ia WHERE ia.loan_id=l.id),0) interest_recognized,
                  COALESCE((SELECT SUM(amount) FROM transactions t WHERE t.loan_id=l.id AND t.txn_type='INTEREST_PAYMENT'),0) interest_paid
           FROM loans l JOIN associates a ON a.id=l.associate_id JOIN loan_balances b ON b.loan_id=l.id ORDER BY l.id"""
    ))
    current_rate = con.execute("SELECT * FROM bnr_reference_rates ORDER BY effective_date DESC,id DESC LIMIT 1").fetchone()
    totals = {
        "principal": round(sum(float(row["principal"]) for row in loans), 2),
        "repaid": round(sum(float(row["repaid"]) for row in loans), 2),
        "balance": round(sum(float(row["balance"]) for row in loans), 2),
        "interest_calculated": round(sum(float(row["interest_calculated"]) for row in loans), 2),
        "interest_recognized": round(sum(float(row["interest_recognized"]) for row in loans), 2),
        "interest_paid": round(sum(float(row["interest_paid"]) for row in loans), 2),
    }
    totals["interest_outstanding"] = round(totals["interest_recognized"] - totals["interest_paid"], 2)
    recent = rows_to_dicts(con.execute(
        """SELECT t.id,t.txn_date,t.txn_type,t.amount,t.tax_withheld,t.reference,l.contract_no,a.name associate_name
           FROM transactions t JOIN loans l ON l.id=t.loan_id JOIN associates a ON a.id=l.associate_id
           WHERE t.txn_type<>'OPENING_BALANCE' ORDER BY t.txn_date DESC,t.id DESC LIMIT 8"""
    ))
    return {"company": company, "loans": loans, "totals": totals, "recent": recent, "current_bnr_rate": dict(current_rate) if current_rate else None}


def csv_export(con: sqlite3.Connection, dataset: str) -> tuple[bytes, str]:
    definitions = {
        "loans": "SELECT l.*,a.name associate_name,b.funded AS funded_principal,b.repaid,b.balance FROM loans l JOIN associates a ON a.id=l.associate_id JOIN loan_balances b ON b.loan_id=l.id ORDER BY l.id",
        "transactions": "SELECT t.*,l.contract_no,a.name associate_name FROM transactions t JOIN loans l ON l.id=t.loan_id JOIN associates a ON a.id=l.associate_id ORDER BY t.txn_date,t.id",
        "interest": "SELECT ia.*,l.contract_no,a.name associate_name FROM interest_accruals ia JOIN loans l ON l.id=ia.loan_id JOIN associates a ON a.id=l.associate_id ORDER BY ia.period_start,ia.loan_id",
        "interest_segments": "SELECT s.*,l.contract_no,a.name associate_name FROM interest_segments s JOIN interest_accruals ia ON ia.id=s.accrual_id JOIN loans l ON l.id=ia.loan_id JOIN associates a ON a.id=l.associate_id ORDER BY s.segment_start,s.accrual_id",
        "bnr_rates": "SELECT * FROM bnr_reference_rates ORDER BY effective_date",
        "documents": "SELECT * FROM documents ORDER BY id",
    }
    if dataset not in definitions:
        raise ValueError("Set de date neacceptat.")
    rows = con.execute(definitions[dataset]).fetchall()
    output = io.StringIO(newline="")
    writer = csv.writer(output, delimiter=";")
    if rows:
        writer.writerow(rows[0].keys())
        for row in rows:
            writer.writerow([row[key] for key in row.keys()])
    return ("\ufeff" + output.getvalue()).encode("utf-8"), f"loancopilot_{dataset}.csv"
