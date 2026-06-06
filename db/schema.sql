-- =============================================================================
-- GitHub Pulse — database schema
-- =============================================================================
-- This file is loaded automatically when the Postgres container first starts.
--
-- LEARNING NOTE: This schema is intentionally a STARTING POINT, not a finished
-- design. The TODOs are the parts where the real database-scaling lessons live.
-- Do them yourself, measure the effect, and write what you learned in NOTES.md.
-- =============================================================================

-- -----------------------------------------------------------------------------
-- 1. RAW EVENTS  (the write-heavy, append-only table)
-- -----------------------------------------------------------------------------
-- This is where the firehose lands. It is append-only and grows fast, so it is
-- the table that teaches you partitioning, indexing trade-offs, and write
-- throughput.
--
-- We partition BY RANGE on created_at (time). Why time?
--   - Events arrive in time order, so writes hit the newest partition (hot).
--   - Old data can be dropped by DETACHing a whole partition (instant) instead
--     of a slow DELETE that bloats the table.
--   - Queries are almost always time-bounded ("last 24h"), so the planner can
--     skip (prune) partitions it doesn't need.

CREATE TABLE IF NOT EXISTS events (
    id          BIGINT       NOT NULL,
    event_type  TEXT         NOT NULL,   -- PushEvent, PullRequestEvent, ...
    actor       TEXT         NOT NULL,   -- the user login
    repo        TEXT         NOT NULL,   -- "owner/name"
    created_at  TIMESTAMPTZ  NOT NULL,
    ingested_at TIMESTAMPTZ  NOT NULL DEFAULT now(),
    -- Note: PRIMARY KEY on a partitioned table MUST include the partition key.
    -- This is a real constraint that surprises people — write it in NOTES.md.
    PRIMARY KEY (id, created_at)
) PARTITION BY RANGE (created_at);

-- One partition per day. In production you'd automate this (pg_partman or a
-- cron job). For now, create a few by hand so you understand what's happening.
CREATE TABLE IF NOT EXISTS events_2026_06_06 PARTITION OF events
    FOR VALUES FROM ('2026-06-06') TO ('2026-06-07');
CREATE TABLE IF NOT EXISTS events_2026_06_07 PARTITION OF events
    FOR VALUES FROM ('2026-06-07') TO ('2026-06-08');

-- TODO (indexing exercise):
--   The dashboard asks "top repos in the last hour" and "events for actor X".
--   Add the indexes you think those queries need. Then EXPLAIN ANALYZE the
--   queries BEFORE and AFTER and record the row counts / timings in NOTES.md.
--   Question to answer: why might an index HURT your ingest throughput?
-- CREATE INDEX ... ;


-- -----------------------------------------------------------------------------
-- 2. ROLLUPS  (the read-fast, pre-aggregated tables)
-- -----------------------------------------------------------------------------
-- Querying raw events for every dashboard refresh does not scale. The standard
-- fix is to pre-aggregate into small "rollup" tables on a fixed time grain.
-- The dashboard reads these instead of the firehose.

-- Per-minute counts of each event type.
CREATE TABLE IF NOT EXISTS rollup_event_type_1m (
    bucket      TIMESTAMPTZ NOT NULL,   -- truncated to the minute
    event_type  TEXT        NOT NULL,
    n           BIGINT      NOT NULL,
    PRIMARY KEY (bucket, event_type)
);

-- Per-minute counts per repo (feeds "trending repos").
CREATE TABLE IF NOT EXISTS rollup_repo_1m (
    bucket  TIMESTAMPTZ NOT NULL,
    repo    TEXT        NOT NULL,
    n       BIGINT      NOT NULL,
    PRIMARY KEY (bucket, repo)
);

-- TODO (rollup exercise):
--   Write the SQL that rolls raw events into these tables. Two approaches:
--     (a) INSERT ... SELECT date_trunc('minute', created_at), count(*) ...
--         ON CONFLICT (...) DO UPDATE SET n = ...   <- idempotent upsert
--     (b) A materialized view you REFRESH on a schedule.
--   Try both. Which is idempotent if you run it twice? Which handles late data?
--   Put the answer in NOTES.md — this is a classic interview question.


-- -----------------------------------------------------------------------------
-- 3. INGEST BOOKKEEPING (idempotency / dedup)
-- -----------------------------------------------------------------------------
-- The Events API returns overlapping pages, so you WILL see the same event id
-- twice. Your pipeline must be idempotent. The events PK (id, created_at)
-- already lets you use INSERT ... ON CONFLICT DO NOTHING — but think about
-- whether that's enough, and why a dedup based purely on id could be wrong
-- across day boundaries. Notes go in NOTES.md.
