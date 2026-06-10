# GitHub Pulse

A write-heavy analytics platform for exploring GitHub’s public event stream.

GitHub Pulse continuously polls public GitHub events, writes them to a day-partitioned PostgreSQL database, generates per-minute rollups, and serves analytics through a FastAPI API.

The main goal of this project is not simply to ingest a large number of events. It is to understand exactly where the system slows down as traffic increases.

Every major architecture decision, rejected alternative, and measured trade-off is documented in [`DESIGN.md`](DESIGN.md).

## Why I Built This

High-throughput data systems often sound simple at first:

1. Fetch some events.
2. Store them in a database.
3. Expose an API.
4. Scale it.

The difficult part is figuring out what happens when the event volume grows.

Does PostgreSQL become the bottleneck?
Do indexes make writes too expensive?
Does opening a new connection for every API request limit throughput?
Should frequently requested data be cached, or should it be pre-aggregated?

This project explores those questions using benchmarks rather than assumptions.

## How It Works

```text
api.github.com/events
          │
          │ ETag-aware polling
          ▼
    Python ingester
          │
          │ batched, idempotent writes
          ▼
 PostgreSQL
 ├── events             raw, append-only events
 └── rollup_*           per-minute aggregates
          │
          │ API reads rollups only
          ▼
 FastAPI query layer
 with pooled connections
```

The system has three main parts:

* A Python ingester that polls the GitHub Events API
* A partitioned PostgreSQL database for raw events and rollups
* A FastAPI service that answers queries using pre-aggregated data

## A Note About the GitHub Events API

GitHub does not provide a public push-based event firehose.

The `/events` endpoint must be polled and returns roughly 300 events per page. Results can overlap between requests, so duplicate events are expected and must be handled safely.

The poller uses ETags. When GitHub’s response has not changed, the API returns `304 Not Modified`, and the request does not consume a primary rate-limit point.

For testing beyond GitHub’s API limits, the project includes a synthetic event generator in [`loadtest/`](loadtest/).

## Measured Performance

These results were collected on:

* 4-core ARM64 Linux
* 4 GB RAM
* PostgreSQL 18
* A single machine with the ingester and database co-located

The tests can be reproduced with:

```bash
make bench
make loadtest
```

### Write Performance

Benchmark: 50,000 synthetic events using a single database connection.

| Write strategy                           |     Throughput | Improvement |
| ---------------------------------------- | -------------: | ----------: |
| Commit every row                         |  ~3,400 rows/s |          1× |
| `executemany`, batch size 500            | ~43,000 rows/s |         13× |
| `COPY` through staging, batch size 500   | ~62,000 rows/s |         18× |
| `COPY` through staging, batch size 5,000 | ~81,000 rows/s |         24× |

The results show how expensive per-row commits are and how much throughput can improve through batching and PostgreSQL’s `COPY` protocol.

### The Cost of Indexes

Indexes improve reads, but they are not free.

Adding the two secondary indexes needed by the ad-hoc query path reduced fresh-partition `COPY` throughput from approximately:

```text
154,000 rows/s → 84,000 rows/s
```

That is a **46% reduction in write throughput**.

In exchange, a query for an actor’s events from the previous hour improved from:

```text
75.3 ms parallel sequential scan
```

to:

```text
0.21 ms index scan
```

That is approximately a **366× read improvement** on a table containing 300,000 events.

This trade-off is documented in more detail in [`DESIGN.md`](DESIGN.md).

### API Performance

The API benchmark used:

* 300,000 raw events
* 60,000 rollup rows within the query window
* Pooled PostgreSQL connections

| Concurrency | Throughput | p50 latency | p95 latency |
| ----------: | ---------: | ----------: | ----------: |
|           4 |   76 req/s |       56 ms |       60 ms |
|          16 |  309 req/s |       54 ms |       59 ms |
|          50 |  369 req/s |      141 ms |      182 ms |

Originally, the API opened a new database connection for every request.

At concurrency 50, that approach was limited to:

* 266 requests per second
* 279 ms p95 latency

Switching to a connection pool produced:

* **39% higher throughput**
* **35% lower p95 latency**

At 50 concurrent requests, connections are no longer the main bottleneck. The aggregation query is now CPU-bound.

The next likely optimization is therefore a coarser rollup interval rather than adding a cache. This decision is discussed in `DESIGN.md` under **D6**.

## Key Design Properties

### Idempotent Ingestion

Events are deduplicated inside PostgreSQL:

```sql
ON CONFLICT (id, created_at) DO NOTHING
```

This makes retries safe and prevents overlapping GitHub API pages from creating duplicate records.

It also allows the ingester to restart—or multiple ingester replicas to run—without requiring in-memory deduplication.

Both supported write paths provide the same guarantee:

* Batched `executemany`
* `COPY` through a staging table

### Day-Partitioned Storage

Raw events are partitioned by UTC day.

This provides two important benefits:

* Time-bounded queries only scan the required partitions.
* Retention can be handled with `DROP TABLE` instead of large `DELETE` operations.

Dropping an expired partition is fast and avoids the table bloat and cleanup work caused by deleting millions of individual rows.

### Rollup-Backed Reads

The public API does not query the raw `events` table.

Instead, raw events are converted into per-minute aggregates. API requests read those smaller rollup tables, which reduces the amount of data scanned for every request.

Rollups are refreshed using an idempotent, windowed upsert.

Running the same refresh multiple times produces the same result, and late-arriving events are included as long as they fall within the refresh window.

This approach was chosen instead of a PostgreSQL materialized view. The reasoning is documented in `DESIGN.md` under **D3**.

## Getting Started

### 1. Start PostgreSQL and Redis

```bash
make up
```

The database schema is loaded automatically.

### 2. Install the Project

```bash
pip install -e ".[dev]"
```

### 3. Configure GitHub Authentication

Without authentication, GitHub allows approximately 60 requests per hour. A GitHub token increases that limit to approximately 5,000 requests per hour.

```bash
export GITHUB_TOKEN=ghp_xxx
```

Do not commit your token to the repository.

### 4. Start the Services

Run each command in a separate terminal.

Start the event ingester:

```bash
make ingest
```

Start the rollup refresh worker:

```bash
make rollup
```

Start the API:

```bash
make api
```

The interactive API documentation will be available at:

```text
http://localhost:8000/docs
```

## Testing and Benchmarking

Run the unit tests:

```bash
make test
```

Set `DATABASE_URL` to include the PostgreSQL integration tests.

Run the linter:

```bash
make lint
```

Benchmark the write path:

```bash
make bench
```

Run the API load test:

```bash
make loadtest
```

The API must already be running before starting the read-path load test.

## Repository Structure

```text
db/schema.sql
```

Defines the partitioned events table, rollup tables, indexes, and rollup refresh function.

```text
ingestor/firehose.py
```

Polls the GitHub Events API and handles ETag-based conditional requests.

```text
ingestor/writer.py
```

Implements the `executemany` and `COPY`-through-staging write paths.

```text
ingestor/rollup.py
```

Continuously refreshes the per-minute rollup tables.

```text
api/main.py
```

Provides the FastAPI read layer using pooled PostgreSQL connections.

```text
loadtest/
```

Contains the synthetic event generator, write benchmarks, and Locust API load tests.

```text
tests/
```

Contains unit and database integration tests for ingestion idempotency, deduplication, and rollup correctness.

```text
DESIGN.md
```

Documents the major design decisions, measured costs, rejected alternatives, and possible next steps.



## License

This project is available under the MIT License.
