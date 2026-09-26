"""Le prenotazioni escono dal prodotto.

**Prenotazioni.** In questo magazzino non servono: la merce si riceve, si
sposta e si consegna, non si impegna in anticipo. La funzione esisteva solo
nell'API — nessuna pagina l'ha mai offerta — e il beta test ha trovato che
accettava prenotazioni oltre la giacenza senza un avviso. Invece di
correggere una funzione che nessuno usa, si toglie.

La disponibilità era «giacenza meno prenotato»: senza prenotazioni è la
giacenza, e tenere due colonne sempre uguali inviterebbe a chiedersi quale
guardare. La vista resta una, con la sola giacenza.

La migrazione **si rifiuta** se trova prenotazioni o pezzi prenotati, invece
di cancellarli: toglierli è una decisione, non un effetto collaterale di un
aggiornamento. Il valore «reserved» resta nel tipo `unit_status`: toglierlo
vorrebbe dire ricostruire la colonna degli stati sotto le viste che la usano,
un rischio senza guadagno visto che nessun percorso lo imposta più.

**Nessuna riga esistente viene cancellata.** L'unica tabella tolta è
`reservations`, e solo dopo aver verificato — con un lucchetto che impedisce
scritture fra la verifica e l'eliminazione — che sia vuota. Una prima stesura
cancellava anche `warranty_alert_days` da `app_settings`: una riga che nessuna
versione del codice ha mai letto né creato. Inerte, ma pur sempre una riga
esistente: la garanzia «l'aggiornamento non cancella dati» vale di più di una
tabella in ordine, e la riga resta dov'è.

Revision ID: 0010
Revises: 0009
Create Date: 2026-09-26

"""
from typing import Sequence, Union

from alembic import op

revision: str = "0010"
down_revision: Union[str, None] = "0009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_VISTA_SENZA_PRENOTAZIONI = """
    CREATE VIEW v_item_availability AS
    SELECT ci.id AS catalog_item_id,
           ci.part_number,
           ci.name,
           v.code AS vendor_code,
           c.code AS category_code,
           ci.is_serialized,
           ci.reorder_point,
           COALESCE(sum(sb.quantity), 0::numeric) AS qty_on_hand,
           ci.reorder_point IS NOT NULL
               AND COALESCE(sum(sb.quantity), 0::numeric) <= ci.reorder_point::numeric
               AS below_reorder_point
    FROM catalog_items ci
    JOIN vendors v ON v.id = ci.vendor_id
    JOIN categories c ON c.id = ci.category_id
    LEFT JOIN v_stock_balance sb ON sb.catalog_item_id = ci.id
    GROUP BY ci.id, ci.part_number, ci.name, v.code, c.code, ci.is_serialized, ci.reorder_point
"""

_VISTA_CON_PRENOTAZIONI = """
    CREATE VIEW v_item_availability AS
    SELECT ci.id AS catalog_item_id,
           ci.part_number,
           ci.name,
           v.code AS vendor_code,
           c.code AS category_code,
           ci.is_serialized,
           ci.reorder_point,
           COALESCE(sum(sb.quantity), 0::numeric) AS qty_on_hand,
           COALESCE(res.qty_reserved, 0::numeric) AS qty_reserved,
           COALESCE(sum(sb.quantity), 0::numeric) - COALESCE(res.qty_reserved, 0::numeric)
               AS qty_available,
           ci.reorder_point IS NOT NULL
               AND (COALESCE(sum(sb.quantity), 0::numeric) - COALESCE(res.qty_reserved, 0::numeric))
                   <= ci.reorder_point::numeric AS below_reorder_point
    FROM catalog_items ci
    JOIN vendors v ON v.id = ci.vendor_id
    JOIN categories c ON c.id = ci.category_id
    LEFT JOIN v_stock_balance sb ON sb.catalog_item_id = ci.id
    LEFT JOIN (
        SELECT catalog_item_id, sum(quantity) AS qty_reserved
        FROM reservations WHERE status = 'open'::reservation_status
        GROUP BY catalog_item_id
    ) res ON res.catalog_item_id = ci.id
    GROUP BY ci.id, ci.part_number, ci.name, v.code, c.code, ci.is_serialized, ci.reorder_point,
             res.qty_reserved
"""


def upgrade() -> None:
    op.execute(
        """
        DO $$
        DECLARE
            prenotazioni integer;
            prenotati integer;
        BEGIN
            -- Il lucchetto rende la verifica una garanzia: fino alla fine
            -- della transazione nessuno può inserire una prenotazione o
            -- prenotare un pezzo, quindi quello che si elimina più sotto è
            -- esattamente quello che si è contato qui — cioè niente.
            LOCK TABLE reservations, stock_units IN SHARE ROW EXCLUSIVE MODE;
            SELECT count(*) INTO prenotazioni FROM reservations;
            SELECT count(*) INTO prenotati FROM stock_units WHERE status = 'reserved';
            IF prenotazioni > 0 OR prenotati > 0 THEN
                RAISE EXCEPTION
                    'Ci sono % prenotazioni e % pezzi prenotati: la migrazione non li '
                    'cancella da sola. Chiudile o annullale, poi riprova.',
                    prenotazioni, prenotati;
            END IF;
        END $$;
        """
    )
    op.execute("DROP VIEW v_item_availability")
    op.execute(_VISTA_SENZA_PRENOTAZIONI)
    # Una vista ricreata perde i permessi: senza questa riga il ruolo
    # dell'applicazione non la leggerebbe più, e dashboard e giacenze
    # cadrebbero al primo avvio dopo l'aggiornamento.
    op.execute("GRANT SELECT ON v_item_availability TO netstock_app")
    op.execute("DROP TABLE reservations")
    op.execute("DROP TYPE reservation_status")


def downgrade() -> None:
    op.execute("CREATE TYPE reservation_status AS ENUM ('open', 'fulfilled', 'cancelled', 'expired')")
    op.execute(
        """
        CREATE TABLE reservations (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            catalog_item_id UUID NOT NULL REFERENCES catalog_items(id) ON DELETE RESTRICT,
            stock_unit_id   UUID REFERENCES stock_units(id) ON DELETE RESTRICT,
            quantity        NUMERIC(12,2) NOT NULL CHECK (quantity > 0),
            location_id     UUID REFERENCES locations(id) ON DELETE RESTRICT,
            reference       TEXT NOT NULL,
            requested_by    TEXT NOT NULL,
            status          reservation_status NOT NULL DEFAULT 'open',
            expires_at      DATE,
            fulfilled_movement_id UUID REFERENCES stock_movements(id) ON DELETE RESTRICT,
            notes           TEXT,
            created_by      UUID NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("CREATE INDEX idx_res_open ON reservations(catalog_item_id) WHERE status = 'open'")
    op.execute("CREATE INDEX idx_res_unit ON reservations(stock_unit_id) WHERE status = 'open'")
    op.execute(
        "CREATE TRIGGER trg_reservations_updated BEFORE UPDATE ON reservations "
        "FOR EACH ROW EXECUTE FUNCTION set_updated_at()"
    )
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON reservations TO netstock_app")
    op.execute("DROP VIEW v_item_availability")
    op.execute(_VISTA_CON_PRENOTAZIONI)
    # Gli stessi permessi che la vista aveva prima: la 0001 li dava con
    # «ON ALL TABLES», che include le viste. Scrivere in una vista con
    # GROUP BY è impossibile comunque, ma tornare indietro deve voler dire
    # tornare esattamente a com'era, permessi compresi.
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON v_item_availability TO netstock_app")
