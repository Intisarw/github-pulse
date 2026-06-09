# GitHub Pulse

![CI](https://github.com/Intisarw/github-pulse/actions/workflows/ci.yml/badge.svg)

A write-heavy analytics platform for the GitHub public events stream. It polls
events at high volume, stores them in a day-partitioned Postgres schema with
idempotent batch writes, pre-aggregates them into per-minute rollups, and
serves the read path from those rollups through a pooled FastAPI layer.

The design goal: keep accepting writes as volume grows, and know — with a
measured number, not a guess — where each bottleneck is. The decision log in
[`DESIGN.md`](DESIGN.md) records every trade-off and what it cost.

> Reality note: GitHub has no push "firehose". The public
> [`/events`](https://api.github.com/events) endpoint is *polled* (~300 events/page,
> rate-limited, overlapping pages → dedup required). The poller is ETag-aware, so
> unchanged polls cost no rate-limit points. For load past the rate limit, use the
> synthetic generator in `loadtest/`.

## Measured results

Environment: 4-core arm64 Linux, 4 GB RAM, Postgres 18 — single node, ingester
and DB co-located. Reproduce with `make bench` and `make loadtest`.

**Write path** (50k synthetic events, single connection):

| Strategy                     | Throughput      | vs. worst |
|------------------------------|-----------------|-----------|
| commit-per-row               |   ~3,400 rows/s | 1x        |
| executemany, batch=500       |  ~43,000 rows/s | 13x       |
| COPY + staging, batch=500    |  ~62,000 rows/s | 18x       |
| COPY + staging, batch=5000   |  ~81,000 rows/s | 24x       |

**Index trade-offs** (the part nobody tells you):

- The two secondary indexes the ad-hoc queries need cut COPY ingest from
  ~154k to ~84k rows/s (**-46%** write throughput on a fresh partition).
- In exchange, "events for actor X, last hour" went from a 75.3 ms parallel
  seq scan to a 0.21 ms index scan (**366x**) on 300k rows.

**Read path** (rollup-backed API, 300k events / 60k rollup rows in window):

| Concurrency | Throughput | p50    | p95    |
|-------------|------------|--------|--------|
| 4           |   76 req/s |  56 ms |  60 ms |
| 16          |  309 req/s |  54 ms |  59 ms |
| 50          |  369 req/s | 141 ms | 182 ms |

Connect-per-request capped the API at 266 req/s with p95 279 ms at
concurrency 50; switching to a connection pool gave +39% throughput and
-35% p95. At 50 concurrent the bottleneck is now the aggregation query
itself (CPU-bound), not connections — the next lever is a coarser rollup
grain, not a cache (see DESIGN.md D6).

## Architecture

```
        api.github.com/events  ── polled, ETag-aware ──►  Python ingester
                                                               │  batched, idempotent
                                                               ▼
                                                    PostgreSQL (partitioned by day)
                                                     ├─ events        (raw, append-only)
                                                     └─ rollup_*      (per-minute aggregates)
                                                               │  reads rollups only
                                                               ▼
                                                  FastAPI query layer (pooled)
```

Key properties, each verified by an integration test:

- **Idempotent ingest** — dedup lives in the DB (`ON CONFLICT (id, created_at)
  DO NOTHING`), so restarts and multiple ingester replicas are safe. Both write
  paths (executemany and COPY-via-staging) share this guarantee.
- **Partitioned storage** — one partition per UTC day. Retention is
  `DROP TABLE` (instant, no bloat) instead of `DELETE`; time-bounded queries
  prune to the partitions they touch.
- **Rollups, not raw scans** — the API never reads `events`. Rollup refresh is
  an idempotent windowed upsert: re-running converges, and late-arriving
  events inside the window are absorbed (chosen over a materialized view —
  DESIGN.md D3).

## Quickstart

```bash
# 1. Start infra (Postgres + Redis); schema auto-loads
make up

# 2. Install deps
pip install -e ".[dev]"

# 3. Run the ingester (set GITHUB_TOKEN to get 5000 req/hr instead of 60)
export GITHUB_TOKEN=ghp_xxx
make ingest        # terminal 1: poll events into Postgres
make rollup        # terminal 2: refresh rollups every 15s
make api           # terminal 3: http://localhost:8000/docs

# 4. Tests / lint / benchmarks
make test          # unit tests; set DATABASE_URL to include integration tests
make lint
make bench         # write-path benchmark
make loadtest      # read-path load test (needs API running)
```

## Repo layout

```
db/schema.sql            partitioned events table, rollups, refresh function
ingestor/firehose.py     ETag-aware poller
ingestor/writer.py       batch writer: executemany + COPY paths
ingestor/rollup.py       rollup refresh loop
api/main.py              read-path API (rollups only, pooled connections)
loadtest/                synthetic generator, write benchmark, Locust read test
tests/                   unit + DB integration tests (idempotency, rollup correctness)
DESIGN.md                decision log: what was chosen, what it cost, what was rejected
```

## License

MIT
