# Licenze e uso in azienda

> **In breve.** NetStock si può usare in un'azienda di qualunque dimensione,
> per qualunque numero di utenti, **senza pagare licenze**.
>
> - Il codice di NetStock è sotto licenza MIT.
> - Tutti i componenti che usa sono open source, con licenze permissive.
> - Nessuna di queste licenze prevede costi, soglie di dipendenti o di fatturato, o limiti di utenti.
>
> Le attenzioni sono due, e nessuna riguarda l'installazione standard: **Docker Desktop** e il **modello di lettura**, se lo si cambia (§4).

Questo documento è scritto per chi deve decidere, per esempio l'ufficio legale o acquisti. Riassume le licenze dichiarate dai componenti, verificate in automatico a ogni modifica del codice (§5). Non è un parere legale: la valutazione finale spetta a chi ne ha la responsabilità in azienda. Il materiale per farla, però, è tutto qui.

## 1. NetStock

Licenza **MIT** (file [`LICENSE`](../LICENSE)). Chiunque, azienda compresa, può:
- usarlo;
- copiarlo e modificarlo;
- installarlo su quante macchine vuole, anche a scopo commerciale;

senza costi. L'unico obbligo è conservare l'avviso di copyright e di licenza nelle copie del codice.

## 2. Cosa usa, e con quali licenze

L'inventario completo è in [`licenses.csv`](licenses.csv): per ogni componente, la versione, la licenza e l'origine. È generato dai pacchetti davvero installati, mai scritto a mano. Al 27/09/2026 conta **392 componenti**:
- 50 pacchetti Python, cioè l'immagine che va in produzione;
- 332 pacchetti npm, cioè l'interfaccia e gli strumenti per costruirla;
- 10 componenti di sistema (immagini, motore OCR, modello, NetStock stesso).

| Licenza | Che tipo | Cosa comporta |
|---|---|---|
| MIT, MIT-0, MIT-CMU, ISC, BSD (2 e 3 clausole), 0BSD, Zlib, BlueOak-1.0.0 | Permissive | Nessun obbligo per l'uso. Chi ridistribuisce conserva l'avviso di copyright |
| Apache-2.0 | Permissiva, con licenza sui brevetti | Come sopra. Chi ridistribuisce conserva anche l'eventuale file NOTICE |
| PSF-2.0 / Python-2.0, PostgreSQL | Permissive | Come le precedenti |
| Unlicense, CC0-1.0 | Pubblico dominio | Nessuno |
| MPL-2.0 (un solo pacchetto, `certifi`) | Copyleft **limitato ai suoi file** | Solo chi modifica quei file e li ridistribuisce deve renderne disponibili le modifiche |

Fra i pacchetti non ci sono **licenze GPL, AGPL, SSPL o commerciali**.

**Componenti che non stanno in un gestore di pacchetti**

