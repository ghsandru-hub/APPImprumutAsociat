#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

APP_ROOT = Path(os.getenv("LOANCOPILOT_PRIVATE_ROOT", "/home/aiallro/loancopilot.privat")) / "app"
if APP_ROOT.is_dir():
    sys.path.insert(0, str(APP_ROOT))
else:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))

from loancopilot.anaf import lookup_company, parse_v9_response

SAMPLE = {
    "cod": 200,
    "message": "SUCCESS",
    "found": [
        {
            "date_generale": {
                "data": "2026-07-30",
                "cui": 4996264,
                "denumire": "QUASAR COMEX SRL",
                "adresa": "MUNICIPIUL BUCUREȘTI, SECTOR 1, STR. EXEMPLU, NR.1",
                "nrRegCom": "J40/1234/1993",
                "stare_inregistrare": "INREGISTRAT din data 01.01.1993",
                "data_inregistrare": "1993-01-01",
                "cod_CAEN": "4690",
                "iban": "",
                "statusRO_e_Factura": True,
                "organFiscalCompetent": "Administrația Sector 1 a Finanțelor Publice",
                "forma_de_proprietate": "PROPRIETATE PRIVATĂ",
                "forma_organizare": "PERSOANĂ JURIDICĂ",
                "forma_juridica": "SOCIETATE CU RĂSPUNDERE LIMITATĂ",
            },
            "inregistrare_scop_Tva": {"scpTVA": True, "perioade_TVA": []},
            "inregistrare_RTVAI": {"statusTvaIncasare": False},
            "stare_inactiv": {"statusInactivi": False},
            "inregistrare_SplitTVA": {"statusSplitTVA": False},
            "adresa_sediu_social": {
                "sdenumire_Strada": "Str. Exemplu",
                "snumar_Strada": "1",
                "sdenumire_Localitate": "Mun. București Sector 1",
                "sdenumire_Judet": "MUNICIPIUL BUCUREȘTI",
                "scod_Postal": "010101",
            },
        }
    ],
    "notFound": [],
}


def main() -> int:
    parser = argparse.ArgumentParser(description="Verifică parserul și, opțional, conectarea ANAF v9.")
    parser.add_argument("--live", action="store_true", help="Execută și o interogare reală la ANAF.")
    parser.add_argument("--cui", default="4996264", help="CUI pentru testul live.")
    args = parser.parse_args()

    parsed = parse_v9_response(SAMPLE, "4996264", "2026-07-30")
    assert parsed.name == "QUASAR COMEX SRL"
    assert parsed.reg_com == "J40/1234/1993"
    assert parsed.vat_registered is True
    assert parsed.inactive is False
    assert "Str. Exemplu" in parsed.address
    print("Parser ANAF v9: OK")
    print(json.dumps(parsed.as_dict(), ensure_ascii=False, indent=2))

    if args.live:
        result = lookup_company(args.cui)
        print("Interogare live ANAF v9: OK")
        print(json.dumps(result.as_dict(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
