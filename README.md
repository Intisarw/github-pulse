# GitHub Pulse

![CI](https://github.com/Intisarw/github-pulse/actions/workflows/ci.yml/badge.svg)

**Status:** In active development

A write-heavy analytics platform for the GitHub public events stream. It ingests
events at high volume, stores them in a partitioned Postgres schema, pre-aggregates
them into rollups, and serves sub-second analytics to a live dashboard.

This is a **learning project built to scale**: the goal is to hit real
database-scaling problems — partitioning, indexing trade-offs, write throughput,
rollups vs raw scans — and document the decisions with measured numbers. See
[`DESIGN.md`](DESIGN.md) for the decision log and [`LEARNING.md`](LEARNING.md) for
the build plan.

> Reality note: GitHub has no push "firehose". The public
> [`/events`](https://api.github.com/events) endpoint is *polled* (~300 events/page,
> rate-limited, overlapping pages → dedup required). For load testing past the rate
> limit, use the synthetic generator in `loadtest/`.

## Results (fill in as you measure)

| Metric                        | Result                |
|-------------------------------|-----------------------|
| Sustained write throughput    | _TBD_ events/sec      |
| Read p95 (trending repos)     | _TBD_ ms              |
| Breaking point + root cause   | _TBD_                 |

## Architecture

```
        api.github.com/events  ── polled, ETag-aware ──►  Python ingester
                                                               │  batched, idempotent
                                                               ▼
                                                    PostgreSQL (partitioned by day)
                                                     ├─ events        (raw, append-only)
                                                     └─ rollup_*       (pre-aggregated)
                                                               │  reads rollups only
                                                               ▼
                                                       FastAPI query layer
                                                               │  (+ Redis cache, when measured-needed)
                                                               ▼
                                                    Vite + React dashboard
```

**Stretch goal:** a C++ aggregator (Count-Min Sketch for top-K, HyperLogLog for
unique users) callable from Python via pybind11. Intentionally *not* load-bearing
— v1 aggregates in SQL. See `DESIGN.md` D7.

## Quickstart

```bash
# 1. Start infra (Postgres + Redis); schema auto-loads
make up

# 2. Install deps
pip install -e ".[dev]"

# 3. Run the ingester (set GITHUB_TOKEN to get 5000 req/hr instead of 60)
export GITHUB_TOKEN=ghp_xxx
make ingest

# 4. Serve the query API
make api          # http://localhost:8000/health

# 5. Tests / lint / load test
make test
make lint
make loadtest     # needs the API running
```

## Repo layout

```
db/schema.sql            partitioned events table + rollups (with guided TODOs)
ingestor/                firehose poller, batch writer, config
api/main.py              read-path query API (reads rollups)
loadtest/                synthetic event generator + Locust read-path test
tests/                   unit tests (green) + integration TODOs
DESIGN.md                decision log — the most interview-relevant file
LEARNING.md              week-by-week plan + concept map + question bank
NOTES.md                 measurement log / lab notebook
```

## License

MIT
