.PHONY: help up down ingest api test lint loadtest psql

help:
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

up:        ## Start Postgres + Redis
	docker compose up -d

down:      ## Stop infra
	docker compose down

psql:      ## Open a psql shell
	docker compose exec postgres psql -U pulse -d pulse

ingest:    ## Run the ingester once
	python -m ingestor.firehose

api:       ## Run the query API
	uvicorn api.main:app --reload

test:      ## Run tests
	pytest

lint:      ## Lint
	ruff check .

loadtest:  ## Run the load test (needs API running)
	locust -f loadtest/locustfile.py
