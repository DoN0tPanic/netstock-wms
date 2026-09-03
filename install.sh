#!/usr/bin/env bash
# Installatore completo di NetStock: verifica cosa manca, lo installa e avvia
# il sistema.
#
# Tre regole che questo script si dà:
#
# 1. **Niente `curl | sudo bash`.** I pacchetti arrivano dai repository
#    ufficiali delle rispettive distribuzioni o dei rispettivi progetti, con
#    la chiave di firma verificata. Uno script scaricato ed eseguito alla cieca
#    con privilegi di root è esattamente ciò che si insegna a non fare.
# 2. **Ogni azione con privilegi viene annunciata prima.** Si vede cosa sta per
#    essere installato e si può dire di no. La password di sudo viene chiesta
#    una volta sola, e solo se serve davvero qualcosa.
# 3. **Rieseguibile.** Quello che c'è già viene saltato. Se qualcosa va storto
#    a metà, si rilancia senza disfare nulla a mano.
#
# Uso:
#   ./install.sh              installazione interattiva
#   ./install.sh --si         non fa domande, accetta tutto (per automazioni)
#   ./install.sh --senza-ai   installa senza il modello di estrazione
#   ./install.sh --controlla  dice solo cosa manca, senza installare niente

set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$REPO_DIR"

AUTOMATICO=0
SOLO_CONTROLLO=0
CON_AI=""
for argomento in "$@"; do
  case "$argomento" in
    --si|--yes|-y) AUTOMATICO=1 ;;
    --senza-ai)    CON_AI=0 ;;
    --con-ai)      CON_AI=1 ;;
    --controlla|--check) SOLO_CONTROLLO=1 ;;
    -h|--help) sed -n '2,25p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "Opzione non riconosciuta: $argomento (usa --help)" >&2; exit 2 ;;
  esac
done

# ---------------------------------------------------------------- aspetto ---
if [ -t 1 ]; then
  G=$'\e[32m'; R=$'\e[31m'; Y=$'\e[33m'; B=$'\e[1m'; Z=$'\e[0m'
else
  G=""; R=""; Y=""; B=""; Z=""
fi
titolo() { printf '\n%s== %s ==%s\n' "$B" "$1" "$Z"; }
ok()     { printf '  %s✓%s %s\n' "$G" "$Z" "$1"; }
manca()  { printf '  %s•%s %s\n' "$Y" "$Z" "$1"; }
errore() { printf '  %s✗%s %s\n' "$R" "$Z" "$1" >&2; }

chiedi() {  # chiedi "domanda" [s|n predefinito]
  local domanda="$1" predefinito="${2:-s}" risposta
  [ "$AUTOMATICO" = 1 ] && { echo "  $domanda → sì (automatico)"; return 0; }
  local suggerimento="[S/n]"; [ "$predefinito" = "n" ] && suggerimento="[s/N]"
  read -r -p "  $domanda $suggerimento " risposta </dev/tty || risposta=""
  risposta="${risposta:-$predefinito}"
  [[ "$risposta" =~ ^[SsYy] ]]
}

# ------------------------------------------------- già installato? --------
# Chi rilancia l'installatore su una macchina dove NetStock c'è già quasi
# sempre vuole aggiornarlo. Questo script, per costruzione, non aggiorna
# niente: salta tutto ciò che trova a posto, e lascerebbe in esecuzione la
# versione di prima senza dire una parola.
if [ -f "$REPO_DIR/.env" ] && [ "$SOLO_CONTROLLO" = 0 ]; then
  echo
  echo "  Su questa macchina NetStock risulta già installato."
  echo "  Per portarlo alla versione nuova:  ${B}./update.sh${Z}"
  echo "  (scarica gli aggiornamenti, fa il backup, ricostruisce, riavvia e verifica)"
  if ! chiedi "Proseguo comunque con l'installatore?" n; then
    echo "  Va bene: non ho toccato niente."
    exit 0
  fi
fi

# ------------------------------------------------------------------ sudo ---
# Si chiede una volta sola, e solo quando c'è davvero da installare qualcosa.
SUDO=""
prepara_sudo() {
  [ -n "$SUDO" ] && return 0
  if [ "$(id -u)" -eq 0 ]; then SUDO=""; return 0; fi
  command -v sudo >/dev/null || {
    errore "Serve installare dei pacchetti, ma sudo non è disponibile e non sei root."
    errore "Rilancia come root, oppure installa a mano quanto elencato sopra."
    exit 1
  }
  if ! sudo -n true 2>/dev/null; then
    echo
    echo "  Per installare i pacchetti serve la password di amministratore."
    sudo -v || { errore "Password non valida: interrompo."; exit 1; }
  fi
  SUDO="sudo"
  # Tiene viva l'autorizzazione per tutta la durata dello script, così non la
  # richiede di nuovo a metà di un'installazione lunga.
  ( while kill -0 "$$" 2>/dev/null; do sudo -n true 2>/dev/null; sleep 50; done ) &
  SUDO_KEEPALIVE=$!
  trap 'kill "$SUDO_KEEPALIVE" 2>/dev/null || true' EXIT
}

