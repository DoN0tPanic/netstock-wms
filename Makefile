.PHONY: install update test-db backup-timer backup-verify import-catalogo import-giacenza ai-report certs-ca up up-ai ollama-pull licenses check-sensitive gitleaks gitleaks-baseline down logs ps build migrate seed reconcile backup restore reset-data certs bootstrap fmt lint test

# Installazione da zero: dipendenze di sistema, permessi, primo avvio.
install:
	./install.sh

# Aggiornamento di un'installazione già in funzione: backup, codice nuovo,
# ricostruzione, riavvio, verifica. Non tocca .env né i dati.
update:
	./update.sh

up:
	docker compose up -d --build

# Avvia anche Ollama. La GPU viene usata se c'è, altrimenti si gira su CPU:
# l'applicativo deve funzionare identico sulle due macchine, la scheda video
# cambia solo la latenza (vedi docker-compose.gpu.yml).
up-ai:
	@if nvidia-smi >/dev/null 2>&1; then \
		echo "GPU rilevata: avvio con accelerazione."; \
		docker compose -f docker-compose.yml -f docker-compose.gpu.yml --profile ai up -d --build; \
	else \
		echo "Nessuna GPU: avvio su CPU."; \
		docker compose --profile ai up -d --build; \
	fi

# Scarica il modello di estrazione nel volume condiviso. Necessario perché la
# rete del servizio è isolata da internet per progetto — vedi lo script.
ollama-pull:
	./scripts/ollama-pull.sh $(MODEL)

down:
	docker compose down

logs:
	docker compose logs -f --tail=200

ps:
	docker compose ps

build:
	docker compose build

migrate:
	docker compose exec api alembic upgrade head

seed:
	docker compose exec api python -m app.cli seed

# Import da CSV. Senza APPLICA=1 non scrivono niente: leggono, controllano e
# dicono cosa farebbero. Il file viene copiato dentro il container, quindi il
# percorso è quello della macchina, non quello del container.
import-catalogo:
	@test -n "$(FILE)" || { echo "Uso: make import-catalogo FILE=catalogo.csv [APPLICA=1]"; exit 1; }
	docker compose cp "$(FILE)" api:/tmp/import.csv
	docker compose exec api python -m app.cli import-catalogo /tmp/import.csv $(if $(APPLICA),--applica,)

import-giacenza:
	@test -n "$(FILE)" || { echo "Uso: make import-giacenza FILE=giacenza.csv [APPLICA=1] [DATA=2026-01-07]"; exit 1; }
	docker compose cp "$(FILE)" api:/tmp/import.csv
	docker compose exec api python -m app.cli import-giacenza /tmp/import.csv \
	  $(if $(APPLICA),--applica,) $(if $(DATA),--data=$(DATA),) $(if $(UTENTE),--utente=$(UTENTE),)

# I numeri per decidere se la lettura automatica dei documenti vale quello che
# costa: quante letture, quante sono state davvero usate, quanto ci mettono.
# Finché `accepted` non veniva scritto, questa domanda non aveva risposta.
ai-report:
	docker compose exec -T db psql -U $${POSTGRES_USER:-netstock} -d $${POSTGRES_DB:-netstock} -c "\
	  SELECT engine, count(*) AS letture, \
	         count(*) FILTER (WHERE accepted) AS usate, \
	         count(*) FILTER (WHERE accepted IS FALSE) AS scartate, \
	         count(*) FILTER (WHERE accepted IS NULL) AS senza_esito, \
	         round(avg(duration_ms)/1000.0, 1) AS secondi_medi, \
	         count(*) FILTER (WHERE error IS NOT NULL) AS errori \
	  FROM extraction_runs WHERE ts > now() - interval '90 days' \
	  GROUP BY engine ORDER BY letture DESC"

reconcile:
	docker compose exec api python -m app.cli reconcile

reconcile-fix:
	docker compose exec api python -m app.cli reconcile --fix

