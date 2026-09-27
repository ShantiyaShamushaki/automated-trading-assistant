SHELL := /bin/bash

.PHONY: env up down restart logs ps pull clean validate

env:
	cp -n .env.example .env || true

up:
	docker compose up -d

down:
	docker compose down

restart:
	docker compose down && docker compose up -d

logs:
	docker compose logs -f --tail=200

ps:
	docker compose ps

pull:
	docker compose pull

validate:
	docker compose config

clean:
	docker compose down -v --remove-orphans