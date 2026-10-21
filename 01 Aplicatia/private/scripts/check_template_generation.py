"""Integration checks using isolated temporary databases, never production data."""
from __future__ import annotations

import hashlib
import gc
import io
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch
import zipfile
from xml.dom import minidom


class GenerationChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="loancopilot_generation_", dir=os.getenv("LOANCOPILOT_TEST_TMP"))
        cls.root = Path(cls.temp.name)
        os.environ["LOANCOPILOT_PRIVATE_ROOT"] = str(cls.root)
        os.environ["LOANCOPILOT_COOKIE_SECURE"] = "0"
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
        # The production-only ANAF file lock is unrelated to these checks.
        # Fail explicitly if a tested flow unexpectedly calls it on Windows.
        if sys.platform == "win32":
            import types
            cls.fcntl_patch = patch.dict(sys.modules, {"fcntl": types.SimpleNamespace(
                LOCK_EX=2, LOCK_UN=8, flock=Mock(side_effect=AssertionError("ANAF locking is outside this test")))})
            cls.fcntl_patch.start()
        from loancopilot import app, db, docx_templates, config
        from loancopilot.security import token_hash
        cls.db, cls.docx, cls.config = db, docx_templates, config
        cls.app = app.create_app()
        cls.app.testing = True
        source = Path(__file__).resolve().parents[1] / "sabloane" / "standard"
        shutil.copytree(source, cls.root / "sabloane" / "standard", dirs_exist_ok=True)
        with db.auth_connect() as con:
            company_id = db.register_company(con, slug="qa", name="Compania QA", cui="123456")
            con.execute("INSERT INTO users(id,email,display_name,password_hash,is_superadmin) VALUES(1,'qa@example.invalid','QA','unused',1)")
            con.execute("INSERT INTO users(id,email,display_name,password_hash) VALUES(2,'viewer@example.invalid','Viewer','unused')")
            con.execute("INSERT INTO user_companies(user_id,company_id,role) VALUES(2,?,'VIEWER')", (company_id,))
            for user_id, token in ((1, "qa-session"), (2, "viewer-session")):
                con.execute("""INSERT INTO auth_sessions(token_hash,user_id,current_company_id,csrf_token,created_at,expires_at,last_seen_at)
                               VALUES(?,?,?,'qa-csrf','2026-01-01T00:00:00+00:00','2099-01-01T00:00:00+00:00','2026-01-01T00:00:00+00:00')""",
                            (token_hash(token), user_id, company_id))
            con.commit()
            cls.company = con.execute("SELECT * FROM companies WHERE id=?", (company_id,)).fetchone()
        db.ensure_tenant_schema(db.tenant_db_path(cls.company))

    @classmethod
    def tearDownClass(cls):
        gc.collect()
        cls.temp.cleanup()
        if hasattr(cls, "fcntl_patch"):
            cls.fcntl_patch.stop()

    def setUp(self):
        self.client = self.app.test_client()
        self.client.set_cookie("loancopilot_session", "qa-session")
        with self.db.tenant_connect(self.company) as con:
            con.execute("DELETE FROM documents")
            con.execute("DELETE FROM transactions")
            con.execute("DELETE FROM interest_accruals")
            con.execute("DELETE FROM bnr_reference_rates")
            con.execute("INSERT INTO bnr_reference_rates(effective_date,rate) VALUES('2024-08-08',6.5)")
            con.execute("DELETE FROM loans")
            con.execute("DELETE FROM associates")
            con.execute("DELETE FROM company")
            con.execute("INSERT INTO company(id,name,cui,administrator) VALUES(1,'Compania QA','123456','Administrator QA')")
            for i in (1, 2):
                con.execute("INSERT INTO associates(id,name) VALUES(?,?)", (i, f"Creditor {i}"))
                con.execute("""INSERT INTO loans(id,contract_no,contract_date,original_contract_date,interest_start_date,associate_id,maturity_date)
                               VALUES(?,?,'2025-01-01','2025-01-01','2027-01-01',?,'2028-12-31')""", (i, f"QA-{i}", i))
            for i, loan, start, end, calculated, recognized in (
                (1, 1, "2027-01-01", "2027-03-31", 123.45, 100),
                (2, 2, "2027-01-01", "2027-03-31", 234.56, 0),
                (3, 1, "2027-04-01", "2027-06-30", 345.67, 300),
            ):
                con.execute("""INSERT INTO interest_accruals(id,loan_id,period_start,period_end,opening_balance,closing_balance,days,calculated_amount,recognized_amount,status,recognized_date)
                               VALUES(?,?,?,?,10000,9000,90,?,?,?,?)""",
                            (i, loan, start, end, calculated, recognized, "RECOGNIZED" if recognized else "CALCULATED", end if recognized else None))
                con.execute("""INSERT INTO interest_segments(accrual_id,segment_start,segment_end,days,rate,balance_days,calculated_amount)
                               VALUES(?,?,?,90,6.5,900000,?)""", (i, start, end, calculated))
            con.commit()

    def post(self, url, data):
        return self.client.post(url, json=data, headers={"X-CSRF-Token": "qa-csrf"})

    def request_data(self, ids=None):
        return {"template_path": "standard/" + self.docx.INTEREST_TEMPLATE, "doc_no": "QA-2027", "doc_date": "2027-07-01", "interest_ids": [1, 2] if ids is None else ids}

    def test_recognition_updates_existing_and_new_without_touching_other_rows(self):
        response = self.post("/api/interest/recognize-selected", {"interest_ids": [1, 2, 2]})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["periods"], 2)
        with self.db.tenant_connect(self.company) as con:
            rows = con.execute("SELECT recognized_amount,status,recognized_date FROM interest_accruals ORDER BY id").fetchall()
        self.assertEqual(tuple(rows[0]), (123.45, "RECOGNIZED", "2027-03-31"))
        self.assertEqual(tuple(rows[1]), (234.56, "RECOGNIZED", "2027-03-31"))
        self.assertEqual(rows[2][0], 300)

    def test_paid_guard_is_atomic_and_single_endpoint_also_protects_payments(self):
        with self.db.tenant_connect(self.company) as con:
            con.execute("INSERT INTO transactions(loan_id,accrual_id,txn_date,txn_type,amount) VALUES(2,2,'2027-04-01','INTEREST_PAYMENT',240)")
            con.commit()
        self.assertEqual(self.post("/api/interest/recognize-selected", {"interest_ids": [1, 2]}).status_code, 400)
        self.assertEqual(self.post("/api/interest/recognize", {"id": 2, "recognized_amount": 230}).status_code, 400)
        with self.db.tenant_connect(self.company) as con:
            self.assertEqual(con.execute("SELECT recognized_amount FROM interest_accruals WHERE id=1").fetchone()[0], 100)

    def test_generate_selected_rows_history_download_print_and_unchanged_template(self):
        source = self.root / "sabloane" / self.request_data()["template_path"]
        before = hashlib.sha256(source.read_bytes()).hexdigest()
        context = self.post("/api/documents/template-context", self.request_data())
        self.assertEqual(context.status_code, 200)
        self.assertEqual(context.json["calculated_total"], 358.01)
        response = self.post("/api/documents/generate", self.request_data())
        self.assertEqual(response.status_code, 200, response.json)
        with self.client.get(response.json["download_url"]) as download:
            content = download.data
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            doc = minidom.parseString(archive.read("word/document.xml"))
            body = self.docx.text(doc)
            self.assertIn("358,01", body)
            self.assertIn("Creditor 1", body)
            self.assertIn("Creditor 2", body)
            self.assertIn("2027", body)
            self.assertNotIn("2026", body)
            self.assertNotIn("345,67", body)
            self.assertNotIn("|~", body)
            self.assertIn("word/styles.xml", archive.namelist())
        self.assertEqual(before, hashlib.sha256(source.read_bytes()).hexdigest())
        self.assertEqual(self.client.get(response.json["print_url"]).status_code, 200)
        history = self.client.get(f"/api/documents/{response.json['id']}/history").json
        self.assertEqual(history["word_items"][0]["version_no"], 1)
        self.assertEqual(history["word_items"][0]["sha256"], hashlib.sha256(content).hexdigest())
        self.assertEqual(len(self.client.get("/api/documents").json["items"]), 1)

    def test_interest_company_not_repeated_in_new_or_legacy_print(self):
        response = self.post("/api/documents/generate", self.request_data())
        self.assertEqual(response.status_code, 200, response.json)
        with self.client.get(response.json["download_url"]) as download:
            original = download.data
        with zipfile.ZipFile(io.BytesIO(original)) as archive:
            doc = minidom.parseString(archive.read("word/document.xml"))
            self.assertNotIn("Compania QA", self.docx.text(doc))
            headers = "".join(self.docx.text(minidom.parseString(archive.read(n))) for n in archive.namelist() if n.startswith("word/header") and n.endswith(".xml"))
            self.assertIn("Compania QA", headers)
            body = doc.getElementsByTagNameNS(self.docx.W, "body")[0]
            first = next(n for n in body.childNodes if n.nodeType == n.ELEMENT_NODE)
            body.insertBefore(self.docx.paragraph(doc, "Compania QA · CUI 123456"), first.nextSibling)
            legacy = self.root / "legacy_interest.docx"
            with zipfile.ZipFile(legacy, "w") as result:
                for info in archive.infolist():
                    result.writestr(info, doc.toxml(encoding="utf-8") if info.filename == "word/document.xml" else archive.read(info.filename))
        from loancopilot.docx_print import DocxPrintRenderer
        with DocxPrintRenderer(legacy) as renderer:
            self.assertNotIn("Compania QA", "".join("".join(page) for page in renderer._body_pages()))
        with zipfile.ZipFile(legacy) as archive:
            self.assertIn("Compania QA", self.docx.text(minidom.parseString(archive.read("word/document.xml"))))

    def test_validation_no_selection_missing_row_mismatched_contract_and_traversal(self):
        for data in (self.request_data([]), self.request_data([999]), {**self.request_data(), "loan_id": 1},
                     {**self.request_data(), "template_path": "../../outside.docx"}):
            self.assertIn(self.post("/api/documents/generate", data).status_code, (400, 404))
        with self.db.tenant_connect(self.company) as con:
            self.assertEqual(con.execute("SELECT COUNT(*) FROM documents").fetchone()[0], 0)
        self.assertEqual(self.post("/api/interest/recognize-selected", {"interest_ids": [True]}).status_code, 400)

    def test_permissions_csrf_health_and_tabs(self):
        self.assertEqual(self.client.get("/health").json["version"], self.config.APP_VERSION)
        page = self.client.get("/")
        self.assertEqual(page.status_code, 200)
        for name in ("page-interest", "page-documents", "page-templates", "page-bnr", "page-settings", "page-transactions"):
            self.assertIn(name.encode(), page.data)
        self.assertEqual(self.client.post("/api/documents/generate", json=self.request_data()).status_code, 403)
        self.client.set_cookie("loancopilot_session", "viewer-session")
        self.assertEqual(self.post("/api/documents/generate", self.request_data()).status_code, 403)
        self.assertEqual(self.post("/api/interest/recognize-selected", {"interest_ids": [1]}).status_code, 403)
        self.client.delete_cookie("loancopilot_session")
        self.assertEqual(self.post("/api/documents/generate", self.request_data()).status_code, 401)

    def test_split_tokens_keep_surrounding_text_and_run_styles(self):
        doc = minidom.parseString(f'<w:p xmlns:w="{self.docx.W}"><w:r><w:rPr><w:b/></w:rPr><w:t>Salut |~Comp</w:t></w:r><w:r><w:t>anieNume~| și |~Alt~|.</w:t></w:r></w:p>')
        self.docx.replace_paragraph(doc.documentElement, {"CompanieNume": "A & B", "Alt": "text"})
        self.assertEqual(self.docx.text(doc), "Salut A & B și text.")
        self.assertEqual(len(doc.getElementsByTagNameNS(self.docx.W, "b")), 1)

    def test_other_template_fields_are_prefilled_and_missing_values_are_required(self):
        data = {**self.request_data([1]), "loan_id": 1,
                "template_path": "standard/02_Contract_cadru_imprumut_asociat_fara_dobanda.docx"}
        context = self.post("/api/documents/template-context", data)
        self.assertEqual(context.status_code, 200)
        values = {f["name"]: f["value"] for f in context.json["fields"]}
        self.assertEqual(values["ContractNumar"], "QA-1")
        self.assertEqual(values["AsociatNume"], "Creditor 1")
        self.assertEqual(self.post("/api/documents/generate", data).status_code, 400)
        values.update({k: v or "QA completat" for k, v in values.items()})
        response = self.post("/api/documents/generate", {**data, "fields": values})
        self.assertEqual(response.status_code, 200, response.json)
        with self.client.get(response.json["download_url"]) as download:
            with zipfile.ZipFile(io.BytesIO(download.data)) as archive:
                doc = minidom.parseString(archive.read("word/document.xml"))
                self.assertNotIn("|~", self.docx.text(doc))
                self.assertIn("Compania QA", self.docx.text(doc))

    def test_schedule_uses_cutoff_for_principal_recognition_and_gross_payments(self):
        from datetime import date
        from loancopilot.business import schedule_at
        with self.db.tenant_connect(self.company) as con:
            con.executemany("INSERT INTO transactions(loan_id,txn_date,txn_type,amount,tax_withheld) VALUES(1,?,?,?,?)", [
                ("2026-01-01", "OPENING_BALANCE", 10000, 0),
                ("2027-03-31", "REPAYMENT", 1000, 0),
                ("2027-04-01", "REPAYMENT", 2000, 0),
                ("2027-03-31", "INTEREST_PAYMENT", 30, 3),
                ("2027-04-01", "INTEREST_PAYMENT", 20, 2),
            ])
            con.execute("UPDATE loans SET status='CLOSED',maturity_date='2027-03-01' WHERE id=1")
            con.commit()
            before = con.total_changes
            report = schedule_at(con, date(2027, 3, 31), 1)
            self.assertEqual(con.total_changes, before)
            self.assertEqual(report["totals"]["funded"], 10000)
            self.assertEqual(report["totals"]["principal_balance"], 9000)
            self.assertEqual(report["totals"]["interest_recognized"], 100)
            self.assertEqual(report["totals"]["interest_paid"], 30)
            self.assertEqual(report["totals"]["interest_balance"], 70)
            self.assertEqual(report["totals"]["interest_calculated"], 123.45)
            events = report["loans"][0]["events"]
            self.assertEqual(events[0]["principal_balance"], 10000)
            self.assertEqual(events[0]["rate"], 0)
            self.assertEqual(events[-1]["principal_balance"], 9000)
            self.assertEqual(events[-1]["interest_balance"], 70)
            self.assertEqual(events[-1]["rate"], 6.5)
            self.assertEqual(events[-2]["label"], "Dobândă trimestrială")
            self.assertEqual(events[-2]["calculated"], 123.45)
            self.assertEqual(events[-2]["recognized"], 100)
            self.assertEqual(events[-2]["interest_balance"], 100)
            self.assertTrue(all(e["date"] <= "2027-03-31" for e in events))
            self.assertEqual(schedule_at(con, date(2024, 1, 1))["loans"], [])
        response = self.client.get("/reports/schedule?as_of=2027-03-31&loan_id=1")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["Cache-Control"], "private, no-store")
        self.assertIn("Scadențar la 31.03.2027".encode(), response.data)
        self.assertIn(b"9.000,00", response.data)
        self.assertIn("Sold principal".encode(), response.data)
        self.assertIn(b"window.print()", response.data)

    def test_schedule_credit_validation_and_read_only_access(self):
        from datetime import date
        from loancopilot.business import schedule_at
        with self.db.tenant_connect(self.company) as con:
            con.execute("INSERT INTO transactions(loan_id,txn_date,txn_type,amount) VALUES(1,'2027-03-31','INTEREST_PAYMENT',150)")
            con.commit()
            report = schedule_at(con, date(2027, 3, 31), 1)
        self.assertEqual(report["totals"]["interest_balance"], -50)
        self.assertEqual(report["loans"][0]["events"][-1]["interest_balance"], -50)
        self.assertEqual(self.client.get("/reports/schedule?as_of=2027-02-30").status_code, 400)
        self.assertEqual(self.client.get("/reports/schedule?loan_id=999").status_code, 404)
        self.assertEqual(self.client.get("/reports/schedule?loan_id=-1").status_code, 400)
        self.client.set_cookie("loancopilot_session", "viewer-session")
        self.assertEqual(self.client.get("/reports/schedule").status_code, 200)
        self.client.delete_cookie("loancopilot_session")
        response = self.client.get("/reports/schedule")
        self.assertEqual(response.status_code, 302)
        self.assertIn("/login", response.location)

    def test_schedule_tracks_rate_changes_and_separates_contract_balances(self):
        from datetime import date
        from loancopilot.business import schedule_at
        with self.db.tenant_connect(self.company) as con:
            con.execute("INSERT INTO bnr_reference_rates(effective_date,rate) VALUES('2027-02-01',7)")
            con.execute("INSERT INTO transactions(loan_id,txn_date,txn_type,amount) VALUES(1,'2027-01-01','ADVANCE',1000)")
            con.execute("INSERT INTO transactions(loan_id,txn_date,txn_type,amount) VALUES(2,'2027-01-02','ADVANCE',2000)")
            con.commit()
            report = schedule_at(con, date(2027, 2, 10))
            self.assertEqual(report["totals"]["principal_balance"], 3000)
            self.assertEqual(report["loans"][0]["events"][-1]["principal_balance"], 1000)
            self.assertEqual(report["loans"][1]["events"][-1]["principal_balance"], 2000)
            self.assertEqual(report["loans"][0]["events"][-1]["rate"], 7)
            self.assertEqual(report["loans"][0]["events"][-1]["label"], "Modificare rată BNR")
            self.assertEqual(report["loans"][0]["events"][-2]["rate"], 6.5)
            self.assertEqual(report["totals"]["interest_calculated"], 0)
            con.execute("UPDATE loans SET interest_rate_mode='FIXED',interest_rate=5 WHERE id=1")
            con.commit()
            fixed = schedule_at(con, date(2027, 2, 10), 1)
            self.assertEqual(fixed["loans"][0]["events"][-1]["rate"], 5)
            self.assertNotIn("Modificare rată BNR", [e["label"] for e in fixed["loans"][0]["events"]])


if __name__ == "__main__":
    unittest.main()