backup:
	./scripts/backup.sh

# Installa (o reinstalla) il timer systemd che fa il backup ogni notte.
backup-timer:
	./scripts/install-backup-timer.sh

# Ripristina l'ultimo dump in un database usa e getta e conta le righe:
# l'installazione non viene toccata. Un backup mai riaperto non è un backup.
backup-verify:
	./scripts/restore.sh "$$(ls -t /var/backups/netstock/daily/*.dump | head -1)" --prova

restore:
	./scripts/restore.sh

# Svuota i dati di movimentazione tenendo le anagrafiche: serve a ripulire
# un'installazione dopo la fase di prova. Fa un backup prima di procedere.
reset-data:
	./scripts/reset-transactional-data.sh

# Cerca dati sensibili in ciò che verrebbe pubblicato: ragioni sociali e
# seriali di documenti reali, chiavi, password, indirizzi della macchina.
# Rigenera compliance/licenses.csv da cio' che e' davvero installato.
licenses:
	./scripts/licenses.sh

check-sensitive:
	./scripts/check-sensitive.sh

# Scansione segreti su tutta la storia, come in CI.
gitleaks:
	docker run --rm -v "$$PWD:/repo" -w /repo zricethezav/gitleaks:latest detect \
	  --source /repo --config /repo/.gitleaks.toml \
	  --baseline-path /repo/.gitleaks-baseline.json --redact --no-banner --verbose

# Riscrive l'elenco dei riscontri accettati: farlo significa dichiarare di
# aver guardato ciò che contiene. Vedi .gitleaks-baseline.md.
gitleaks-baseline:
	docker run --rm -v "$$PWD:/repo" -w /repo zricethezav/gitleaks:latest detect \
	  --source /repo --config /repo/.gitleaks.toml --redact --no-banner \
	  --report-path /repo/.gitleaks-baseline.json --exit-code 0

certs:
	./scripts/gen-selfsigned-cert.sh

# Come sopra, ma con una piccola autorità locale che firma il certificato:
# installando una volta certs/netstock-ca.crt su telefoni e computer,
# l'avviso del browser sparisce — e la fotocamera del lettore di barcode
# smette di dipendere da un'eccezione di sicurezza.
certs-ca:
	./scripts/gen-selfsigned-cert.sh --con-ca --rigenera
	@echo "Ricorda: docker compose restart caddy"

bootstrap:
	./scripts/bootstrap.sh

fmt:
	docker compose exec api ruff format app tests

lint:
	docker compose exec api ruff check app tests
	docker compose exec api mypy app

# I test girano su netstock_test, mai sul database dell'installazione: lo
# prepara test-db.sh e lo pretende conftest.py, che si ferma se il nome non
# finisce per _test. Le variabili si derivano dentro il container da quelle
# vere, così nessuna password passa da qui.
test:
	./scripts/test-db.sh
	# pytest/mypy/ruff are dev-only and not in the production image on purpose
	# (smaller, fewer packages to audit at runtime) — installed on demand here.
	docker compose exec -u root api pip install --no-cache-dir '.[dev]'
	# COVERAGE_FILE fuori da /app: nel container si gira come utente non
	# privilegiato e /app non è scrivibile, quindi coverage falliva a fine
	# corsa e `make test` usciva con errore **con tutti i test verdi**. Un
	# comando di prova che dice rosso quando è tutto a posto insegna a non
	# guardare l'esito, che è il modo migliore per non accorgersi del giorno
	# in cui è rosso davvero.
	docker compose exec api sh -c 'DATABASE_URL="$${DATABASE_URL}_test" \
	  MIGRATE_DATABASE_URL="$${MIGRATE_DATABASE_URL}_test" \
	  COVERAGE_FILE=/tmp/.coverage \
	  pytest tests/ -v -p no:cacheprovider --cov=app --cov-report=term-missing'
