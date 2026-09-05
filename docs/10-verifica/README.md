# Verifica funzionale

Cosa è stato provato, come, e cosa è venuto fuori. Gli script che hanno
prodotto questi risultati stanno qui accanto e si rilanciano: un documento che
dice «funziona» senza il modo di riprovarlo invecchia il giorno dopo.

```bash
export NETSTOCK_URL=https://indirizzo-della-tua-installazione
export NETSTOCK_PASSWORD='…'          # dell'utente amministratore

docs/10-verifica/endpoint.sh     # 60 chiamate all'API, esito atteso per ognuna
docs/10-verifica/database.sh     # prova a violare le garanzie del database
docs/10-verifica/container.sh    # spegne, uccide e rimuove i container
node docs/10-verifica/client.mjs <cartella-scarichi>   # 49 prove in un browser vero

# Scrive nel registro: solo su un'istanza usa e getta, e lo pretende.
NETSTOCK_SCRIVE=si node docs/10-verifica/flussi.mjs    # il giro completo della merce
```

Indirizzo e credenziali non stanno negli script: sono di un'installazione
precisa, e un file che li contiene non si pubblica.

`container.sh` **ferma i servizi**: si lancia quando non sta lavorando
nessuno. `client.mjs` richiede `puppeteer-core` e un Chrome locale.

Quello che questo documento riporta è **cosa è stato provato e con che
esito**, non quanti apparati ci fossero nel magazzino usato per provarlo.

---

## 1. Endpoint — 60 prove, 0 fallite

Ogni chiamata è verificata sul **codice atteso**, non sul fatto che risponda:
un 200 dove serviva un 403 è un difetto, non un successo.

| Area | Verificato |
|---|---|
| Autenticazione | accesso valido 200 · sessione corrente 200 · credenziali sbagliate **401** |
| Anagrafiche | vendor, categorie, fornitori, ubicazioni, catalogo: elenco e ricerca 200 · risorsa inesistente **404** |
| Magazzino | giacenza aggregata, per ubicazione, magazzino unificato, filtri, unità, movimenti 200 |
| Esportazioni | giacenza, magazzino, movimenti, archivio completo 200 · filtro vuoto **422** (vedi §5) |
| Bolle e ricerca | bolle, prenotazioni, ricerca globale, cruscotto 200 |
| Regole di dominio | data nel futuro **422** · rettifica con motivazione troppo corta **422** |
| Amministrazione | utenti (anche eliminati), registro, impostazioni, template, stato copie 200 |
| Salute | `/health` pubblica 200 · `/health/ready` autenticata 200 |

### Permessi, provati con un utente in sola lettura creato e poi rimosso

| Operazione | Atteso | Ottenuto |
|---|---|---|
| Leggere il magazzino | 200 | 200 |
| Leggere le prenotazioni | 200 | 200 |
| Elenco utenti | 403 | **403** |
| Registro di sicurezza | 403 | **403** |
| Creare un'ubicazione | 403 | **403** |
| Registrare merce | 403 | **403** |
| Stato delle copie di sicurezza | 403 | **403** |

---

## 2. Database — 12 verifiche, 0 fallite

Non si legge lo schema: si prova a violarlo.

- **Schema**: tabelle, viste, indici e vincoli di chiave esterna presenti
  nel numero atteso dalla revisione applicata, nessun vincolo non validato.
- **Registro append-only, doppia difesa**:

  | Tentativo | Chi lo ferma | Esito |
  |---|---|---|
  | `UPDATE stock_movements` come utenza applicativa | permessi revocati | `permission denied` |
  | `DELETE stock_movements` come utenza applicativa | permessi revocati | `permission denied` |
  | `DELETE audit_log` come utenza applicativa | permessi revocati | `permission denied` |
  | `UPDATE stock_movements` come **proprietario** | trigger | «La tabella è append-only» |

  La seconda difesa è quella che conta: i permessi si possono cambiare, il
  trigger ferma anche chi possiede la tabella.
- **Ledger e proiezione coincidono**: `v_reconciliation_errors` vuota, e la
  giacenza calcolata dai movimenti corrisponde alle unità in magazzino.
- **Separazione**: `netstock` e `netstock_test` sono due database distinti, con
  contenuti diversi, e `conftest.py` si rifiuta di far girare i test fuori dal
  secondo.

---

## 3. Container — 4 prove, 0 fallite

Impronta confrontata prima e dopo ogni prova: unità, movimenti, righe di
registro, utenti e somma delle quantità movimentate: **identica in tutti e
quattro i casi**. Lo script la ricalcola e la confronta da solo, quindi la
verifica si rifà senza sapere quali fossero i numeri.

| Prova | Comando | Esito |
|---|---|---|
| Arresto ordinato | `docker compose stop` → `start` | dati invariati |
| Interruzione brutale | `docker compose kill` → `start` | dati invariati |
| Rimozione e ricreazione | `docker compose down` → `up -d` | dati invariati, volume `netstock_pgdata` presente |
| Riavvio del solo database | `docker compose restart db` | dati invariati, l'API si riconnette da sola |

