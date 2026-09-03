#!/usr/bin/env bash
# Aggiornamento di un'installazione NetStock già in funzione.
#
# `install.sh` porta la macchina da zero a sistema avviato. Questo script fa
# l'altra metà: porta un sistema avviato alla versione nuova, senza perdere né
# i dati né la configurazione.
#
# Le regole sono quelle dell'installatore, più una:
#
# 1. **Prima il backup.** Un aggiornamento può portare migrazioni di schema, e
#    una migrazione non si annulla desiderandolo. Il dump viene fatto e
#    verificato prima di toccare qualunque cosa; se fallisce, ci si ferma lì.
# 2. **Ogni azione viene annunciata prima**, e si vede cosa cambia — commit,
#    migrazioni, voci nuove in `.env` — prima di dire di sì.
# 3. **Rieseguibile.** Se si interrompe a metà, si rilancia. Se non c'è niente
#    di nuovo, lo dice e non fa niente.
# 4. **La configurazione non si tocca.** `.env` non viene mai sovrascritto: le
#    voci nuove si aggiungono in fondo, quelle esistenti restano come sono.
#
# Uso:
#   ./update.sh                 aggiornamento interattivo
#   ./update.sh --si            non fa domande (per automazioni)
#   ./update.sh --controlla     dice solo cosa cambierebbe, senza toccare niente
#   ./update.sh --senza-backup  salta il dump (sconsigliato: vedi regola 1)
#
# Il backup finisce in /var/backups/netstock. Se lì non si può scrivere:
#   BACKUP_DIR="$HOME/netstock-backup" ./update.sh

set -euo pipefail

# Bash legge lo script un pezzo per volta *mentre* lo esegue. Questo qui
# riscrive i propri stessi file: senza questa copia, dal momento del `git
# merge` in poi il resto verrebbe letto dal file nuovo, a un offset calcolato
# sul vecchio — cioè da metà di una riga qualsiasi.
if [ "${NETSTOCK_UPDATE_COPIA:-}" = 1 ]; then
  REPO_DIR="${NETSTOCK_REPO_DIR:?}"
  trap 'rm -f "$0"' EXIT
else
  REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  COPIA="$(mktemp -t netstock-update.XXXXXX)"
  cat "$0" > "$COPIA"
  chmod +x "$COPIA"
  NETSTOCK_UPDATE_COPIA=1 NETSTOCK_REPO_DIR="$REPO_DIR" exec bash "$COPIA" "$@"
fi
cd "$REPO_DIR"

AUTOMATICO=0
SOLO_CONTROLLO=0
CON_BACKUP=1
for argomento in "$@"; do
  case "$argomento" in
    --si|--yes|-y) AUTOMATICO=1 ;;
    --controlla|--check) SOLO_CONTROLLO=1 ;;
    --senza-backup) CON_BACKUP=0 ;;
    -h|--help) sed -n '2,28p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
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
nota()   { printf '  %s•%s %s\n' "$Y" "$Z" "$1"; }
errore() { printf '  %s✗%s %s\n' "$R" "$Z" "$1" >&2; }

chiedi() {
  local domanda="$1" predefinito="${2:-s}" risposta
  [ "$AUTOMATICO" = 1 ] && { echo "  $domanda → sì (automatico)"; return 0; }
  local suggerimento="[S/n]"; [ "$predefinito" = "n" ] && suggerimento="[s/N]"
  read -r -p "  $domanda $suggerimento " risposta </dev/tty || risposta=""
  risposta="${risposta:-$predefinito}"
  [[ "$risposta" =~ ^[SsYy] ]]
}

# --------------------------------------------------- 1. che cosa c'è qui ---
titolo "1/6  Che installazione è"

if [ ! -f .env ]; then
  errore "Qui non c'è un'installazione da aggiornare: manca il file .env."
  errore "Per installare da zero: ./install.sh"
  exit 1
