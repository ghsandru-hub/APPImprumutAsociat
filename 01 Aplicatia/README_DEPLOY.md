# LoanCopilot 2.5.0 — kit complet CloudLinux / Python 3.11

Versiunea 2.5.0 păstrează structura multi-companie, multiuser, 2FA opțional, bazele SQLite separate pe companie, documentele private și șabloanele standard/custom.

## Noutatea principală: PDF fără LibreOffice

Aplicația nu mai depinde de LibreOffice pentru fluxul uzual Word → PDF.

Pentru fiecare document Word există butonul `Tipărește / PDF`, care:

1. citește documentul DOCX direct din folderul privat;
2. generează o previzualizare paginată în browser, inclusiv antet, subsol, tabele și marcajele de pagină salvate de Word;
3. deschide dialogul de tipărire;
4. permite alegerea destinației `Save as PDF / Salvează ca PDF`.

Nu se instalează pachete Office pe server. Pentru redare absolut identică motorului Microsoft Word, utilizatorul poate descărca DOCX-ul și folosi local în Word `Fișier → Salvare ca → PDF`.

Dacă LibreOffice este instalat ulterior, conversia server-side rămâne disponibilă ca opțiune suplimentară și PDF-urile pot fi arhivate în tabelul existent `generated_pdf_versions`.

## Documente

În tabul `Documente`:

- documentul Word curent poate fi descărcat;
- un `EDITOR` sau `ADMIN` îl poate înlocui cu alt DOCX formatat;
- versiunea anterioară se păstrează în istoric;
- orice versiune Word poate fi descărcată sau deschisă în previzualizarea de tipărire;
- PDF-ul salvat local poate fi încărcat ca versiune PDF generată și arhivată;
- după semnare, același flux permite încărcarea separată a PDF-ului semnat;
- versiunile Word, PDF generate anterior și PDF semnate rămân auditate prin utilizator, dată, mărime și SHA-256.

## Șabloane

- șabloane standard: `/home/aiallro/loancopilot.privat/sabloane/standard`;
- șabloane proprii: `/home/aiallro/loancopilot.privat/sabloane/custom`;
- la crearea unei companii, șabloanele standard sunt copiate în dosarul companiei;
- șabloanele custom nu sunt suprascrise la actualizare.

## Structura de producție

```text
/home/aiallro/loancopilot_app
/home/aiallro/loancopilot.aiall.ro
/home/aiallro/loancopilot.privat
/home/aiallro/virtualenv/loancopilot_app/3.11
```

Bazele companiilor sunt în:

```text
/home/aiallro/loancopilot.privat/dbsqlite/companies
```

Documentele sunt în:

```text
/home/aiallro/loancopilot.privat/documente/<slug-companie>
```

## Instalare / actualizare

```bash
cd /home/aiallro
unzip LoanCopilot_multicompany_python_deploy_v11_browser_pdf.zip
cd LoanCopilot_deploy_v11_browser_pdf
chmod +x install.sh check_install.sh
./install.sh
```

Installerul înlocuiește integral codul aplicației, dar păstrează:

- baza centrală de autentificare;
- bazele SQLite ale companiilor;
- utilizatorii, parolele, rolurile și 2FA;
- documentele Word personalizate;
- istoricul Word;
- PDF-urile deja generate și PDF-urile semnate;
- șabloanele custom;
- backupurile.

## Configurare CloudLinux

```text
Python version:             3.11
Application root:           loancopilot_app
Application URL:            loancopilot.aiall.ro /
Application startup file:   passenger_wsgi.py
Application Entry point:    application
```

## Verificare

```bash
./check_install.sh
```

Testul documentelor validează toate DOCX-urile companiei MTM prin rendererul de previzualizare, fără LibreOffice:

```bash
PYTHONPATH=/home/aiallro/loancopilot.privat/app \
/home/aiallro/virtualenv/loancopilot_app/3.11/bin/python \
/home/aiallro/loancopilot.privat/scripts/check_document_workflow.py --write-test
```

## Utilizare Print → PDF

1. Deschide `Documente`.
2. Apasă `Tipărește / PDF`.
3. În previzualizare apasă `Tipărește / Salvează PDF`.
4. În dialogul browserului alege `Save as PDF / Salvează ca PDF`.
5. Salvează fișierul local.
6. Folosește `PDF generat` pentru arhivarea versiunii nesemnate în aplicație.
7. După semnare, folosește `PDF semnat` pentru încărcarea versiunii semnate.