L'interruzione brutale è quella che vale: `kill` manda SIGKILL, che è ciò che
succede togliendo la corrente. I dati restano perché PostgreSQL scrive il
proprio giornale prima di confermare, e il volume è indipendente dal
container.

---

## 4. Interfaccia — 38 prove in un browser vero

Non chiamate all'API: pulsanti premuti, file che arrivano sul disco.

| Area | Verificato |
|---|---|
| Accesso | password sbagliata → messaggio e nessun accesso · password giusta → entra |
| Cruscotto | riquadri di sintesi e grafico disegnato |
| Magazzino | tabella popolata · ubicazione **per esteso** · filtro per stato · scelta colonne · colonna Note aggiunta |
| Esportazioni | `magazzino.csv` scaricato, una riga per pezzo e colonna Note presente · archivio ZIP scaricato |
| Dettaglio pezzo | cronologia presente · operazione scritta «Carico», non `receipt` |
| Navigazione | movimenti, ubicazioni, bolle, catalogo, vendor, categorie, fornitori, ricezione: tutte si aprono |
| Prenotazioni | nessuna pagina: si ricade sul cruscotto (lacuna nota, §5.3) |
| Ricerca globale | un seriale parziale propone risultati |
| Amministrazione | utenti, template, audit |
| Copia di sicurezza | dati tecnici, spazio, tabelle, copie sul server, copia **scaricata davvero** e non vuota |
| Ripristino | chiede file e parola di conferma · il pulsante parte disabilitato |

Il ripristino è stato anche provato **nei suoi due rifiuti**, che è ciò che si
può provare senza cancellare un magazzino:

| Tentativo | Risposta | Dati |
|---|---|---|
| Parola di conferma sbagliata | «Per procedere serve la parola RIPRISTINA» | intatti |
| Parola giusta, file qualsiasi | «Il file non è una copia di sicurezza leggibile» | intatti |
| Tre copie chieste insieme | una 200, due **409** | serializzate |

Il giro completo — copia, sporca, ripristina, verifica — gira sul database di
prova in `api/tests/test_manutenzione.py`.
| Uscita | «Esci» riporta alla pagina di accesso e la sessione sul server è chiusa |
| Barra laterale | si riduce a 64 px |

**Zero errori in console** durante tutto il percorso.

---

## 5. Cosa è stato trovato, e cosa è stato fatto

### Corretto

1. **L'uscita non usciva.** «Esci» chiudeva la sessione sul server — le
   chiamate successive rispondevano 401 — ma l'interfaccia restava dov'era,
   con l'utente ancora scritto in alto a destra. Causa:
   `setQueryData(chiave, undefined)`, che in TanStack Query significa «non
   cambiare nulla». Ora si svuota tutta la cache, che è anche ciò che serve
   quando sullo stesso computer entra un'altra persona.

2. **Le due strade di backup producevano file incompatibili.** Il client
   PostgreSQL di Debian 13 è la versione 17 e scrive archivi in formato 1.16,
   che il `pg_restore` 16 del container del database rifiuta con «unsupported
   version»: la copia scaricata dall'applicazione non sarebbe stata
   ripristinabile dallo script sul sistema operativo. L'immagine dell'API ora
   installa `postgresql-client-16`, della stessa versione maggiore del server.
   Verificato che la copia fatta dall'applicazione sia leggibile da entrambe
   le strade.

### Corretto dopo una revisione indipendente

Il codice di copia e ripristino è stato sottoposto a una revisione
indipendente, con il mandato di cercarci difetti. Otto rilievi, sei accolti:

| Rilievo | Fatto |
|---|---|
| Nessuna serializzazione: due ripristini in parallelo, o una copia durante un ripristino, si sovrappongono sulle stesse tabelle | Una serratura sola per entrambe le operazioni; la seconda richiesta riceve 409 invece di accodarsi |
| Se fallisce anche il rientro allo stato precedente, la risposta non lo distingue da un fallimento normale | Messaggio esplicito, entrambi i dettagli, e l'indicazione di fermare l'applicazione e ripristinare a mano |
| Lo `stderr` degli strumenti esce verso il client | Redatto dalla password e registrato lato server prima di uscire |
| Il limite di caricamento è applicato quando il file è già stato ricevuto | Il limite vero è nel proxy: `request_body 2GB` sulla sola rotta di ripristino |
| La cartella temporanea del backup resta nel container sui rami d'errore | Rimossa comunque vada |
| L'audit del ripristino viene cancellato dal ripristino stesso | Si scrive **dopo**, nel database appena ripristinato |
| Nessun tempo massimo per i sottoprocessi | 15 minuti, poi si interrompono |
| `decode()` senza `errors="replace"` può sollevare e nascondere l'errore vero | Corretto |

