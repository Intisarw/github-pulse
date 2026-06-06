# Learning Plan — build it AND understand it

You know Python and relational SQL basics. The gap is *database design at scale*:
partitioning, indexing trade-offs, write throughput, rollups, and knowing when a
specialized store earns its place. This plan closes that gap by making you hit
each problem for real, with a number attached.

## How we work together (read this — it's the whole strategy)

To learn under time pressure, split the work by who does what:

- **I scaffold the boring/boilerplate** (project structure, CI, config, test
  harness, the diagram). It teaches little, so don't spend your hours on it.
- **YOU implement the learning-critical parts** — every `TODO` in the code and
  schema. These are the partitioning, batching, rollup, and indexing pieces.
  That's where the knowledge actually sticks.
- **I act as your tutor/reviewer, not autocomplete.** For each TODO:
  1. You attempt it.
  2. Ask me to explain the concept *before* I show code ("explain partition
     pruning with EXPLAIN", "why is COPY faster than executemany").
  3. You write the code; I review it, point out edge cases, and quiz you.
  4. You record the result (a number, a gotcha) in `NOTES.md`.

> Rule of thumb: if you couldn't explain it on a whiteboard tomorrow, you copied
> instead of learned. Slow down on those.

A good prompt to me looks like: *"Explain why a PK on a partitioned table must
include the partition key, then review my schema change."* — concept first, code
second.

## The measure-break-fix loop (the core skill)

Every milestone ends the same way: turn the volume up with
`loadtest/generate_events.py` until something breaks, find out **why** with
`EXPLAIN ANALYZE` / `pg_stat_statements` / Locust, fix it, and log the
before/after number. Interviewers don't want "I used partitioning" — they want
"writes dropped from 8k/s to 1k/s once the table passed 50M rows because the
index couldn't stay in cache; daily partitions fixed it." Numbers = credibility.

## Week-by-week (≈1 month, solo)

### Week 1 — Ingest end-to-end (get data flowing)
- [ ] `make up` — Postgres running, schema loaded. Inspect partitions in `psql`.
- [ ] Implement ETag handling in `firehose.py`; measure requests saved (NOTES).
- [ ] Implement `writer.write_batch` with `executemany`; get events into Postgres.
- [ ] Replace the in-memory dedup with `ON CONFLICT DO NOTHING`.
- **Checkpoint:** real events landing in `events`, no duplicates on restart.
- **Concepts to be able to explain:** polling vs streaming; idempotency; why
  batching beats row-by-row inserts.

### Week 2 — Make the database scale (THE interview goldmine)
- [ ] Add the indexes the dashboard queries need; `EXPLAIN ANALYZE` before/after.
- [ ] Implement the rollup SQL (both upsert and matview); pick one, justify it.
- [ ] Add a COPY-based fast path to the writer; benchmark vs executemany.
- [ ] Load-test with the generator: find the write rate where it degrades. Why?
- **Checkpoint:** a table of measured numbers in NOTES.md + DESIGN.md §2 filled.
- **Concepts:** partition pruning, index vs write-throughput trade-off,
  rollups vs raw scans, when an index lives in cache vs hits disk.

### Week 3 — Read path + dashboard
- [ ] Implement the API endpoints against rollups only.
- [ ] Locust the read path; record p95 at increasing concurrency.
- [ ] Add a Redis cache ONLY after you've shown the DB is the bottleneck.
- [ ] Minimal Vite/React dashboard hitting the API (keep it small).
- **Checkpoint:** dashboard shows live trending repos; read p95 documented.
- **Concepts:** read vs write path separation, cache invalidation, why you
  measure before caching.

### Week 4 — Polish + stretch
- [ ] Fill DESIGN.md decisions and the "Lessons" section honestly.
- [ ] Make the integration tests pass (remove the skips).
- [ ] Write the README results table with real numbers + a screenshot/gif.
- [ ] STRETCH: the C++ aggregator (Count-Min Sketch / HyperLogLog) as one
      module called from Python. Skip guilt-free if behind.
- **Checkpoint:** green CI, real numbers, a design doc you'd defend.

## Companion reading (do in parallel, not before)
- *Designing Data-Intensive Applications* — Ch. 3 (storage/LSM vs B-tree),
  Ch. 6 (partitioning), Ch. 11 (stream processing). Read the chapter for the
  week you're on.
- Postgres docs: table partitioning; `EXPLAIN`; `COPY`.
- CMU 15-445 lectures on storage & indexing (optional deep dive).

## Interview question bank (you should be able to answer all by Week 4)
1. Why partition by time and not by repo here?
2. Why does adding an index slow your ingest? When is it worth it?
3. How do you make ingestion idempotent across multiple ingester replicas?
4. Rollup via upsert vs materialized view — trade-offs? Late data?
5. When would you reach for ClickHouse over partitioned Postgres? What changes?
6. How do you drop 30-day-old data without a slow, bloating DELETE?
7. Where's your bottleneck under load, and how did you find it?
