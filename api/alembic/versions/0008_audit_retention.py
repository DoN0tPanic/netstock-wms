"""Conservazione del registro di controllo: dodici mesi, poi si cancella.

`audit_log` è append-only e lo è per due barriere: il ruolo applicativo non ha
il permesso di cancellare, e un trigger rifiuta comunque `UPDATE` e `DELETE` —
anche al proprietario della tabella. Una conservazione a tempo va in conflitto
con la seconda, e il modo sbagliato di risolverlo sarebbe disattivare il
trigger mentre si cancella: fra il `DISABLE` e l'`ENABLE` la tabella resta
scoperta, e se il processo muore lì in mezzo ci resta.

Il modo giusto è **scrivere la regola dentro il trigger**: una riga si può
cancellare solo se è più vecchia della finestra di conservazione *e* solo
mentre è in corso una pulizia dichiarata. Ogni altra cancellazione, e
qualunque modifica, restano rifiutate come prima. La garanzia non diventa «si
può cancellare»: diventa «si può cancellare solo ciò che è scaduto, e solo
dicendolo».

`stock_movements` non è toccato e continua a usare `prevent_mutation()`: il
registro dei movimenti **è** la giacenza, non un registro di controllo, e non
ha nessuna conservazione a tempo. Le due tabelle avevano la stessa funzione;
da qui in poi no, ed è voluto — una modifica alla conservazione dell'audit non
deve poter arrivare per sbaglio al ledger.

Revision ID: 0008
Revises: 0007
Create Date: 2026-09-04

"""
from typing import Sequence, Union

from alembic import op

revision: str = "0008"
down_revision: Union[str, None] = "0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION audit_log_immutable() RETURNS trigger AS $$
        DECLARE
            finestra text := current_setting('netstock.audit_retention', true);
        BEGIN
            -- L'unico varco: una cancellazione dichiarata, su una riga già
            -- scaduta. `current_setting(..., true)` torna NULL se la
            -- variabile non è impostata, quindi una sessione qualunque non
            -- passa di qui nemmeno per sbaglio.
            IF TG_OP = 'DELETE'
               AND current_setting('netstock.pulizia_audit', true) = 'in-corso'
               AND finestra IS NOT NULL AND finestra <> ''
               AND OLD.ts < now() - finestra::interval THEN
                RETURN OLD;
            END IF;
            RAISE EXCEPTION
                'La tabella audit_log è append-only: % non consentita '
                '(la conservazione a tempo passa dalla pulizia dichiarata)',
                TG_OP;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute("DROP TRIGGER IF EXISTS trg_audit_immutable ON audit_log")
    op.execute(
        """
        CREATE TRIGGER trg_audit_immutable
        BEFORE DELETE OR UPDATE ON audit_log
        FOR EACH ROW EXECUTE FUNCTION audit_log_immutable()
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_audit_immutable ON audit_log")
    op.execute(
        """
        CREATE TRIGGER trg_audit_immutable
        BEFORE DELETE OR UPDATE ON audit_log
        FOR EACH ROW EXECUTE FUNCTION prevent_mutation()
        """
    )
    op.execute("DROP FUNCTION IF EXISTS audit_log_immutable()")
