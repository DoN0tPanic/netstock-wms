# ADR 0001 — Ledger dei movimenti append-only
Data: 2026-08-26 · Stato: accettato

## Contesto

NetStock deve essere ricostruibile in audit: per ogni unità o quantità a magazzino deve essere possibile spiegare esattamente come ci è arrivata (bolla, prelievo, reso, RMA, rettifica) e chi ha effettuato ciascuna operazione. Un modello con un campo "giacenza" aggiornabile in-place perde questa storia: un `UPDATE` può correggere un errore ma cancella l'evidenza dell'errore stesso.

## Decisione

`stock_movements` (e `audit_log`) sono tabelle **append-only**: nessuna riga viene mai modificata o cancellata. Le correzioni si registrano come nuovi movimenti (`adjustment`, `scrap`, o uno storno con `reverses_id` valorizzato). La giacenza non è un campo: è calcolata dalla somma dei movimenti (`v_stock_balance`).

L'immutabilità è applicata su due livelli indipendenti:
1. **Trigger DB** (`prevent_mutation()`) che solleva eccezione su `UPDATE`/`DELETE`, attivo anche per il proprietario dello schema.
2. **Privilegi**: il ruolo runtime `netstock_app` (usato dall'API) non ha `UPDATE`/`DELETE`/`TRUNCATE` su queste due tabelle — solo il ruolo di migration (superuser, usato solo da Alembic) potrebbe bypassare il trigger, e comunque non lo fa mai.

`stock_units.location_id`/`status` restano una **proiezione** mantenuta nella stessa transazione del movimento, per query veloci; un job notturno e un comando CLI (`reconcile`) verificano che proiezione e ledger coincidano. Se divergono, il ledger vince sempre.

## Alternative considerate

- **Giacenza come campo aggiornato in-place**: scartata, è l'esatto problema che il progetto deve risolvere (nessuna fonte di verità storica).
- **Solo trigger, senza REVOKE separato**: scartata perché un owner di schema può comunque disabilitare temporaneamente un trigger (`ALTER TABLE ... DISABLE TRIGGER`); la doppia barriera rende l'aggiramento un'azione esplicita e visibile, non un incidente.
- **Soft delete con `deleted_at`**: scartata per lo stesso motivo del campo aggiornabile — un soft delete su un movimento nasconde comunque un fatto avvenuto.

## Conseguenze

Positive: storia completa e non manomettibile, criterio di audit verificabile con un test automatico (`UPDATE` su `stock_movements` deve sollevare eccezione), nessuna ambiguità su "cosa è successo".

Negative: ogni errore di registrazione richiede un movimento di storno esplicito invece di una semplice correzione; la giacenza è sempre calcolata (mai letta direttamente), quindi le query di disponibilità devono passare dalle viste o da somme sul ledger.
