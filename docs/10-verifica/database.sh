#!/usr/bin/env bash
# Il database non si verifica leggendo lo schema: si verifica provando a
# violarlo. Qui si tenta di fare ciò che il progetto dichiara impossibile.
set -uo pipefail
cd "$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
psql_app() { docker compose exec -T db psql -U netstock -d netstock -Atc "$1" 2>&1; }
FALLITI=0
esito() { # etichetta, condizione
  if [ "$2" = "1" ]; then echo "  OK      $1"; else FALLITI=$((FALLITI+1)); echo "  FALLITO $1"; fi
}

echo "== Integrità dello schema =="
echo "  revisione: $(psql_app "SELECT version_num FROM alembic_version")"
echo "  tabelle: $(psql_app "SELECT count(*) FROM pg_tables WHERE schemaname='public'") · viste: $(psql_app "SELECT count(*) FROM pg_views WHERE schemaname='public'")"
echo "  indici: $(psql_app "SELECT count(*) FROM pg_indexes WHERE schemaname='public'") · vincoli FK: $(psql_app "SELECT count(*) FROM pg_constraint WHERE contype='f'")"
esito "nessun vincolo FK non validato" "$([ "$(psql_app "SELECT count(*) FROM pg_constraint WHERE contype='f' AND NOT convalidated")" = "0" ] && echo 1)"

echo
echo "== Il registro è davvero append-only =="
# Si prova a modificare e a cancellare un movimento con l'utenza applicativa.
R=$(docker compose exec -T db psql -U netstock_app -d netstock -Atc "UPDATE stock_movements SET quantity = 999 WHERE id = (SELECT id FROM stock_movements LIMIT 1)" 2>&1)
esito "UPDATE su stock_movements rifiutato ($(echo "$R" | head -1 | cut -c1-60))" "$(echo "$R" | grep -qiE 'denied|permission|not allowed|append-only|immutab' && echo 1)"
R=$(docker compose exec -T db psql -U netstock_app -d netstock -Atc "DELETE FROM stock_movements WHERE id = (SELECT id FROM stock_movements LIMIT 1)" 2>&1)
esito "DELETE su stock_movements rifiutato ($(echo "$R" | head -1 | cut -c1-60))" "$(echo "$R" | grep -qiE 'denied|permission|not allowed|append-only|immutab' && echo 1)"
R=$(docker compose exec -T db psql -U netstock_app -d netstock -Atc "DELETE FROM audit_log WHERE id = (SELECT id FROM audit_log LIMIT 1)" 2>&1)
esito "DELETE su audit_log rifiutato ($(echo "$R" | head -1 | cut -c1-60))" "$(echo "$R" | grep -qiE 'denied|permission|not allowed|append-only|immutab' && echo 1)"
# E anche con l'utenza proprietaria, dove a fermare è il trigger e non i permessi.
R=$(psql_app "UPDATE stock_movements SET quantity = 999 WHERE id = (SELECT id FROM stock_movements LIMIT 1)")
esito "UPDATE rifiutato anche al proprietario, dal trigger ($(echo "$R" | head -1 | cut -c1-50))" "$(echo "$R" | grep -qiE 'append|immutab|not allowed|consentit' && echo 1)"

echo
echo "== Giacenza e proiezione coincidono =="
DIV=$(psql_app "SELECT count(*) FROM v_reconciliation_errors")
esito "nessuna divergenza fra ledger e proiezione (trovate: $DIV)" "$([ "$DIV" = "0" ] && echo 1)"
echo "  giacenza dalla vista: $(psql_app "SELECT coalesce(sum(quantity),0) FROM v_stock_balance") pezzi"
echo "  unità in magazzino:   $(psql_app "SELECT count(*) FROM stock_units WHERE status='in_stock'")"

echo
echo "== Separazione dei database =="
echo "  database presenti: $(psql_app "SELECT string_agg(datname,', ') FROM pg_database WHERE datname LIKE 'netstock%'")"
P=$(psql_app "SELECT count(*) FROM users"); T=$(docker compose exec -T db psql -U netstock -d netstock_test -Atc "SELECT count(*) FROM users" 2>/dev/null)
esito "produzione e prova sono separati (utenti: $P contro $T)" "$([ "$P" != "$T" ] || [ -n "$T" ] && echo 1)"

echo
echo "== Permessi dell'utenza applicativa =="
for t in stock_movements audit_log; do
  for p in UPDATE DELETE; do
    HA=$(psql_app "SELECT has_table_privilege('netstock_app','$t','$p')")
    esito "netstock_app NON ha $p su $t (ha: $HA)" "$([ "$HA" = "f" ] && echo 1)"
  done
done
echo "  netstock_app può inserire in stock_movements: $(psql_app "SELECT has_table_privilege('netstock_app','stock_movements','INSERT')")"
echo
echo "  totale: $FALLITI verifiche fallite"
exit "$FALLITI"
