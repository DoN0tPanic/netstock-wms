#!/usr/bin/env bash
# Disinstalla NetStock da questa macchina.
#
# È lo script più pericoloso del progetto, e la sua forma segue da lì.
#
# **Non tocca i dati se non glielo si chiede per nome.** Senza opzioni ferma e
# rimuove i container e le immagini: l'applicazione sparisce, il magazzino
# resta nel volume e basta un `./install.sh` per ritrovarlo com'era. Cancellare
# il database è un'altra cosa, si chiede con `--dati`, e prima si scrive una
# parola per esteso.
#
# **Prima di cancellare fa una copia**, e la mette dove nessuna delle
# operazioni successive la può toccare. Un disinstallatore che non lascia
# niente dietro è comodo per la macchina e pessimo per chi, tre giorni dopo,
# si accorge che quella bolla serviva.
#
# Uso:
#   ./uninstall.sh                 ferma e rimuove container e immagini
#   ./uninstall.sh --controlla     dice cosa toglierebbe, senza toccare niente
#   ./uninstall.sh --dati          rimuove anche il database (chiede conferma)
#   ./uninstall.sh --tutto         database, backup, .env, certificati, timer
#   ./uninstall.sh --senza-backup  salta la copia finale (sconsigliato)
set -uo pipefail
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$REPO_DIR"

CON_DATI=0
CON_TUTTO=0
SOLO_CONTROLLO=0
CON_BACKUP=1
AUTOMATICO=0
CONFERMA_RICHIESTA="CANCELLA I DATI"

for argomento in "$@"; do
  case "$argomento" in
    --dati) CON_DATI=1 ;;
    --tutto|--all) CON_DATI=1; CON_TUTTO=1 ;;
    --controlla|--check) SOLO_CONTROLLO=1 ;;
    --senza-backup) CON_BACKUP=0 ;;
    --si|--yes|-y) AUTOMATICO=1 ;;
    -h|--help) sed -n '2,26p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "Opzione non riconosciuta: $argomento (usa --help)" >&2; exit 2 ;;
  esac
done

if [ -t 1 ]; then
  G=$'\e[32m'; R=$'\e[31m'; Y=$'\e[33m'; B=$'\e[1m'; Z=$'\e[0m'
else
  G=""; R=""; Y=""; B=""; Z=""
fi
titolo() { printf '\n%s== %s ==%s\n' "$B" "$1" "$Z"; }
ok()     { printf '  %s✓%s %s\n' "$G" "$Z" "$1"; }
nota()   { printf '  %s•%s %s\n' "$Y" "$Z" "$1"; }
errore() { printf '  %s✗%s %s\n' "$R" "$Z" "$1" >&2; }

c_e_terminale() { ( exec </dev/tty ) 2>/dev/null; }

chiedi() {
  local domanda="$1" predefinito="${2:-s}" risposta
  [ "$AUTOMATICO" = 1 ] && { echo "  $domanda → sì (automatico)"; return 0; }
  # Senza terminale vale il valore predefinito, in silenzio: il messaggio di
  # errore della shell su `/dev/tty` non aiuta nessuno.
  if ! c_e_terminale; then
    echo "  $domanda → $predefinito (nessun terminale)"
    [[ "$predefinito" =~ ^[Ss] ]] && return 0 || return 1
  fi
  local suggerimento="[S/n]"; [ "$predefinito" = "n" ] && suggerimento="[s/N]"
  read -r -p "  $domanda $suggerimento " risposta </dev/tty || risposta=""
  risposta="${risposta:-$predefinito}"
  [[ "$risposta" =~ ^[SsYy] ]]
}

peso_volume() { docker system df -v 2>/dev/null | awk -v v="$1" '$1==v {print $3}'; }

# ------------------------------------------------------- 1. cosa c'è qui ---
titolo "1/4  Cosa c'è da rimuovere"

if [ ! -f docker-compose.yml ]; then
  errore "Non sembra la cartella di NetStock: manca docker-compose.yml."
  exit 1
fi
if ! docker info >/dev/null 2>&1; then
  errore "Docker non risponde: senza non posso rimuovere niente."
  exit 1
fi

# Il nome del progetto Compose decide come si chiamano i volumi. Sta nel file
# (`name:`) e in mancanza è il nome della cartella — le stesse regole che usa
# Compose. Scrivere `netstock_` a mano qui vorrebbe dire rimuovere i volumi
# sbagliati, o nessuno, su un'installazione rinominata.
PROGETTO="$(sed -n 's/^name:[[:space:]]*//p' docker-compose.yml | head -1)"
PROGETTO="${PROGETTO:-$(basename "$REPO_DIR")}"

