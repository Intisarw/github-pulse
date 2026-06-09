"""
Batch writer: moves normalized events into Postgres at high throughput.

Two paths, both idempotent (duplicates are dropped by the events PK):

- write_batch:      executemany of INSERT ... ON CONFLICT DO NOTHING.
                    Simple, pipelined by psycopg3.
- write_batch_copy: COPY into an UNLOGGED staging table, then a single
                    INSERT ... SELECT ... ON CONFLICT DO NOTHING.
                    COPY skips per-row statement overhead entirely; the
                    staging hop exists because COPY itself cannot express
                    ON CONFLICT. Measured 1.4x faster at batch=500, 1.9x
                    at batch=5000 (see README results).

Both wrap the batch in one transaction. Committing per row is ~25x slower
than the slowest batched path — every commit is a synchronous WAL flush.
"""
from __future__ import annotations

from collections.abc import Iterable

import psycopg

from . import config

COLUMNS = ("id", "event_type", "actor", "repo", "created_at")

INSERT_SQL = """
    INSERT INTO events (id, event_type, actor, repo, created_at)
    VALUES (%(id)s, %(event_type)s, %(actor)s, %(repo)s, %(created_at)s)
    ON CONFLICT (id, created_at) DO NOTHING
"""

_STAGING_DDL = """
    CREATE UNLOGGED TABLE IF NOT EXISTS events_staging (
        id          BIGINT      NOT NULL,
        event_type  TEXT        NOT NULL,
        actor       TEXT        NOT NULL,
        repo        TEXT        NOT NULL,
        created_at  TIMESTAMPTZ NOT NULL
    )
"""

_FLUSH_SQL = """
    INSERT INTO events (id, event_type, actor, repo, created_at)
    SELECT id, event_type, actor, repo, created_at FROM events_staging
    ON CONFLICT (id, created_at) DO NOTHING
"""


def _connect() -> psycopg.Connection:
    return psycopg.connect(config.DATABASE_URL)


def write_batch(rows: Iterable[dict], conn: psycopg.Connection | None = None) -> int:
    """Insert a batch idempotently via executemany. Returns rows attempted.

    Pass an open connection to amortize connection setup across batches
    (the ingester loop does); otherwise one is opened per call.
    """
    rows = list(rows)
    if not rows:
        return 0
    own = conn is None
    conn = conn or _connect()
    try:
        with conn.cursor() as cur:
            cur.executemany(INSERT_SQL, rows)
        conn.commit()
    finally:
        if own:
            conn.close()
    return len(rows)


def write_batch_copy(rows: Iterable[dict], conn: psycopg.Connection | None = None) -> int:
    """Insert a batch idempotently via COPY + staging table. Returns rows attempted."""
    rows = list(rows)
    if not rows:
        return 0
    own = conn is None
    conn = conn or _connect()
    try:
        with conn.cursor() as cur:
            cur.execute(_STAGING_DDL)
            cur.execute("TRUNCATE events_staging")
            with cur.copy(
                "COPY events_staging (id, event_type, actor, repo, created_at) FROM STDIN"
            ) as copy:
                for r in rows:
                    copy.write_row(tuple(r[c] for c in COLUMNS))
            cur.execute(_FLUSH_SQL)
        conn.commit()
    finally:
        if own:
            conn.close()
    return len(rows)
