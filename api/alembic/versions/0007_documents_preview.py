"""L'anteprima della prima pagina di un documento archiviato.

Perché conservarla invece di ricavarla ogni volta: una griglia di venti
documenti chiederebbe venti rendering a ogni apertura di pagina, e
renderizzare un PDF costa più che leggerne il testo. Si fa una volta e resta.

Sta nel database accanto al file, per la stessa ragione del file (§0004): il
backup notturno copia il database, e un'anteprima su disco risulterebbe vuota
al primo ripristino.

Revision ID: 0007
Revises: 0006
Create Date: 2026-09-04

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: Union[str, None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("documents", sa.Column("preview", sa.LargeBinary(), nullable=True))
    # Vuoto con `preview` a NULL significa «mai provata»; valorizzato con
    # `preview` a NULL significa «provata e non riuscita», e non si riprova a
    # ogni apertura di pagina per un documento che non si lascia disegnare.
    op.add_column(
        "documents", sa.Column("preview_at", sa.DateTime(timezone=True), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("documents", "preview_at")
    op.drop_column("documents", "preview")
