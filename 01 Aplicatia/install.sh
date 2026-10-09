#!/usr/bin/env bash
set -euo pipefail

HOME_ROOT="/home/aiallro"
APP_ROOT="$HOME_ROOT/loancopilot_app"
PUBLIC_ROOT="$HOME_ROOT/loancopilot.aiall.ro"
PRIVATE_ROOT="$HOME_ROOT/loancopilot.privat"
DB_ROOT="$PRIVATE_ROOT/dbsqlite"
DOCUMENT_ROOT="$PRIVATE_ROOT/documente"
TEMPLATE_ROOT="$PRIVATE_ROOT/sabloane"
VENV_ROOT="$HOME_ROOT/virtualenv/loancopilot_app/3.11"
PACKAGE_ROOT="$(cd "$(dirname "$0")" && pwd)"
DOMAIN="loancopilot.aiall.ro"
APP_SLUG="loancopilot_app"
PYTHON_VERSION="3.11"

fail() {
  echo "Eroare: $*" >&2
  exit 1
}

require_command() {
  command -v "$1" >/dev/null 2>&1 || fail "Comanda '$1' nu este disponibilă."
}

copy_replace() {
  local source="$1"
  local destination="$2"
  [[ -d "$source" ]] || fail "Director sursă lipsă: $source"
  rm -rf "$destination"
  mkdir -p "$destination"
  cp -a "$source/." "$destination/"
}

copy_missing() {
  local source="$1"
  local destination="$2"
  [[ -d "$source" ]] || fail "Director sursă lipsă: $source"
  mkdir -p "$destination"
  cp -a -n "$source/." "$destination/"
}

update_managed_documents() {
  local source="$1"
  local destination="$2"
  local manifest="$source/.managed_v9_sha256"
  local backup_root="$PRIVATE_ROOT/backup/pre_2.5.0_documente_$(date +%Y%m%d_%H%M%S)"
  local copied=0 updated=0 preserved=0
  declare -A previous_hashes=()

  [[ -d "$source" ]] || fail "Director sursă lipsă: $source"
  [[ -f "$manifest" ]] || fail "Manifest documente gestionate lipsă: $manifest"
  mkdir -p "$destination"

  while read -r previous_hash relative_path; do
    [[ -n "${previous_hash:-}" && -n "${relative_path:-}" ]] || continue
    previous_hashes["$relative_path"]="$previous_hash"
  done < "$manifest"

  while IFS= read -r -d '' source_file; do
    local relative_path="${source_file#"$source/"}"
    local target_file="$destination/$relative_path"
    local target_dir
    target_dir="$(dirname "$target_file")"
    mkdir -p "$target_dir"

    if [[ ! -e "$target_file" ]]; then
      cp -a "$source_file" "$target_file"
      copied=$((copied + 1))
      continue
    fi

    local expected_previous_hash="${previous_hashes[$relative_path]:-}"
    if [[ -n "$expected_previous_hash" ]]; then
      local current_hash ignored
      read -r current_hash ignored < <(sha256sum "$target_file")
      if [[ "$current_hash" == "$expected_previous_hash" ]]; then
        mkdir -p "$backup_root/$(dirname "$relative_path")"
        cp -a "$target_file" "$backup_root/$relative_path"
        cp -a "$source_file" "$target_file"
        updated=$((updated + 1))
        continue
      fi
    fi

    echo "Document personalizat păstrat: $relative_path"
    preserved=$((preserved + 1))
  done < <(find "$source" -type f ! -name '.managed_v9_sha256' -print0)

  if [[ "$updated" -eq 0 ]]; then
    rmdir "$backup_root" 2>/dev/null || true
  fi
  echo "Documente companie: noi=$copied, actualizate=$updated, personalizate păstrate=$preserved."
}

selector_has_app() {
  local output
  output="$(cloudlinux-selector get --json --interpreter python --user aiallro 2>/dev/null || true)"
  printf '%s' "$output" | grep -q '"loancopilot_app"'
}

