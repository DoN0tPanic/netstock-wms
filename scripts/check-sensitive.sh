#!/usr/bin/env bash
# Cerca dati sensibili in ciò che finirebbe pubblicato.
#
# Esiste perché è già successo: i dati di un documento reale, tolti una prima
# volta, sono rientrati scrivendo i test di regressione dei giri successivi — un
# seriale vero copiato dentro un caso di prova sembra innocuo mentre lo si
# scrive. Un controllo che gira in pochi secondi è l'unico modo per non
# doversene ricordare.
#
# Guarda tre cose, e le guarda sia nella copia di lavoro sia in **tutti** i
# commit: i modelli generici qui sotto, i seriali di apparato (segnalati per
# forma, e ammessi solo se dichiarati) e i formati di file che in un
# repository di codice non hanno motivo di esistere — fra cui i documenti
# scansionati, che essendo binari nessun modello può leggere.
#
# I modelli qui dentro sono **generici**: non nominano nessuno. Le ragioni
# sociali e i codici dei documenti reali su cui è stato tarato il progetto
# stanno in `.sensitive-patterns`, che è escluso da git — un controllo che
# elenca i nomi che cerca li pubblicherebbe lui stesso, ed è esattamente
# l'errore che questo file ha commesso alla prima stesura.
#
# Formato di `.sensitive-patterns`: un'espressione regolare per riga, righe
# vuote e commenti (#) ignorati.
#
# Uso:  ./scripts/check-sensitive.sh        (esce 1 se trova qualcosa)
set -uo pipefail
cd "$(dirname "$0")/.."

