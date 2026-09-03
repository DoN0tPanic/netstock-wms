# ADR 0006 — FFmpeg (LGPL) dentro il wheel di OpenCV
Data: 2026-08-28 · Stato: accettato

## Contesto

`compliance/allowed-licenses.txt` non ammette LGPL: «è ammessa solo dietro ADR
esplicito». Questo è quell'ADR.

`opencv-python-headless` dichiara Apache-2.0 nei propri metadati, ed è corretto
per il codice OpenCV. Il **wheel distribuito su PyPI**, però, include anche le
librerie condivise di FFmpeg:

```
libavcodec-*.so    libavformat-*.so    libswscale-*.so
```

FFmpeg è **LGPL-2.1 o successiva** (e diventa GPL se compilato con certe
opzioni; le build dei wheel OpenCV usano la configurazione LGPL).

Il punto rilevante: **nessuna scansione basata sui metadati dei pacchetti può
trovarlo.** `pip-licenses` legge ciò che il pacchetto dichiara, e il pacchetto
dichiara Apache-2.0. Il binario incluso non compare da nessuna parte. È stato
trovato guardando i file dentro la directory installata, non l'inventario.

## Decisione

**Si accetta la presenza di FFmpeg LGPL nel wheel di OpenCV.** Non si compila
OpenCV da sorgente e non si sostituisce la libreria.

## Perché è accettabile

**Il codice non le raggiunge.** In OpenCV quelle librerie stanno dietro a due
sole funzioni: `cv2.VideoCapture` e `cv2.VideoWriter`, cioè leggere e scrivere
video da file o da rete. NetStock non ne chiama nessuna delle due — verificato
su tutto `api/app`. Di OpenCV usa sedici simboli, tutti su una singola immagine
ferma: conversione in scala di grigi, calcolo dell'inclinazione, rotazione,
contrasto locale, soglie, ridimensionamento. Sono le poche righe del
preprocessing OCR in `services/extraction/ocr.py`.

Anche la lettura del barcode dal vivo non passa di lì: gira nel browser con
zxing, e al server arrivano immagini già decodificate.

**Gli obblighi LGPL scattano sulla distribuzione.** Un'installazione interna non
distribuisce niente a terzi. Questo repository distribuisce sorgente e
`Dockerfile`; il wheel viene scaricato da PyPI al momento della costruzione, da
chi costruisce, per sé.

**E se si distribuisse davvero.** Gli obblighi LGPL per una libreria collegata
dinamicamente e non modificata sono limitati: fornire il testo della licenza,
attribuire, e non impedire a chi riceve di sostituire la libreria con una
propria versione. Il collegamento dinamico c'è già (sono `.so` separati) e non
tocchiamo il codice FFmpeg, quindi nessuno di questi punti richiederebbe una
modifica al progetto — solo di allegare licenza e attribuzione al pacchetto
distribuito.

## Alternative considerate

- **Compilare OpenCV da sorgente senza FFmpeg** (`-DWITH_FFMPEG=OFF`).
  Toglie la libreria ma aggiunge al `Dockerfile` una compilazione di OpenCV:
  minuti di build, una toolchain C++ nell'immagine, e una dipendenza da
  mantenere a ogni aggiornamento. Costo alto per rimuovere codice che nessuno
  esegue.

- **Abbandonare OpenCV per Pillow e numpy.** Delle funzioni usate,
  `createCLAHE`, `adaptiveThreshold` e `minAreaRect` non hanno equivalente
  diretto e andrebbero riscritte. Sono il cuore del preprocessing OCR, la cui
  qualità è stata misurata sul campo: rifarlo significa rimettere in
  gioco quel risultato per una ragione che non è tecnica.

- **Non fare niente e non documentarlo.** È la sola alternativa davvero
  sbagliata: la politica dichiarata direbbe una cosa e l'installato un'altra, e
  chi controlla troverebbe una discrepanza senza spiegazione.

## Conseguenze

`compliance/README.md` documenta la cosa accanto all'inventario, così chi guarda
le licenze la trova senza doverla scoprire.

Se un domani NetStock dovesse leggere video — filmati di ispezione, riprese da
telecamera lato server — questa decisione va rivista: da quel momento il codice
raggiungerebbe FFmpeg davvero, e l'argomento principale di questo ADR
decadrebbe.