register_or_update_selector_app() {
  local env_vars
  env_vars='{"LOANCOPILOT_HOME":"/home/aiallro","LOANCOPILOT_PUBLIC_ROOT":"/home/aiallro/loancopilot.aiall.ro","LOANCOPILOT_PRIVATE_ROOT":"/home/aiallro/loancopilot.privat","LOANCOPILOT_DB_ROOT":"/home/aiallro/loancopilot.privat/dbsqlite","LOANCOPILOT_DOCUMENT_ROOT":"/home/aiallro/loancopilot.privat/documente","LOANCOPILOT_TEMPLATE_ROOT":"/home/aiallro/loancopilot.privat/sabloane","LOANCOPILOT_COOKIE_SECURE":"1","LOANCOPILOT_TRUST_PROXY":"1","PYTHONUNBUFFERED":"1"}'

  if selector_has_app; then
    echo "Aplicația CloudLinux '$APP_SLUG' există. Se actualizează configurația..."
    cloudlinux-selector set --json \
      --interpreter python \
      --user aiallro \
      --app-root "$APP_SLUG" \
      --new-version "$PYTHON_VERSION" \
      --startup-file passenger_wsgi.py \
      --entry-point application \
      --env-vars "$env_vars" >/dev/null
    return 0
  fi

  echo "Aplicația CloudLinux '$APP_SLUG' nu există. Se încearcă înregistrarea automată..."
  if cloudlinux-selector create --json \
      --interpreter python \
      --domain "$DOMAIN" \
      --app-root "$APP_SLUG" \
      --app-uri "" \
      --version "$PYTHON_VERSION" \
      --startup-file passenger_wsgi.py \
      --entry-point application \
      --env-vars "$env_vars" >/dev/null; then
    echo "Aplicația CloudLinux a fost creată."
    return 0
  fi

  echo >&2
  echo "Înregistrarea automată nu a reușit. Fișierele au fost pregătite, dar aplicația trebuie creată din cPanel:" >&2
  echo "  Python version:           3.11" >&2
  echo "  Application root:         loancopilot_app" >&2
  echo "  Application URL:          loancopilot.aiall.ro /" >&2
  echo "  Application startup file: passenger_wsgi.py" >&2
  echo "  Application Entry point:  application" >&2
  echo >&2
  echo "După creare, rulează din nou ./install.sh." >&2
  exit 3
}

if [[ "$(id -un)" != "aiallro" ]]; then
  fail "Scriptul trebuie rulat ca utilizatorul cPanel 'aiallro'."
fi

require_command cp
require_command find
require_command grep
require_command cloudlinux-selector
require_command sha256sum

[[ -f "$PACKAGE_ROOT/application_root/passenger_wsgi.py" ]] || fail "Lipsește application_root/passenger_wsgi.py."
[[ -f "$PACKAGE_ROOT/private/dbsqlite/seed/mtm_18235662.sqlite" ]] || fail "Lipsește baza seed MTM."

mkdir -p \
  "$APP_ROOT/tmp" \
  "$PUBLIC_ROOT" \
  "$PRIVATE_ROOT/app" \
  "$PRIVATE_ROOT/dbsqlite/companies" \
  "$PRIVATE_ROOT/dbsqlite/seed" \
  "$PRIVATE_ROOT/documente" \
  "$PRIVATE_ROOT/sabloane/standard" \
  "$PRIVATE_ROOT/sabloane/custom" \
  "$PRIVATE_ROOT/backup" \
  "$PRIVATE_ROOT/logs" \
  "$PRIVATE_ROOT/secrets" \
  "$PRIVATE_ROOT/scripts" \
  "$PRIVATE_ROOT/tmp"

# Actualizare clean a codului. Datele persistente nu sunt șterse.
copy_replace "$PACKAGE_ROOT/private/app" "$PRIVATE_ROOT/app"
copy_replace "$PACKAGE_ROOT/private/scripts" "$PRIVATE_ROOT/scripts"
cp -a "$PACKAGE_ROOT/private/dbsqlite/seed/mtm_18235662.sqlite" \
  "$PRIVATE_ROOT/dbsqlite/seed/mtm_18235662.sqlite"
update_managed_documents "$PACKAGE_ROOT/private/documente" "$PRIVATE_ROOT/documente"
copy_replace "$PACKAGE_ROOT/private/sabloane/standard" "$PRIVATE_ROOT/sabloane/standard"
copy_missing "$PACKAGE_ROOT/private/sabloane/custom" "$PRIVATE_ROOT/sabloane/custom"

