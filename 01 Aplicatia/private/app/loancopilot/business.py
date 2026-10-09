from __future__ import annotations

import csv
import io
import json
import re
import sqlite3
from datetime import date, datetime, timedelta
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


def normalize_html_text(raw_html: str) -> str:
    text = re.sub(r"(?is)<script.*?</script>|<style.*?</style>", " ", raw_html)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    text = unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def parse_ro_date(text: str) -> str | None:
    match = re.search(r"(\d{1,2})\s+([A-Za-zăâîșțĂÂÎȘȚ]+)\.?\s*(\d{4})", text)
    if not match:
        return None
    day = int(match.group(1))
    month_token = match.group(2).lower().replace("ş", "ș").replace("ţ", "ț")
    month = MONTHS_RO.get(month_token) or MONTHS_RO.get(month_token[:3])
    if not month:
        return None
    return date(int(match.group(3)), month, day).isoformat()


def parse_bnr_rate_page(raw_html: str, source_url: str) -> dict:
    text = normalize_html_text(raw_html)
    date_match = re.search(
        r"Valabil[ăa]\s+din\s+(\d{1,2})\s+([A-Za-zăâîșțĂÂÎȘȚ]+)\.?\s*(\d{4})",
        text,
        flags=re.I,
    )
    effective_date = None
    if date_match:
        effective_date = parse_ro_date(" ".join(date_match.groups()))
    rate = None
    if date_match:
        nearby = text[date_match.end():date_match.end() + 250]
        rate_match = re.search(r"([0-9]+(?:[,.][0-9]+)?)\s*%", nearby)
        if rate_match:
            rate = float(rate_match.group(1).replace(",", "."))
    if rate is None:
        rate_match = re.search(
            r"rata dobânzii de politică monetară.{0,500}?(?:nivelul de\s+)?([0-9]+(?:[,.][0-9]+)?)\s*(?:la sută|%)",
            text,
            flags=re.I,
        )
        if rate_match:
            rate = float(rate_match.group(1).replace(",", "."))
    if rate is None or effective_date is None:
        raise ValueError("Pagina BNR a fost accesată, dar rata sau data de intrare în vigoare nu au putut fi identificate automat.")
    if not 0 <= rate <= 30:
        raise ValueError("Valoarea identificată în pagina BNR este în afara intervalului de control.")
    return {
        "effective_date": effective_date,
        "rate": round(rate, 4),
        "rate_name": "Rata dobânzii de politică monetară",
        "source_url": source_url,
        "source_document": "Pagina oficială BNR – rata dobânzii de politică monetară",
        "entry_mode": "BNR_AUTO",
        "notes": "Preluare automată din sursa oficială BNR.",
    }


def fetch_current_bnr_rate() -> dict:
    errors = []
    for url in BNR_RATE_URLS:
        try:
            req = Request(url, headers={"User-Agent": f"LoanCopilot/{APP_VERSION} Mozilla/5.0"})
            with urlopen(req, timeout=25) as response:
                raw = response.read().decode("utf-8", "ignore")
            return parse_bnr_rate_page(raw, url)
        except Exception as exc:
            errors.append(f"{url}: {exc}")
    raise RuntimeError("Actualizarea automată BNR nu a reușit. Verificați conexiunea sau introduceți rata manual. " + " | ".join(errors))


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


def recalculate_all(con: sqlite3.Connection, *, user_email: str = "system", sync_recognized: bool = False, cutoff: date | None = None) -> int:
    count = 0
    loans = con.execute("SELECT * FROM loans WHERE status<>'CLOSED' ORDER BY id").fetchall()
    for loan in loans:
        if not loan["interest_start_date"]:
            continue
        start = parse_date(loan["interest_start_date"])
        maturity = parse_date(loan["maturity_date"]) if loan["maturity_date"] else (cutoff or date.today())
        effective_cutoff = min(cutoff or date.today(), maturity)
        for period_start, period_end in iter_completed_quarters(start, effective_cutoff, include_partial_end=False):
            calc = calculate_period(con, loan, period_start, period_end)
            existing = con.execute(
                "SELECT id,status,recognized_amount FROM interest_accruals WHERE loan_id=? AND period_start=? AND period_end=?",
                (loan["id"], calc["period_start"], calc["period_end"]),
            ).fetchone()
            notes = f"Rată BNR variabilă · Actual/365 · {calc['rate_summary']}."
            if existing:
                recognized = calc["calculated_amount"] if sync_recognized and existing["status"] == "RECOGNIZED" else existing["recognized_amount"]
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
