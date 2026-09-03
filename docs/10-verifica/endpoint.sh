#!/usr/bin/env bash
# Passa in rassegna ogni endpoint dell'API e ne registra l'esito.
# Solo letture e operazioni reversibili: niente movimenti nel registro, che è
# append-only e non si ripulisce.
set -uo pipefail
# Indirizzo e credenziali non stanno qui dentro: sono di questa installazione,
# e un file che li contiene non si pubblica. Si passano dall'ambiente.
#
#   NETSTOCK_URL=https://il-tuo-indirizzo \
#   NETSTOCK_UTENTE=admin NETSTOCK_PASSWORD='…' docs/10-verifica/endpoint.sh
BASE_URL="${NETSTOCK_URL:?Manca NETSTOCK_URL, es. https://192.0.2.10}"
UTENTE="${NETSTOCK_UTENTE:-admin}"
PASSWORD="${NETSTOCK_PASSWORD:?Manca NETSTOCK_PASSWORD}"
BASE="$BASE_URL/api/v1"
C=$(mktemp); trap 'rm -f "$C"' EXIT
ESITI=0; FALLITI=0

login() { curl -sk -c "$C" -X POST "$BASE/auth/login" -H 'Content-Type: application/json' \
  -H 'X-Requested-With: XMLHttpRequest' -d "{\"username\":\"$1\",\"password\":\"$2\"}" -o /dev/null -w '%{http_code}'; }

prova() { # nome, atteso, metodo, percorso, [corpo]
  local nome="$1" atteso="$2" metodo="$3" percorso="$4" corpo="${5:-}"
  local args=(-sk -b "$C" -H 'X-Requested-With: XMLHttpRequest' -o /tmp/risposta.json -w '%{http_code}')
  [ -n "$corpo" ] && args+=(-H 'Content-Type: application/json' -d "$corpo")
  local codice; codice=$(curl "${args[@]}" -X "$metodo" "$BASE$percorso")
  ESITI=$((ESITI+1))
  if [ "$codice" = "$atteso" ]; then
    printf '  OK    %-3s  %-6s %-46s %s\n' "$codice" "$metodo" "$percorso" "$nome"
  else
    FALLITI=$((FALLITI+1))
    printf '  FALLITO atteso %s ottenuto %s — %s %s (%s)\n' "$atteso" "$codice" "$metodo" "$percorso" "$nome"
    head -c 220 /tmp/risposta.json; echo
  fi
}

echo "== Autenticazione =="
printf '  OK    %-3s  %-6s %-46s %s\n' "$(login "$UTENTE" "$PASSWORD")" POST "/auth/login" "credenziali valide"
prova "sessione corrente" 200 GET /auth/me
prova "credenziali sbagliate rifiutate" 401 POST /auth/login '{"username":"admin","password":"sbagliata-di-proposito"}'

echo "== Anagrafiche =="
for risorsa in vendors categories suppliers locations catalog-items; do
  prova "elenco $risorsa" 200 GET "/$risorsa?page_size=5"
done
prova "ricerca su ubicazioni" 200 GET "/locations?q=mag"
prova "risorsa inesistente" 404 GET "/locations/00000000-0000-0000-0000-000000000000"

echo "== Magazzino =="
prova "giacenza aggregata" 200 GET /stock
prova "giacenza per ubicazione" 200 GET /stock/by-location
prova "esportazione giacenza" 200 GET "/stock/export?format=csv"
prova "magazzino unificato" 200 GET "/inventory?page_size=5"
prova "magazzino filtrato" 200 GET "/inventory?status=in_stock&page_size=5"
prova "esportazione magazzino" 200 GET "/inventory/export?format=csv"
prova "esportazione con filtro vuoto" 422 GET "/inventory/export?format=csv&location="
prova "unità" 200 GET "/units?page_size=5"
prova "movimenti" 200 GET "/movements?page_size=5"
prova "esportazione movimenti" 200 GET "/movements/export?format=csv"

echo "== Bolle, prenotazioni, ricerca, cruscotto =="
prova "bolle" 200 GET "/delivery-notes?page_size=5"
prova "prenotazioni" 200 GET "/reservations?page_size=5"
prova "ricerca globale" 200 GET "/search?q=${NETSTOCK_SERIALE:-A}"
prova "cruscotto" 200 GET /dashboard
prova "esportazione completa" 200 GET /export

echo "== Regole di dominio =="
prova "data nel futuro rifiutata" 422 POST /movements/receive \
  '{"occurred_at":"2030-01-01T00:00:00Z","location_id":"11111111-2222-3333-4444-555555555555","confirm_warnings":[],"lines":[]}'
prova "rettifica senza motivazione rifiutata" 422 POST /movements/adjust \
  '{"reason":"corta","catalog_item_id":"66666666-7777-8888-9999-aaaaaaaaaaaa","quantity":1}'

echo "== Amministrazione =="
prova "utenti" 200 GET "/users?page_size=5"
prova "utenti compresi gli eliminati" 200 GET "/users?include_deleted=true"
prova "registro di sicurezza" 200 GET "/audit?page_size=5"
prova "impostazioni" 200 GET /settings
prova "stato delle copie" 200 GET /maintenance/backup
prova "template di estrazione" 200 GET /extraction-templates

echo "== Salute =="
prova "salute pubblica" 200 GET "/../../health"
prova "salute autenticata" 200 GET "/../../health/ready"

echo "== Permessi (utente in sola lettura) =="
curl -sk -b "$C" -X POST "$BASE/auth/logout" -H 'X-Requested-With: XMLHttpRequest' -o /dev/null
echo
echo "  totale: $ESITI prove, $FALLITI fallite"
exit "$FALLITI"
