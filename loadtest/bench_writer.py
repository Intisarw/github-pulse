"""
Benchmark the write path: commit-per-row vs executemany vs COPY.

This script produced the numbers in the README results table. Run it against
a scratch database — it writes real rows (to a dedicated repo prefix) and
deletes them afterwards.

Usage:
    DATABASE_URL=postgresql://pulse:pulse@localhost:5432/pulse \
        python -m loadtest.bench_writer --rows 50000 --batch 500
"""
from __future__ import annotations

import argparse
import random
import time
from datetime import datetime, timedelta, timezone

import psycopg

from ingestor import config, writer
from loadtest.generate_events import EVENT_TYPES, REPOS

BENCH_PREFIX = "bench/"


def mk_rows(n: int) -> list[dict]:
    base = random.randrange(30_000_000_000, 2**62)
    now = datetime.now(timezone.utc)  # noqa: UP017
    return [
        {
            "id": base + i,
            "event_type": random.choice(EVENT_TYPES),
            "actor": f"user{random.randrange(5000)}",
            "repo": BENCH_PREFIX + random.choice(REPOS),
            "created_at": now - timedelta(seconds=random.uniform(0, 3600)),
        }
        for i in range(n)
    ]


def bench(label: str, rows: list[dict], fn) -> float:
    t0 = time.perf_counter()
    fn(rows)
    dt = time.perf_counter() - t0
    rate = len(rows) / dt
    print(f"{label:<28} {len(rows):>7} rows  {dt:7.2f}s  {rate:>10,.0f} rows/s")
    return rate


def commit_per_row(rows: list[dict]) -> None:
    """The anti-pattern, for scale: every commit is a synchronous WAL flush."""
    with psycopg.connect(config.DATABASE_URL) as conn:
        for r in rows:
            conn.execute(writer.INSERT_SQL, r)
            conn.commit()


def batched(fn, batch_size: int):
    def run(rows: list[dict]) -> None:
        with psycopg.connect(config.DATABASE_URL) as conn:
            for i in range(0, len(rows), batch_size):
                fn(rows[i : i + batch_size], conn=conn)

    return run


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rows", type=int, default=50_000)
    ap.add_argument("--batch", type=int, default=500)
    ap.add_argument("--per-row-rows", type=int, default=2_000,
                    help="commit-per-row is so slow it gets a smaller sample")
    args = ap.parse_args()

    print(f"batch={args.batch}, fresh ids per run (no conflicts)\n")
    bench("commit-per-row", mk_rows(args.per_row_rows), commit_per_row)
    bench(f"executemany (batch={args.batch})", mk_rows(args.rows),
          batched(writer.write_batch, args.batch))
    bench(f"COPY+staging (batch={args.batch})", mk_rows(args.rows),
          batched(writer.write_batch_copy, args.batch))
    bench("COPY+staging (batch=5000)", mk_rows(args.rows),
          batched(writer.write_batch_copy, 5000))

    with psycopg.connect(config.DATABASE_URL) as conn:
        conn.execute("DELETE FROM events WHERE repo LIKE %s", (BENCH_PREFIX + "%",))
        conn.commit()
    print("\nbench rows cleaned up")


if __name__ == "__main__":
    main()
