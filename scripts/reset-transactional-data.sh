#!/usr/bin/env bash
# Azzera i dati di movimentazione mantenendo le anagrafiche.
#
# Cancella: movimenti, unità a magazzino, bolle e loro righe, prenotazioni,
# esecuzioni di estrazione, audit log.
# Mantiene: ubicazioni, catalogo, vendor, categorie, fornitori, utenti,
# template di estrazione, impostazioni.
#
# Pensato per ripulire un'installazione dopo la fase di prova, prima di
# iniziare a usarla sul serio. NON usarlo su un magazzino già in esercizio:
# il registro dei movimenti è la fonte di verità e qui viene svuotato.
#
# Fa un backup completo prima di toccare qualsiasi cosa.
set -euo pipefail

cd "$(dirname "$0")/.."

DB_USER="${POSTGRES_USER:-netstock}"
DB_NAME="${POSTGRES_DB:-netstock}"
BACKUP_DIR="backups"
STAMP="$(date +%Y%m%d-%H%M%S)"
BACKUP_FILE="${BACKUP_DIR}/pre-reset-${STAMP}.sql"

echo "Verranno cancellati i dati di movimentazione del database '${DB_NAME}':"
docker compose exec -T db psql -U "$DB_USER" -d "$DB_NAME" -c "
SELECT 'movimenti' AS tabella, count(*) FROM stock_movements
UNION ALL SELECT 'unità', count(*) FROM stock_units
UNION ALL SELECT 'righe bolla', count(*) FROM delivery_note_lines
UNION ALL SELECT 'bolle', count(*) FROM delivery_notes
UNION ALL SELECT 'prenotazioni', count(*) FROM reservations
UNION ALL SELECT 'audit', count(*) FROM audit_log;"

if [ "${FORCE:-}" != "1" ]; then
  read -r -p "Confermi? Scrivi AZZERA per procedere: " answer
  [ "$answer" = "AZZERA" ] || { echo "Annullato."; exit 1; }
fi

mkdir -p "$BACKUP_DIR"
echo "Backup in corso → ${BACKUP_FILE}"
docker compose exec -T db pg_dump -U "$DB_USER" -d "$DB_NAME" > "$BACKUP_FILE"
echo "Backup completato ($(du -h "$BACKUP_FILE" | cut -f1))."

# I trigger append-only proteggono l'uso quotidiano di movimenti e audit:
# qui vengono scavalcati una tantum, in modo esplicito e dentro una
# transazione, così un errore a metà non lascia il database a pezzi.
docker compose exec -T db psql -U "$DB_USER" -d "$DB_NAME" -v ON_ERROR_STOP=1 <<'SQL'
BEGIN;
ALTER TABLE stock_movements DISABLE TRIGGER trg_movements_immutable;
ALTER TABLE audit_log       DISABLE TRIGGER trg_audit_immutable;

DELETE FROM reservations;
DELETE FROM stock_movements;
DELETE FROM stock_units;
DELETE FROM delivery_note_lines;
DELETE FROM delivery_notes;
DELETE FROM extraction_runs;
DELETE FROM audit_log;

ALTER TABLE stock_movements ENABLE TRIGGER trg_movements_immutable;
ALTER TABLE audit_log       ENABLE TRIGGER trg_audit_immutable;
COMMIT;
SQL

echo
echo "Fatto. Situazione attuale:"
docker compose exec -T db psql -U "$DB_USER" -d "$DB_NAME" -c "
SELECT 'movimenti' AS tabella, count(*) FROM stock_movements
UNION ALL SELECT 'unità', count(*) FROM stock_units
UNION ALL SELECT 'bolle', count(*) FROM delivery_notes
UNION ALL SELECT 'ubicazioni (mantenute)', count(*) FROM locations
UNION ALL SELECT 'articoli (mantenuti)', count(*) FROM catalog_items
UNION ALL SELECT 'utenti (mantenuti)', count(*) FROM users;"
echo
echo "Se serve tornare indietro: make restore FILE=${BACKUP_FILE}"