# Application root Passenger separat de document root-ul public.
cp -a "$PACKAGE_ROOT/application_root/passenger_wsgi.py" "$APP_ROOT/passenger_wsgi.py"
cp -a "$PACKAGE_ROOT/application_root/requirements.txt" "$APP_ROOT/requirements.txt"
mkdir -p "$APP_ROOT/tmp"

# Document root public: numai reguli Passenger și fișiere publice minime.
cp -a "$PACKAGE_ROOT/public/.htaccess" "$PUBLIC_ROOT/.htaccess"
cp -a "$PACKAGE_ROOT/public/robots.txt" "$PUBLIC_ROOT/robots.txt"
rm -f "$PUBLIC_ROOT/passenger_wsgi.py"

# Curățare artefacte Python generate local.
find "$PRIVATE_ROOT/app" -type d -name '__pycache__' -prune -exec rm -rf {} +
find "$PRIVATE_ROOT/app" -type f \( -name '*.pyc' -o -name '*.pyo' \) -delete

# Permisiuni.
chmod 711 "$HOME_ROOT"
chmod 755 "$APP_ROOT" "$APP_ROOT/tmp" "$PUBLIC_ROOT"
chmod 644 "$APP_ROOT/passenger_wsgi.py" "$APP_ROOT/requirements.txt" "$PUBLIC_ROOT/.htaccess" "$PUBLIC_ROOT/robots.txt"
chmod 750 "$PRIVATE_ROOT" "$PRIVATE_ROOT/app" "$PRIVATE_ROOT/dbsqlite" "$PRIVATE_ROOT/dbsqlite/companies" \
  "$PRIVATE_ROOT/dbsqlite/seed" "$PRIVATE_ROOT/documente" "$PRIVATE_ROOT/sabloane" "$PRIVATE_ROOT/sabloane/standard" "$PRIVATE_ROOT/sabloane/custom" "$PRIVATE_ROOT/backup" "$PRIVATE_ROOT/logs" \
  "$PRIVATE_ROOT/secrets" "$PRIVATE_ROOT/scripts" "$PRIVATE_ROOT/tmp"
find "$PRIVATE_ROOT/app" -type d -exec chmod 750 {} +
find "$PRIVATE_ROOT/app" -type f -exec chmod 640 {} +
chmod 750 "$PRIVATE_ROOT/app/manage.py"
find "$PRIVATE_ROOT/scripts" -type f -name '*.sh' -exec chmod 750 {} +
find "$PRIVATE_ROOT/dbsqlite" -type f -name '*.sqlite' -exec chmod 600 {} +
find "$PRIVATE_ROOT/sabloane" -type f -exec chmod 640 {} +
find "$PRIVATE_ROOT/documente" -type d -exec chmod 750 {} +
find "$PRIVATE_ROOT/documente" -type f -exec chmod 640 {} +

register_or_update_selector_app

# Python Selector poate genera propriul passenger_wsgi.py și poate rescrie blocul
# Passenger din .htaccess. Reaplicăm fișierele validate după înregistrare.
cp -a "$PACKAGE_ROOT/application_root/passenger_wsgi.py" "$APP_ROOT/passenger_wsgi.py"
cp -a "$PACKAGE_ROOT/application_root/requirements.txt" "$APP_ROOT/requirements.txt"
cp -a "$PACKAGE_ROOT/public/.htaccess" "$PUBLIC_ROOT/.htaccess"
cp -a "$PACKAGE_ROOT/public/robots.txt" "$PUBLIC_ROOT/robots.txt"
chmod 644 "$APP_ROOT/passenger_wsgi.py" "$APP_ROOT/requirements.txt" "$PUBLIC_ROOT/.htaccess" "$PUBLIC_ROOT/robots.txt"

[[ -x "$VENV_ROOT/bin/python" ]] || fail "Mediul virtual CloudLinux nu există la $VENV_ROOT. Deschide aplicația în Setup Python App, salveaz-o, apoi rulează din nou installerul."

