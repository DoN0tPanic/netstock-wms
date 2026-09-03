# ADR 0007 — Eliminazione di un utente
Data: 2026-08-31 · Stato: accettato

## Contesto

Fino a oggi un utente si poteva creare e disattivare, mai togliere. Non era
una svista di prodotto: è la conseguenza diretta di [ADR
0001](0001-ledger-append-only.md). Sette colonne puntano a `users` con
`ON DELETE RESTRICT`, e le due più frequentate — `stock_movements.performed_by`
e `audit_log.actor_id` — stanno su tabelle rese immutabili da trigger. Perché
un `DELETE FROM users` riesca, quelle righe dovrebbero prima sparire o essere
riscritte: entrambe le cose sono esattamente ciò che il progetto esiste per
impedire.

Il vincolo scatta prima di quanto sembri. Non serve aver movimentato merce:
**basta essere entrati una volta**, perché l'accesso riuscito scrive una riga
di audit con `actor_id`. Un'eliminazione che funziona solo per chi non ha mai
fatto il login sarebbe, in pratica, un pulsante rotto.

## Decisione

Una sola azione, «Elimina», con due esiti decisi dai dati e non dall'operatore:

- **Nessuna riga lo referenzia** → l'utente viene rimosso dal database. Le sue
  sessioni, che sono in `CASCADE`, spariscono con lui. È il caso dell'account
  creato per sbaglio o mai usato.
- **Almeno una riga lo referenzia** → l'account viene **chiuso**:
  `deleted_at` valorizzata, `is_active` a falso, `password_hash` azzerata,
  sessioni aperte revocate. Esce dall'elenco, non può più entrare, e resta
  soltanto come firma leggibile sotto le operazioni che ha fatto.

La risposta dice quale dei due è avvenuto (`removed`) e, nel secondo caso,
quante righe e in quali tabelle (`traces`), così l'interfaccia può spiegare il
perché invece di limitarsi ad affermarlo.

Un account chiuso si ripristina, ma con una **password nuova**: la chiusura
l'ha cancellata, e non c'è niente da rimettere com'era. Il suo nome utente
resta riservato a lui — nel registro le righe vecchie lo citano per nome, e
riassegnarlo a una persona diversa renderebbe illeggibile chi ha fatto cosa.

## Perché non le alternative

- **Rendere `actor_id` cancellabile (`ON DELETE SET NULL`)**. Toglierebbe il
  vincolo e con esso la garanzia: un movimento senza autore non è più
  ricostruibile in audit, che è il requisito di §1.2. In più `audit_log` è
  immutabile per trigger, quindi nemmeno un `SET NULL` passerebbe.

- **Anonimizzare l'utente al posto di chiuderlo**. Non otterrebbe niente:
  `audit_log.actor_username` è una colonna di testo scritta al momento del
  fatto, e resta leggibile qualunque cosa si faccia alla riga di `users`.
  Cancellare nome e cognome dall'anagrafica renderebbe solo più difficile
  capire chi fosse quella persona, senza rimuovere alcun dato.

- **Solo la disattivazione, come oggi**. È una cosa diversa e serve a un altro
  scopo: un utente disattivato è temporaneamente fuori (ferie, sospensione) e
  ha senso vederlo in elenco. Chi se n'è andato no. Tenerli nello stesso stato
  costringe a leggere una lista che cresce e non cala mai.

## Conseguenze

L'elenco utenti mostra per impostazione predefinita solo chi non è stato
eliminato; una casella «Mostra anche gli eliminati» li fa riapparire, con la
possibilità di ripristinarli.

`USER_REFERENCES` in `api/app/api/v1/users.py` elenca le colonne che vincolano.
È scritto a mano, quindi può invecchiare: `tests/test_user_delete.py` lo
confronta con i vincoli davvero presenti nel catalogo di PostgreSQL, e una
nuova tabella che punti a `users` fa fallire quel test invece di far fallire
l'eliminazione in produzione.

Effetto collaterale accettato: **un account chiuso non si riapre come vuoto**.
Non esiste più un modo di far sparire del tutto chi ha lavorato in magazzino,
nemmeno per un account di prova usato una volta. È il prezzo dell'append-only,
ed è lo stesso prezzo che il progetto paga già per i movimenti.

## Aggiornamento del 2026-09-01 — due passi invece di un esito automatico

L'esito che si sceglieva da sé aveva un difetto visibile solo usandolo: chi
eliminava un account senza storia lo vedeva sparire, e spuntando «Mostra anche
gli eliminati» non trovava niente. L'operazione era riuscita nel modo più
completo possibile, ma da fuori era indistinguibile da un'eliminazione
fallita — e non c'era modo di accorgersi che il caso era l'altro.

Le due forme restano, perché le impone il database; cambia chi le sceglie e
quando:

- `DELETE /users/{id}` **chiude** l'account, sempre, anche quando il database
  permetterebbe di più. Vale in ogni caso, non si annulla mai a sorpresa e si
  disfa con «Ripristina».
- `DELETE /users/{id}/permanent` lo toglie dal database, e solo se nessuna
  riga di registro lo cita. Si applica a un account **già chiuso**: chi lo
  esegue ha davanti la riga, il suo stato e il fatto che non è citata da
  nessuna parte. Il nome utente torna libero.

L'elenco degli eliminati dice per ogni riga se il secondo passo è ancora
possibile (`can_purge`, una query sola per tutta la pagina): dove non lo è, al
posto di un pulsante spento c'è il motivo — quell'account ha firmato
operazioni e resta.

Con [ADR 0008](0008-accessi-fuori-dall-audit.md) il caso «senza tracce» smette
di essere raro: da quando l'accesso riuscito non scrive più in `audit_log`, un
account creato e mai usato per lavorare si può davvero togliere. Il paragrafo
qui sopra sul contesto — «basta essere entrati una volta» — non vale più.
