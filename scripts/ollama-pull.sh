#!/usr/bin/env bash
# Scarica un modello nel volume condiviso con il servizio `ollama`.
#
# Serve uno script apposito perché la rete `backend` del compose è
# `internal: true` (§7.5: il container che vede il testo OCR non deve avere
# una via d'uscita verso internet). Il servizio quindi non può scaricare
# nulla da sé, e non vogliamo togliergli quell'isolamento per comodità.
#
# Qui il download lo fa un container temporaneo, sulla rete bridge di
# default, che monta lo stesso volume dei modelli e poi sparisce. Il
# servizio vero resta isolato come prima.
set -euo pipefail
cd "$(dirname "$0")/.."

MODEL="${1:-${EXTRACT_MODEL:-qwen3:4b}}"
PROJECT="${COMPOSE_PROJECT_NAME:-$(basename "$PWD" | tr '[:upper:]' '[:lower:]' | tr -cd 'a-z0-9_-')}"
VOLUME="${PROJECT}_ollama_models"
HELPER="netstock-ollama-pull"

echo "Modello:  $MODEL"
echo "Volume:   $VOLUME"
echo

# Idempotente: se il volume esiste già (creato da un `up` precedente) viene
# riusato, altrimenti lo creiamo qui con lo stesso nome che compose si
# aspetta, così il servizio lo adotta al primo avvio.
docker volume create "$VOLUME" >/dev/null

cleanup() { docker rm -f "$HELPER" >/dev/null 2>&1 || true; }
trap cleanup EXIT
cleanup

# Il servizio vero va fermato durante il download: due server Ollama che
# scrivono lo stesso volume insieme possono corrompere il blob store.
if [ -n "$(docker compose ps -q ollama 2>/dev/null)" ]; then
    echo "Fermo temporaneamente il servizio ollama…"
    docker compose stop ollama >/dev/null
    RESTART_SERVICE=1
else
    RESTART_SERVICE=0
fi

docker run -d --name "$HELPER" -v "$VOLUME:/root/.ollama" ollama/ollama >/dev/null

printf 'Attendo il server'
for _ in $(seq 1 30); do
    if docker exec "$HELPER" ollama list >/dev/null 2>&1; then break; fi
    printf '.'; sleep 1
done
echo

docker exec "$HELPER" ollama pull "$MODEL"
echo
docker exec "$HELPER" ollama list

if [ "$RESTART_SERVICE" = "1" ]; then
    echo
    echo "Riavvio il servizio ollama…"
    docker compose start ollama >/dev/null
fi

echo
echo "Fatto. Il modello è nel volume e il servizio lo vede senza uscire in rete."
