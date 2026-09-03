"""Utenti eliminabili: `deleted_at` sulla tabella `users`.

Un utente che ha già fatto qualcosa non si può togliere dal database: ogni
riga di `stock_movements`, `audit_log`, `delivery_notes`, `reservations` punta
a chi l'ha scritta con ON DELETE RESTRICT, e le prime due tabelle sono
append-only per trigger. Cancellare davvero quell'utente vorrebbe dire o
rompere il vincolo, o riscrivere il registro: nessuna delle due è accettabile.

`deleted_at` è la terza strada: l'account sparisce dall'elenco e non può più
accedere, mentre le righe che porta la sua firma restano leggibili. Chi non ha
mai scritto niente viene invece rimosso davvero — la colonna non lo riguarda.

Revision ID: 0003
Revises: 0002
Create Date: 2026-08-31

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))
    # L'elenco degli utenti esclude gli eliminati a ogni caricamento: l'indice
    # parziale copre esattamente le righe che restano.
    op.execute("CREATE INDEX idx_users_active ON users (username) WHERE deleted_at IS NULL")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_users_active")
    op.drop_column("users", "deleted_at")