"$VENV_ROOT/bin/python" -m pip install --disable-pip-version-check --upgrade pip setuptools wheel
"$VENV_ROOT/bin/python" -m pip install --disable-pip-version-check -r "$APP_ROOT/requirements.txt"

export LOANCOPILOT_HOME="$HOME_ROOT"
export LOANCOPILOT_PUBLIC_ROOT="$PUBLIC_ROOT"
export LOANCOPILOT_PRIVATE_ROOT="$PRIVATE_ROOT"
export LOANCOPILOT_DB_ROOT="$DB_ROOT"
export LOANCOPILOT_DOCUMENT_ROOT="$DOCUMENT_ROOT"
export LOANCOPILOT_TEMPLATE_ROOT="$TEMPLATE_ROOT"
export LOANCOPILOT_COOKIE_SECURE=1
export LOANCOPILOT_TRUST_PROXY=1
export PYTHONUNBUFFERED=1
export PYTHONPATH="$PRIVATE_ROOT/app"

if [[ ! -f "$DB_ROOT/loancopilot_auth.sqlite" ]]; then
  echo
  echo "Prima instalare: se creează administratorul și compania MTM."
  read -r -p "Email administrator: " ADMIN_EMAIL
  read -r -p "Nume afișat administrator [Gheorghe Șandru]: " ADMIN_NAME
  ADMIN_NAME="${ADMIN_NAME:-Gheorghe Șandru}"
  "$VENV_ROOT/bin/python" "$PRIVATE_ROOT/app/manage.py" init \
    --admin-email "$ADMIN_EMAIL" \
    --admin-name "$ADMIN_NAME"
else
  echo "Baza de autentificare există; utilizatorii, parolele și 2FA se păstrează."
  "$VENV_ROOT/bin/python" - <<'PY'
from manage import seed_mtm
from loancopilot.config import ensure_directories
from loancopilot.db import auth_connect, copy_standard_templates_to_company, init_auth_db, tenant_documents_path

ensure_directories()
init_auth_db()
company_id = seed_mtm()
copied = 0
with auth_connect() as con:
    admins = con.execute("SELECT id FROM users WHERE active=1 AND is_superadmin=1").fetchall()
    for admin in admins:
        con.execute(
            "INSERT INTO user_companies(user_id,company_id,role) VALUES(?,?,'ADMIN') "
            "ON CONFLICT(user_id,company_id) DO UPDATE SET role='ADMIN'",
            (admin["id"], company_id),
        )
    companies = con.execute("SELECT * FROM companies WHERE active=1").fetchall()
    for company in companies:
        copied += copy_standard_templates_to_company(tenant_documents_path(company))
    con.commit()
print(f"Schema, seed-ul MTM, accesul administratorilor și șabloanele sunt la zi. Șabloane noi copiate: {copied}.")
PY
fi

# Test real prin startup file-ul Passenger, fără import recursiv.
cd "$APP_ROOT"
"$VENV_ROOT/bin/python" - <<'PY'
from passenger_wsgi import application
print("WSGI OK:", application.name)
print("Număr rute:", len(application.url_map._rules))
PY

touch "$APP_ROOT/tmp/restart.txt"
cloudlinux-selector restart --json \
  --interpreter python \
  --user aiallro \
  --app-root "$APP_SLUG" >/dev/null

echo
if ! command -v libreoffice >/dev/null 2>&1 && ! command -v soffice >/dev/null 2>&1; then
  echo "PDF: LibreOffice nu este instalat; aplicația folosește previzualizarea Word în browser și Print → Save as PDF."
else
  echo "PDF: LibreOffice/soffice detectat ca opțiune suplimentară; Print → Save as PDF rămâne disponibil."
fi

echo "LoanCopilot 2.5.0 a fost instalat/actualizat."
echo "URL:          https://$DOMAIN"
echo "App root:     $APP_ROOT"
echo "Public root:  $PUBLIC_ROOT"
echo "Cod privat:   $PRIVATE_ROOT/app"
echo "Auth DB:      $DB_ROOT/loancopilot_auth.sqlite"
echo "Baze firme:   $DB_ROOT/companies"
echo "Documente:    $DOCUMENT_ROOT"
echo "Șabloane:     $TEMPLATE_ROOT"
echo "Virtualenv:   $VENV_ROOT"
