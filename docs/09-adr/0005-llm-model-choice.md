# ADR 0005 — Scelta del modello LLM per l'estrazione
Data: 2026-08-26 · Stato: accettato, modificato il 2026-08-28

## Contesto

Lo stadio 4 della pipeline di estrazione (§7.2) usa un LLM locale per leggere testo OCR quando barcode e regole non bastano. Un requisito del progetto impone inferenza locale, nessuna chiamata a servizi esterni, funzionamento anche senza rete. Il requisito di licenza (§2.3/§2.4) esclude qualunque modello con clausole d'uso non permissive.

## Decisione

Modello di default: **Phi-4-mini (3.8B, quantizzato Q4)**, licenza **MIT**, eseguito via **Ollama** (MIT) come servizio separato nella rete Docker interna (`backend`, senza uscita a Internet). Alternativa più leggera ammessa: Granite 3.x 2B (IBM, Apache-2.0). Percorso VLM opzionale con Granite Vision 3.2 2B (Apache-2.0), da attivare solo se l'OCR degrada su layout complessi.

Esplicitamente **vietati**: Qwen2.5-VL-3B (Qwen Research License, non commerciale — l'errore più facile da commettere scegliendo "il modello piccolo"), Llama e Gemma (licenze con condizioni d'uso incompatibili con la whitelist).

## Alternative considerate

- **Qwen2.5-VL-3B**: scartato nonostante le dimensioni comode per CPU, perché la licenza Qwen Research vieta l'uso commerciale — userlo esporrebbe l'azienda a un rischio di conformità diretto.
- **Modelli via API cloud**: scartati per quel requisito (nessun dato esce dalla macchina) — le etichette e i seriali non devono transitare su servizi terzi.
- **Nessun LLM, solo OCR + regole**: rimane il comportamento di fallback quando `EXTRACT_ENABLED=false` o Ollama non è raggiungibile; non è però sufficiente come esperienza di default perché le bolle cartacee e le etichette rovinate hanno un tasso di riconoscimento più basso con le sole regole.

## Conseguenze

Positive: nessun dato esce mai dalla macchina; licenza MIT verificabile senza ambiguità; footprint contenuto (~3 GB RAM quantizzato) compatibile con una VM di fascia media.

Negative: un modello da 3.8B ha comunque un tasso di errore non nullo sui casi difficili (testo manoscritto, foto mosse) — mitigato dallo stadio 5 di verifica anti-allucinazione (§7.2), che scarta ogni valore non letteralmente presente nel testo sorgente, e dal fatto che il salvataggio richiede sempre conferma umana esplicita.


---

## Aggiornamento 2026-08-28 — il default passa a Qwen3 4B

Alla prima prova sul campo, **Phi-4-mini non si è rivelato adeguato al
compito**: sulla tabella di una bolla confondeva sistematicamente le colonne (il
nome del destinatario finiva nel campo del codice articolo) e sulle pagine con
elenchi lunghi degenerava in ripetizione fino a saturare il limite di token.

Default: **Qwen3 4B** (`qwen3:4b`), che sullo stesso documento ricostruisce la
tabella correttamente e in modo riproducibile.

**Sulla licenza, che è il punto delicato di questa modifica.** Sopra sono vietati
i modelli Qwen2.5-VL sotto *Qwen Research License*, che esclude l'uso
commerciale. La famiglia **Qwen3 è rilasciata sotto Apache-2.0**, licenza già in
`compliance/allowed-licenses.txt`: è una licenza diversa da quella del modello
vietato, non un'eccezione a quel divieto. Il divieto su Qwen2.5-VL-3B resta in
vigore.

Phi-4-mini (MIT) resta un'alternativa valida e supportata: si cambia con
`EXTRACT_MODEL` in `.env`, senza toccare il codice.

### Conseguenza sull'hardware

Misurato sullo stesso documento, stesso risultato identico: **pochi secondi con
una GPU di fascia media, contro diversi minuti su sola CPU**. Il modello su sola CPU funziona — il
vincolo di §2 resta soddisfatto — ma non entro i tempi di una richiesta HTTP: da
qui la scelta di far girare la lettura strutturale in sottofondo e di tenere la
riserva GPU in un override compose separato, così che una macchina senza scheda
video parta comunque.
