# ADR 0003 — Sessioni server-side invece di JWT
Data: 2026-08-26 · Stato: accettato

## Contesto

NetStock ha 5-15 utenti, 1-3 concorrenti, un solo processo API, nessun bisogno di scaling orizzontale (§1.4). Serve un meccanismo di autenticazione che permetta la **revoca immediata** di una sessione (utente disattivato, sospetto di compromissione, logout) e che riduca la superficie di attacco lato browser.

## Decisione

Autenticazione via **sessione server-side**: al login viene generato un token opaco casuale (32 byte, `secrets.token_urlsafe`), di cui solo lo **SHA-256** è salvato in `sessions.token_hash` — il token in chiaro non è mai persistito. Il token viaggia in un cookie `netstock_session` con `httpOnly`, `Secure`, `SameSite=Strict`, mai in `localStorage`. Ogni richiesta autenticata rinnova la scadenza (durata scorrevole di 12 ore). Il logout e la disattivazione di un utente revocano la sessione lato server in modo immediato.

## Alternative considerate

- **JWT stateless**: scartato. Un JWT firmato non è revocabile prima della scadenza senza mantenere comunque uno stato server-side (blocklist), che vanifica il vantaggio di essere stateless. Per 1-3 utenti concorrenti non c'è alcun beneficio di scalabilità da guadagnare, mentre si perde la revoca immediata — rilevante per un sistema con requisiti di audit e tracciabilità (§V4).
- **Token in `localStorage`**: scartato per esposizione a XSS; il cookie `httpOnly` non è leggibile da JavaScript.

## Conseguenze

Positive: revoca istantanea di una sessione; nessun segreto applicativo lato client oltre al cookie opaco; superficie di attacco XSS ridotta (il token non è mai accessibile a script).

Negative: ogni richiesta autenticata comporta una query sulla tabella `sessions` (accettabile al volume atteso: 1-3 utenti concorrenti, query indicizzata su `token_hash`); il meccanismo non scala orizzontalmente a più processi API senza uno store di sessioni condiviso — non è un problema per il perimetro di v1.0 (un solo container `api`).
