# Versione esatta, Debian compresa: il client PostgreSQL più sotto viene dal
# repository «trixie-pgdg», e una base che cambiasse Debian da sola lo
# romperebbe. Gli aggiornamenti arrivano come proposte di Dependabot.
FROM python:3.12.14-slim-trixie AS builder

WORKDIR /build

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    git \
    && rm -rf /var/lib/apt/lists/*

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Le versioni esatte, con le loro hash: l'immagine installa quello che la CI
# ha provato, non l'ultima uscita il giorno della build. Si rigenera con
# `make lock` dopo aver toccato le dipendenze in pyproject.toml.
COPY requirements.txt ./
RUN pip install --no-cache-dir --require-hashes -r requirements.txt

# Da quale commit è costruita l'immagine, e quando: la pagina Impostazioni lo
# mostra, per capire quale versione gira in produzione e quale in sviluppo. Si
# legge dal .git del repository — il contesto «git» in docker-compose.yml —
# senza copiarlo nell'immagine; per questo l'immagine si costruisce con compose.
RUN --mount=type=bind,from=git,target=/tmp/git \
    { git -c safe.directory='*' --git-dir=/tmp/git log -1 \
        --format='{"commit": "%h", "data_commit": "%cI", ' 2>/dev/null || printf '{'; \
      printf '"costruita": "%s"}\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"; } > /versione.json

FROM python:3.12.14-slim-trixie AS runtime

RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    tesseract-ocr-ita \
    tesseract-ocr-eng \
    tesseract-ocr-deu \
    libgl1 \
    libglib2.0-0 \
    curl \
    ca-certificates \
    gnupg \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd -r app && useradd -r -g app -d /app -s /usr/sbin/nologin app

# Client PostgreSQL **della stessa versione maggiore del server** (16), per
# copia di sicurezza e ripristino dalle Impostazioni. Non è pignoleria di
# versione: Debian 13 porta il client 17, che scrive archivi in formato 1.16 —
# e il `pg_restore` 16 del container del database li rifiuta con «unsupported
# version». Le due strade di backup, quella dell'applicazione e quella dello
# script notturno, produrrebbero file che l'altra non sa rileggere. Misurato,
# non temuto.
RUN curl -fsSL https://www.postgresql.org/media/keys/ACCC4CF8.asc \
      | gpg --dearmor -o /usr/share/keyrings/pgdg.gpg \
    && echo "deb [signed-by=/usr/share/keyrings/pgdg.gpg] https://apt.postgresql.org/pub/repos/apt trixie-pgdg main" \
      > /etc/apt/sources.list.d/pgdg.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends postgresql-client-16 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app
COPY --chown=app:app . .
COPY --from=builder /versione.json /app/versione.json

USER app

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"

CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000"]
