#!/usr/bin/env bash
# Backup del database (§11.6). Conservazione: 30 giornalieri + 12 mensili.
#
# Tre cose che un backup deve fare, e che questo per mesi non ha fatto:
# partire da solo (lo installa install.sh come timer systemd), **uscire dalla
# macchina** (BACKUP_REMOTE) ed **essere ripristinato ogni tanto** per finta,
# perché un dump mai riaperto è un file di cui ci si fida, non una copia di
# sicurezza. Finché sono mancate, la sola copia dei dati stava sullo stesso
# disco del database che doveva proteggere.
#
# Uso:  ./scripts/backup.sh [--prova-ripristino]
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKUP_DIR="${BACKUP_DIR:-/var/backups/netstock}"
TIMESTAMP="$(date +%Y%m%d-%H%M%S)"
DAY_OF_MONTH="$(date +%d)"

mkdir -p "$BACKUP_DIR/daily" "$BACKUP_DIR/monthly"

# Le variabili passate a riga di comando vincono su quelle del file. Senza
# questo `source` le sovrascrive in silenzio, e un comando che la
# documentazione dichiara — `BACKUP_RESTORE_TEST=0 ./scripts/backup.sh` —
# non ha nessun effetto se quella riga esiste anche in `.env`. Trovato
# provando l'interruttore, non leggendolo.
DA_RIGA_DI_COMANDO="$(export -p)"
source "$REPO_DIR/.env"
eval "$DA_RIGA_DI_COMANDO"

DUMP_FILE="$BACKUP_DIR/daily/netstock-${TIMESTAMP}.dump"

echo "Backup di netstock in corso -> $DUMP_FILE"
docker compose -f "$REPO_DIR/docker-compose.yml" exec -T db \
  pg_dump -Fc -U "${POSTGRES_USER:-netstock}" "${POSTGRES_DB:-netstock}" > "$DUMP_FILE"

echo "Verifica integrità del dump..."
docker compose -f "$REPO_DIR/docker-compose.yml" exec -T db pg_restore --list < "$DUMP_FILE" > /dev/null
echo "Dump verificato correttamente."

if [ "$DAY_OF_MONTH" = "01" ]; then
  cp "$DUMP_FILE" "$BACKUP_DIR/monthly/netstock-$(date +%Y%m).dump"
  echo "Copia mensile salvata."
fi

find "$BACKUP_DIR/daily" -name "netstock-*.dump" -mtime +30 -delete
find "$BACKUP_DIR/monthly" -name "netstock-*.dump" -mtime +366 -delete

# --- fuori dalla macchina ------------------------------------------------
# Un backup accanto al database protegge dal `DROP TABLE`, non dal disco che
# muore né dalla VM che sparisce — che sono i due modi in cui si perde
# davvero un magazzino. La destinazione è una sola riga in `.env`: un percorso
# montato (`/mnt/nas/netstock`) o un bersaglio rsync (`nas:/backup/netstock`).
# Qui non si cancella niente da remoto: la rotazione di là la decide chi
# possiede quel disco. Sono ~100 kB al giorno.
if [ -n "${BACKUP_REMOTE:-}" ]; then
  echo "Copia fuori dalla macchina -> $BACKUP_REMOTE"
  if command -v rsync >/dev/null; then
    COMANDO=(rsync -a "$DUMP_FILE" "$BACKUP_REMOTE")
  elif [[ "$BACKUP_REMOTE" != *:* ]]; then
    COMANDO=(cp "$DUMP_FILE" "$BACKUP_REMOTE")
  else
    echo "BACKUP_REMOTE è un bersaglio remoto ma rsync non è installato." >&2
    exit 1
  fi
  if ! "${COMANDO[@]}"; then
    # Il dump locale c'è, ma la copia che serve nel giorno brutto no: questo
    # deve risultare un fallimento, o `systemctl status` dirà verde per mesi.
    echo "BACKUP INCOMPLETO: il dump è in $DUMP_FILE ma non è uscito dalla macchina." >&2
    exit 1
  fi
  echo "Copia remota completata."
else
  echo "Nota: BACKUP_REMOTE non impostata — la copia resta su questo disco."
  echo "      Se muore il disco, muore anche il backup. Vedi .env.example."
fi

# --- prova di ripristino -------------------------------------------------
# Una volta a settimana (e a comando) il dump appena fatto viene davvero
# ripristinato in un database usa e getta e le righe si contano. È l'unica
# differenza fra «abbiamo i backup» e «sappiamo che i backup tornano».
# **Quando** rifarla non è «di domenica»: era così, e una domenica a macchina
# spenta la saltava senza recuperarla mai — il backup sì (`Persistent=true`
# nel timer lo rifà all'accensione), la prova no, perché il lunedì non è
# domenica. Si guarda invece **quanto tempo è passato** dall'ultima riuscita:
# una macchina spenta nel fine settimana la fa al primo avvio utile.
PROVA="${1:-}"
SEGNO_PROVA="$BACKUP_DIR/.ultima-prova-ripristino"
GIORNI_FRA_PROVE="${BACKUP_RESTORE_TEST_DAYS:-7}"

scaduta() {
  [ "${BACKUP_RESTORE_TEST:-1}" = "0" ] && return 1
  [ -f "$SEGNO_PROVA" ] || return 0
  local ultima adesso
  ultima=$(cat "$SEGNO_PROVA" 2>/dev/null || echo 0)
  adesso=$(date +%s)
  [ $(( (adesso - ultima) / 86400 )) -ge "$GIORNI_FRA_PROVE" ]
}

if [ "$PROVA" = "--prova-ripristino" ] || scaduta; then
  echo
  "$REPO_DIR/scripts/restore.sh" "$DUMP_FILE" --prova
  # Solo se è andata bene: con `set -e` un fallimento ferma tutto qui, il
  # segno resta vecchio e la prova si rifà al giro dopo.
  date +%s > "$SEGNO_PROVA"
fi

echo "Backup completato: $DUMP_FILE"