fi
ok "configurazione presente (.env)"

command -v git >/dev/null || {
  errore "Serve git per sapere cosa c'è di nuovo e per scaricarlo."
  errore "In alternativa, sostituisci i file a mano e lancia"
  errore "'docker compose up -d --build'."
  exit 1
}
git rev-parse --git-dir >/dev/null 2>&1 || {
  errore "Questa cartella non è una copia git del progetto: non posso sapere"
  errore "cosa è cambiato. Aggiorna a mano, oppure reinstalla da un clone."
  exit 1
}

command -v docker >/dev/null && docker compose version >/dev/null 2>&1 || {
  errore "Docker o il plugin Compose non rispondono. Prova ./install.sh --controlla"
  exit 1
}
docker info >/dev/null 2>&1 || {
  errore "Il tuo utente non riesce a parlare con Docker (gruppo 'docker'?)."
  exit 1
}
ok "Docker raggiungibile"

# Le dipendenze di sistema non le installa questo script: quello è il mestiere
# dell'installatore, che sa anche chiedere la password. Qui si guarda soltanto
# se ne manca qualcuna, per non scoprirlo a metà di una ricostruzione.
CONTROLLO="$(./install.sh --controlla 2>&1 || true)"
if printf '%s' "$CONTROLLO" | grep -q 'non manca niente'; then
  ok "dipendenze di sistema a posto"
else
  nota "l'installatore segnala qualcosa sulla macchina:"
  printf '%s\n' "$CONTROLLO" | grep '•' | sed 's/^ */    /' || true
  nota "se la ricostruzione non riesce, lancia prima ./install.sh"
fi

VERSIONE_ORA="$(git rev-parse --short HEAD)"
RAMO="$(git rev-parse --abbrev-ref HEAD)"
echo "  versione installata: $VERSIONE_ORA ($RAMO) del $(git log -1 --format=%cd --date=short)"

# ------------------------------------------------------- 2. cosa cambia ----
titolo "2/6  Cosa cambia"

git remote get-url origin >/dev/null 2>&1 || {
  errore "Nessun repository di origine configurato: non so da dove scaricare."
  exit 1
}
git fetch --quiet origin 2>/dev/null || {
  errore "Non riesco a contattare l'origine. Controlla la rete e riprova."
  exit 1
}

REMOTO="origin/$RAMO"
git rev-parse --verify --quiet "$REMOTO" >/dev/null || {
  errore "Il ramo '$RAMO' non esiste sull'origine: non c'è niente da aggiornare."
  exit 1
}
NUOVI="$(git rev-list --count "HEAD..$REMOTO")"
if [ "$NUOVI" = 0 ]; then
  ok "il codice è già all'ultima versione."
else
  echo "  $NUOVI aggiornamenti disponibili:"
  git log -n 20 --format='    · %s' "HEAD..$REMOTO"
  [ "$NUOVI" -gt 20 ] && echo "    … e altri $((NUOVI - 20))"

  # Le migrazioni sono la parte che non si annulla: vanno dette per nome, prima.
  MIGRAZIONI="$(git diff --name-only --diff-filter=A "HEAD..$REMOTO" -- api/alembic/versions/ || true)"
  if [ -n "$MIGRAZIONI" ]; then
    echo
    nota "l'aggiornamento cambia lo schema del database:"
    printf '%s\n' "$MIGRAZIONI" | sed 's|.*/|    · |'
    nota "per questo il backup del passo 3 non è una formalità."
  fi
fi

