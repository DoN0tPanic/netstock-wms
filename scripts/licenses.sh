#!/usr/bin/env bash
# Inventario delle licenze (compliance/licenses.csv) e controllo che siano
# tutte ammesse. Le regole stanno in scripts/licenze.py, lo stesso che gira in
# CI; qui si prepara solo l'elenco dei pacchetti Python, letto dentro
# l'immagine dell'API — quella che va in produzione.
#
# Uso:  ./scripts/licenses.sh            controlla, senza cambiare file
#       ./scripts/licenses.sh --scrivi   rigenera l'inventario, poi controlla
set -euo pipefail
cd "$(dirname "$0")/.."

PYTHON_CSV=$(mktemp)
trap 'rm -f "$PYTHON_CSV"' EXIT

# `run` e non `exec`: un container nuovo dall'immagine, senza i pacchetti di
# sviluppo che un container già acceso può aver ricevuto per i test. Lo
# scanner usa solo la libreria standard: non serve installare niente, né rete.
docker compose run --rm --no-deps -T --entrypoint python api - \
  < scripts/licenze_python.py > "$PYTHON_CSV"

python3 scripts/licenze.py --python-csv "$PYTHON_CSV" "$@"
