# GitHub Pulse — Design & Decision Log

Decisions are recorded with the options that were rejected and the measured
cost of what was chosen. Numbers come from `make bench` / `make loadtest` on
the environment described in the README.

## 1. Problem statement

Ingest a high-rate stream of GitHub public events, store it durably and
cheaply, and serve sub-second analytics ("trending repos", "event volume over
time") to a live dashboard. The system must keep accepting writes without
falling over as volume grows.

**Non-goals (scope control):** not a general-purpose query engine, not
multi-region, not exactly-once across the whole pipeline (idempotency makes
at-least-once safe, which is cheaper and sufficient here).

## 2. Constraints & measured numbers

| Constraint            | Target / measured                                       |
|-----------------------|---------------------------------------------------------|
| Write rate            | measured ~81k rows/s sustained (COPY, batch=5000)       |
| Read latency          | p95 59 ms at 16 concurrent; 182 ms at 50 (saturated)    |
| Data retention        | raw: 30 days (partition drop), rollups: indefinite      |
| Storage budget        | measured 337 B/row incl. indexes → ~2.9 GB/day at 100 ev/s, ~87 GB for 30-day raw retention |
| Availability goal     | best-effort (single node) for v1                        |

## 3. Key decisions

### D1 — Primary store: vanilla Postgres
- **Options:** Postgres (vanilla) · Postgres + TimescaleDB · ClickHouse.
- **Decision:** vanilla Postgres.
- **Why:** measured headroom says it's enough: 81k rows/s write throughput is
  ~800x GitHub's real public event rate, and the read path saturates CPU at
  ~370 req/s — far beyond a dashboard's needs. Adopting a specialized store
  before vanilla Postgres measurably fails would be unjustifiable complexity.
- **Revisit when:** sustained ingest approaches ~10k events/s real load,
  retention requirements grow past what partition-drop handles, or analytical
  queries stop fitting the rollup model (ad-hoc OLAP → ClickHouse territory).

### D2 — Partitioning: range by time, one partition per UTC day
- **Options:** none · range-by-time (daily) · hash-by-repo · composite.
- **Decision:** daily range partitions on `created_at`.
- **Why:**
  - *Write locality:* events arrive in time order, so all writes hit one hot
    partition whose indexes stay cache-resident.
  - *Retention:* dropping a 30-day-old partition is a metadata operation;
    `DELETE` on a monolithic table bloats and needs vacuum.
  - *Pruning:* dashboard queries are time-bounded; the planner skips
    partitions outside the window (visible in every EXPLAIN below).
  - Hash-by-repo was rejected: it scatters writes across all partitions,
    loses pruning for time-window queries, and hot repos skew partition sizes.
- **Consequence:** the PK must include the partition key → `(id, created_at)`.
  Uniqueness is enforced per partition; fine here because a GitHub event id
  always carries the same `created_at`.

### D3 — Reads come from rollups, never raw events
- **Decision:** per-minute rollup tables (`rollup_repo_1m`,
  `rollup_event_type_1m`), refreshed by an idempotent windowed upsert
  (`refresh_rollups()`), every 15 s over a 5-minute window.
- **Why:** rollup size is bounded by (minutes × distinct values), not event
  volume — the read path's cost stays flat as ingest grows.
- **Upsert vs materialized view:** upsert won. It recomputes only the recent
  window (a matview `REFRESH` recomputes everything), it's idempotent
  (re-running converges to the same state), and late-arriving events inside
  the window are absorbed on the next run. The overlap between runs is the
  late-data tolerance, and it's configurable.

### D4 — No buffer between ingest and DB (yet)
- **Options:** write straight to Postgres · Redis Stream · Kafka.
- **Decision:** write straight to Postgres.
- **Why:** the writer sustains ~81k rows/s; GitHub's real stream is ~100/s.
  A buffer absorbs bursts and decouples failure domains, but it's another
  component to run, monitor, and reason about — unjustified at 0.1% utilization.
- **Revisit when:** ingest bursts approach write capacity, or when a second
  consumer of the raw stream appears (then a log becomes the natural seam).

### D5 — Idempotency / dedup in the database
- **Decision:** `INSERT ... ON CONFLICT (id, created_at) DO NOTHING`.
- **Why:** the Events API returns overlapping pages, so duplicates are
  guaranteed. DB-level dedup survives ingester restarts and stays correct with
  N concurrent replicas; an in-memory seen-set does neither, and grows
  unboundedly. COPY can't express ON CONFLICT, so the COPY fast path goes
  through an UNLOGGED staging table and a single INSERT...SELECT — keeping the
  same guarantee at 1.4–1.9x executemany throughput.

### D6 — No cache in front of the API
- **Decision:** measured first; not added.
- **Why:** the suspected bottleneck (connection setup) was real but cheap to
  fix properly — pooling took p95 from 279 ms to 182 ms at 50 concurrent. The
  remaining cost is the aggregation query itself, which is the same work
  whether a cache misses or the DB serves it. The honest next lever is a
  coarser rollup grain (e.g. 5-minute buckets for wide windows), which removes
  work instead of memoizing it. A cache also buys an invalidation problem on a
  60-second-fresh dashboard.

### D7 — Secondary indexes: two, deliberately
- **Decision:** `(repo, created_at)` and `(actor, created_at)` partitioned
  indexes — and nothing else.
- **Why (measured):** they cost 46% of COPY ingest throughput on a fresh
  partition (154k → 84k rows/s) and bought a 366x speedup on the actor lookup
  (75.3 ms seq scan → 0.21 ms index scan at 300k rows). Worth it for query
  shapes that exist; ruinous as a habit. Each index is per-partition, so the
  hot partition's index stays small and cached.

## 4. Architecture (current)

See the README diagram. The dashboard and a C++ sketch-based aggregator
(Count-Min Sketch top-K) were considered and cut for scope — v1 aggregates in
SQL, and the rollup model makes the SQL cheap.

## 5. Lessons / what I'd do differently

- **Batching is the whole ballgame on the write path.** Commit-per-row ran at
  ~3.4k rows/s; one transaction per 500-row batch was 13x faster before any
  COPY cleverness. The per-commit WAL flush dominates everything else.
- **COPY's win over executemany is real but smaller than folklore says**
  (1.4–1.9x here, not 10x) — psycopg3 already pipelines executemany. The
  bigger lever was batch size.
- **Indexes are 2x more expensive than I expected.** -46% ingest for two
  B-trees. The "before" EXPLAIN made the case for them; the benchmark made
  the case against a third.
- **The first read-path bottleneck wasn't the query** — it was opening a
  connection per request. Measure before optimizing the obvious-looking thing.
- **Test the failure that will actually happen.** The integration tests
  replay the real hazards: a retried batch after a crash, a rollup run twice,
  an event arriving late into an already-rolled-up minute.
- **What I'd do differently:** automate partition creation from day one
  (a missing partition is an ingest outage waiting for midnight UTC), and
  pick rollup grains from query shapes earlier — per-minute is right for
  60-minute windows but wasteful for 24-hour ones.