# Voci nuove in .env.example: senza, Compose rifiuta di partire con un errore
# che non spiega niente ("variable is not set").
CHIAVI_NUOVE=()
CHIAVI_VUOTE=()
while IFS= read -r grezza; do
  [ -n "$grezza" ] || continue
  riga="$(printf '%s' "$grezza" | sed 's/[[:space:]]*#.*$//')"
  chiave="${riga%%=*}"
  if ! grep -q "^${chiave}=" .env; then
    CHIAVI_NUOVE+=("$riga")
    # Vuota non vuol dire mancante. Alcune voci possono restare vuote per
    # scelta — «non mando i backup da nessuna parte» è una risposta — e
    # bloccare l'aggiornamento per farsele compilare significa pretendere una
    # decisione che l'utente ha già preso. Chi aggiunge la voce lo dichiara
    # in `.env.example`, che è l'unico posto dove sta già scrivendo cosa fa.
    if [ -z "${riga#*=}" ] && ! printf '%s' "$grezza" | grep -qi '#.*facoltativ'; then
      CHIAVI_VUOTE+=("$chiave")
    fi
  fi
done < <(git show "$REMOTO:.env.example" | grep -E '^[A-Z_]+=')
if [ ${#CHIAVI_NUOVE[@]} -gt 0 ]; then
  echo
  nota "la versione nuova aggiunge queste voci di configurazione:"
  printf '    · %s\n' "${CHIAVI_NUOVE[@]}"
  if [ ${#CHIAVI_VUOTE[@]} -gt 0 ]; then
    nota "queste non hanno un valore predefinito e le devi decidere tu:"
    printf '    · %s\n' "${CHIAVI_VUOTE[@]}"
  fi
fi

# Le modifiche locali sono un problema solo se c'è qualcosa da sovrapporre.
SPORCO="$(git status --porcelain --untracked-files=no)"
if [ -n "$SPORCO" ] && [ "$NUOVI" != 0 ]; then
  echo
  errore "Ci sono modifiche locali a file del progetto:"
  printf '%s\n' "$SPORCO" | sed 's/^/    /' >&2
  errore "L'aggiornamento le sovrascriverebbe. Mettile da parte (git stash) o"
  errore "annullale (git checkout -- <file>), poi rilancia."
  exit 1
fi

if [ "$SOLO_CONTROLLO" = 1 ]; then
  echo
  echo "Controllo soltanto: non ho scaricato né riavviato niente."
  exit 0
fi

echo
if [ "$NUOVI" = 0 ]; then
  # Il codice aggiornato non garantisce che *giri* il codice aggiornato: può
  # essere arrivato con un 'git pull' a mano, o l'aggiornamento precedente può
  # essersi interrotto dopo aver scaricato e prima di ricostruire.
  #
  # Le voci nuove di `.env`, però, sono da aggiungere comunque: senza,
  # Compose si ferma su «variable is not set», e dire «niente da fare» dopo
  # averle appena elencate è una bugia a due righe di distanza. È il caso di
  # un aggiornamento arrivato per un'altra strada, che è precisamente quello
  # che questo ramo esiste per riconoscere.
  if [ "$AUTOMATICO" = 1 ] && [ ${#CHIAVI_NUOVE[@]} -eq 0 ]; then
    ok "niente da fare."
    exit 0
  fi
  if [ "$AUTOMATICO" != 1 ]; then
    chiedi "Ricostruisco e riavvio lo stesso, per essere sicuri che giri questa versione?" n \
      || { echo "  Va bene: non ho toccato niente."; exit 0; }
  fi
else
  chiedi "Procedo con l'aggiornamento?" || { echo "  Annullato."; exit 0; }
fi

# ------------------------------------------------------- 3. backup ---------
titolo "3/6  Backup"

DUMP=""
if [ "$CON_BACKUP" = 1 ]; then
  # Il dump si prende dal database in esecuzione: se è fermo, lo si accende
  # solo per questo. `up -d` su un servizio già acceso non fa nulla.
  docker compose up -d db >/dev/null
  until docker compose ps db | grep -q healthy; do sleep 2; done
  if ! ESITO="$(./scripts/backup.sh 2>&1)"; then
    printf '%s\n' "$ESITO" | sed 's/^/    /' >&2
    errore "Il backup non è riuscito, quindi mi fermo prima di cambiare qualcosa."
    errore "Se è un problema di permessi sulla cartella, indica dove scriverlo:"
    errore "    BACKUP_DIR=\"\$HOME/netstock-backup\" ./update.sh"
    exit 1
  fi
  printf '%s\n' "$ESITO" | sed 's/^/  /'
  DUMP="$(printf '%s\n' "$ESITO" | sed -n 's/^Backup completato: //p')"
  ok "copia di sicurezza verificata"
else
  nota "backup saltato su tua richiesta: se una migrazione va male, non c'è ritorno."
fi

# ------------------------------------------------------- 4. codice ---------
titolo "4/6  Codice"

if [ "$NUOVI" = 0 ]; then
  ok "niente da scaricare: il codice è già quello giusto"
else
  git merge --ff-only "$REMOTO" >/dev/null || {
    errore "Il ramo locale è divergente da quello di origine: non posso avanzare"
    errore "senza fondere due storie. Risolvi a mano con git, poi rilancia."
    exit 1
  }
fi
VERSIONE_NUOVA="$(git rev-parse --short HEAD)"
[ "$VERSIONE_NUOVA" != "$VERSIONE_ORA" ] && ok "codice aggiornato: $VERSIONE_ORA → $VERSIONE_NUOVA"

if [ ${#CHIAVI_NUOVE[@]} -gt 0 ]; then
  {
    echo ""
    echo "# Aggiunte dall'aggiornamento del $(date +%Y-%m-%d) ($VERSIONE_ORA → $VERSIONE_NUOVA)"
    printf '%s\n' "${CHIAVI_NUOVE[@]}"
  } >> .env
  ok "aggiunte a .env ${#CHIAVI_NUOVE[@]} voci nuove (le tue restano invariate)"
  if [ ${#CHIAVI_VUOTE[@]} -gt 0 ]; then
    errore "Queste sono state aggiunte vuote e vanno compilate prima di ripartire:"
    printf '    · %s\n' "${CHIAVI_VUOTE[@]}" >&2
    errore "Modifica .env e rilancia ./update.sh (il codice è già aggiornato)."
    exit 1
  fi
fi

# ------------------------------------------------------- 5. riavvio --------
titolo "5/6  Ricostruzione e riavvio"

# Stesse regole di bootstrap.sh: la GPU si usa se c'è, e Ollama parte solo se
# l'estrazione è accesa in *questa* installazione.
COMPOSE_FILES=(-f docker-compose.yml)
if nvidia-smi >/dev/null 2>&1; then
  ok "GPU rilevata: l'estrazione la userà"
  COMPOSE_FILES+=(-f docker-compose.gpu.yml)
fi
PROFILI=()
grep -q "^EXTRACT_ENABLED=true" .env && PROFILI=(--profile ai)

echo "  Ricostruzione delle immagini (qualche minuto)…"
docker compose "${COMPOSE_FILES[@]}" "${PROFILI[@]}" build

# L'API esegue `alembic upgrade head` all'avvio: le migrazioni partono qui, con
# l'immagine nuova — l'unica che le contiene. Per questo non si aggiorna lo
# schema prima di aver ricostruito.
echo "  Riavvio dei servizi…"
docker compose "${COMPOSE_FILES[@]}" "${PROFILI[@]}" up -d

# ------------------------------------------------------- 6. verifica -------
titolo "6/6  Verifica"

# `/health` è l'unico endpoint pubblico (§885 della specifica): `/health/ready`
# vuole una sessione, e da qui risponderebbe sempre 401. Non è una perdita:
# l'immagine avvia uvicorn solo dopo `alembic upgrade head`, quindi un 200 su
# /health dice già che le migrazioni sono passate e l'app è salita.
PRONTO=0
for _ in $(seq 1 60); do
  if docker compose exec -T api python -c \
      "import urllib.request;urllib.request.urlopen('http://localhost:8000/health')" >/dev/null 2>&1; then
    PRONTO=1; break
  fi
  sleep 2
done

if [ "$PRONTO" != 1 ]; then
  errore "L'API non risponde dopo due minuti. Ultime righe di log:"
  docker compose logs --tail=40 api 2>&1 | sed 's/^/    /' >&2
  echo >&2
  errore "Per tornare alla versione di prima:"
  echo "    git checkout $VERSIONE_ORA && docker compose up -d --build" >&2
  if [ -n "$DUMP" ]; then
    echo "    ./scripts/restore.sh '$DUMP'   # solo se anche i dati sono compromessi" >&2
  fi
  exit 1
fi
ok "API avviata (e quindi migrazioni passate: senza, non partirebbe)"

# Che l'API risponda non dice niente di chi le sta davanti: il browser passa da
# Caddy e dai file serviti da web, e un container fermo lì si vedrebbe solo
# aprendo il sito.
GUASTI=()
for servizio in db api web caddy; do
  contenitore="$(docker compose ps -q "$servizio" 2>/dev/null || true)"
  if [ -z "$contenitore" ] || [ "$(docker inspect -f '{{.State.Running}}' "$contenitore" 2>/dev/null)" != true ]; then
    GUASTI+=("$servizio")
  fi
done
if [ ${#GUASTI[@]} -gt 0 ]; then
  errore "Questi servizi non sono in esecuzione: ${GUASTI[*]}"
  docker compose logs --tail=20 "${GUASTI[@]}" 2>&1 | sed 's/^/    /' >&2
  errore "Per tornare alla versione di prima:"
  echo "    git checkout $VERSIONE_ORA && docker compose up -d --build" >&2
  exit 1
fi
ok "servizi in esecuzione: db, api, web, caddy"

REVISIONE="$(docker compose exec -T api alembic current 2>/dev/null || true)"
REVISIONE="$(printf '%s' "$REVISIONE" | grep -oE '^[0-9a-f]+' || true)"
ATTESA="$(docker compose exec -T api alembic heads 2>/dev/null || true)"
ATTESA="$(printf '%s' "$ATTESA" | grep -oE '^[0-9a-f]+' || true)"
if [ -n "$REVISIONE" ] && [ "$REVISIONE" = "$ATTESA" ]; then
  ok "schema del database alla revisione $REVISIONE (l'ultima)"
elif [ -n "$REVISIONE" ]; then
  nota "schema alla revisione $REVISIONE, ma l'ultima è $ATTESA: controlla i log di api"
fi

# Su un'installazione che esisteva già, il backup automatico non c'è: è
# arrivato dopo. Non lo si installa di nascosto — chiede sudo — ma nemmeno si
# tace, perché è la differenza fra avere copie e ricordarsi di farle.
if [ -d /run/systemd/system ] && ! systemctl is-enabled netstock-backup.timer >/dev/null 2>&1; then
  nota "il backup notturno non è installato: 'make backup-timer' lo attiva."
fi

SITE_ADDRESS="$(grep '^SITE_ADDRESS=' .env | cut -d= -f2)"
echo
printf '%s================================================%s\n' "$B" "$Z"
if [ "$VERSIONE_NUOVA" = "$VERSIONE_ORA" ]; then
  ok "NetStock ricostruito e riavviato sulla versione $VERSIONE_ORA"
else
  ok "NetStock aggiornato: $VERSIONE_ORA → $VERSIONE_NUOVA"
fi
echo "  https://${SITE_ADDRESS}"
[ -n "$DUMP" ] && echo "  Backup di prima dell'aggiornamento: $DUMP"
if [ "$VERSIONE_NUOVA" != "$VERSIONE_ORA" ]; then
  echo
  echo "  Cosa è cambiato:"
  git log -n 10 --format='    · %s' "$VERSIONE_ORA..HEAD"
fi
echo
