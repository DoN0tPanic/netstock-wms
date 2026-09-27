# compliance/

**Per sapere se e come si può usare NetStock in azienda, si parte da [`LICENZE.md`](LICENZE.md).** Questo file spiega come si mantengono gli altri.

| File | Cos'è |
|---|---|
| [`LICENZE.md`](LICENZE.md) | Il documento per chi deve decidere: licenze, obblighi, attenzioni |
| [`licenses.csv`](licenses.csv) | L'inventario di ciò che è **davvero installato**, generato e mai scritto a mano |
| [`allowed-licenses.txt`](allowed-licenses.txt) | Le licenze ammesse, in sigle SPDX |
| [`eccezioni-licenze.txt`](eccezioni-licenze.txt) | Componenti ammessi fuori elenco, ciascuno con il suo perché |
| [`allowed-secrets.txt`](allowed-secrets.txt) | Valori che sembrano un segreto ma sono stati esaminati e non lo sono. Non riguarda le licenze: lo usano i controlli sui dati sensibili |

## Rigenerare e controllare

```bash
make licenses-check   # controlla, senza cambiare file
make licenses         # rigenera licenses.csv, poi controlla
```

Servono l'immagine dell'API (`make build`) e `web/node_modules` (`npm ci` in `web/`). I pacchetti Python si leggono dentro l'immagine con `scripts/licenze_python.py`, che usa solo la libreria standard. Le regole stanno in `scripts/licenze.py`, lo stesso script che gira in CI.

## Il controllo in CI

Il job **«Licenze»**, a ogni push:
1. lancia `scripts/test_licenze.py`, per vedere che il controllo fermi davvero GPL, AGPL, licenze sconosciute ed eccezioni scadute;
2. installa le sole dipendenze di produzione in un ambiente pulito, e l'interfaccia dal lockfile;
3. si ferma se:
   - una licenza è fuori elenco e senza eccezione;
   - un componente manca da `licenses.csv`;
   - il modello predefinito ha una licenza non dichiarata;
   - OpenCV comincia ad aprire video (ADR 0006).

La licenza del modello non sta in nessun metadato. È dichiarata per famiglia in `scripts/licenze.py` (`MODELLI`), seguendo l'ADR 0005.

## Se il controllo si ferma

- **Componente mancante dall'inventario**: `make licenses` e si committa `licenses.csv`. Succede quando cambia una dipendenza, anche una indiretta.
- **Licenza non ammessa.** Prima si guarda cosa è: il dettaglio è nel pacchetto, non nei metadati. Poi le strade sono tre:
  1. si sostituisce il componente;
  2. se la licenza è permissiva ma scritta in modo nuovo, si aggiunge la sigla ad `allowed-licenses.txt`, o un sinonimo in `scripts/licenze.py`;
  3. altrimenti si scrive un'eccezione in `eccezioni-licenze.txt`, con il motivo, e per un copyleft anche un ADR, come per FFmpeg.

Una licenza fuori elenco non è vietata per sempre, è vietata **in silenzio**: motivarla per iscritto la rende una decisione invece di una svista.
