"""
Rollup runner: periodically re-aggregates the recent window of raw events
into the rollup tables via the refresh_rollups() SQL function.

The recompute window (ROLLUP_WINDOW_MINUTES, default 5) deliberately overlaps
previous runs: the upsert is idempotent, so re-aggregating a minute we've
already rolled up just overwrites it with the (possibly larger) correct count.
That overlap is what makes late-arriving events safe.
"""
from __future__ import annotations

import time

import psycopg

from . import config


def refresh_once(conn: psycopg.Connection) -> None:
    conn.execute(
        "SELECT refresh_rollups(now() - make_interval(mins => %s), now() + interval '1 minute')",
        (config.ROLLUP_WINDOW_MINUTES,),
    )
    conn.commit()


def run() -> None:
    with psycopg.connect(config.DATABASE_URL) as conn:
        while True:
            refresh_once(conn)
            time.sleep(config.ROLLUP_INTERVAL_SECONDS)


if __name__ == "__main__":
    run()
