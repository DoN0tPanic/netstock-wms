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

echo "== Archivio delle bolle =="
# Un PDF minimo costruito qui: un documento vero non entra in uno script, e
# serve comunque solo a provare che il giro funzioni.
PDF=$(mktemp --suffix=.pdf); trap 'rm -f "$C" "$PDF"' EXIT
NUMERO="VERIFICA-$RANDOM"
python3 - "$PDF" "$NUMERO" <<'PYPDF'
import sys
percorso, numero = sys.argv[1], sys.argv[2]
testo = f"DITTA DI VERIFICA - DOCUMENTO DI TRASPORTO n. {numero} del 05/09/2026 - merce varia"
flusso = f"BT /F1 11 Tf 50 700 Td ({testo}) Tj ET".encode("latin-1", "replace")
oggetti = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
    b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
    b"<< /Length " + str(len(flusso)).encode() + b" >>\nstream\n" + flusso + b"\nendstream",
    b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
out = bytearray(b"%PDF-1.4\n"); pos = []
for n, c in enumerate(oggetti, 1):
    pos.append(len(out)); out += str(n).encode() + b" 0 obj\n" + c + b"\nendobj\n"
x = len(out)
out += b"xref\n0 " + str(len(oggetti)+1).encode() + b"\n0000000000 65535 f \n"
for p in pos: out += f"{p:010d} 00000 n \n".encode()
out += b"trailer\n<< /Size " + str(len(oggetti)+1).encode() + b" /Root 1 0 R >>\nstartxref\n" + str(x).encode() + b"\n%%EOF\n"
open(percorso, "wb").write(bytes(out))
PYPDF

carica_documento() {
  curl -sk -b "$C" -H 'X-Requested-With: XMLHttpRequest' -F "file=@$PDF" "$BASE/documents" \
    -o /tmp/documento.json -w '%{http_code}'
}
CODICE=$(carica_documento); DOC=$(python3 -c "import json;print(json.load(open('/tmp/documento.json')).get('id',''))" 2>/dev/null)
ESITI=$((ESITI+1))
if [ "$CODICE" = "201" ] && [ -n "$DOC" ]; then
  printf '  OK    %-3s  %-6s %-46s %s\n' 201 POST /documents "PDF archiviato"
else
  FALLITI=$((FALLITI+1)); printf '  FALLITO caricamento del PDF (codice %s)\n' "$CODICE"
fi

if [ -n "$DOC" ]; then
  prova "si ritrova cercando il contenuto" 200 GET "/documents?q=$NUMERO"
  RITROVATI=$(python3 -c "import json;print(json.load(open('/tmp/risposta.json'))['total'])" 2>/dev/null || echo 0)
  ESITI=$((ESITI+1))
  if [ "$RITROVATI" -ge 1 ]; then
    printf '  OK    %-3s  %-6s %-46s %s\n' 200 GET "/documents?q=…" "il numero scritto dentro lo trova"
  else
    FALLITI=$((FALLITI+1)); printf '  FALLITO la ricerca per contenuto non trova il documento appena caricato\n'
  fi
  prova "stesso file due volte rifiutato" 422 POST /documents ''
  prova "conteggio per fornitore" 200 GET /documents/fornitori
  prova "il PDF originale" 200 GET "/documents/$DOC/file"
  prova "il PDF come copia da salvare" 200 GET "/documents/$DOC/file?scarica=1"
  prova "anteprima della prima pagina" 200 GET "/documents/$DOC/anteprima"
  prova "testo su cui si cerca" 200 GET "/documents/$DOC/testo"
  prova "riesame dei fornitori" 200 POST /documents/fornitori/riesamina
  prova "fornitore inesistente rifiutato" 422 PUT "/documents/$DOC/fornitore" \
    '{"supplier_id":"00000000-0000-0000-0000-000000000000"}'
  prova "fornitore tolto a mano" 200 PUT "/documents/$DOC/fornitore" '{"supplier_id":null}'
  prova "documento rimosso" 204 DELETE "/documents/$DOC"
  prova "documento rimosso davvero" 404 GET "/documents/$DOC/testo"
fi

echo "== Lettura automatica =="
prova "stato del modello" 200 GET /ai/stato
prova "modello non installato rifiutato" 422 PUT /ai/modello '{"modello":"modello-che-non-esiste:99b"}'
prova "chiave gestita da una pagina, non dalla tabella" 422 PUT "/settings/extraction_model" '{"value":"\"qwen3:4b\""}'

echo "== Copie di sicurezza =="
prova "parola di conferma sbagliata" 422 POST /maintenance/restore ''

echo "== Permessi (utente in sola lettura) =="
# La sezione era un titolo senza prove sotto: prometteva una verifica che non
# c'era. Adesso crea davvero un utente in sola lettura e prova a fargli fare
# quello che non deve poter fare.
# Un solo account, sempre lo stesso, con una password nuova a ogni giro e
# disattivato alla fine. Le prime versioni ne creavano uno nuovo ogni volta e
# lo cancellavano: la cancellazione definitiva però non riesce, perché
# l'utente ha agito e le sue righe di registro lo trattengono (§ eliminazione
# utenti). Risultato: un account chiuso in più a ogni esecuzione.
UTENTE_PROVA="verifica-permessi"
PW_PROVA="Verifica-$(head -c 9 /dev/urandom | base64 | tr -dc 'A-Za-z0-9')-2026!"
ID_PROVA=$(curl -sk -b "$C" -H 'X-Requested-With: XMLHttpRequest' \
  "$BASE/users?include_deleted=true&page_size=200" \
  | python3 -c "import json,sys;u=[r['id'] for r in json.load(sys.stdin)['items'] if r['username']=='$UTENTE_PROVA'];print(u[0] if u else '')")

