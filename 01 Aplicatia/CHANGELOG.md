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
