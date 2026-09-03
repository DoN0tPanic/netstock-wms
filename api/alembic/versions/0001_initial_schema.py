"""Initial schema: extensions, enums, tables, indexes, triggers, views, roles.

Revision ID: 0001
Revises:
Create Date: 2026-08-26

"""
import os
from typing import Sequence, Union

from alembic import op

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _split_sql(script: str) -> list[str]:
    """Splits a script into individual statements on top-level semicolons.

    asyncpg's extended query protocol (used by SQLAlchemy's async dialect)
    rejects multiple commands in one prepared statement, unlike psycopg2.
    Dollar-quoted function bodies (`$$ ... $$`) contain internal semicolons
    that must not be treated as statement boundaries.
    """
    statements: list[str] = []
    buffer: list[str] = []
    in_dollar_quote = False
    i = 0
    while i < len(script):
        if script[i : i + 2] == "$$":
            in_dollar_quote = not in_dollar_quote
            buffer.append("$$")
            i += 2
            continue
        char = script[i]
        if char == ";" and not in_dollar_quote:
            statements.append("".join(buffer))
            buffer = []
        else:
            buffer.append(char)
        i += 1
    tail = "".join(buffer).strip()
    if tail:
        statements.append(tail)
    return [s.strip() for s in statements if s.strip()]


