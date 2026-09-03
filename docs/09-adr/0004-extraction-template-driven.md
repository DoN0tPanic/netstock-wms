# ADR 0004 — Estrazione template-driven invece di codice per vendor
Data: 2026-08-26 · Stato: accettato

## Contesto

Il magazzino riceve etichette e bolle in formati diversi per vendor (Cisco, Meraki, Palo Alto, APC, ...) e questi formati cambiano nel tempo senza preavviso. Se ogni formato richiedesse una funzione di parsing dedicata nel codice, ogni nuova etichetta o bolla non riconosciuta bloccherebbe l'operatore fino al prossimo deploy.

## Decisione

I campi da estrarre, i loro pattern (regex), le keyword di prossimità, i formati di barcode attesi e le istruzioni aggiuntive per l'LLM sono dati in `extraction_templates.field_specs` (JSONB), non codice. Un template nuovo si crea da UI (playground admin) e diventa immediatamente utilizzabile, senza deploy. Il codice conosce solo la **struttura** del formato (`FieldSpec`), mai il contenuto specifico di un vendor.

## Alternative considerate

- **Un parser Python per vendor** (`parse_cisco_label()`, `parse_meraki_label()`, ...): scartato. Ogni variazione di etichetta (anche minima) richiede una release; con un piccolo team IT che non può presidiare un ciclo di rilascio rapido, il sistema diventerebbe rapidamente disallineato con la realtà delle etichette in mano agli operatori.
- **Regole hardcoded in configurazione YAML versionata**: simile nello spirito, ma richiede comunque un redeploy per essere applicata; il requisito esplicito era "zero deploy per nuovi formati" (§7.3).

## Conseguenze

Positive: onboarding di un nuovo formato di etichetta o bolla senza toccare il codice; il playground permette di iterare su un template guardando il risultato in tempo reale su un'immagine reale, prima di usarlo in produzione.

Negative: la qualità dell'estrazione dipende dalla qualità del template scritto da un admin, non da codice testato; per questo il golden set (§7.8) e le soglie di precisione/recall restano necessari anche con questo approccio, e il playground non scrive mai a magazzino (nessun rischio nel testare un template).