| Componente | Licenza |
|---|---|
| PostgreSQL (database) | PostgreSQL License, permissiva |
| Caddy (HTTPS) | Apache-2.0 |
| nginx (serve l'interfaccia) | BSD-2-Clause |
| Ollama (esegue il modello di lettura) | MIT |
| Tesseract (OCR), con i dati delle lingue | Apache-2.0 |
| Modello di lettura predefinito `qwen3:4b` | Apache-2.0: uso commerciale ammesso, senza soglie |
| Interprete Python | PSF-2.0 |
| Base Debian dell'immagine API | Mista: vedi §3 |

## 3. Quello che i metadati dei pacchetti non dicono

Alcuni pacchetti contengono librerie compilate con licenze proprie, che i metadati non riportano. Sono state cercate una per una.

| Dove | Cosa | Licenza | Perché va bene |
|---|---|---|---|
| OpenCV | FFmpeg (`libavcodec`…) | LGPL-2.1+ | Serve a leggere video, e NetStock non ne apre. La CI lo verifica a ogni push. Decisione: [ADR 0006](../docs/09-adr/0006-ffmpeg-lgpl-in-opencv.md) |
| numpy, OpenCV | Runtime GCC (`libgfortran`, `libquadmath`) | GPL-3 con *GCC Runtime Library Exception*, LGPL-2.1 | L'eccezione esenta espressamente i programmi che la usano, qualunque sia la loro licenza |
| Pillow, pypdfium2 | FreeType | Doppia: FTL oppure GPL-2 | Si applica la FTL, permissiva in stile BSD |
| pypdfium2 | PDFium e librerie incluse (ICU, libjpeg-turbo, libpng, libtiff, OpenJPEG, lcms, zlib…) | Permissive | Testi delle licenze nel pacchetto. Eccezione motivata in [`eccezioni-licenze.txt`](eccezioni-licenze.txt) |
| Immagine API | Programmi Debian (bash, coreutils, glibc…) | GPL, LGPL | Programmi separati, eseguiti e non collegati al codice di NetStock |

**Per l'uso interno nessuno di questi casi comporta obblighi.** Gli obblighi di LGPL e GPL scattano solo se si **distribuiscono le immagini Docker costruite a terzi**, fuori dall'azienda: in quel caso va offerto il sorgente di quelle parti. Il repository distribuisce sorgente e `Dockerfile`, non immagini.

## 4. Le due attenzioni

**Docker Desktop.**
- `install.sh` installa Docker Engine su Linux, che è Apache-2.0 e gratuito. L'installazione standard è quindi a posto.
- Docker Desktop, l'applicazione per Windows e Mac, è gratuito solo per aziende con meno di 250 dipendenti *e* meno di 10 milioni di dollari di fatturato annuo (termini di Docker a settembre 2026).
- In un'azienda più grande, far girare NetStock su Windows o Mac con Docker Desktop richiede un abbonamento Docker a pagamento.
- **Si usa un server o una VM Linux.**

**Il modello di lettura.** Quello predefinito, `qwen3:4b`, è Apache-2.0. La pagina Impostazioni lascia scegliere qualunque modello scaricato in Ollama, e altri modelli hanno altre licenze ([ADR 0005](../docs/09-adr/0005-llm-model-choice.md)):
- **ammessi**: Phi-4-mini (MIT), Granite 3.x (Apache-2.0);
- **vietati**:
  - Qwen2.5-VL, la cui licenza vieta l'uso commerciale;
  - Llama e Gemma, con condizioni d'uso proprie.

Prima di scaricare un modello diverso se ne controlla la licenza. Se si cambia il modello predefinito, la CI si ferma finché la sua licenza non è dichiarata.

La **scheda video** è facoltativa. I driver NVIDIA sono proprietari ma gratuiti, e l'NVIDIA Container Toolkit è Apache-2.0: nessun costo.

## 5. Come si mantiene vero

Un documento sulle licenze invecchia al primo aggiornamento di una dipendenza. Per questo il job **«Licenze»** della CI rifà la verifica a ogni push, partendo da un'installazione pulita delle dipendenze di produzione e dal lockfile dell'interfaccia. Si ferma se:
- un componente dichiara una licenza che non è in [`allowed-licenses.txt`](allowed-licenses.txt) e non ha un'eccezione motivata in [`eccezioni-licenze.txt`](eccezioni-licenze.txt);
- un componente installato manca dall'inventario pubblicato;
- il modello predefinito ha una licenza non dichiarata;
- OpenCV comincia ad aprire video, facendo cadere la premessa dell'ADR 0006.

Un'eccezione vale per la **dichiarazione esatta** del componente: se il componente cambia licenza, l'eccezione decade e la CI torna a fermarsi. Prima di fidarsi del verde, lo stesso job verifica che il controllo blocchi davvero GPL, AGPL, licenze sconosciute ed eccezioni scadute.

Aggiungere una licenza, quindi, è sempre una decisione scritta, mai una svista. In locale: `make licenses-check` per controllare, `make licenses` per rigenerare l'inventario.

## 6. Per l'ufficio legale

Documenti da consegnare, tutti in questo repository:

- questo file;
- [`licenses.csv`](licenses.csv), l'inventario completo;
- [`allowed-licenses.txt`](allowed-licenses.txt), le licenze ammesse;
- [`eccezioni-licenze.txt`](eccezioni-licenze.txt), le eccezioni con il loro perché;
- [ADR 0005](../docs/09-adr/0005-llm-model-choice.md), il modello di lettura, e [ADR 0006](../docs/09-adr/0006-ffmpeg-lgpl-in-opencv.md), FFmpeg dentro OpenCV;
- [`LICENSE`](../LICENSE), la licenza di NetStock.