# ------------------------------------------------------------- ricognizione -
titolo "1/6  Che sistema è"

if [ ! -r /etc/os-release ]; then
  errore "Non riesco a riconoscere la distribuzione (manca /etc/os-release)."
  exit 1
fi
# shellcheck disable=SC1091
. /etc/os-release
DISTRO="${ID:-sconosciuta}"
FAMIGLIA="${ID_LIKE:-$DISTRO}"
echo "  ${PRETTY_NAME:-$DISTRO} · $(uname -m)"

case " $DISTRO $FAMIGLIA " in
  *ubuntu*|*debian*) GESTORE="apt" ;;
  *fedora*|*rhel*|*centos*) GESTORE="dnf" ;;
  *) GESTORE="" ;;
esac
if [ -z "$GESTORE" ]; then
  errore "Distribuzione non gestita da questo script: $DISTRO."
  errore "NetStock gira comunque: servono Docker Engine, il plugin Compose,"
  errore "curl, openssl e make. Installali col tuo gestore di pacchetti e"
  errore "lancia ./scripts/bootstrap.sh."
  exit 1
fi
ok "gestore pacchetti: $GESTORE"

RAM_MB=$(free -m | awk '/^Mem:/{print $2}')
DISCO_GB=$(df -BG --output=avail "$REPO_DIR" | tail -1 | tr -dc '0-9')
echo "  RAM ${RAM_MB} MB · spazio libero ${DISCO_GB} GB"
[ "$RAM_MB" -lt 3800 ] && manca "RAM sotto il minimo consigliato (4 GB senza AI, 8+ con AI)"
[ "$DISCO_GB" -lt 15 ] && manca "spazio ridotto: le immagini e il modello occupano una decina di GB"

GPU_PRESENTE=0
if command -v nvidia-smi >/dev/null 2>&1 && nvidia-smi >/dev/null 2>&1; then
  GPU_PRESENTE=1
  ok "GPU NVIDIA: $(nvidia-smi --query-gpu=name --format=csv,noheader | head -1)"
elif [ -e /dev/nvidia0 ] || lspci 2>/dev/null | grep -qi 'vga.*nvidia'; then
  manca "scheda NVIDIA rilevata ma i driver non rispondono: si userà la CPU"
fi

# ------------------------------------------------------------ cosa manca ---
titolo "2/6  Cosa manca"

DA_INSTALLARE=()
serve() {  # serve <comando> <pacchetto> <descrizione>
  if command -v "$1" >/dev/null 2>&1; then ok "$3"; else manca "$3"; DA_INSTALLARE+=("$2"); fi
}
serve curl curl "curl"
serve openssl openssl "openssl (genera segreti e certificato)"
serve make make "make (i comandi abbreviati del progetto)"

DOCKER_DA_INSTALLARE=0
if command -v docker >/dev/null 2>&1; then
  ok "Docker Engine $(docker --version 2>/dev/null | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' | head -1)"
  if docker compose version >/dev/null 2>&1; then
    ok "plugin Docker Compose"
  else
    manca "plugin Docker Compose"
    DOCKER_DA_INSTALLARE=1
  fi
else
  manca "Docker Engine e plugin Compose"
  DOCKER_DA_INSTALLARE=1
fi

TOOLKIT_DA_INSTALLARE=0
if [ "$GPU_PRESENTE" = 1 ]; then
  if docker info 2>/dev/null | grep -q nvidia || [ -f /etc/docker/daemon.json ] && grep -q nvidia /etc/docker/daemon.json 2>/dev/null; then
    ok "runtime NVIDIA per Docker"
  else
    manca "runtime NVIDIA per Docker (senza, l'estrazione gira su CPU)"
    TOOLKIT_DA_INSTALLARE=1
  fi
fi

