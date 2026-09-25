"""Le operazioni di magazzino si possono ripetere senza registrarle due volte.

Il browser mandava già un'intestazione `Idempotency-Key` sulle ricezioni, ma
il server la ignorava: la stessa ricezione di merce sfusa mandata due volte —
un doppio invio, una risposta persa sulla rete e il pulsante premuto di nuovo —
registrava due carichi, in un registro che per progetto non si può cancellare.
Il beta test l'ha misurato: dieci cavi ricevuti, venti in giacenza.

Questa tabella tiene le chiavi già usate, per utente, con la risposta data la
prima volta. La riga si scrive nella stessa transazione dei movimenti, quindi
non esiste un momento in cui l'operazione è registrata e la chiave no.

Non è una tabella di registro: le righe servono solo finché una ripetizione
è plausibile, e dopo una settimana si cancellano (`main.py`). Per questo il
ruolo applicativo può cancellarle, a differenza di `stock_movements` e
`audit_log`.

Revision ID: 0009
Revises: 0008
Create Date: 2026-09-25

"""
from typing import Sequence, Union

from alembic import op

revision: str = "0009"
down_revision: Union[str, None] = "0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Nessun vincolo verso `users`: la tabella non deve comparire fra i
    # riferimenti che impediscono di rimuovere definitivamente un account.
    op.execute(
        """
        CREATE TABLE idempotency_keys (
            user_id       UUID NOT NULL,
            key           VARCHAR(200) NOT NULL,
            route         TEXT NOT NULL,
            request_hash  VARCHAR(64) NOT NULL,
            status_code   INTEGER,
            response      JSONB,
            created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (user_id, key)
        )
        """
    )
    op.execute("CREATE INDEX idx_idempotency_created ON idempotency_keys (created_at)")
    op.execute(
        "GRANT SELECT, INSERT, UPDATE, DELETE ON idempotency_keys TO netstock_app"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS idempotency_keys")
