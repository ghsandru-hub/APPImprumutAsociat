# APPImprumutAsociat

Codul aplicației LoanCopilot 2.6.1, configurația Passenger și șabloanele standard se află în `01 Aplicatia`.

Instrucțiuni de deploy: [README_DEPLOY.md](01%20Aplicatia/README_DEPLOY.md).

Bazele SQLite, documentele completate ale companiilor, secretele și arhivele versiunilor anterioare nu sunt incluse în repository.

Kitul existent de instalare necesită separat baza seed MTM și documentele inițiale private. Acestea trebuie furnizate din sursa locală autorizată înainte de rularea `install.sh`; o clonă a repository-ului nu include aceste date.

## Sursa versiunii 2.6.1

Codul, fișierele publice `.htaccess` și `robots.txt`, scripturile private și șabloanele standard au fost preluate din arhiva locală a hostului `loancopilot.aiall.ro.zip` la 9 octombrie 2026. Versiunea și SHA-256 al `auth.css` corespund deploy-ului live. Bazele de date, secretele și documentele companiilor sunt excluse.

Arhiva nu include application root-ul Passenger. `application_root/passenger_wsgi.py` și documentația/kitul de instalare din versiunea 2.5.0 sunt păstrate din commitul anterior; nu au fost verificate față de host. Kitul de instalare necesită în continuare datele private menționate mai sus.