if [ ${#DA_INSTALLARE[@]} -eq 0 ] && [ "$DOCKER_DA_INSTALLARE" = 0 ] && [ "$TOOLKIT_DA_INSTALLARE" = 0 ]; then
  ok "non manca niente"
fi

if [ "$SOLO_CONTROLLO" = 1 ]; then
  echo
  echo "Controllo soltanto: non ho installato né avviato nulla."
  exit 0
fi

# ------------------------------------------------------------ installazione -
titolo "3/6  Installazione"

aggiorna_indice() {
  if [ "$GESTORE" = apt ]; then $SUDO apt-get update -qq; fi
}

if [ ${#DA_INSTALLARE[@]} -gt 0 ]; then
  echo "  Da installare dai repository della distribuzione: ${DA_INSTALLARE[*]}"
  if chiedi "Procedo?"; then
    prepara_sudo; aggiorna_indice
    case "$GESTORE" in
      apt) $SUDO env DEBIAN_FRONTEND=noninteractive apt-get install -y -qq "${DA_INSTALLARE[@]}" ;;
      dnf) $SUDO dnf install -y -q "${DA_INSTALLARE[@]}" ;;
    esac
    ok "installati: ${DA_INSTALLARE[*]}"
  else
    errore "Senza quei pacchetti non posso proseguire."
    exit 1
  fi
fi

if [ "$DOCKER_DA_INSTALLARE" = 1 ]; then
  echo
  echo "  Docker verrà installato dal repository ufficiale di Docker, con la"
  echo "  sua chiave di firma — non con lo script scaricato da internet."
  if chiedi "Installo Docker Engine e il plugin Compose?"; then
    prepara_sudo
    case "$GESTORE" in
      apt)
        $SUDO install -m 0755 -d /etc/apt/keyrings
        DISTRO_DOCKER="$DISTRO"
        case " $FAMIGLIA " in *ubuntu*) DISTRO_DOCKER="ubuntu" ;; *debian*) [ "$DISTRO" != ubuntu ] && DISTRO_DOCKER="debian" ;; esac
        curl -fsSL "https://download.docker.com/linux/${DISTRO_DOCKER}/gpg" \
          | $SUDO gpg --dearmor -o /etc/apt/keyrings/docker.gpg --yes
        $SUDO chmod a+r /etc/apt/keyrings/docker.gpg
        CODENAME="${VERSION_CODENAME:-${UBUNTU_CODENAME:-}}"
        echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/${DISTRO_DOCKER} ${CODENAME} stable" \
          | $SUDO tee /etc/apt/sources.list.d/docker.list >/dev/null
        $SUDO apt-get update -qq
        $SUDO env DEBIAN_FRONTEND=noninteractive apt-get install -y -qq \
          docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
        ;;
      dnf)
        $SUDO dnf -y -q install dnf-plugins-core
        $SUDO dnf config-manager --add-repo "https://download.docker.com/linux/${DISTRO}/docker-ce.repo" 2>/dev/null \
          || $SUDO dnf config-manager --add-repo "https://download.docker.com/linux/fedora/docker-ce.repo"
        $SUDO dnf install -y -q docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
        ;;
    esac
    $SUDO systemctl enable --now docker
    ok "Docker installato e avviato"
  else
    errore "NetStock gira dentro Docker: senza, non c'è modo di procedere."
    exit 1
  fi
fi

if [ "$TOOLKIT_DA_INSTALLARE" = 1 ]; then
  echo
  echo "  Il runtime NVIDIA permette ai container di usare la GPU. Senza,"
  echo "  l'estrazione funziona lo stesso ma sulla CPU: stesso risultato,"
  echo "  minuti invece di secondi."
  if chiedi "Installo il runtime NVIDIA per Docker?"; then
    prepara_sudo
    case "$GESTORE" in
      apt)
        curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey \
          | $SUDO gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg --yes
        curl -fsSL https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list \
          | sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' \
          | $SUDO tee /etc/apt/sources.list.d/nvidia-container-toolkit.list >/dev/null
        $SUDO apt-get update -qq
        $SUDO env DEBIAN_FRONTEND=noninteractive apt-get install -y -qq nvidia-container-toolkit
        ;;
      dnf)
        curl -fsSL https://nvidia.github.io/libnvidia-container/stable/rpm/nvidia-container-toolkit.repo \
          | $SUDO tee /etc/yum.repos.d/nvidia-container-toolkit.repo >/dev/null
        $SUDO dnf install -y -q nvidia-container-toolkit
        ;;
    esac
    $SUDO nvidia-ctk runtime configure --runtime=docker
    $SUDO systemctl restart docker
    ok "runtime NVIDIA configurato"
  else
    manca "salto la GPU: l'estrazione userà la CPU"
    GPU_PRESENTE=0
  fi
fi

# --------------------------------------------------------- permessi docker -
titolo "4/6  Permessi"

