SHELL := /bin/bash

-include .env
export

COMPOSE ?= docker compose
POSTGRES_USER ?= archiver
POSTGRES_DB ?= archiver
APP_PORT ?= 8000
BACKUP_DIR ?= backups

.PHONY: up up-d down restart logs ps health backup restore reset

up:
	$(COMPOSE) up --build

up-d:
	$(COMPOSE) up -d --build

down:
	$(COMPOSE) down

restart:
	$(COMPOSE) down
	$(COMPOSE) up -d --build

logs:
	$(COMPOSE) logs -f app postgres

ps:
	$(COMPOSE) ps

health:
	curl -fsS http://127.0.0.1:$(APP_PORT)/api/health | python -m json.tool

backup:
	@mkdir -p "$(BACKUP_DIR)"
	@file="$(BACKUP_DIR)/archiver-$$(date +%Y%m%d-%H%M%S).sql"; \
	$(COMPOSE) exec -T postgres pg_dump -U "$(POSTGRES_USER)" "$(POSTGRES_DB)" > "$$file"; \
	echo "Backup written to $$file"

restore:
	@[ -n "$(RESTORE_FILE)" ] || (echo "Usage: make restore RESTORE_FILE=backups/file.sql" && exit 2)
	@$(COMPOSE) exec -T postgres psql -U "$(POSTGRES_USER)" "$(POSTGRES_DB)" < "$(RESTORE_FILE)"

reset:
	@read -r -p "Delete app containers and Docker volumes? Type RESET to continue: " answer; \
	if [[ "$$answer" == "RESET" ]]; then \
		$(COMPOSE) down -v; \
	else \
		echo "Cancelled"; \
	fi
