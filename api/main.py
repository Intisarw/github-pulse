"""
Read path: the query API the dashboard calls.

LEARNING FOCUS: every endpoint here should read from a ROLLUP table, never scan
raw `events`. If you find yourself querying `events` for a dashboard request,
that's a signal you need another rollup. Add a Redis cache in front only AFTER
you've measured that the DB query is actually the bottleneck (don't cache blind).
"""
from __future__ import annotations

import psycopg
from fastapi import FastAPI

from ingestor import config

app = FastAPI(title="GitHub Pulse API")


def _query(sql: str, params: tuple = ()) -> list[dict]:
    with psycopg.connect(config.DATABASE_URL) as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            cols = [c.name for c in cur.description]
            return [dict(zip(cols, row, strict=False)) for row in cur.fetchall()]


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/trending/repos")
def trending_repos(minutes: int = 60, limit: int = 20) -> list[dict]:
    """Top repos by event count over the last N minutes — reads the rollup.

    TODO: implement against rollup_repo_1m. Starter query:
      SELECT repo, sum(n) AS events
      FROM rollup_repo_1m
      WHERE bucket >= now() - make_interval(mins => %s)
      GROUP BY repo ORDER BY events DESC LIMIT %s
    Then EXPLAIN ANALYZE it and add the index it wants. Record before/after.
    """
    return _query(
        """
        SELECT repo, sum(n) AS events
        FROM rollup_repo_1m
        WHERE bucket >= now() - make_interval(mins => %s)
        GROUP BY repo
        ORDER BY events DESC
        LIMIT %s
        """,
        (minutes, limit),
    )


@app.get("/stats/event-types")
def event_type_stats(minutes: int = 60) -> list[dict]:
    """TODO: same pattern against rollup_event_type_1m."""
    return []