def upgrade() -> None:
    app_db_password = os.environ.get("APP_DB_PASSWORD")
    if not app_db_password:
        raise RuntimeError(
            "APP_DB_PASSWORD non impostata: richiesta per creare il ruolo runtime netstock_app."
        )

    schema_sql = """
        -- ============================================================
        -- Estensioni
        -- ============================================================
        CREATE EXTENSION IF NOT EXISTS pg_trgm;
        CREATE EXTENSION IF NOT EXISTS pgcrypto;
        CREATE EXTENSION IF NOT EXISTS citext;

        -- ============================================================
        -- Tipi enumerati
        -- ============================================================
        CREATE TYPE user_role        AS ENUM ('viewer', 'operator', 'admin');
        CREATE TYPE location_type    AS ENUM ('warehouse', 'shelf', 'box', 'remote_site', 'transit');
        CREATE TYPE item_condition   AS ENUM ('new', 'refurbished', 'used', 'faulty');
        CREATE TYPE unit_status      AS ENUM ('in_stock', 'reserved', 'issued', 'in_rma', 'scrapped', 'lost');
        CREATE TYPE movement_type    AS ENUM ('receipt', 'issue', 'transfer', 'return',
                                              'rma_out', 'rma_in', 'adjustment', 'scrap');
        CREATE TYPE reservation_status AS ENUM ('open', 'fulfilled', 'cancelled', 'expired');
        CREATE TYPE template_doc_type  AS ENUM ('device_label', 'box_label', 'delivery_note', 'packing_list');

        -- ============================================================
        -- Utenti e autenticazione
        -- ============================================================
        CREATE TABLE users (
            id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            username            CITEXT NOT NULL UNIQUE,
            email               CITEXT,
            full_name           TEXT NOT NULL,
            role                user_role NOT NULL DEFAULT 'viewer',
            password_hash       TEXT,
            auth_provider       TEXT NOT NULL DEFAULT 'local',
            is_active           BOOLEAN NOT NULL DEFAULT TRUE,
            must_change_password BOOLEAN NOT NULL DEFAULT FALSE,
            failed_attempts     INTEGER NOT NULL DEFAULT 0,
            locked_until        TIMESTAMPTZ,
            last_login_at       TIMESTAMPTZ,
            created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
        );

        CREATE TABLE sessions (
            id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id       UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            token_hash    TEXT NOT NULL UNIQUE,
            issued_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
            expires_at    TIMESTAMPTZ NOT NULL,
            revoked_at    TIMESTAMPTZ,
            ip_address    INET,
            user_agent    TEXT
        );
        CREATE INDEX idx_sessions_user   ON sessions(user_id) WHERE revoked_at IS NULL;
        CREATE INDEX idx_sessions_expiry ON sessions(expires_at);

        -- ============================================================
        -- Anagrafiche
        -- ============================================================
        CREATE TABLE vendors (
            id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            code        TEXT NOT NULL UNIQUE,
            name        TEXT NOT NULL,
            notes       TEXT,
            is_active   BOOLEAN NOT NULL DEFAULT TRUE,
            created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
        );

        CREATE TABLE categories (
            id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            code        TEXT NOT NULL UNIQUE,
            name        TEXT NOT NULL,
            parent_id   UUID REFERENCES categories(id) ON DELETE RESTRICT,
            created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
        );

        CREATE TABLE suppliers (
            id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            name        TEXT NOT NULL UNIQUE,
            vat_number  TEXT,
            contact_ref TEXT,
            notes       TEXT,
            is_active   BOOLEAN NOT NULL DEFAULT TRUE,
            created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
        );

        CREATE TABLE locations (
            id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            code        TEXT NOT NULL UNIQUE,
            name        TEXT NOT NULL,
            type        location_type NOT NULL,
            parent_id   UUID REFERENCES locations(id) ON DELETE RESTRICT,
            address     TEXT,
            is_active   BOOLEAN NOT NULL DEFAULT TRUE,
            created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        CREATE INDEX idx_locations_parent ON locations(parent_id);

        -- ============================================================
        -- Catalogo articoli
        -- ============================================================
        CREATE TABLE catalog_items (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            vendor_id       UUID NOT NULL REFERENCES vendors(id) ON DELETE RESTRICT,
            category_id     UUID NOT NULL REFERENCES categories(id) ON DELETE RESTRICT,
            part_number     TEXT NOT NULL,
            name            TEXT NOT NULL,
            description     TEXT,
            is_serialized   BOOLEAN NOT NULL DEFAULT TRUE,
            uom             TEXT NOT NULL DEFAULT 'PZ',
            reorder_point   INTEGER,
            eol_date        DATE,
            eos_date        DATE,
            serial_pattern  TEXT,
            notes           TEXT,
            is_active       BOOLEAN NOT NULL DEFAULT TRUE,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_catalog_vendor_pn UNIQUE (vendor_id, part_number)
        );
        CREATE INDEX idx_catalog_pn_trgm  ON catalog_items USING gin (part_number gin_trgm_ops);
        CREATE INDEX idx_catalog_name_trgm ON catalog_items USING gin (name gin_trgm_ops);
        CREATE INDEX idx_catalog_category ON catalog_items(category_id);
        CREATE INDEX idx_catalog_active   ON catalog_items(is_active) WHERE is_active;

        -- ============================================================
        -- Bolle di consegna (DDT)
        -- ============================================================
        CREATE TABLE delivery_notes (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            number          TEXT NOT NULL,
            note_date       DATE NOT NULL,
            supplier_id     UUID NOT NULL REFERENCES suppliers(id) ON DELETE RESTRICT,
            po_number       TEXT,
            carrier         TEXT,
            tracking_number TEXT,
            received_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
            received_by     UUID NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
            is_closed       BOOLEAN NOT NULL DEFAULT FALSE,
            notes           TEXT,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_ddt_supplier_number UNIQUE (supplier_id, number)
        );
        CREATE INDEX idx_ddt_date     ON delivery_notes(note_date DESC);
        CREATE INDEX idx_ddt_number   ON delivery_notes USING gin (number gin_trgm_ops);
        CREATE INDEX idx_ddt_po       ON delivery_notes(po_number);

        CREATE TABLE delivery_note_lines (
            id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            delivery_note_id  UUID NOT NULL REFERENCES delivery_notes(id) ON DELETE RESTRICT,
            line_number       INTEGER NOT NULL,
            catalog_item_id   UUID NOT NULL REFERENCES catalog_items(id) ON DELETE RESTRICT,
            qty_expected      NUMERIC(12,2) NOT NULL CHECK (qty_expected > 0),
            qty_received      NUMERIC(12,2) NOT NULL DEFAULT 0 CHECK (qty_received >= 0),
            condition         item_condition NOT NULL DEFAULT 'new',
            notes             TEXT,
            created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_ddt_line UNIQUE (delivery_note_id, line_number)
        );
        CREATE INDEX idx_ddt_lines_note ON delivery_note_lines(delivery_note_id);
        CREATE INDEX idx_ddt_lines_item ON delivery_note_lines(catalog_item_id);

        -- ============================================================
        -- Unità serializzate
        -- ============================================================
        CREATE TABLE stock_units (
            id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            catalog_item_id       UUID NOT NULL REFERENCES catalog_items(id) ON DELETE RESTRICT,
            serial_number         TEXT NOT NULL,
            mac_address           MACADDR,
            status                unit_status NOT NULL DEFAULT 'in_stock',
            condition             item_condition NOT NULL DEFAULT 'new',
            location_id           UUID REFERENCES locations(id) ON DELETE RESTRICT,
            delivery_note_line_id UUID REFERENCES delivery_note_lines(id) ON DELETE RESTRICT,
            purchase_date         DATE,
            warranty_end          DATE,
            contract_ref          TEXT,
            notes                 TEXT,
            created_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_unit_item_serial UNIQUE (catalog_item_id, serial_number)
        );
        CREATE INDEX idx_units_serial_trgm ON stock_units USING gin (serial_number gin_trgm_ops);
        CREATE INDEX idx_units_serial_upper ON stock_units (upper(serial_number));
        CREATE INDEX idx_units_item        ON stock_units(catalog_item_id);
        CREATE INDEX idx_units_location    ON stock_units(location_id) WHERE status = 'in_stock';
        CREATE INDEX idx_units_status      ON stock_units(status);
        CREATE INDEX idx_units_mac         ON stock_units(mac_address) WHERE mac_address IS NOT NULL;
        CREATE INDEX idx_units_warranty    ON stock_units(warranty_end) WHERE warranty_end IS NOT NULL;

        -- ============================================================
        -- Ledger movimenti — APPEND ONLY
        -- ============================================================
        CREATE TABLE stock_movements (
            id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            occurred_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
            type              movement_type NOT NULL,
            catalog_item_id   UUID NOT NULL REFERENCES catalog_items(id) ON DELETE RESTRICT,
            stock_unit_id     UUID REFERENCES stock_units(id) ON DELETE RESTRICT,
            quantity          NUMERIC(12,2) NOT NULL CHECK (quantity > 0),
            condition         item_condition NOT NULL DEFAULT 'new',
            location_from_id  UUID REFERENCES locations(id) ON DELETE RESTRICT,
            location_to_id    UUID REFERENCES locations(id) ON DELETE RESTRICT,
            delivery_note_id  UUID REFERENCES delivery_notes(id) ON DELETE RESTRICT,
            reference         TEXT,
            assignee          TEXT,
            reason            TEXT,
            reverses_id       UUID REFERENCES stock_movements(id) ON DELETE RESTRICT,
            performed_by      UUID NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
            notes             TEXT,
            created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ck_movement_has_direction
                CHECK (location_from_id IS NOT NULL OR location_to_id IS NOT NULL),
            CONSTRAINT ck_movement_not_self
                CHECK (location_from_id IS DISTINCT FROM location_to_id
                       OR location_from_id IS NULL),
            CONSTRAINT ck_serialized_qty
                CHECK (stock_unit_id IS NULL OR quantity = 1)
        );
        CREATE INDEX idx_mov_item_time  ON stock_movements(catalog_item_id, occurred_at DESC);
        CREATE INDEX idx_mov_unit_time  ON stock_movements(stock_unit_id, occurred_at DESC);
        CREATE INDEX idx_mov_time       ON stock_movements(occurred_at DESC);
        CREATE INDEX idx_mov_ddt        ON stock_movements(delivery_note_id);
        CREATE INDEX idx_mov_from       ON stock_movements(location_from_id);
        CREATE INDEX idx_mov_to         ON stock_movements(location_to_id);
        CREATE INDEX idx_mov_reference  ON stock_movements USING gin (reference gin_trgm_ops);

        -- ============================================================
        -- Prenotazioni
        -- ============================================================
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
        );
        CREATE INDEX idx_res_open ON reservations(catalog_item_id) WHERE status = 'open';
        CREATE INDEX idx_res_unit ON reservations(stock_unit_id) WHERE status = 'open';

        -- ============================================================
        -- Template di estrazione
        -- ============================================================
        CREATE TABLE extraction_templates (
            id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            name          TEXT NOT NULL UNIQUE,
            vendor_id     UUID REFERENCES vendors(id) ON DELETE RESTRICT,
            category_id   UUID REFERENCES categories(id) ON DELETE RESTRICT,
            doc_type      template_doc_type NOT NULL,
            field_specs   JSONB NOT NULL,
            llm_prompt    TEXT,
            priority      INTEGER NOT NULL DEFAULT 100,
            is_active     BOOLEAN NOT NULL DEFAULT TRUE,
            version       INTEGER NOT NULL DEFAULT 1,
            created_by    UUID NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
            created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        CREATE INDEX idx_tmpl_vendor ON extraction_templates(vendor_id) WHERE is_active;

        CREATE TABLE extraction_runs (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            ts              TIMESTAMPTZ NOT NULL DEFAULT now(),
            user_id         UUID NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
            template_id     UUID REFERENCES extraction_templates(id) ON DELETE SET NULL,
            image_count     INTEGER NOT NULL,
            image_bytes     BIGINT NOT NULL,
            engine          TEXT NOT NULL,
            fields_found    JSONB NOT NULL,
            confidence      JSONB NOT NULL,
            duration_ms     INTEGER NOT NULL,
            accepted        BOOLEAN,
            error           TEXT
        );
        CREATE INDEX idx_runs_ts ON extraction_runs(ts DESC);

        -- ============================================================
        -- Audit log — APPEND ONLY
        -- ============================================================
        CREATE TABLE audit_log (
            id              BIGSERIAL PRIMARY KEY,
            ts              TIMESTAMPTZ NOT NULL DEFAULT now(),
            actor_id        UUID REFERENCES users(id) ON DELETE RESTRICT,
            actor_username  TEXT NOT NULL,
            action          TEXT NOT NULL,
            entity_type     TEXT,
            entity_id       TEXT,
            details         JSONB NOT NULL DEFAULT '{}'::jsonb,
            ip_address      INET,
            user_agent      TEXT
        );
        CREATE INDEX idx_audit_ts     ON audit_log(ts DESC);
        CREATE INDEX idx_audit_actor  ON audit_log(actor_id, ts DESC);
        CREATE INDEX idx_audit_entity ON audit_log(entity_type, entity_id);
        CREATE INDEX idx_audit_action ON audit_log(action);

        -- ============================================================
        -- Impostazioni applicative
        -- ============================================================
        CREATE TABLE app_settings (
            key         TEXT PRIMARY KEY,
            value       JSONB NOT NULL,
            updated_by  UUID REFERENCES users(id) ON DELETE RESTRICT,
            updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
        );

        -- ============================================================
        -- Trigger: updated_at automatico
        -- ============================================================
        CREATE OR REPLACE FUNCTION set_updated_at() RETURNS TRIGGER AS $$
        BEGIN
            NEW.updated_at = now();
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;

        CREATE TRIGGER trg_users_updated BEFORE UPDATE ON users
            FOR EACH ROW EXECUTE FUNCTION set_updated_at();
        CREATE TRIGGER trg_vendors_updated BEFORE UPDATE ON vendors
            FOR EACH ROW EXECUTE FUNCTION set_updated_at();
        CREATE TRIGGER trg_categories_updated BEFORE UPDATE ON categories
            FOR EACH ROW EXECUTE FUNCTION set_updated_at();
        CREATE TRIGGER trg_suppliers_updated BEFORE UPDATE ON suppliers
            FOR EACH ROW EXECUTE FUNCTION set_updated_at();
        CREATE TRIGGER trg_locations_updated BEFORE UPDATE ON locations
            FOR EACH ROW EXECUTE FUNCTION set_updated_at();
        CREATE TRIGGER trg_catalog_items_updated BEFORE UPDATE ON catalog_items
            FOR EACH ROW EXECUTE FUNCTION set_updated_at();
        CREATE TRIGGER trg_delivery_notes_updated BEFORE UPDATE ON delivery_notes
            FOR EACH ROW EXECUTE FUNCTION set_updated_at();
        CREATE TRIGGER trg_delivery_note_lines_updated BEFORE UPDATE ON delivery_note_lines
            FOR EACH ROW EXECUTE FUNCTION set_updated_at();
        CREATE TRIGGER trg_stock_units_updated BEFORE UPDATE ON stock_units
            FOR EACH ROW EXECUTE FUNCTION set_updated_at();
        CREATE TRIGGER trg_reservations_updated BEFORE UPDATE ON reservations
            FOR EACH ROW EXECUTE FUNCTION set_updated_at();
        CREATE TRIGGER trg_extraction_templates_updated BEFORE UPDATE ON extraction_templates
            FOR EACH ROW EXECUTE FUNCTION set_updated_at();

        -- ============================================================
        -- Trigger: immutabilità di ledger e audit
        -- ============================================================
        CREATE OR REPLACE FUNCTION prevent_mutation() RETURNS TRIGGER AS $$
        BEGIN
            RAISE EXCEPTION 'La tabella % è append-only: % non consentita (usare un movimento di rettifica)',
                TG_TABLE_NAME, TG_OP;
        END;
        $$ LANGUAGE plpgsql;

        CREATE TRIGGER trg_movements_immutable
            BEFORE UPDATE OR DELETE ON stock_movements
            FOR EACH ROW EXECUTE FUNCTION prevent_mutation();

        CREATE TRIGGER trg_audit_immutable
            BEFORE UPDATE OR DELETE ON audit_log
            FOR EACH ROW EXECUTE FUNCTION prevent_mutation();

        -- ============================================================
        -- Viste di giacenza
        -- ============================================================
        CREATE VIEW v_stock_balance AS
        WITH ledger AS (
            SELECT catalog_item_id, location_to_id AS location_id, condition, quantity AS qty
            FROM stock_movements WHERE location_to_id IS NOT NULL
            UNION ALL
            SELECT catalog_item_id, location_from_id AS location_id, condition, -quantity AS qty
            FROM stock_movements WHERE location_from_id IS NOT NULL
        )
        SELECT
            l.catalog_item_id,
            l.location_id,
            l.condition,
            SUM(l.qty) AS quantity
        FROM ledger l
        GROUP BY l.catalog_item_id, l.location_id, l.condition
        HAVING SUM(l.qty) <> 0;

        CREATE VIEW v_item_availability AS
        SELECT
            ci.id                                    AS catalog_item_id,
            ci.part_number,
            ci.name,
            v.code                                   AS vendor_code,
            c.code                                   AS category_code,
            ci.is_serialized,
            ci.reorder_point,
            COALESCE(SUM(sb.quantity), 0)            AS qty_on_hand,
            COALESCE(res.qty_reserved, 0)            AS qty_reserved,
            COALESCE(SUM(sb.quantity), 0) - COALESCE(res.qty_reserved, 0) AS qty_available,
            (ci.reorder_point IS NOT NULL
                AND COALESCE(SUM(sb.quantity), 0) - COALESCE(res.qty_reserved, 0) <= ci.reorder_point
            )                                        AS below_reorder_point
        FROM catalog_items ci
        JOIN vendors v      ON v.id = ci.vendor_id
        JOIN categories c   ON c.id = ci.category_id
        LEFT JOIN v_stock_balance sb ON sb.catalog_item_id = ci.id
        LEFT JOIN (
            SELECT catalog_item_id, SUM(quantity) AS qty_reserved
            FROM reservations WHERE status = 'open'
            GROUP BY catalog_item_id
        ) res ON res.catalog_item_id = ci.id
        GROUP BY ci.id, ci.part_number, ci.name, v.code, c.code,
                 ci.is_serialized, ci.reorder_point, res.qty_reserved;

        CREATE VIEW v_reconciliation_errors AS
        SELECT
            COALESCE(led.catalog_item_id, proj.catalog_item_id) AS catalog_item_id,
            COALESCE(led.location_id, proj.location_id)         AS location_id,
            COALESCE(led.qty_ledger, 0)                         AS qty_ledger,
            COALESCE(proj.qty_projection, 0)                    AS qty_projection
        FROM (
            SELECT sb.catalog_item_id, sb.location_id, SUM(sb.quantity) AS qty_ledger
            FROM v_stock_balance sb
            JOIN catalog_items ci ON ci.id = sb.catalog_item_id AND ci.is_serialized
            GROUP BY sb.catalog_item_id, sb.location_id
        ) led
        FULL OUTER JOIN (
            SELECT su.catalog_item_id, su.location_id, COUNT(*)::NUMERIC AS qty_projection
            FROM stock_units su
            WHERE su.location_id IS NOT NULL
            GROUP BY su.catalog_item_id, su.location_id
        ) proj ON proj.catalog_item_id = led.catalog_item_id
              AND proj.location_id IS NOT DISTINCT FROM led.location_id
        WHERE COALESCE(led.qty_ledger, 0) <> COALESCE(proj.qty_projection, 0);
        """
    for statement in _split_sql(schema_sql):
        op.execute(statement)

    # Ruolo applicativo runtime: privilegi limitati, niente scrittura su ledger/audit.
    role_sql = f"""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'netstock_app') THEN
                CREATE ROLE netstock_app LOGIN PASSWORD '{app_db_password}';
            ELSE
                ALTER ROLE netstock_app WITH PASSWORD '{app_db_password}';
            END IF;
        END
        $$;

        GRANT USAGE ON SCHEMA public TO netstock_app;
        GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO netstock_app;
        GRANT SELECT ON v_stock_balance, v_item_availability, v_reconciliation_errors TO netstock_app;
        GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO netstock_app;

        REVOKE UPDATE, DELETE, TRUNCATE ON stock_movements FROM netstock_app;
        REVOKE UPDATE, DELETE, TRUNCATE ON audit_log       FROM netstock_app;
        """
    for statement in _split_sql(role_sql):
        op.execute(statement)


