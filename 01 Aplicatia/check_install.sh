#!/usr/bin/env bash
set -u

HOME_ROOT="/home/aiallro"
APP_ROOT="$HOME_ROOT/loancopilot_app"
PUBLIC_ROOT="$HOME_ROOT/loancopilot.aiall.ro"
PRIVATE_ROOT="$HOME_ROOT/loancopilot.privat"
VENV="$HOME_ROOT/virtualenv/loancopilot_app/3.11"

echo "=== CloudLinux application ==="
cloudlinux-selector get --json --interpreter python --user aiallro 2>&1 | grep -o '"loancopilot_app"[^}]*' || true

echo
echo "=== Paths ==="
ls -ld "$APP_ROOT" "$PUBLIC_ROOT" "$PRIVATE_ROOT" "$PRIVATE_ROOT/app" "$PRIVATE_ROOT/dbsqlite" "$PRIVATE_ROOT/documente" "$PRIVATE_ROOT/sabloane" "$PRIVATE_ROOT/sabloane/standard" 2>&1

echo
echo "=== Files ==="
ls -l "$APP_ROOT/passenger_wsgi.py" "$APP_ROOT/requirements.txt" "$PUBLIC_ROOT/.htaccess" \
  "$PRIVATE_ROOT/dbsqlite/seed/mtm_18235662.sqlite" 2>&1

echo
echo "=== Python ==="
if [[ -x "$VENV/bin/python" ]]; then
  "$VENV/bin/python" --version
  "$VENV/bin/python" -m pip --version
else
  echo "Lipsește virtualenv: $VENV"
fi

echo
echo "=== WSGI import ==="
if [[ -x "$VENV/bin/python" ]]; then
  cd "$APP_ROOT" || exit 1
  LOANCOPILOT_HOME="$HOME_ROOT" \
  LOANCOPILOT_PUBLIC_ROOT="$PUBLIC_ROOT" \
  LOANCOPILOT_PRIVATE_ROOT="$PRIVATE_ROOT" \
  LOANCOPILOT_DB_ROOT="$PRIVATE_ROOT/dbsqlite" \
  LOANCOPILOT_DOCUMENT_ROOT="$PRIVATE_ROOT/documente" \
  LOANCOPILOT_TEMPLATE_ROOT="$PRIVATE_ROOT/sabloane" \
  "$VENV/bin/python" - <<'PY'
from passenger_wsgi import application
print("WSGI OK:", application.name)
print("Număr rute:", len(application.url_map._rules))
PY
fi

echo
echo "=== Word → Print / Save as PDF ==="
echo "Conversia principală rulează în browser și nu necesită LibreOffice."
if command -v libreoffice >/dev/null 2>&1; then
  echo "Convertor server opțional detectat: $(libreoffice --version 2>/dev/null | head -1)"
elif command -v soffice >/dev/null 2>&1; then
  echo "Convertor server opțional detectat: $(soffice --version 2>/dev/null | head -1)"
else
  echo "LibreOffice lipsește: se folosește previzualizarea Word și Print → Save as PDF."
fi

echo
echo "=== Documente și șabloane ==="
find "$PRIVATE_ROOT/documente" -maxdepth 5 -type f \( -name '*.docx' -o -name '*.pdf' \) -printf '%P\n' 2>/dev/null | head -80
find "$PRIVATE_ROOT/sabloane" -maxdepth 3 -type f -printf '%P\n' 2>/dev/null | head -40

echo
echo "=== Flux documente ==="
if [[ -x "$VENV/bin/python" && -f "$PRIVATE_ROOT/scripts/check_document_workflow.py" && -f "$PRIVATE_ROOT/dbsqlite/loancopilot_auth.sqlite" ]]; then
  PYTHONPATH="$PRIVATE_ROOT/app" \
  LOANCOPILOT_HOME="$HOME_ROOT" \
  LOANCOPILOT_PUBLIC_ROOT="$PUBLIC_ROOT" \
  LOANCOPILOT_PRIVATE_ROOT="$PRIVATE_ROOT" \
  LOANCOPILOT_DB_ROOT="$PRIVATE_ROOT/dbsqlite" \
  LOANCOPILOT_DOCUMENT_ROOT="$PRIVATE_ROOT/documente" \
  LOANCOPILOT_TEMPLATE_ROOT="$PRIVATE_ROOT/sabloane" \
  "$VENV/bin/python" "$PRIVATE_ROOT/scripts/check_document_workflow.py" || true
else
  echo "Verificarea documentelor nu poate fi rulată încă."
fi

echo
echo "=== HTTP ==="
curl -k -sS -o /dev/null -w 'HTTP %{http_code}\n' https://loancopilot.aiall.ro/ || true

echo
echo "=== Recent logs ==="
tail -n 40 "$PRIVATE_ROOT/logs/passenger_startup_error.log" 2>/dev/null || echo "Fără passenger_startup_error.log"
tail -n 40 "$PUBLIC_ROOT/stderr.log" 2>/dev/null || echo "Fără stderr.log public"
