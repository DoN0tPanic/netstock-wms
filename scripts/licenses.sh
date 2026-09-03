#!/usr/bin/env bash
# Rigenera l'inventario delle licenze da ciò che è davvero installato.
#
# L'elenco non si scrive a mano: si legge dai pacchetti presenti, altrimenti
# invecchia in silenzio e dice il falso al primo aggiornamento di dipendenza.
#
# Uso:  ./scripts/licenses.sh        (riscrive compliance/licenses.csv)
set -euo pipefail
cd "$(dirname "$0")/.."

USCITA="compliance/licenses.csv"
TEMP=$(mktemp); trap 'rm -f "$TEMP"' EXIT

echo "componente,versione,licenza,origine" > "$TEMP"

echo "Python…" >&2
docker compose exec -u root -T api sh -c \
  'pip install --quiet pip-licenses >/dev/null 2>&1; pip-licenses --format=csv --with-system' \
  2>/dev/null | tail -n +2 | tr -d '"' | awk -F, '{print $1","$2","$3",python"}' >> "$TEMP"

echo "npm…" >&2
(cd web && node -e '
const fs = require("fs"); const righe = [];
function scan(dir) {
  for (const d of fs.readdirSync(dir, { withFileTypes: true })) {
    if (!d.isDirectory()) continue;
    const f = dir + "/" + d.name;
    if (d.name.startsWith("@")) { scan(f); continue; }
    try {
      const j = JSON.parse(fs.readFileSync(f + "/package.json"));
      const l = typeof j.license === "string" ? j.license
              : (j.license && j.license.type) || (j.licenses && j.licenses[0] && j.licenses[0].type) || "SCONOSCIUTA";
      righe.push([j.name, j.version, l, "npm"].join(","));
    } catch (e) { /* pacchetto senza manifesto leggibile */ }
  }
}
scan("node_modules");
console.log(righe.join("\n"));
') >> "$TEMP"

# I componenti che non stanno in nessun gestore di pacchetti: immagini, motore
# di OCR, modello. Le versioni sono quelle fissate in docker-compose.yml e
# nella configurazione, quindi si leggono da lì invece di riscriverle.
POSTGRES=$(grep -oE 'postgres:[0-9.]+-alpine' docker-compose.yml | head -1)
CADDY=$(grep -oE 'caddy:[0-9]+-alpine' docker-compose.yml | head -1)
MODELLO=$(grep -oE 'EXTRACT_MODEL:-[^}]+' docker-compose.yml | head -1 | cut -d- -f2-)
{
  echo "${POSTGRES%%:*},${POSTGRES##*:},PostgreSQL License,immagine"
  echo "${CADDY%%:*},${CADDY##*:},Apache-2.0,immagine"
  echo "ollama,latest,MIT,immagine"
  echo "${MODELLO},—,Apache-2.0,modello"
  echo "tesseract-ocr,5.x,Apache-2.0,pacchetto di sistema"
  echo "debian (base python:3.12-slim),12,misto (vedi compliance/README.md),immagine"
} >> "$TEMP"

mv "$TEMP" "$USCITA"; trap - EXIT
# `mktemp` crea a 600: un file versionato deve essere leggibile come gli altri.
chmod 644 "$USCITA"
echo "Scritto $USCITA: $(($(wc -l < "$USCITA") - 1)) componenti." >&2
echo >&2
echo "Riepilogo per licenza:" >&2
tail -n +2 "$USCITA" | cut -d, -f3 | sort | uniq -c | sort -rn | sed 's/^/  /' >&2