SERVIZI=$(docker compose ps --format '{{.Service}}' 2>/dev/null | wc -l)
# L'unione di due criteri, e non uno solo: l'etichetta di Compose trova i
# volumi che ha creato lui, il prefisso del nome trova quelli nati altrove —
# `ollama_models` su questa macchina non ha l'etichetta, e cercandola soltanto
# l'elenco dimenticava cinque gigabyte. In un disinstallatore, dimenticare è
# il difetto peggiore: chi legge decide su quello che vede.
VOLUMI=$( {
  docker volume ls --format '{{.Name}}' --filter "label=com.docker.compose.project=$PROGETTO"
  docker volume ls --format '{{.Name}}' | grep "^${PROGETTO}_" || true
} | sort -u )
IMMAGINI=$(docker images --format '{{.Repository}}:{{.Tag}}' \
  | grep -E "^${PROGETTO}-(api|web):" || true)

ok "progetto Compose: $PROGETTO · servizi in esecuzione: $SERVIZI"
if [ -n "$VOLUMI" ]; then
  echo "  volumi con i dati:"
  while IFS= read -r volume; do
    printf '    %-28s %s\n' "$volume" "$(peso_volume "$volume")"
  done <<< "$VOLUMI"
fi
[ -n "$IMMAGINI" ] && echo "  immagini costruite qui: $(echo "$IMMAGINI" | tr '\n' ' ')"

