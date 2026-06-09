"""
Integration tests against a REAL Postgres (docker compose locally, service
container in CI). They exercise the properties the design depends on:
idempotent writes (both paths) and rollup correctness.

Opt in by setting DATABASE_URL; unit tests always run without it.
"""
from __future__ import annotations

import os
import random
import uuid
from datetime import datetime, timedelta, timezone

import pytest

UTC = timezone.utc  # noqa: UP017  (datetime.UTC needs 3.11; keep 3.10-runnable)

HAS_DB = bool(os.getenv("DATABASE_URL"))
pytestmark = pytest.mark.skipif(not HAS_DB, reason="set DATABASE_URL to run DB tests")

if HAS_DB:
    import psycopg

    from ingestor import config, writer


def _mk_events(n: int, *, repo: str, start_id: int | None = None) -> list[dict]:
    # Unique ids per call: event identity is (id, created_at), so reusing ids
    # across tests would be silently deduped by design.
    start_id = start_id or random.randrange(20_000_000_000, 2**62)
    now = datetime.now(UTC).replace(second=0, microsecond=0)
    return [
        {
            "id": start_id + i,
            "event_type": "PushEvent" if i % 2 else "WatchEvent",
            "actor": f"user{i}",
            "repo": repo,
            "created_at": now - timedelta(seconds=i),
        }
        for i in range(n)
    ]


@pytest.fixture()
def conn():
    with psycopg.connect(config.DATABASE_URL) as c:
        yield c


def _count(conn, repo: str) -> int:
    return conn.execute("SELECT count(*) FROM events WHERE repo = %s", (repo,)).fetchone()[0]


@pytest.mark.parametrize("write", ["write_batch", "write_batch_copy"])
def test_batch_insert_is_idempotent(conn, write):
    """Writing the same batch twice must not create duplicates."""
    repo = f"test/idem-{uuid.uuid4().hex[:8]}"
    batch = _mk_events(100, repo=repo)
    fn = getattr(writer, write)

    assert fn(batch, conn=conn) == 100
    assert _count(conn, repo) == 100

    fn(batch, conn=conn)  # retry the whole batch — e.g. after a crash
    assert _count(conn, repo) == 100, "duplicates created on retry"


def test_rollup_matches_raw_counts(conn):
    """After rolling up, sum(rollup.n) for the window == count of raw events."""
    repo = f"test/rollup-{uuid.uuid4().hex[:8]}"
    writer.write_batch(_mk_events(57, repo=repo), conn=conn)

    conn.execute("SELECT refresh_rollups(now() - interval '1 hour', now() + interval '1 hour')")
    conn.commit()

    rolled = conn.execute(
        "SELECT coalesce(sum(n), 0) FROM rollup_repo_1m WHERE repo = %s", (repo,)
    ).fetchone()[0]
    assert rolled == _count(conn, repo) == 57


def test_rollup_is_idempotent_and_absorbs_late_data(conn):
    """Re-running the rollup converges; late events inside the window are counted."""
    repo = f"test/late-{uuid.uuid4().hex[:8]}"
    writer.write_batch(_mk_events(10, repo=repo), conn=conn)

    def roll():
        conn.execute(
            "SELECT refresh_rollups(now() - interval '1 hour', now() + interval '1 hour')"
        )
        conn.commit()

    roll()
    roll()  # second run must not double-count
    rolled = conn.execute(
        "SELECT sum(n) FROM rollup_repo_1m WHERE repo = %s", (repo,)
    ).fetchone()[0]
    assert rolled == 10

    # a late event arrives inside the already-rolled-up window
    writer.write_batch(_mk_events(1, repo=repo), conn=conn)
    roll()
    rolled = conn.execute(
        "SELECT sum(n) FROM rollup_repo_1m WHERE repo = %s", (repo,)
    ).fetchone()[0]
    assert rolled == 11
