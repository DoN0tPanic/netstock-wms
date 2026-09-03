"""Il fornitore di una bolla archiviata.

Perché una colonna e non una ricerca al volo: l'archivio si sfoglia per
fornitore, e contare i documenti di ognuno rileggendo il testo di tutti a ogni
apertura di pagina non è sostenibile. Il riconoscimento avviene una volta, al
caricamento, e resta scritto — insieme a **come** è avvenuto, che è ciò che
permette di fidarsi o di controllare.

Revision ID: 0006
Revises: 0005
Create Date: 2026-09-03

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: Union[str, None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "documents",
        sa.Column(
            "supplier_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("suppliers.id", ondelete="RESTRICT"),
            nullable=True,
        ),
    )
    # Come si è arrivati a quel fornitore: `piva` (la partita IVA del fornitore
    # è scritta nel documento — è una prova), `intestazione` (il nome compare
    # nella testata, è probabile), `manuale` (l'ha deciso una persona). Un
    # valore vuoto con `supplier_id` a NULL significa «mai riconosciuto», ed è
    # diverso da `manuale` con NULL, che significa «una persona ha detto che
    # non si sa»: il riesame automatico deve saltare il secondo.
    op.add_column("documents", sa.Column("supplier_source", sa.Text(), nullable=True))
    op.create_index("idx_documents_supplier", "documents", ["supplier_id"])


def downgrade() -> None:
    op.drop_index("idx_documents_supplier", table_name="documents")
    op.drop_column("documents", "supplier_source")
    op.drop_column("documents", "supplier_id")
