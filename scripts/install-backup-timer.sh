#!/usr/bin/env bash
# Installa il backup notturno come timer systemd.
#
# Finché è mancato, i backup erano quelli che qualcuno si ricordava di fare a
# mano: pochi, e a distanza irregolare. Un backup che dipende dalla memoria
# di una persona non è una copia di sicurezza, è un proposito.
#
# Uso:  ./scripts/install-backup-timer.sh [--disinstalla]
set -euo pipefail
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
UNITA=/etc/systemd/system

if ! command -v systemctl >/dev/null; then
  echo "systemd non è disponibile: pianifica ./scripts/backup.sh con cron." >&2
  exit 1
fi

SUDO=""
[ "$(id -u)" -ne 0 ] && SUDO="sudo"

if [ "${1:-}" = "--disinstalla" ]; then
  $SUDO systemctl disable --now netstock-backup.timer 2>/dev/null || true
  $SUDO rm -f "$UNITA/netstock-backup.timer" "$UNITA/netstock-backup.service"
  $SUDO systemctl daemon-reload
  echo "Backup automatico rimosso."
  exit 0
fi

# L'unità cita il percorso del repository e l'utente che possiede Docker: sono
# le due cose che non si possono indovinare e che cambiano da macchina a
# macchina, quindi si sostituiscono qui invece di chiedere di modificare un
# file a mano dopo l'installazione.
for nome in netstock-backup.service netstock-backup.timer; do
  sed -e "s#__REPO__#$REPO_DIR#g" -e "s#__UTENTE__#${SUDO_USER:-$USER}#g" \
    "$REPO_DIR/scripts/systemd/$nome" | $SUDO tee "$UNITA/$nome" >/dev/null
done

$SUDO systemctl daemon-reload
$SUDO systemctl enable --now netstock-backup.timer

echo "Backup automatico attivo. Prossima esecuzione:"
systemctl list-timers netstock-backup.timer --no-pager | sed -n 2p
echo
echo "  systemctl status netstock-backup      esito dell'ultimo backup"
echo "  journalctl -u netstock-backup         cosa ha fatto"
