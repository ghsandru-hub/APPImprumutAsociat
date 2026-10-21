# APPImprumutAsociat

Codul aplicației LoanCopilot 2.6.20, configurația Passenger și șabloanele standard se află în `01 Aplicatia`.

Versiunea 2.6.5 permite alegerea orientării Portrait / Landscape direct în scadențar, pentru previzualizare și tipărire / Save as PDF.

Versiunea 2.6.4 adaugă „Contracte de împrumut → Scadențar / Print”: selectați data de referință și toate contractele sau un singur contract, actualizați raportul și folosiți „Tipărește / Salvează PDF”. Raportul prezintă mișcările cronologic, soldurile după fiecare mișcare și rata anuală aplicabilă, inclusiv schimbările de rată BNR. Dobânda calculată, cea recunoscută și plățile rămân distincte. Sunt excluse operațiunile ulterioare datei alese; raportul nu recalculează dobânzi și nu reconstituie versiunile anterioare ale datelor modificate.

Versiunea 2.6.3 permite preluarea dobânzii calculate în cea recunoscută pentru liniile selectate, inclusiv actualizarea celor deja recunoscute. Recalcularea rămâne separată de recunoaștere. Din „Dobânzi trimestriale”, „Șabloane” sau „Documente” se pot genera documente Word completate cu datele companiei și contractului. Fișa standard de calcul folosește liniile trimestriale și subperioadele selectate, iar documentul este salvat în registru și în istoricul Word. Pentru șabloane proprii, marcajul `|~DobanziTrimestriale~|` se pune singur într-un paragraf din corpul documentului.

Instrucțiuni de deploy: [README_DEPLOY.md](01%20Aplicatia/README_DEPLOY.md).

Bazele SQLite, documentele completate ale companiilor, secretele și arhivele versiunilor anterioare nu sunt incluse în repository.

Kitul existent de instalare necesită separat baza seed MTM și documentele inițiale private. Acestea trebuie furnizate din sursa locală autorizată înainte de rularea `install.sh`; o clonă a repository-ului nu include aceste date.

## Sursa versiunii 2.6.1

Codul, fișierele publice `.htaccess` și `robots.txt`, scripturile private și șabloanele standard au fost preluate din arhiva locală a hostului `loancopilot.aiall.ro.zip` la 9 octombrie 2026. Versiunea și SHA-256 al `auth.css` corespund deploy-ului live. Bazele de date, secretele și documentele companiilor sunt excluse.

Application root-ul Passenger (`application_root/passenger_wsgi.py`, `requirements.txt` și `tmp/.keep`) a fost sincronizat și verificat față de arhiva hostului `loancopilot_app.zip`, furnizată la 9 octombrie 2026. Logul `stderr.log` și markerul runtime `tmp/restart.txt` nu sunt versionate. Documentația/kitul de instalare din versiunea 2.5.0 sunt păstrate din commitul inițial; kitul necesită în continuare datele private menționate mai sus.
