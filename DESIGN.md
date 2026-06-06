# GitHub Pulse — Design & Decision Log

> This is the most important file in the repo for an interview. It shows you can
> reason about trade-offs, not just write code. Fill in the **Decision** and
> **Why** sections as you build. Leave the rejected options in — showing what you
> *didn't* do and why is exactly the judgment interviewers probe for.

## 1. Problem statement

Ingest a high-rate stream of GitHub public events, store it durably and
cheaply, and serve sub-second analytics ("trending repos", "event volume over
time", "top languages") to a live dashboard. The system must keep accepting
writes without falling over as volume grows.

**Non-goals (scope control):** not building a general-purpose query engine, not
multi-region, not exactly-once semantics across the whole pipeline. Say no on
purpose.

## 2. Constraints & target numbers

Fill these in once you've measured — vague claims are worthless in interviews.

| Constraint            | Target / measured                          |
|-----------------------|--------------------------------------------|
| Write rate            | ____ events/sec sustained                  |
| Read latency          | p95 < ____ ms for dashboard queries        |
| Data retention        | raw: ____ days, rollups: ____              |
| Storage budget        | ____ GB                                    |
| Availability goal     | best-effort (single node) for v1           |

## 3. Key decisions (resolve these as you go)

### D1 — Primary store
- **Options:** Postgres (vanilla) · Postgres + TimescaleDB · ClickHouse.
- **Decision:** _Start on vanilla Postgres_ (you already know it).
- **Why:** Build on known ground, push it until something measurably breaks,
  THEN adopt a specialized store with a real reason. Adopting ClickHouse on day
  one means you can't explain why you needed it.
- **Revisit when:** ingest or query latency misses the targets in §2.

### D2 — Partitioning strategy
- **Options:** none · range-by-time (daily) · hash-by-repo · composite.
- **Decision:** ____  (the schema starts you on daily range partitions)
- **Why:** ____  (hint: write locality, retention via DROP/DETACH, pruning)
- **Question to answer in NOTES.md:** what breaks if you partition by repo
  instead of time, given events arrive in time order?

### D3 — Raw vs. pre-aggregated reads
- **Decision:** dashboard reads **rollup tables**, never raw `events`.
- **Why:** ____  (scanning millions of rows per refresh doesn't scale)
- **Open:** rollup via incremental upsert vs. materialized view — which is
  idempotent, which handles late-arriving data? Decide and justify.

### D4 — Buffer between ingest and DB
- **Options:** write straight to Postgres · Redis Stream · Kafka.
- **Decision:** ____  (README diagram shows Redis Stream; do you need it yet?)
- **Why:** ____  (a buffer absorbs bursts and decouples failure domains, but
  it's also a component to run and reason about — don't add it prematurely)

### D5 — Idempotency / dedup
- **Decision:** `INSERT ... ON CONFLICT (id, created_at) DO NOTHING`.
- **Why:** the Events API returns overlapping pages; writes must be safe to
  retry. Explain why DB-level dedup beats an in-memory set across replicas.

### D6 — Caching
- **Decision:** add Redis cache in front of the API **only after** measuring the
  DB is the bottleneck.
- **Why:** premature caching hides bugs and adds an invalidation problem.

### D7 — The C++ aggregator (the README's ambitious part)
- **Decision:** **stretch goal, not load-bearing.** v1 aggregates in SQL.
- **Why:** the interview value is in the data/scaling decisions above; a C++
  engine is a great systems story but high-risk for a one-month budget. Build it
  last, as one focused module (Count-Min Sketch for top-K, HyperLogLog for
  unique users) if time allows — and you'll have a genuinely standout artifact.

## 4. Architecture (current)

See README.md for the diagram. Update the diagram as decisions above change it —
a design doc that matches the code is worth ten that don't.

## 5. Lessons / what I'd do differently

> Fill this in at the end. Reflection here is what separates a tutorial clone
> from an engineer. Include the experiments that FAILED.
