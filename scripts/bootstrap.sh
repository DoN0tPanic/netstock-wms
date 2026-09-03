#!/usr/bin/env bash
# Idempotent first-install script (§11.5).
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_DIR"

echo "== 1/5: verifica prerequisiti =="
command -v docker >/dev/null || { echo "Docker non trovato." >&2; exit 1; }
docker compose version >/dev/null || { echo "Docker Compose plugin non trovato." >&2; exit 1; }

AVAILABLE_RAM_MB=$(free -m | awk '/^Mem:/{print $2}')
AVAILABLE_DISK_GB=$(df -BG --output=avail "$REPO_DIR" | tail -1 | tr -dc '0-9')
echo "RAM disponibile: ${AVAILABLE_RAM_MB} MB, disco disponibile: ${AVAILABLE_DISK_GB} GB"
if [ "$AVAILABLE_RAM_MB" -lt 3800 ]; then
  echo "Attenzione: RAM sotto il minimo consigliato (4 GB senza AI, 8+ GB con AI)."
fi

echo "== 2/5: generazione .env =="
if [ ! -f .env ]; then
  cp .env.example .env
  POSTGRES_PASSWORD=$(openssl rand -hex 24)
  APP_DB_PASSWORD=$(openssl rand -hex 24)
  SECRET_KEY=$(openssl rand -hex 32)
  ADMIN_PASSWORD=$(openssl rand -base64 18 | tr -d '/+=')
  sed -i "s|^POSTGRES_PASSWORD=.*|POSTGRES_PASSWORD=${POSTGRES_PASSWORD}|" .env
  sed -i "s|^APP_DB_PASSWORD=.*|APP_DB_PASSWORD=${APP_DB_PASSWORD}|" .env
  sed -i "s|^SECRET_KEY=.*|SECRET_KEY=${SECRET_KEY}|" .env
  sed -i "s|^ADMIN_PASSWORD=.*|ADMIN_PASSWORD=${ADMIN_PASSWORD}|" .env
  # L'installatore chiede se attivare l'estrazione automatica e passa qui la
  # risposta: il `.env` lo crea questo script, ed è l'unico posto dove la
  # scelta può essere scritta senza saltare la generazione dei segreti.
  if [ -n "${NETSTOCK_EXTRACT_ENABLED:-}" ]; then
    sed -i "s|^EXTRACT_ENABLED=.*|EXTRACT_ENABLED=${NETSTOCK_EXTRACT_ENABLED}|" .env
  fi
  echo
  echo "############################################################"
  echo "# Password amministratore iniziale (salvarla ora, non sarà #"
  echo "# più mostrata): ${ADMIN_PASSWORD}"
  echo "############################################################"
  echo
else
  echo ".env già presente, non sovrascritto."
fi

echo "== 3/5: certificato TLS =="
./scripts/gen-selfsigned-cert.sh

echo "== 4/5: avvio database e migrazioni =="
docker compose up -d db
until docker compose ps db | grep -q healthy; do sleep 2; done
docker compose up -d api
until curl -sf http://localhost:8000/health >/dev/null 2>&1 || \
      docker compose exec -T api python -c "import urllib.request;urllib.request.urlopen('http://localhost:8000/health')" >/dev/null 2>&1; do
  sleep 2
done

COMPOSE_FILES="-f docker-compose.yml"
if nvidia-smi >/dev/null 2>&1; then
  echo "GPU NVIDIA rilevata: l'estrazione userà l'accelerazione."
  COMPOSE_FILES="$COMPOSE_FILES -f docker-compose.gpu.yml"
else
  echo "Nessuna GPU: l'estrazione girerà su CPU (più lenta, stesso risultato)."
fi

if grep -q "^EXTRACT_ENABLED=true" .env; then
  echo "== 4b/5: download del modello di estrazione =="
  MODEL=$(grep '^EXTRACT_MODEL=' .env | cut -d= -f2)
  # Il download non può passare dal servizio: la sua rete è `internal: true`,
  # perché il container che vede il testo OCR non deve avere una via d'uscita
  # verso internet. Ci pensa lo script, con un container temporaneo.
  ./scripts/ollama-pull.sh "${MODEL:-qwen3:4b}" || \
    echo "Attenzione: download del modello fallito. Riprovare con './scripts/ollama-pull.sh'."
  docker compose $COMPOSE_FILES --profile ai up -d ollama
fi

echo "== 5/5: avvio completo =="
docker compose $COMPOSE_FILES up -d
echo "Verifica readiness..."
sleep 3
docker compose exec -T api python -c "
import urllib.request
print(urllib.request.urlopen('http://localhost:8000/health').read().decode())
"

SITE_ADDRESS=$(grep '^SITE_ADDRESS=' .env | cut -d= -f2)
echo
echo "NetStock è avviato: https://${SITE_ADDRESS}"
echo "Il browser mostrerà un avviso di sicurezza finché non si installa un certificato firmato dalla CA aziendale."
