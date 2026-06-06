"""
Batch writer: the component that teaches you write throughput.

The single most important lesson here: inserting rows one-by-one is slow because
each INSERT is a network round-trip + a transaction. Batching amortizes both.
psycopg3's executemany / COPY are the tools. Build it, then BENCHMARK it.
"""
from __future__ import annotations

from collections.abc import Iterable

import psycopg

from . import config

INSERT_SQL = """
    INSERT INTO events (id, event_type, actor, repo, created_at)
    VALUES (%(id)s, %(event_type)s, %(actor)s, %(repo)s, %(created_at)s)
    ON CONFLICT (id, created_at) DO NOTHING
"""


def write_batch(rows: Iterable[dict]) -> int:
    """Insert a batch idempotently. Returns rows attempted.

    TODO (throughput exercise):
      1. Get this working with executemany (below).
      2. Then implement a COPY-based path (psycopg `cursor.copy`) and compare
         rows/sec. COPY is usually 5-20x faster — confirm the number yourself.
      3. Wrap the batch in a single transaction. What happens to throughput if
         you commit per row instead? Record all three numbers in NOTES.md.
    """
    rows = list(rows)
    if not rows:
        return 0
    with psycopg.connect(config.DATABASE_URL) as conn:
        with conn.cursor() as cur:
            cur.executemany(INSERT_SQL, rows)
        conn.commit()
    return len(rows)
