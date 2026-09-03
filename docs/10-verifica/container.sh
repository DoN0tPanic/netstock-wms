#!/usr/bin/env bash
# I container si spengono, si uccidono e si rimuovono: i dati devono restare.
# È la domanda che conta su una macchina che qualcuno riavvia.
set -uo pipefail
# L'indirizzo è di questa installazione: si passa dall'ambiente.
BASE_URL="${NETSTOCK_URL:?Manca NETSTOCK_URL, es. https://192.0.2.10}"
cd "$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
FALLITI=0

impronta() {
  docker compose exec -T db psql -U netstock -d netstock -Atc "
    SELECT (SELECT count(*) FROM stock_units) || '/' ||
           (SELECT count(*) FROM stock_movements) || '/' ||
           (SELECT count(*) FROM audit_log) || '/' ||
           (SELECT count(*) FROM users) || '/' ||
           (SELECT coalesce(sum(quantity)::text,'0') FROM stock_movements)" 2>/dev/null
}

attendi() {
  local scaduto=$((SECONDS+120))
  until curl -sk $BASE_URL/health -o /dev/null -w '%{http_code}' 2>/dev/null | grep -q 200; do
    [ $SECONDS -gt $scaduto ] && { echo "  l'applicazione non è tornata su entro 120s"; return 1; }
    sleep 3
  done
  return 0
}

confronta() { # etichetta, prima
  local dopo; dopo=$(impronta)
  if [ "$dopo" = "$2" ]; then
    echo "  OK      $1 — impronta invariata ($dopo)"
  else
    FALLITI=$((FALLITI+1)); echo "  FALLITO $1 — prima $2, dopo $dopo"
  fi
}

PRIMA=$(impronta)
echo "impronta di partenza (unità/movimenti/audit/utenti/somma quantità): $PRIMA"
echo

echo "== 1. Arresto ordinato e riavvio (docker compose stop / start) =="
docker compose stop >/dev/null 2>&1
echo "  servizi fermi: $(docker compose ps --format '{{.Service}}' | wc -l) in esecuzione"
docker compose start >/dev/null 2>&1
attendi && confronta "arresto ordinato" "$PRIMA"
echo

echo "== 2. Interruzione brutale (docker compose kill: come togliere la corrente) =="
docker compose kill >/dev/null 2>&1
docker compose start >/dev/null 2>&1
attendi && confronta "interruzione brutale" "$PRIMA"
echo

echo "== 3. Rimozione dei container e ricreazione (docker compose down / up) =="
docker compose down >/dev/null 2>&1
echo "  container rimossi: $(docker compose ps -a --format '{{.Service}}' | wc -l) rimasti"
echo "  volume dati ancora presente: $(docker volume ls --format '{{.Name}}' | grep -c netstock_pgdata)"
docker compose up -d >/dev/null 2>&1
attendi && confronta "rimozione e ricreazione" "$PRIMA"
echo

echo "== 4. Riavvio del solo database sotto l'applicazione =="
docker compose restart db >/dev/null 2>&1
sleep 8
attendi && confronta "riavvio del database" "$PRIMA"
echo "  l'API si è riconnessa: $(curl -sk $BASE_URL/health -o /dev/null -w '%{http_code}')"
echo
echo "  totale: $FALLITI verifiche fallite"
exit "$FALLITI"
