## 2.6.7

- Câmpurile de input și selectoarele folosesc stilul aplicației inclusiv în tabele și filtre, cu suport light/dark pentru controalele native.

- Iconurile acțiunilor sunt centrate în butoane pătrate, fără spațiul etichetei ascunse.

## 2.6.6

- Acțiunile din paginile principale, tabele și scadențar folosesc iconuri, cu explicații la hover și etichete accesibile. Etichetele câmpurilor, navigarea și confirmările formularelor rămân explicite.
- Scadențarul evită sumarizările repetate și unește calculul și recunoașterea din aceeași zi pe o singură linie, cu sumele în coloane distincte. Fișa Word nu repetă datele companiei deja prezente în antet.

## 2.6.5

- Selector Portrait / Landscape în scadențar; orientarea se aplică imediat previzualizării și tipăririi / Save as PDF și se păstrează la actualizarea raportului.

## 2.6.4

- Scadențar de tipărit / Save as PDF, cu data de referință și contract selectabile, disponibil din Contracte de împrumut.
- Mișcări cronologice cu soldul principalului și al dobânzii recunoscute după fiecare mișcare, rata anuală aplicabilă și schimbările de rată BNR; dobânzile calculate, recunoscute și plătite sunt distincte.
- Raportul este doar pentru citire și nu recalculează ori recunoaște automat dobânzi.

## 2.6.3

- Dobânzi trimestriale: selecție de linii și preluare calculată → recunoscută, inclusiv actualizarea valorilor deja recunoscute, cu protecția sumelor plătite și audit.
- Generare Word din șabloanele existente, cu preluarea datelor companiei și contractului și completarea câmpurilor lipsă.
- Fișa de calcul folosește trimestrele și subperioadele selectate, fără date fixe pentru T1–T2 2026; documentul este salvat în registru și în istoricul Word.
- Șapte verificări de integrare pe baze temporare, fără acces la datele de producție.

## 2.6.2

- Administrare acces: schimbarea parolei proprii și resetarea parolelor de către superadministrator, cu confirmare, audit și revocarea sesiunilor.

# LoanCopilot 2.5.0

- generare de previzualizare paginată direct din DOCX, fără LibreOffice și fără servicii externe;
- buton `Tipărește / PDF` disponibil pentru documentul Word curent;
- Print → Save as PDF din browser;
- încărcarea și versionarea PDF-ului salvat din browser în registrul `generated_pdf_versions`;
- previzualizare și tipărire pentru fiecare versiune Word din istoric;
- păstrarea antetului, subsolului, tabelelor, formatărilor uzuale și a marcajelor de pagină Word;
- fallback automat: endpointul vechi de generare PDF deschide previzualizarea browserului când LibreOffice lipsește;
- conversia LibreOffice rămâne opțională când executabilul există;
- verificarea instalării și testul fluxului documentelor nu mai depind de LibreOffice;
- actualizare completă de cod, cu păstrarea bazelor, utilizatorilor, 2FA, documentelor, istoricului și șabloanelor custom;
- versiune aplicație actualizată la 2.5.0.
