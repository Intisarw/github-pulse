.PHONY: help up down ingest rollup api test lint loadtest bench psql

help:
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

up:        ## Start Postgres + Redis
	docker compose up -d

down:      ## Stop infra
	docker compose down

psql:      ## Open a psql shell
	docker compose exec postgres psql -U pulse -d pulse

ingest:    ## Run the polling ingester
	python -m ingestor.firehose

rollup:    ## Run the rollup refresher loop
	python -m ingestor.rollup

api:       ## Run the query API
	uvicorn api.main:app --reload

test:      ## Run tests
	pytest

lint:      ## Lint
	ruff check .

loadtest:  ## Load-test the read path (needs API running)
	locust -f loadtest/locustfile.py

bench:     ## Benchmark the write path (produces the README numbers)
	python -m loadtest.bench_writer
