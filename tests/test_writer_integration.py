"""
Integration tests against a REAL Postgres (via docker compose or CI service).

These are skipped until you implement the writer/rollup TODOs. Removing each
skip and making the test pass IS the exercise. This is also what an interviewer
loves to see: tests that exercise the hard cases (idempotency, batching).
"""
import os

import pytest

HAS_DB = bool(os.getenv("DATABASE_URL"))
pytestmark = pytest.mark.skipif(not HAS_DB, reason="set DATABASE_URL to run DB tests")


@pytest.mark.skip(reason="TODO: implement write_batch COPY path, then enable")
def test_batch_insert_is_idempotent():
    """Inserting the same batch twice must not create duplicates.
    Hint: assert row count is identical after the second write_batch call."""
    ...


@pytest.mark.skip(reason="TODO: implement rollup SQL, then enable")
def test_rollup_matches_raw_counts():
    """After rolling up, sum(rollup.n) for a window == count(raw events) in it."""
    ...
