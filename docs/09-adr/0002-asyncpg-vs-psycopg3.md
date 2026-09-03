# ADR 0002 — Driver PostgreSQL: asyncpg invece di psycopg3
Data: 2026-08-26 · Stato: accettato

## Contesto

Il backend è FastAPI + SQLAlchemy async. Serve un driver DBAPI asincrono per PostgreSQL. Il candidato più moderno, `psycopg3` (modalità async), è licenziato **LGPL-3.0**. Il progetto opera sotto un vincolo di audit che vieta LGPL senza un ADR esplicito che ne giustifichi l'uso (§2.3).

## Decisione

Si usa **`asyncpg`** (licenza Apache-2.0) come driver, tramite l'URL SQLAlchemy `postgresql+asyncpg://`. Nessuna dipendenza LGPL è introdotta per l'accesso al database.

## Alternative considerate

- **`psycopg3` (async)**: driver maturo e con buon supporto SQLAlchemy 2.0, ma LGPL-3.0. Introdurlo avrebbe richiesto un ADR di eccezione e una verifica di linking dinamico da rifare a ogni release — costo di conformità continuo per un progetto il cui intero scopo è essere auditabile senza sforzo.
- **`psycopg2` (sync) dietro un adattatore async**: scartata, non c'è motivo di introdurre un livello di compatibilità quando esiste un driver nativamente async con licenza pulita.

## Conseguenze

Positive: nessuna dipendenza LGPL nel percorso critico (connessione al database), whitelist di licenze rispettata senza eccezioni, `asyncpg` è generalmente più veloce di `psycopg3` nei benchmark pubblici per carichi OLTP semplici come quelli di NetStock.

Negative: `asyncpg` ha una tipizzazione dei parametri più rigida di `psycopg` — ad esempio richiede cast espliciti (`CAST(:param AS text)`) quando un parametro può essere `NULL` senza altro contesto per inferirne il tipo in una query con più rami opzionali. Va tenuto presente scrivendo query SQL dirette (viste, filtri opzionali).
