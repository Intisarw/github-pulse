"""
Read path: the query API the dashboard calls.

Every endpoint reads from a ROLLUP table, never raw `events`. The rollups are
bounded by (minutes x distinct values), not by event volume, so dashboard
latency stays flat as ingest grows. A Redis cache in front belongs here only
if measurement shows the DB is the bottleneck (it wasn't at our load — see
DESIGN.md D6).
"""
from __future__ import annotations

from fastapi import FastAPI
from psycopg_pool import ConnectionPool

from ingestor import config

app = FastAPI(title="GitHub Pulse API")

# Connection pool, not connect-per-request: every Postgres connection is a
# backend fork + auth round-trip. Measured at 50 concurrent users:
# connect-per-request 266 req/s / p95 279ms; pooled 369 req/s / p95 182ms
# (+39% throughput, -35% p95). See README results.
pool = ConnectionPool(config.DATABASE_URL, min_size=4, max_size=16, open=False)


@app.on_event("startup")
def _open_pool() -> None:
    pool.open()


def _query(sql: str, params: tuple = ()) -> list[dict]:
    with pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            cols = [c.name for c in cur.description]
            return [dict(zip(cols, row, strict=False)) for row in cur.fetchall()]


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/trending/repos")
def trending_repos(minutes: int = 60, limit: int = 20) -> list[dict]:
    """Top repos by event count over the last N minutes — reads rollup_repo_1m.

    The rollup PK (bucket, repo) gives the planner an index range scan on the
    time window; no extra index needed.
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
    """Event volume by type over the last N minutes — reads rollup_event_type_1m."""
    return _query(
        """
        SELECT event_type, sum(n) AS events
        FROM rollup_event_type_1m
        WHERE bucket >= now() - make_interval(mins => %s)
        GROUP BY event_type
        ORDER BY events DESC
        """,
        (minutes,),
    )


@app.get("/stats/timeline")
def timeline(minutes: int = 60) -> list[dict]:
    """Per-minute total event volume — feeds the dashboard's activity chart."""
    return _query(
        """
        SELECT bucket, sum(n) AS events
        FROM rollup_event_type_1m
        WHERE bucket >= now() - make_interval(mins => %s)
        GROUP BY bucket
        ORDER BY bucket
        """,
        (minutes,),
    )
