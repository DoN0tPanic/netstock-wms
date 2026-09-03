#!/usr/bin/env bash
# Certificato TLS per una rete locale, in due modi.
#
#   ./scripts/gen-selfsigned-cert.sh              certificato autofirmato
#   ./scripts/gen-selfsigned-cert.sh --con-ca     CA locale + certificato firmato
#   ./scripts/gen-selfsigned-cert.sh --rigenera   rifà quello che c'è già
#
# La differenza non è estetica. Con un certificato autofirmato ogni telefono
# passa da un avviso di sicurezza prima di arrivare all'applicazione, e — cosa
# che conta di più — la fotocamera del lettore di barcode vive su
# un'eccezione che Android e iOS trattano in modo diverso fra versioni: è la
# funzione su cui è stato speso più lavoro (ventiquattro apparati in meno di
# tre minuti) appesa alla clemenza del browser.
#
# Con `--con-ca` si genera una piccola autorità locale e le si fa firmare il
# certificato del server. Installando **una volta** `certs/netstock-ca.crt`
# su ogni telefono e computer, l'avviso sparisce e il lucchetto è verde come
# su un sito qualunque.
#
# Il compromesso, detto chiaramente: la chiave della CA resta su questa
# macchina, in `certs/`. Chi la prende può fingersi qualunque sito verso i
# dispositivi che l'hanno installata. Per un magazzino su LAN, con `certs/`
# escluso da git e leggibile solo dal proprietario, è proporzionato; in
# un'azienda che ha già una CA interna, la scelta giusta resta farsi firmare
# il certificato da quella.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CERT_DIR="$REPO_DIR/certs"
mkdir -p "$CERT_DIR"

# L'indirizzo vero sta in `.env`, scritto da bootstrap.sh al primo avvio.
# Senza leggerlo, `--rigenera` produrrebbe un certificato per il segnaposto
# `netstock.local` e l'installazione smetterebbe di rispondere sul proprio
# indirizzo — che è il modo peggiore di scoprire un valore predefinito.
# shellcheck disable=SC1091
[ -f "$REPO_DIR/.env" ] && . "$REPO_DIR/.env"

CON_CA=0
RIGENERA=0
for arg in "$@"; do
  case "$arg" in
    --con-ca) CON_CA=1 ;;
    --rigenera) RIGENERA=1 ;;
  esac
done

SITE_ADDRESS="${SITE_ADDRESS:-netstock.local}"
LAN_IP="${LAN_IP:-$(hostname -I | awk '{print $1}')}"
SAN="DNS:${SITE_ADDRESS},DNS:localhost,IP:${LAN_IP},IP:127.0.0.1"

if [ -f "$CERT_DIR/netstock.crt" ] && [ "$RIGENERA" = 0 ]; then
  # Dirlo, invece di uscire e basta: se la macchina ha cambiato indirizzo, il
  # certificato che c'è non copre più quello nuovo e nessuno se ne accorge
  # finché un telefono non smette di funzionare.
  ATTUALI="$(openssl x509 -in "$CERT_DIR/netstock.crt" -noout -ext subjectAltName 2>/dev/null | tail -1 | tr -d ' ')"
  echo "Certificato già presente in $CERT_DIR, nessuna azione."
  echo "  vale per: ${ATTUALI:-sconosciuto}"
  echo "  adesso:   ${SAN}"
  echo "  Se non combaciano: ./scripts/gen-selfsigned-cert.sh --rigenera"
  exit 0
fi

if [ "$CON_CA" = 1 ]; then
  if [ ! -f "$CERT_DIR/netstock-ca.crt" ]; then
    echo "Genero l'autorità locale (dura 10 anni)…"
    openssl req -x509 -nodes -newkey rsa:4096 -days 3650 \
      -keyout "$CERT_DIR/netstock-ca.key" \
      -out "$CERT_DIR/netstock-ca.crt" \
      -subj "/C=IT/O=NetStock/CN=NetStock CA locale" \
      -addext "basicConstraints=critical,CA:TRUE,pathlen:0" \
      -addext "keyUsage=critical,keyCertSign,cRLSign" 2>/dev/null
    chmod 600 "$CERT_DIR/netstock-ca.key"
  fi

  openssl req -nodes -newkey rsa:4096 \
    -keyout "$CERT_DIR/netstock.key" \
    -out "$CERT_DIR/netstock.csr" \
    -subj "/C=IT/O=NetStock/CN=${SITE_ADDRESS}" 2>/dev/null
  # 825 giorni è il massimo che i dispositivi Apple accettano per un
  # certificato di server: più lungo, e iPhone e iPad lo rifiutano comunque.
  openssl x509 -req -in "$CERT_DIR/netstock.csr" -days 825 \
    -CA "$CERT_DIR/netstock-ca.crt" -CAkey "$CERT_DIR/netstock-ca.key" -CAcreateserial \
    -out "$CERT_DIR/netstock.crt" \
    -extfile <(printf 'subjectAltName=%s\nbasicConstraints=CA:FALSE\nkeyUsage=digitalSignature,keyEncipherment\nextendedKeyUsage=serverAuth\n' "$SAN") 2>/dev/null
  rm -f "$CERT_DIR/netstock.csr"
  chmod 600 "$CERT_DIR/netstock.key"

  echo
  echo "Fatto. Certificato firmato dalla CA locale, valido per ${SAN}."
  echo
  echo "  Adesso installa UNA VOLTA questo file su telefoni e computer:"
  echo "    $CERT_DIR/netstock-ca.crt"
  echo
  echo "    Android   Impostazioni → Sicurezza → Altro → Installa certificato →"
  echo "              Certificato CA (l'avviso che compare è normale)"
  echo "    iOS       apri il file → Impostazioni → Profilo scaricato → Installa,"
  echo "              poi Generali → Info → Attendibilità certificati → attiva"
  echo "    Windows   doppio clic → Computer locale → Autorità di certificazione radice attendibili"
  echo "    Linux     copia in /usr/local/share/ca-certificates/ e 'sudo update-ca-certificates'"
  echo
  echo "  Poi: docker compose restart caddy"
else
  openssl req -x509 -nodes -newkey rsa:4096 -days 825 \
    -keyout "$CERT_DIR/netstock.key" \
    -out "$CERT_DIR/netstock.crt" \
    -subj "/C=IT/O=NetStock/CN=${SITE_ADDRESS}" \
    -addext "subjectAltName=${SAN}"
  chmod 600 "$CERT_DIR/netstock.key"
  echo "Certificato autofirmato generato in $CERT_DIR per ${SAN}."
  echo "Il browser mostrerà un avviso finché non si installa un certificato"
  echo "firmato da una CA che i dispositivi conoscono. Per farne una in casa:"
  echo "    ./scripts/gen-selfsigned-cert.sh --con-ca --rigenera"
fi
