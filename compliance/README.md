# Licenze

Tre file, tre ruoli distinti:

| File | Cos'è |
|---|---|
| `allowed-licenses.txt` | Le licenze ammesse. La CI fallisce se ne compare una che non c'è. |
| `licenses.csv` | L'inventario di ciò che è **davvero installato**, generato, non scritto a mano. |
| `allowed-secrets.txt` | Valori che sembrano un segreto ma sono stati esaminati e non lo sono. |

Per rigenerare l'inventario dopo un aggiornamento di dipendenze:

```bash
make licenses
```

Legge dai pacchetti presenti nell'immagine e in `node_modules`. Scriverlo a mano
significherebbe avere un elenco che invecchia in silenzio e dice il falso al
primo `pip install`.

## Cosa c'è dentro

375 componenti al momento dell'ultima generazione, tutti sotto licenza
permissiva:

| Famiglia | Quanti | Note |
|---|---|---|
| MIT (tutte le grafie) | 286 | la grande maggioranza del frontend |
| Apache-2.0 | ~30 | FastAPI, Tesseract, Caddy, OpenCV, il modello |
| BSD-2 / BSD-3 | ~25 | asyncpg, pypdfium2, uvicorn |
| ISC | ~25 | utilità npm |
| MPL-2.0 | 1 | copyleft **per file**, non virale sul progetto |
| PostgreSQL License | 1 | permissiva, simile a BSD |
| PSF / Python-2.0 / Unlicense / CC0 | pochi | permissive |

**Nessuna GPL, AGPL, SSPL o licenza proprietaria** fra le dipendenze
dichiarate. Verificato sull'installato, non sulla lista dei desideri.

## Le due cose che l'inventario non dice da solo

### FFmpeg dentro il wheel di OpenCV — LGPL

`opencv-python-headless` si dichiara Apache-2.0, ed è vero per il codice
OpenCV. Ma il wheel **contiene anche** le librerie FFmpeg (`libavcodec`,
`libavformat`, `libswscale`), che sono LGPL-2.1+. I metadati dei pacchetti non
lo mostrano: una scansione basata su di essi non lo troverebbe mai.

`allowed-licenses.txt` esclude LGPL senza un ADR esplicito. L'ADR c'è:
[`docs/09-adr/0006-ffmpeg-lgpl-in-opencv.md`](../docs/09-adr/0006-ffmpeg-lgpl-in-opencv.md).

In breve: quelle librerie servono a leggere e scrivere **video**, e NetStock non
ne apre nessuno — nessuna chiamata a `VideoCapture` o `VideoWriter` in tutto il
progetto. Sono peso morto trasportato dal wheel.

### L'immagine di base contiene software GPL

`python:3.12-slim` è Debian, e Debian contiene GPL (bash, coreutils) e LGPL
(glibc). Vale per qualunque immagine Docker basata su una distribuzione Linux.

Non tocca il codice di NetStock: sono programmi separati, non modificati,
eseguiti — non collegati al nostro. Diventa un tema solo **distribuendo
l'immagine costruita** a terzi, dove valgono gli obblighi di quei pacchetti
verso Debian. Questo repository distribuisce sorgente e `Dockerfile`, non
immagini.

## Se l'inventario cambia

Un aggiornamento di dipendenza può introdurre una licenza nuova. La procedura:

1. `make licenses` rigenera l'inventario;
2. si guarda cosa è comparso in `licenses.csv`;
3. se è nella whitelist, non serve altro;
4. se non c'è: o si sostituisce la dipendenza, o si scrive un ADR che dice
   perché è accettabile — come si è fatto per FFmpeg.

L'ADR è il punto: una licenza fuori whitelist non è vietata per sempre, è
vietata **in silenzio**. Motivarla per iscritto la rende una decisione invece di
una svista.