# Quanto magazzino c'è dentro: un numero che deve stare davanti agli occhi di
# chi sta per cancellarlo.
if [ "$SERVIZI" -gt 0 ] && docker compose ps db 2>/dev/null | grep -q healthy; then
  CONTENUTO=$(docker compose exec -T db psql -U "${POSTGRES_USER:-netstock}" -d "${POSTGRES_DB:-netstock}" -Atc "
    SELECT (SELECT count(*) FROM stock_units) || ' unità, ' ||
           (SELECT count(*) FROM stock_movements) || ' movimenti, ' ||
           (SELECT count(*) FROM delivery_notes) || ' bolle, ' ||
           (SELECT count(*) FROM documents) || ' documenti archiviati'" 2>/dev/null)
  [ -n "$CONTENUTO" ] && nota "nel database: $CONTENUTO"
fi

if [ -d /var/backups/netstock ]; then
  nota "copie di sicurezza sul disco: $(du -sh /var/backups/netstock 2>/dev/null | cut -f1) in /var/backups/netstock"
fi
if systemctl list-unit-files netstock-backup.timer >/dev/null 2>&1 &&
   systemctl is-enabled netstock-backup.timer >/dev/null 2>&1; then
  nota "timer del backup notturno: attivo"
fi

echo
if [ "$CON_DATI" = 0 ]; then
  ok "modalità: rimuovo l'applicazione, i dati restano"
  echo "    Il magazzino resta nel volume: ./install.sh lo ritrova com'era."
  echo "    Per cancellare anche quello: ./uninstall.sh --dati"
elif [ "$CON_TUTTO" = 1 ]; then
  errore "modalità: rimuovo TUTTO — database, copie di sicurezza, configurazione, certificati, timer"
else
  errore "modalità: rimuovo l'applicazione E il database"
fi

if [ "$SOLO_CONTROLLO" = 1 ]; then
  echo
  echo "Controllo soltanto: non ho toccato niente."
  exit 0
fi

# ------------------------------------------------------- 2. la copia ------
titolo "2/4  Copia di sicurezza"

DUMP=""
if [ "$CON_DATI" = 1 ] && [ "$CON_BACKUP" = 1 ]; then
  # Fuori dal repository e fuori da /var/backups: sono i due posti che i passi
  # successivi possono cancellare. La copia deve sopravvivere alla
  # disinstallazione, o non è una copia.
  DESTINAZIONE="${NETSTOCK_ARCHIVIO:-$HOME/netstock-archivio}"
  mkdir -p "$DESTINAZIONE"
  DUMP="$DESTINAZIONE/netstock-prima-della-disinstallazione-$(date +%Y%m%d-%H%M%S).dump"
  echo "  Copio il database in $DUMP"
  if docker compose exec -T db pg_dump -Fc -U "${POSTGRES_USER:-netstock}" \
       "${POSTGRES_DB:-netstock}" > "$DUMP" 2>/dev/null && [ -s "$DUMP" ]; then
    if docker compose exec -T db pg_restore --list < "$DUMP" >/dev/null 2>&1; then
      ok "copia verificata: $(du -h "$DUMP" | cut -f1)"
    else
      errore "La copia è stata scritta ma non si rilegge: mi fermo."
      errore "Rimuovi --senza-backup solo se sai di non volere i dati."
      exit 1
    fi
  else
    rm -f "$DUMP"; DUMP=""
    errore "Non sono riuscito a copiare il database (è acceso?)."
    if ! chiedi "Proseguo comunque, cancellando i dati senza copia?" n; then
      echo "  Va bene: non ho toccato niente."
      exit 1
    fi
  fi
elif [ "$CON_DATI" = 1 ]; then
  nota "copia saltata su tua richiesta: quello che c'è nel database sparisce e basta"
else
  ok "non serve: i dati restano dove sono"
fi

# ------------------------------------------------------- 3. conferma ------
if [ "$CON_DATI" = 1 ]; then
  titolo "3/4  Conferma"
  echo "  Stai per cancellare il database di NetStock."
  [ -n "$CONTENUTO" ] && echo "  Contiene: $CONTENUTO"
  [ -n "$DUMP" ] && echo "  La copia appena fatta resta in: $DUMP"
  echo "  Il registro dei movimenti è append-only e non si ricostruisce: senza"
  echo "  quella copia, quello che c'è dentro non torna."
  echo
  if [ "$AUTOMATICO" != 1 ]; then
    # Senza terminale non si può chiedere, e chiedere a vuoto qui vorrebbe
    # dire cancellare un database perché nessuno ha risposto. Chi lo lancia da
    # uno script lo dichiara con --si.
    # Non basta che `/dev/tty` esista: il nodo c'è sempre, ed è l'apertura a
    # fallire quando manca un terminale di controllo. Si prova ad aprirlo.
    if ! ( exec </dev/tty ) 2>/dev/null; then
      errore "Non c'è un terminale per chiedere conferma: non cancello niente."
      errore "Da uno script, dichiara l'intenzione con --si."
      exit 1
    fi
    read -r -p "  Scrivi «$CONFERMA_RICHIESTA» per procedere: " risposta </dev/tty || risposta=""
    if [ "$risposta" != "$CONFERMA_RICHIESTA" ]; then
      echo "  Non corrisponde: non ho toccato niente."
      exit 1
    fi
  else
    nota "conferma saltata (--si)"
  fi
else
  titolo "3/4  Conferma"
  if ! chiedi "Fermo e rimuovo i container di NetStock?"; then
    echo "  Va bene: non ho toccato niente."
    exit 0
  fi
fi

# ------------------------------------------------------- 4. rimozione -----
titolo "4/4  Rimozione"

if [ "$CON_DATI" = 1 ]; then
  docker compose down --volumes --remove-orphans >/dev/null 2>&1
  ok "container e volumi rimossi (database compreso)"
else
  docker compose down --remove-orphans >/dev/null 2>&1
  ok "container rimossi, volumi lasciati dove sono"
fi

if [ -n "$IMMAGINI" ]; then
  # Solo le immagini costruite qui: `ollama/ollama` e `postgres` arrivano da
  # internet e possono servire ad altro sulla stessa macchina.
  echo "$IMMAGINI" | xargs -r docker rmi >/dev/null 2>&1
  ok "immagini di NetStock rimosse (postgres e ollama restano: non sono nostre)"
fi

if [ "$CON_TUTTO" = 1 ]; then
  if systemctl list-unit-files netstock-backup.timer >/dev/null 2>&1; then
    if [ "$(id -u)" -eq 0 ] || sudo -n true 2>/dev/null || chiedi "Rimuovo il timer del backup (serve sudo)?"; then
      ./scripts/install-backup-timer.sh --disinstalla >/dev/null 2>&1 && ok "timer del backup rimosso"
    fi
  fi
  if [ -d /var/backups/netstock ]; then
    if chiedi "Cancello anche le copie di sicurezza in /var/backups/netstock?" n; then
      sudo rm -rf /var/backups/netstock && ok "copie di sicurezza rimosse"
    else
      nota "copie di sicurezza lasciate in /var/backups/netstock"
    fi
  fi
  rm -f .env && ok "configurazione (.env) rimossa"
  rm -rf certs && ok "certificati rimossi"
fi

echo
printf '%s================================================%s\n' "$B" "$Z"
ok "NetStock rimosso da questa macchina."
if [ "$CON_DATI" = 0 ]; then
  echo "  I dati sono ancora nei volumi: ./install.sh li ritrova com'erano."
  echo "  Per toglierli davvero: ./uninstall.sh --dati"
fi
[ -n "$DUMP" ] && echo "  Copia del database: $DUMP"
if [ "$CON_TUTTO" = 1 ]; then
  echo "  Resta solo questa cartella, che puoi cancellare a mano:"
  echo "    rm -rf $REPO_DIR"
  echo "  (non la cancello io: ci sto girando dentro)"
fi
echo
