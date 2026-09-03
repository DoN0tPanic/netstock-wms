#!/usr/bin/env bash
# Prepara il database su cui girano i test: `netstock_test`, non quello vero.
#
# Esiste perché senza, `make test` gira sul database dell'applicazione. I
# test creano utenti, forzano blocchi di accesso e scrivono nel registro, e
# la `login()` fa `commit` per progetto (§6.4): nessun rollback li ripulisce,
# quindi restano lì. Gli account di prova che si accumulano sono il danno
# visibile; quello vero arriverebbe il giorno in cui un test tocca
# `stock_movements`, che è append-only — in un registro di magazzino non si
# torna indietro.
#
# Il database di prova sta nello stesso cluster (il ruolo `netstock_app` è di
# cluster, quindi vale per entrambi) e viene ricreato da zero a ogni giro: un
# test che dipende da ciò che ha lasciato il giro prima è un test che mente.
#
# Uso:  ./scripts/test-db.sh [--riusa]
set -euo pipefail
cd "$(dirname "$0")/.."

RIUSA=0
[ "${1:-}" = "--riusa" ] && RIUSA=1

if ! docker compose ps --format '{{.Service}}' | grep -q '^db$'; then
  echo "Il database non è in esecuzione: 'make up' prima." >&2
  exit 1
fi

# Il nome deriva da quello di produzione: se un giorno cambia, il gemello di
# prova lo segue senza doverlo ricordare.
NOME=$(docker compose exec -T db sh -c 'printf %s "${POSTGRES_DB:-netstock}"')_test

if [ "$RIUSA" -eq 0 ]; then
  echo "Ricreo $NOME…"
  docker compose exec -T db sh -c "
    psql -v ON_ERROR_STOP=1 -U \"\$POSTGRES_USER\" -d postgres \
      -c \"DROP DATABASE IF EXISTS $NOME WITH (FORCE)\" \
      -c \"CREATE DATABASE $NOME\"" >/dev/null
else
  docker compose exec -T db sh -c "
    psql -v ON_ERROR_STOP=1 -U \"\$POSTGRES_USER\" -d postgres -tAc \
      \"SELECT 1 FROM pg_database WHERE datname = '$NOME'\" | grep -q 1 ||
    psql -v ON_ERROR_STOP=1 -U \"\$POSTGRES_USER\" -d postgres \
      -c \"CREATE DATABASE $NOME\"" >/dev/null
fi

# Le migrazioni girano con le stesse variabili dell'applicazione, con il nome
# del database sostituito: nessuna password passa dal Makefile o da qui.
echo "Applico le migrazioni a $NOME…"
docker compose exec -T api sh -c '
  export DATABASE_URL="${DATABASE_URL%/*}/'"$NOME"'"
  export MIGRATE_DATABASE_URL="${MIGRATE_DATABASE_URL%/*}/'"$NOME"'"
  alembic upgrade head' >/dev/null

echo "Pronto: $NOME (schema e dati di seed della 0002)."