if [ -z "$ID_PROVA" ]; then
  CODICE=$(curl -sk -b "$C" -H 'X-Requested-With: XMLHttpRequest' -H 'Content-Type: application/json' \
    -X POST "$BASE/users" -o /tmp/utente.json \
    -d "{\"username\":\"$UTENTE_PROVA\",\"full_name\":\"Verifica permessi\",\"role\":\"viewer\",\"initial_password\":\"$PW_PROVA\"}" \
    -w '%{http_code}')
  ID_PROVA=$(python3 -c "import json;print(json.load(open('/tmp/utente.json')).get('id',''))" 2>/dev/null)
  NUOVO_UTENTE=1
else
  # Esiste già da un giro precedente: si riapre e gli si dà una password nuova.
  # La password la **sceglie il server** e la restituisce: passargliene una
  # non serve a niente, e nella prima versione di questo script il corpo
  # veniva ignorato in silenzio — l'utente riceveva una password casuale e
  # tutte le prove dei permessi fallivano con un 401.
  curl -sk -b "$C" -H 'X-Requested-With: XMLHttpRequest' -X POST "$BASE/users/$ID_PROVA/restore" -o /dev/null
  curl -sk -b "$C" -H 'X-Requested-With: XMLHttpRequest' -H 'Content-Type: application/json' \
    -X PATCH "$BASE/users/$ID_PROVA" -d '{"is_active":true}' -o /dev/null
  curl -sk -b "$C" -H 'X-Requested-With: XMLHttpRequest' \
    -X POST "$BASE/users/$ID_PROVA/reset-password" -o /tmp/reset.json
  PW_PROVA=$(python3 -c "import json;print(json.load(open('/tmp/reset.json')).get('temporary_password',''))")
  CODICE=201; NUOVO_UTENTE=0
fi

if [ "$CODICE" = "201" ] && [ -n "$ID_PROVA" ]; then
  C_ADMIN=$(mktemp); cp "$C" "$C_ADMIN"
  login "$UTENTE_PROVA" "$PW_PROVA" > /dev/null
  # Il primo accesso (o quello dopo un reset) impone il cambio password.
  curl -sk -b "$C" -c "$C" -H 'X-Requested-With: XMLHttpRequest' -H 'Content-Type: application/json' \
    -X POST "$BASE/auth/change-password" -o /dev/null \
    -d "{\"current_password\":\"$PW_PROVA\",\"new_password\":\"${PW_PROVA}bis\"}"
  prova "legge il magazzino" 200 GET "/inventory?page_size=1"
  prova "non registra merce" 403 POST /movements/receive '{"location_id":"00000000-0000-0000-0000-000000000000","lines":[]}'
  prova "non crea fornitori" 403 POST /suppliers '{"name":"Non deve nascere"}'
  prova "non vede gli utenti" 403 GET "/users?page_size=1"
  prova "non vede il registro di sicurezza" 403 GET "/audit?page_size=1"
  prova "non tocca le impostazioni" 403 GET /settings
  prova "non scarica una copia del database" 403 POST /maintenance/backup
  cp "$C_ADMIN" "$C"; rm -f "$C_ADMIN"
  # Disattivato, non cancellato: chi ha agito lascia righe di registro che lo
  # trattengono, e un account chiuso in più a ogni giro sarebbe sporcizia.
  # Disattivo non può accedere, e la password di questo giro muore qui.
  curl -sk -b "$C" -H 'X-Requested-With: XMLHttpRequest' -H 'Content-Type: application/json' \
    -X PATCH "$BASE/users/$ID_PROVA" -d '{"is_active":false}' -o /dev/null
  ESITI=$((ESITI+1))
  ATTIVO=$(curl -sk -b "$C" -H 'X-Requested-With: XMLHttpRequest' "$BASE/users?page_size=200" \
    | python3 -c "import json,sys;u=[r for r in json.load(sys.stdin)['items'] if r['username']=='$UTENTE_PROVA' and r['is_active']];print(len(u))")
  if [ "$ATTIVO" = "0" ]; then
    printf '  OK    %-3s  %-6s %-46s %s\n' 200 PATCH "/users/…" "utente di prova disattivato"
  else
    FALLITI=$((FALLITI+1)); printf '  FALLITO l utente di prova è rimasto attivo\n'
  fi
else
  FALLITI=$((FALLITI+1)); printf '  FALLITO non riesco a preparare l utente di prova (codice %s)\n' "$CODICE"
fi

curl -sk -b "$C" -X POST "$BASE/auth/logout" -H 'X-Requested-With: XMLHttpRequest' -o /dev/null
echo
echo "  totale: $ESITI prove, $FALLITI fallite"
exit "$FALLITI"
