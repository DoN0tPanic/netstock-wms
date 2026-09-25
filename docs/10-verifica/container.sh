#!/usr/bin/env bash
# I container si spengono, si uccidono e si rimuovono: i dati devono restare.
# È la domanda che conta su una macchina che qualcuno riavvia.
set -uo pipefail
# L'indirizzo è di questa installazione: si passa dall'ambiente.
BASE_URL="${NETSTOCK_URL:?Manca NETSTOCK_URL, es. https://192.0.2.10}"
# La cartella da cui si lavora decide quale installazione si tocca: Docker
# Compose legge il `.env` della cartella corrente. Con `COMPOSE_FILE` si
# lavora accanto a quel file — altrimenti un'istanza di prova finiva avviata
# con i segreti di questa installazione (e, con la password sbagliata, non
# ripartiva più). Senza, si resta nella cartella del progetto.
if [ -n "${COMPOSE_FILE:-}" ]; then
  cd "$(dirname "${COMPOSE_FILE%%:*}")"
else
  cd "$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
fi
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
    [ $SECONDS -gt $scaduto ] && { FALLITI=$((FALLITI+1)); echo "  FALLITO l'applicazione non è tornata su entro 120s"; return 1; }
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
PROGETTO="${COMPOSE_PROJECT_NAME:-netstock}"
VOLUMI=$(docker volume ls -q --filter "label=com.docker.compose.project=$PROGETTO" --filter "label=com.docker.compose.volume=pgdata" | wc -l)
echo "  volume dati di «$PROGETTO» ancora presente: $VOLUMI"
[ "$VOLUMI" -eq 1 ] || { FALLITI=$((FALLITI+1)); echo "  FALLITO il volume dei dati non c'è più"; }
docker compose up -d >/dev/null 2>&1
attendi && confronta "rimozione e ricreazione" "$PRIMA"
echo

echo "== 4. Riavvio del solo database sotto l'applicazione =="
docker compose restart db >/dev/null 2>&1
sleep 8
attendi && confronta "riavvio del database" "$PRIMA"
RICONNESSA=$(curl -sk "$BASE_URL/health" -o /dev/null -w '%{http_code}')
echo "  l'API si è riconnessa: $RICONNESSA"
[ "$RICONNESSA" = 200 ] || { FALLITI=$((FALLITI+1)); echo "  FALLITO l'API non risponde dopo il riavvio del database"; }
echo
echo "  totale: $FALLITI verifiche fallite"
exit "$FALLITI"