def downgrade() -> None:
    downgrade_sql = """
        DROP VIEW IF EXISTS v_reconciliation_errors;
        DROP VIEW IF EXISTS v_item_availability;
        DROP VIEW IF EXISTS v_stock_balance;

        DROP TABLE IF EXISTS app_settings;
        DROP TABLE IF EXISTS audit_log;
        DROP TABLE IF EXISTS extraction_runs;
        DROP TABLE IF EXISTS extraction_templates;
        DROP TABLE IF EXISTS reservations;
        DROP TABLE IF EXISTS stock_movements;
        DROP TABLE IF EXISTS stock_units;
        DROP TABLE IF EXISTS delivery_note_lines;
        DROP TABLE IF EXISTS delivery_notes;
        DROP TABLE IF EXISTS catalog_items;
        DROP TABLE IF EXISTS locations;
        DROP TABLE IF EXISTS suppliers;
        DROP TABLE IF EXISTS categories;
        DROP TABLE IF EXISTS vendors;
        DROP TABLE IF EXISTS sessions;
        DROP TABLE IF EXISTS users;

        DROP FUNCTION IF EXISTS prevent_mutation();
        DROP FUNCTION IF EXISTS set_updated_at();

        DROP TYPE IF EXISTS template_doc_type;
        DROP TYPE IF EXISTS reservation_status;
        DROP TYPE IF EXISTS movement_type;
        DROP TYPE IF EXISTS unit_status;
        DROP TYPE IF EXISTS item_condition;
        DROP TYPE IF EXISTS location_type;
        DROP TYPE IF EXISTS user_role;

        REASSIGN OWNED BY netstock_app TO CURRENT_USER;
        DROP OWNED BY netstock_app;
        DROP ROLE IF EXISTS netstock_app;
        """
    for statement in _split_sql(downgrade_sql):
        op.execute(statement)
