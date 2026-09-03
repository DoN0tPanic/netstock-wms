# ADR 0008 — Gli accessi riusciti non vanno nel registro di sicurezza
Data: 2026-09-01 · Stato: accettato

## Contesto

`audit_log` è la tabella che per [ADR 0001](0001-ledger-append-only.md) non si
modifica e non si cancella: trigger `prevent_mutation()` su UPDATE e DELETE, e
`REVOKE UPDATE, DELETE, TRUNCATE` sul ruolo applicativo. La §10 aggiunge che
non si pota nemmeno per manutenzione: al più si archivia con un dump della
sola tabella.

Dentro quella tabella finiva anche `auth.login_success`, una riga per ogni
accesso di ogni persona. È l'evento più frequente del sistema e l'unico che
cresce col tempo invece che col lavoro fatto: in un magazzino con sei persone
sono qualche migliaio di righe l'anno che nessuno leggerà, in una tabella
progettata per non poter dimagrire. Sull'installazione di prova, dopo poche
settimane, gli accessi erano già i due terzi delle righe.

Lo stesso vale per `auth.logout`.

## Decisione

`auth.login_success` e `auth.logout` non si scrivono più. Restano
`auth.login_failed` e `auth.login_blocked`, che sono pochi, non crescono col
normale uso e sono quelli che si vanno a cercare davvero dopo un incidente —
oltre a essere l'evidenza del lockout richiesto dalla §9.

Non si perde l'informazione, cambia dove sta:

| Domanda | Prima | Adesso |
|---|---|---|
| Chi è entrato, quando, da che IP, con che browser | `audit_log` | `sessions` (`issued_at`, `ip_address`, `user_agent`, `revoked_at`) |
| Quando è entrato l'ultima volta | `audit_log` | `users.last_login_at` |
| Chi ha provato a entrare e ha sbagliato | `audit_log` | `audit_log`, invariato |

`sessions` è la tabella giusta per questo: registra l'accesso perché quello è
il suo mestiere, e **si può ripulire** — le sessioni scadono, e cancellare le
scadute non toglie nessuna evidenza di un'operazione di magazzino.

## Perché non le alternative

- **Un'impostazione per accenderlo e spegnerlo.** Aggiunge un interruttore che
  qualcuno deve capire, in cambio di una scelta che non ha due risposte
  ragionevoli: nessuna installazione vuole riempire una tabella immutabile di
  righe che non legge.

- **Cancellare le righe già scritte.** Non si fa e non si può: il trigger e i
  privilegi lo impediscono, ed è il cardine su cui poggia tutto il resto. Le
  righe di accesso già presenti restano dove sono; smettono solo di
  aumentare. Chi vuole liberare davvero quello spazio passa dalla procedura di
  archiviazione della §10, che è un'operazione dichiarata e non una `DELETE`
  di comodo.

- **Tenere `auth.logout` e togliere solo l'accesso.** Sarebbe metà evidenza —
  uscite senza entrate — al costo di quasi altrettante righe.

## Conseguenze

Una domanda che prima si rispondeva con una query sola su `audit_log` adesso
ne richiede una su `sessions`. La pagina «Audit» dell'amministrazione mostra
meno rumore: restano le operazioni e i tentativi falliti, che è ciò che si
cerca aprendo quella pagina.

Effetto secondario voluto, che sistema un difetto vero: un utente creato e mai
usato per lavorare adesso non ha più righe che lo citano, quindi si può
davvero togliere dal database (vedi l'aggiornamento all'[ADR
0007](0007-eliminazione-utenti.md)). Prima bastava un login per rendere
quell'account eterno.
