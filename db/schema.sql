-- =============================================================================
-- GitHub Pulse — database schema
-- =============================================================================
-- Loaded automatically when the Postgres container first starts
-- (mounted into /docker-entrypoint-initdb.d by docker-compose.yml).
-- =============================================================================

-- -----------------------------------------------------------------------------
-- 1. RAW EVENTS  (write-heavy, append-only)
-- -----------------------------------------------------------------------------
-- Partitioned BY RANGE on created_at (time), because:
--   - Events arrive in time order, so writes always hit the newest partition,
--     which keeps that partition's indexes hot in cache.
--   - Retention is a metadata operation: DETACH/DROP a whole day instead of a
--     slow DELETE that bloats the table and forces a vacuum.
--   - Dashboard queries are time-bounded ("last 60 minutes"), so the planner
--     prunes every partition outside the window before touching disk.
--
-- Partitioning by repo was rejected: writes would scatter across all
-- partitions (no locality), retention would still require DELETEs, and the
-- hot-repo skew would make partitions wildly uneven. See DESIGN.md D2.

CREATE TABLE IF NOT EXISTS events (
    id          BIGINT       NOT NULL,
    event_type  TEXT         NOT NULL,   -- PushEvent, PullRequestEvent, ...
    actor       TEXT         NOT NULL,   -- the user login
    repo        TEXT         NOT NULL,   -- "owner/name"
    created_at  TIMESTAMPTZ  NOT NULL,
    ingested_at TIMESTAMPTZ  NOT NULL DEFAULT now(),
    -- A PRIMARY KEY on a partitioned table MUST include the partition key:
    -- uniqueness is enforced per-partition, so the key has to determine which
    -- partition a row lives in.
    PRIMARY KEY (id, created_at)
) PARTITION BY RANGE (created_at);

-- Partition management: one partition per UTC day. ensure_events_partition()
-- is idempotent; init covers yesterday..+7 days, and a daily cron (or
-- pg_partman in production) keeps the window rolling.
CREATE OR REPLACE FUNCTION ensure_events_partition(day date)
RETURNS void
LANGUAGE plpgsql AS $$
BEGIN
    EXECUTE format(
        'CREATE TABLE IF NOT EXISTS %I PARTITION OF events
             FOR VALUES FROM (%L) TO (%L)',
        'events_' || to_char(day, 'YYYY_MM_DD'), day, day + 1
    );
END $$;

DO $$
DECLARE d date;
BEGIN
    FOR d IN SELECT generate_series(current_date - 1, current_date + 7, '1 day')::date
    LOOP
        PERFORM ensure_events_partition(d);
    END LOOP;
END $$;

-- Indexes for the ad-hoc queries the rollups don't cover ("events for actor X",
-- "activity for repo Y"). These are partitioned indexes — each daily partition
-- gets its own small B-tree, which stays cache-resident for the hot partition.
--
-- Trade-off (measured, see DESIGN.md §2): every index is extra work per row
-- inserted. With these two indexes, COPY throughput dropped from ~154k to
-- ~84k rows/s (-46%) on a fresh partition. Worth it for read paths we
-- actually have; anything speculative is not.
CREATE INDEX IF NOT EXISTS events_repo_created_idx  ON events (repo,  created_at);
CREATE INDEX IF NOT EXISTS events_actor_created_idx ON events (actor, created_at);


-- -----------------------------------------------------------------------------
-- 2. ROLLUPS  (read-fast, pre-aggregated)
-- -----------------------------------------------------------------------------
-- The dashboard never scans raw events; it reads these per-minute aggregates.
-- Both tables are tiny relative to `events` (bounded by distinct values per
-- minute, not by event volume).

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

-- Incremental rollup via idempotent upsert.
--
-- Chosen over a materialized view because:
--   - Idempotent: recomputes the window from raw events and overwrites, so
--     running it twice (or after a crash) converges to the same state.
--   - Handles late-arriving data: any event that lands inside the recompute
--     window is picked up on the next run; a matview would need a full REFRESH.
--   - Incremental: touches only the window, not the whole history. REFRESH
--     MATERIALIZED VIEW recomputes everything, which stops being viable fast.
--
-- Call with a window that generously covers ingest lag, e.g. every 15s with
-- win_start = now() - interval '5 minutes'.
CREATE OR REPLACE FUNCTION refresh_rollups(win_start timestamptz, win_end timestamptz)
RETURNS void
LANGUAGE sql AS $$
    INSERT INTO rollup_event_type_1m (bucket, event_type, n)
    SELECT date_trunc('minute', created_at), event_type, count(*)
    FROM events
    WHERE created_at >= win_start AND created_at < win_end
    GROUP BY 1, 2
    ON CONFLICT (bucket, event_type) DO UPDATE SET n = EXCLUDED.n;

    INSERT INTO rollup_repo_1m (bucket, repo, n)
    SELECT date_trunc('minute', created_at), repo, count(*)
    FROM events
    WHERE created_at >= win_start AND created_at < win_end
    GROUP BY 1, 2
    ON CONFLICT (bucket, repo) DO UPDATE SET n = EXCLUDED.n;
$$;


-- -----------------------------------------------------------------------------
-- 3. IDEMPOTENCY / DEDUP
-- -----------------------------------------------------------------------------
-- The Events API returns overlapping pages, so the same event id WILL arrive
-- more than once. Dedup lives in the database — INSERT ... ON CONFLICT
-- (id, created_at) DO NOTHING — not in application memory, because:
--   - it survives ingester restarts (an in-memory set does not), and
--   - it stays correct when multiple ingester replicas write concurrently.
-- Caveat: the PK is (id, created_at), so dedup is scoped per partition key
-- value. GitHub event ids are globally unique with a fixed created_at, so a
-- duplicate always carries the same (id, created_at) pair and lands on the
-- same conflict target.
