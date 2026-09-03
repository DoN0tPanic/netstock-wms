#!/usr/bin/env bash
# Restore from a pg_dump -Fc file produced by backup.sh (§11.6).
# Usage: ./scripts/restore.sh <dump-file> [--dry-run] [--prova] [--yes]
#
#   --dry-run  elenca il contenuto del dump e si ferma
#   --prova    lo ripristina davvero, ma in un database usa e getta, e
#              confronta le righe con quelle dell'installazione
#   --yes      salta la conferma (sovrascrive il database vero)
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DUMP_FILE="${1:?Uso: restore.sh <dump-file> [--dry-run] [--yes]}"
DRY_RUN=false
CONFIRMED=false

PROVA=false

for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=true ;;
    --prova) PROVA=true ;;
    --yes) CONFIRMED=true ;;
  esac
done

if [ ! -f "$DUMP_FILE" ]; then
  echo "File di dump non trovato: $DUMP_FILE" >&2
  exit 1
fi

source "$REPO_DIR/.env"

# L'indice del dump serve a chi sta decidendo se ripristinarlo. Nella prova
# automatica settimanale sarebbe solo rumore nel journal, ogni domenica.
if [ "$PROVA" != true ]; then
  echo "Contenuto del dump:"
  docker compose -f "$REPO_DIR/docker-compose.yml" exec -T db pg_restore --list < "$DUMP_FILE"
fi

if [ "$DRY_RUN" = true ]; then
  echo "Dry-run: nessuna modifica applicata."
  exit 0
fi

# --- prova di ripristino -------------------------------------------------
# `pg_restore --list` dice che il file si legge, non che i dati tornano
# indietro: sono due cose diverse, e la seconda è quella che serve la sera in
# cui il disco muore. Qui il dump viene ripristinato davvero, in un database
# usa e getta, e le righe si contano. Un backup mai ripristinato non è un
# backup: è un file di cui ci si fida.
if [ "$PROVA" = true ]; then
  ORIGINE="${POSTGRES_DB:-netstock}"
  BERSAGLIO="${ORIGINE}_prova_ripristino"
  compose() { docker compose -f "$REPO_DIR/docker-compose.yml" "$@"; }
  psql_su() { compose exec -T db psql -v ON_ERROR_STOP=1 -U "${POSTGRES_USER:-netstock}" "$@"; }

  echo "Prova di ripristino in $BERSAGLIO (l'installazione non viene toccata)…"
  psql_su -d postgres -c "DROP DATABASE IF EXISTS $BERSAGLIO WITH (FORCE)" \
                      -c "CREATE DATABASE $BERSAGLIO" >/dev/null

  # `--no-owner` perché il dump cita il ruolo di produzione; gli errori di
  # ripristino non si ignorano: è tutto il punto della prova.
  if ! compose exec -T db pg_restore -U "${POSTGRES_USER:-netstock}" \
        -d "$BERSAGLIO" --no-owner --exit-on-error < "$DUMP_FILE"; then
    echo "PROVA FALLITA: il dump non si ripristina." >&2
    psql_su -d postgres -c "DROP DATABASE IF EXISTS $BERSAGLIO WITH (FORCE)" >/dev/null
    exit 1
  fi

  TABELLE="users catalog_items stock_units stock_movements delivery_notes audit_log"
  ESITO=0
  printf '%-18s %10s %10s\n' "tabella" "adesso" "nel dump"
  for tabella in $TABELLE; do
    VIVE=$(psql_su -d "$ORIGINE" -tAc "SELECT count(*) FROM $tabella" | tr -d '[:space:]')
    COPIA=$(psql_su -d "$BERSAGLIO" -tAc "SELECT count(*) FROM $tabella" | tr -d '[:space:]')
    printf '%-18s %10s %10s\n' "$tabella" "$VIVE" "$COPIA"
    # Zero righe dove l'installazione ne ha è il sintomo del dump troncato:
    # il file si apre, l'elenco si legge, e i dati non ci sono.
    if [ "$VIVE" -gt 0 ] && [ "$COPIA" -eq 0 ]; then
      echo "  ^ vuota nel dump: copia incompleta." >&2
      ESITO=1
    fi
  done

  psql_su -d postgres -c "DROP DATABASE IF EXISTS $BERSAGLIO WITH (FORCE)" >/dev/null
  if [ "$ESITO" -eq 0 ]; then
    echo "Prova riuscita: il dump si ripristina e contiene i dati."
  else
    echo "PROVA FALLITA: il dump si ripristina ma è incompleto." >&2
  fi
  exit "$ESITO"
fi

if [ "$CONFIRMED" != true ]; then
  echo
  echo "ATTENZIONE: questa operazione SOVRASCRIVE il database 'netstock' corrente."
  read -r -p "Digitare 'RIPRISTINA' per confermare: " answer
  if [ "$answer" != "RIPRISTINA" ]; then
    echo "Operazione annullata."
    exit 1
  fi
fi

echo "Arresto dell'API per evitare scritture concorrenti durante il ripristino..."
docker compose -f "$REPO_DIR/docker-compose.yml" stop api

echo "Ripristino in corso..."
docker compose -f "$REPO_DIR/docker-compose.yml" exec -T db \
  pg_restore -U "${POSTGRES_USER:-netstock}" -d "${POSTGRES_DB:-netstock}" \
  --clean --if-exists --no-owner < "$DUMP_FILE"

echo "Riavvio dell'API..."
docker compose -f "$REPO_DIR/docker-compose.yml" start api

echo "Ripristino completato. Registrare data e esito in docs/05-operations.md."