Due rilievi non accolti, con motivo: nascondere il dettaglio dell'errore dietro
un identificativo, su un'installazione con un solo amministratore, vuol dire
mandarlo a leggere i log del container per capire perché non è riuscita una
cosa che ha appena chiesto lui; e il dump di sicurezza «non atomico rispetto
alle richieste in corso» è vero ma inerente — l'operazione va fatta quando non
sta lavorando nessuno, ed è scritto nella pagina.

La revisione ha anche confermato quello che era già a posto: nessuna iniezione di
comando (`create_subprocess_exec` con argv separati), la password passa da
`PGPASSWORD` e non da argv, nessun path traversal dal nome del file caricato,
ed entrambe le rotte sono riservate agli amministratori.

### Da sapere

3. **Le prenotazioni non hanno interfaccia.** L'API è completa
   (`/reservations`, elenco e creazione) e il modello dati c'è, ma nel client
   non esiste nessuna pagina: l'indirizzo `/reservations` ricade sulla
   dashboard. Non è una regressione — la pagina non è mai stata scritta — ma
   è una funzione raggiungibile solo via API.

4. **Il filtro vuoto nell'esportazione risponde 422.** È voluto e resta così:
   l'endpoint dichiara quei parametri come UUID. È il client che non deve
   mandarli vuoti, ed è già corretto.

---

## 6. Copia di sicurezza e ripristino: come sono fatti

**La copia scaricata dalle Impostazioni non resta sul server.** Arriva sul
computer di chi preme il pulsante, e questo è il punto: una copia in più sullo
stesso disco del database non protegge dal disco che si rompe. Le copie sul
server continuano a farle il timer notturno delle 02:30, elencate nella stessa
pagina con peso e data.

Il **ripristino** accetta un file caricato — il caso vero del disastro, in cui
l'unica copia rimasta è quella che qualcuno si era portato via. L'ordine dei
passi è la parte che conta:

1. parola di conferma (`RIPRISTINA`), perché non deve poter partire da un clic;
2. lettura dell'indice del file **prima** di toccare il database: un file
   sbagliato viene rifiutato mentre tutto è ancora intatto;
3. copia dello stato attuale, perché il ripristino è l'unica operazione di
   questo sistema che cancella dei dati;
4. ripristino, e se fallisce si riapplica la copia del punto 3.

Provato per davvero in `api/tests/test_manutenzione.py`: si copia, si sporca il
database, si ripristina, e lo sporco è sparito. La prova gira su un database
usa e getta creato e buttato dal test stesso — la prima versione lavorava su
quello condiviso, e ricreandone le tabelle faceva cadere i test che giravano
dopo, a seconda dell'ordine.

**Limite dichiarato:** durante il ripristino le tabelle vengono ricreate, quindi
chi sta lavorando in quel momento riceve errori. Va fatto quando non c'è
nessuno dentro.


---

## 6. Ripassata completa — cosa ha trovato

Le prove qui sopra sono state estese a tutto quello che è stato aggiunto dopo
la prima stesura — archivio delle bolle, riconoscimento del fornitore,
anteprime, scelta del modello, conservazione del registro di controllo — e
rilanciate. Quattro difetti, tre negli strumenti di verifica e **uno nel
prodotto**.

### Nel prodotto

- **`GET /settings` era leggibile da un utente in sola lettura.** La scrittura
  era riservata agli amministratori, la lettura no. Dentro non ci sono
  segreti, ma la configurazione di un sistema dice come è fatto, e chi non può
  cambiarla non ha ragione di leggerla. Ora pretende il ruolo di
  amministratore, e un test passa in rassegna le rotte amministrative
  controllando che ognuna abbia il guardiano che le compete.

### Negli strumenti

- **La sezione «Permessi» era un titolo senza prove sotto**: prometteva una
  verifica che non esisteva, e infatti il difetto qui sopra era passato
  inosservato. Adesso crea un utente in sola lettura, gli fa provare sette
  cose che non deve poter fare, e lo disattiva.
- **Lasciava un account chiuso a ogni esecuzione**: la cancellazione
  definitiva non riesce per chi ha agito, perché le sue righe di registro lo
  trattengono. Ora l'account è uno solo, riusato, con una password nuova ogni
  volta e disattivato alla fine.
- **La prova della barra laterale cercava un pulsante che non esiste più**
  («Riduci»): il comando è diventato un'icona senza testo, e la prova falliva
  su una funzione che funziona.

### Coperture nuove

Il giro completo della merce — ricezione con acquisizione dei seriali, il
pezzo che compare a magazzino con la sua cronologia, lo storno che aggiunge
una riga invece di toglierne una — non era provato da nessuna parte fino in
fondo: le pagine si aprivano, ma nessuno premeva «Registra». Ora c'è
`flussi.mjs`, che lo fa davvero e per questo pretende un'istanza usa e getta.

Provato: dopo lo storno di un carico l'unità risulta «rimossa per errore di
inserimento», il carico resta scritto, il movimento di rettifica si aggiunge,
e la riconciliazione fra registro e giacenza non segnala nulla.
