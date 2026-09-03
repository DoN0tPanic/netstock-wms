"""Archivio dei documenti: le bolle scansionate, cercabili per contenuto.

Fin qui i documenti attraversavano il sistema senza fermarsi: §7.5 dice che le
immagini non toccano mai un volume persistente, e serviva a impedire che i
dati di un cliente restassero su disco per svista. Questo archivio è un'altra
cosa e va detto chiaramente: qui i documenti si conservano **apposta**, perché
qualcuno ha deciso di conservarli.

Due scelte che hanno conseguenze.

**Il PDF sta nel database, non su un volume.** Un file su disco è più leggero
per il database e più pesante per tutto il resto: il backup notturno copia il
database e non i volumi, quindi al primo ripristino l'archivio risulterebbe
vuoto — con i riferimenti ancora al loro posto, che è il modo peggiore di
accorgersene. Dentro il database, copia e ripristino continuano a valere per
tutto. Il prezzo è che i dump crescono con l'archivio, e va tenuto d'occhio:
la pagina Impostazioni mostra quanto pesa ogni tabella.

**Il testo si indicizza con la configurazione `simple`.** Quella italiana
riduce le parole alla radice, il che aiuta con «bolle» e «bolla» ma rovina
proprio ciò che si cerca qui: un numero d'ordine, un codice cliente, una
matricola. `simple` non stemma e non toglie nulla, quindi «DEMO-4471» resta
«DEMO-4471».

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-03

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "documents",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("filename", sa.Text(), nullable=False),
        sa.Column("mime_type", sa.Text(), nullable=False),
        sa.Column("byte_size", sa.BigInteger(), nullable=False),
        # L'impronta del contenuto: lo stesso PDF caricato due volte è lo
        # stesso documento, anche se il nome del file cambia. Chi scansiona
        # ricarica per sbaglio più spesso di quanto ammetta.
        sa.Column("sha256", sa.Text(), nullable=False, unique=True),
        sa.Column("pages", sa.Integer()),
        sa.Column("content", postgresql.BYTEA(), nullable=False),
        sa.Column("extracted_text", sa.Text(), nullable=False, server_default=""),
        # Come è stato letto il testo: dal livello di testo del PDF, oppure
        # con l'OCR perché era una scansione. Serve a spiegare una ricerca
        # che non trova: su una scansione storta l'OCR sbaglia, e saperlo
        # cambia cosa si fa dopo.
        sa.Column("extraction_method", sa.Text(), nullable=False, server_default="none"),
        sa.Column("notes", sa.Text()),
        # Collegamento facoltativo alla bolla registrata. Facoltativo perché
        # si archivia anche ciò che non è ancora stato registrato, ed è
        # proprio il caso in cui serve ritrovarlo.
        sa.Column(
            "delivery_note_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("delivery_notes.id", ondelete="SET NULL"),
        ),
        sa.Column(
            "uploaded_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "uploaded_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )

    # Il vettore di ricerca è **generato**: non esiste un percorso in cui il
    # testo cambia e l'indice resta indietro, perché non c'è codice
    # applicativo che lo aggiorni. Comprende anche il nome del file: chi
    # cerca «pdf123» deve trovarlo come chi cerca quello che c'è dentro.
    op.execute(
        """
        ALTER TABLE documents
        ADD COLUMN search_vector tsvector
        GENERATED ALWAYS AS (
            to_tsvector('simple', coalesce(filename, '') || ' ' ||
                                  coalesce(extracted_text, '') || ' ' ||
                                  coalesce(notes, ''))
        ) STORED
        """
    )
    op.execute("CREATE INDEX idx_documents_search ON documents USING GIN (search_vector)")
    # Ricerca per frammento: un numero d'ordine si ricorda a metà più spesso
    # che per intero, e la ricerca a parole intere lì non aiuta.
    op.execute(
        "CREATE INDEX idx_documents_text_trgm ON documents "
        "USING GIN (extracted_text gin_trgm_ops)"
    )
    op.execute("CREATE INDEX idx_documents_uploaded ON documents (uploaded_at DESC)")
    op.execute("CREATE INDEX idx_documents_note ON documents (delivery_note_id)")

    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON documents TO netstock_app")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS documents")