DOCKER_SENZA_SUDO=1
if ! docker info >/dev/null 2>&1; then
  DOCKER_SENZA_SUDO=0
  echo "  Il tuo utente non può ancora parlare con Docker."
  if chiedi "Ti aggiungo al gruppo 'docker'?"; then
    prepara_sudo
    $SUDO usermod -aG docker "$USER"
    ok "aggiunto al gruppo docker"
    # L'appartenenza a un gruppo vale dalla sessione successiva: per il resto
    # di questo script si usa `sg` invece di chiedere di uscire e rientrare.
    if sg docker -c 'docker info' >/dev/null 2>&1; then
      DOCKER_SENZA_SUDO=2
      ok "uso il nuovo gruppo per il resto dell'installazione"
    fi
    echo
    echo "  ${Y}Nota:${Z} nelle prossime sessioni funzionerà da solo. In questa"
    echo "  finestra, se lanci 'docker' a mano, potresti dover fare prima"
    echo "  'newgrp docker' o riaprire il terminale."
  else
    errore "Senza accesso a Docker non posso avviare NetStock."
    exit 1
  fi
else
  ok "accesso a Docker già a posto"
fi

# ------------------------------------------------------------ scelta AI ----
titolo "5/6  Estrazione automatica"

if [ -z "$CON_AI" ]; then
  echo "  NetStock può leggere bolle ed etichette da foto e PDF, con un modello"
  echo "  che gira in locale: nessun dato esce dalla macchina."
  if [ "$GPU_PRESENTE" = 1 ]; then
    echo "  Con la tua GPU una bolla si legge in pochi secondi."
  else
    echo "  Senza GPU funziona lo stesso, ma una bolla richiede qualche minuto"
    echo "  e l'analisi prosegue in sottofondo."
  fi
  echo "  Costo: circa 3 GB di download una tantum."
  if chiedi "La attivo?"; then CON_AI=1; else CON_AI=0; fi
fi

if [ -f .env ]; then
  ATTUALE=$(grep '^EXTRACT_ENABLED=' .env | cut -d= -f2 | tr -d ' ')
  ok ".env già presente: resta com'è (estrazione: ${ATTUALE:-non impostata})"
  # Dirlo, invece di lasciar credere che l'opzione abbia avuto effetto: su una
  # macchina già installata `--senza-ai` non cambia niente, e senza questa riga
  # sembrerebbe che l'abbia fatto.
  if { [ "$CON_AI" = 0 ] && [ "$ATTUALE" = true ]; } || { [ "$CON_AI" = 1 ] && [ "$ATTUALE" = false ]; }; then
    manca "l'opzione che hai passato non è stata applicata: vale solo alla prima"
    manca "installazione. Per cambiarla ora, modifica EXTRACT_ENABLED in .env."
  fi
elif [ "$CON_AI" = 0 ]; then
  ok "estrazione disattivata (si riattiva con EXTRACT_ENABLED=true in .env)"
else
  ok "estrazione attiva: il modello verrà scaricato fra poco"
fi

# ------------------------------------------------------------ avvio -------
titolo "6/6  Configurazione e avvio"

# La preferenza si passa a bootstrap.sh, che è l'unico a creare il `.env` e a
# generarne i segreti. Scriverlo qui significherebbe fargli trovare un file
# già esistente, che lui non sovrascrive: resterebbero le password vuote.
export NETSTOCK_EXTRACT_ENABLED=$([ "$CON_AI" = 0 ] && echo false || echo true)

# L'appartenenza al gruppo docker vale dalla sessione successiva: se è stata
# appena concessa si usa `sg` per il resto, invece di chiedere di riaprire il
# terminale e rilanciare tutto.
if [ "$DOCKER_SENZA_SUDO" = 2 ]; then
  sg docker -c "NETSTOCK_EXTRACT_ENABLED=$NETSTOCK_EXTRACT_ENABLED ./scripts/bootstrap.sh"
else
  ./scripts/bootstrap.sh
fi

# ------------------------------------------------------- backup notturno --
# Chiesto qui e non prima perché ha senso solo su un'installazione che esiste.
# Senza, i backup sono quelli che qualcuno si ricorda di fare, cioè pochi e
# a distanza irregolare.
echo
if [ -d /run/systemd/system ] && ! systemctl is-enabled netstock-backup.timer >/dev/null 2>&1; then
  echo "  Il database può essere copiato ogni notte alle 02:30, da solo."
  if chiedi "Installo il backup automatico?"; then
    prepara_sudo
    ./scripts/install-backup-timer.sh || manca "timer non installato: './scripts/install-backup-timer.sh' quando vuoi"
  else
    manca "backup manuale: ricordati 'make backup', oppure installalo dopo con 'make backup-timer'"
  fi
fi

echo
printf '%s================================================%s\n' "$B" "$Z"
ok "NetStock è installato e in esecuzione."
echo
echo "  Comandi utili:"
echo "    make ps        stato dei servizi"
echo "    make logs      log in tempo reale"
echo "    make down      arresto"
echo "    make backup    copia di sicurezza del database"
echo "    make backup-verify  riapre l'ultimo backup per controllare che torni"
echo
echo "  Se hai appena aggiunto il tuo utente al gruppo docker, riapri il"
echo "  terminale prima di usare 'make' e 'docker' a mano."