# Il controllo esclude sé stesso: contiene per forza i modelli che cerca.
mapfile -t FILES < <(git ls-files --cached --others --exclude-standard | grep -v '^scripts/check-sensitive.sh$')
[ ${#FILES[@]} -eq 0 ] && { echo "Nessun file da controllare."; exit 0; }

AMMESSI="compliance/allowed-secrets.txt"

trovato=0
controlla() {
  local etichetta="$1" pattern="$2"
  local esito
  # I file di test NON sono esenti da nulla. Erano esclusi dal controllo
  # password perché le loro credenziali sono inventate — ma i test sono
  # precisamente il posto dove un dato reale era già rientrato una volta,
  # copiato dentro un caso di prova mentre lo si scriveva. Meglio qualche
  # falso positivo su una password finta che nessun allarme su una vera.
  # Le righe che contengono un valore già esaminato (compliance/allowed-secrets.txt)
  # non vengono segnalate: è quello che permette di NON esentare intere cartelle.
  local righe
  righe=$(grep -niE "$pattern" "${FILES[@]}" 2>/dev/null || true)
  [ -f "$AMMESSI" ] && righe=$(echo "$righe" | grep -vFf <(grep -vE '^\s*(#|$)' "$AMMESSI") || true)
  if [ -n "$righe" ]; then
    trovato=1
    echo "TROVATO — $etichetta:"
    echo "$righe" | cut -d: -f1 | sort -u | sed 's/^/   /'
    echo "$righe" | head -4 | sed 's/^/      /'
  fi
}

# --- Modelli generici, validi per qualunque progetto ---------------------
# Dichiarati una volta sola: gli stessi modelli valgono per i file di adesso e
# per tutti i commit passati. Prima la storia ne guardava quattro su dodici, e
# un hostname interno o una stringa di connessione tolti dalla copia di lavoro
# restavano invisibili nel commit che li aveva introdotti.
ETICHETTE=(); MODELLI=()
modello() { ETICHETTE+=("$1"); MODELLI+=("$2"); }

# Le classi POSIX ([[:space:]]) e non `\s`: `git grep -E` non conosce la
# scorciatoia GNU, e i modelli che la usavano erano più deboli sulla storia
# che sui file — dove invece li applica GNU grep, che la conosce.
modello "chiavi private" 'BEGIN [A-Z ]*PRIVATE KEY'
# Solo valori letterali fra virgolette e abbastanza lunghi: `password=password`
# è codice, non un segreto.
modello "password in chiaro" '(password|secret|token|api[_-]?key)["'\'']?[[:space:]]*[:=][[:space:]]*["'\''][A-Za-z0-9!@#$%^&*_+-]{12,}["'\'']'
modello "indirizzi IP privati" '\b(192\.168|10\.[0-9]{1,3}|172\.(1[6-9]|2[0-9]|3[01]))\.[0-9]{1,3}\.[0-9]{1,3}\b'
# `netstock.local` nei file di esempio è un segnaposto: si cercano solo i
# suffissi che indicano una rete davvero esistente.
modello "hostname interni" '[a-z0-9-]+\.(lab|lan|internal|intranet)\.[a-z]{2,}\b'
modello "percorsi personali" '/home/[a-z]+/|/Users/[a-z]+/'
# Formati di credenziale riconoscibili a vista: qui un riscontro è quasi sempre
# un segreto vero, non un falso positivo.
modello "token GitHub" '\b(ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{30,}|\bgithub_pat_[A-Za-z0-9_]{20,}'
modello "chiavi AWS" '\bAKIA[0-9A-Z]{16}\b|aws_secret_access_key'
modello "token generici (JWT, Bearer)" '\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}|Authorization:[[:space:]]*Bearer[[:space:]]+[A-Za-z0-9._-]{16,}'
modello "stringhe di connessione con credenziali" '(postgres(ql)?|mysql|mongodb(\+srv)?|redis|amqp)://[^:/@[:space:]]+:[^@/[:space:]]+@'
modello "chiavi Slack e simili" '\bxox[baprs]-[A-Za-z0-9-]{10,}|\bsk-[A-Za-z0-9]{20,}'
modello "MAC address" '\b([0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}\b'
modello "partite IVA e codici fiscali" '\b(IT)?[0-9]{11}\b|\b[A-Z]{6}[0-9]{2}[A-Z][0-9]{2}[A-Z][0-9]{3}[A-Z]\b'

for i in "${!MODELLI[@]}"; do
  controlla "${ETICHETTE[$i]}" "${MODELLI[$i]}"
done

# --- Seriali di apparato -------------------------------------------------
# È il dato per cui questo controllo esiste, ed è il più difficile da
# riconoscere rileggendo un diff: un seriale ha la forma di un codice
# qualunque, e dentro un caso di prova sembra un valore di comodo. Un modello
# che distingua i veri dai finti non può esistere — hanno la stessa forma —
# quindi qui si ragiona al contrario: si estrae ogni token con la forma di un
# seriale e si segnala tutto ciò che **non è dichiarato** in
# compliance/allowed-secrets.txt. Un seriale nuovo suona l'allarme anche se
# somiglia in tutto a quelli già presenti.
SERIALI='\b[A-Z]{2,4}[0-9]{4,5}[A-Z0-9]{3,5}\b|\bQ2[A-Z0-9]{2}-[A-Z0-9]{4}-[A-Z0-9]{4}\b'

# Sull'elenco dei valori esaminati si filtra per riga intera: un seriale è un
# token, non un frammento di riga come le password ammesse.
dichiarati() {
  if [ -f "$AMMESSI" ]; then
    grep -vxFf <(grep -vE '^\s*(#|$)' "$AMMESSI") || true
  else
    cat
  fi
}

seriali_nei_file() {
  local nuovi
  nuovi=$(grep -ohE "$SERIALI" "${FILES[@]}" 2>/dev/null | sort -u | dichiarati)
  [ -z "$nuovi" ] && return
  trovato=1
  echo "TROVATO — seriali non dichiarati:"
  while IFS= read -r seriale; do
    [ -z "$seriale" ] && continue
    echo "   $seriale — $(grep -lF "$seriale" "${FILES[@]}" 2>/dev/null | head -3 | tr '\n' ' ')"
  done <<< "$nuovi"
  echo "      Se è inventato, dichiaralo in $AMMESSI; se viene da un documento"
  echo "      vero, non deve stare qui."
}
seriali_nei_file

# Formati che non appartengono a un repository di codice: materiale
# crittografico, dump, esportazioni, catture di rete, stato dell'infrastruttura.
# I documenti scansionati — PDF, foto delle bolle, HEIC dai telefoni — sono qui
# per una ragione in più: sono **binari**, e tutti i modelli di sopra li
# attraversano senza vedere niente. Una bolla vera in PDF passerebbe ogni altro
# controllo di questo file.
# `compliance/licenses.csv` è un inventario generato da `make licenses`, non
# un'esportazione di dati: l'eccezione vale per quel file, non per i CSV.
FORMATI_VIETATI='\.(pem|key|p12|pfx|jks|ovpn|pcapng?|sql|dump|bak|xlsx?|csv|kubeconfig|tfstate|pdf|png|jpe?g|heic|heif|tiff?|webp|avif|gif|bmp|docx?|odt|ods|eml|msg|zip|7z|rar)$'
FILE_VIETATI=$(printf '%s\n' "${FILES[@]}" \
  | grep -iE "$FORMATI_VIETATI" \
  | grep -v '^compliance/licenses\.csv$' || true)

if [ -n "$FILE_VIETATI" ]; then
  trovato=1
  echo "TROVATO — file di formato non ammesso:"
  echo "$FILE_VIETATI" | sed 's/^/   /'
fi

# --- Modelli specifici di questa installazione, se presenti --------------
ELENCO=".sensitive-patterns"
if [ -f "$ELENCO" ]; then
  n=0
  while IFS= read -r riga; do
    [[ -z "${riga// }" || "$riga" == \#* ]] && continue
    n=$((n + 1))
    controlla "dati riservati locali (riga $n di $ELENCO)" "$riga"
  done < "$ELENCO"
  echo "Controllati anche $n modelli da $ELENCO."
else
  echo "Nota: $ELENCO non presente — controllati solo i modelli generici."
  echo "      Mettici ragioni sociali e codici dei documenti reali, una regex per riga."
fi

# La copia di lavoro pulita non basta: un file cancellato oggi resta nei commit
# di ieri, ed è da lì che si recupera. Se c'è una storia, la si guarda tutta.
if git rev-parse --verify HEAD >/dev/null 2>&1; then
  echo
  echo "Controllo anche la storia dei commit…"
  STORIA=0
  # Ogni commit, non ogni file: lo stesso blob viene riletto una volta per
  # commit che lo contiene, ed è lo spreco che paga la garanzia — non sfugge
  # niente, nemmeno un contenuto arrivato da un ramo unito. Con la storia di
  # questo progetto sono pochi secondi; se un giorno diventassero minuti, la
  # via è `git log -p --all` scritto una volta su file e riletto, non meno
  # modelli.
  COMMIT=$(git rev-list --all)
  # `git grep` su più revisioni stampa `commit:file:riga:contenuto`.
  storia() {
    local etichetta="$1" pattern="$2" righe
    righe=$(git grep -I -inE "$pattern" $COMMIT -- ':!scripts/check-sensitive.sh' 2>/dev/null || true)
    [ -f "$AMMESSI" ] && righe=$(echo "$righe" | grep -vFf <(grep -vE '^\s*(#|$)' "$AMMESSI") || true)
    if [ -n "$righe" ]; then
      trovato=1; STORIA=1
      echo "TROVATO in un commit passato — $etichetta:"
      echo "$righe" | cut -d: -f1,2 | sort -u | head -3 | sed 's/^/   /'
    fi
  }
  for i in "${!MODELLI[@]}"; do
    storia "${ETICHETTE[$i]}" "${MODELLI[$i]}"
  done

  # Un seriale tolto ieri resta nel commit di ieri, ed è da lì che si recupera.
  NUOVI=$(git grep -ohE "$SERIALI" $COMMIT -- ':!scripts/check-sensitive.sh' 2>/dev/null | sort -u | dichiarati)
  if [ -n "$NUOVI" ]; then
    trovato=1; STORIA=1
    echo "TROVATO in un commit passato — seriali non dichiarati:"
    echo "$NUOVI" | head -5 | sed 's/^/   /'
  fi

  # Un PDF aggiunto e cancellato subito dopo resta nel pacchetto: qui contano i
  # nomi che sono *esistiti*, non quelli che esistono adesso.
  BINARI=$(git log --all --pretty=format: --name-only | sort -u \
    | grep -iE "$FORMATI_VIETATI" | grep -v '^compliance/licenses\.csv$' || true)
  if [ -n "$BINARI" ]; then
    trovato=1; STORIA=1
    echo "TROVATO in un commit passato — file di formato non ammesso:"
    echo "$BINARI" | sed 's/^/   /'
  fi

  if [ -f "$ELENCO" ]; then
    while IFS= read -r riga; do
      [[ -z "${riga// }" || "$riga" == \#* ]] && continue
      if git grep -I -q -iE "$riga" $COMMIT -- ':!scripts/check-sensitive.sh' 2>/dev/null; then
        trovato=1; STORIA=1
        echo "TROVATO in un commit passato (modello locale): $riga"
      fi
    done < "$ELENCO"
  fi
  [ "$STORIA" -eq 0 ] && echo "  storia pulita ($(git rev-list --count --all) commit)"
  echo
fi

if [ "$trovato" -eq 0 ]; then
  echo "Pulito: nessun dato sensibile nei ${#FILES[@]} file pubblicabili."
else
  echo
  echo "Correggi prima di pubblicare."
fi
exit "$trovato"
