"""Unit tests for the polling loop — no network, no DB.

httpx.MockTransport fakes the GitHub API; write_batch is monkeypatched to
capture what would be written. Verifies the ETag round-trip, 304 handling,
and X-Poll-Interval adherence.
"""
from __future__ import annotations

import httpx

from ingestor import firehose


def _event(i: int) -> dict:
    return {
        "id": str(i),
        "type": "PushEvent",
        "actor": {"login": f"user{i}"},
        "repo": {"name": "octocat/hello"},
        "created_at": "2026-06-09T12:00:00Z",
    }


def test_poll_once_writes_events_and_keeps_etag(monkeypatch):
    written: list[dict] = []
    monkeypatch.setattr(
        firehose.writer, "write_batch", lambda rows, conn=None: written.extend(rows) or len(rows)
    )

    def handler(request: httpx.Request) -> httpx.Response:
        assert "If-None-Match" not in request.headers  # first poll: no etag yet
        return httpx.Response(
            200,
            json=[_event(1), _event(2)],
            headers={"ETag": 'W/"abc"', "X-Poll-Interval": "2"},
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        etag, wrote, sleep_s = firehose.poll_once(client, conn=None, etag=None)

    assert etag == 'W/"abc"'
    assert wrote == 2
    assert sleep_s == 2.0
    assert written[0]["id"] == 1 and written[0]["actor"] == "user1"


def test_poll_once_sends_etag_and_handles_304(monkeypatch):
    monkeypatch.setattr(
        firehose.writer, "write_batch",
        lambda rows, conn=None: (_ for _ in ()).throw(AssertionError("must not write on 304")),
    )

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["If-None-Match"] == 'W/"abc"'
        return httpx.Response(304)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        etag, wrote, _ = firehose.poll_once(client, conn=None, etag='W/"abc"')

    assert etag == 'W/"abc"'  # kept for the next poll
    assert wrote == 0


def test_poll_once_chunks_large_pages(monkeypatch):
    batches: list[int] = []
    monkeypatch.setattr(
        firehose.writer, "write_batch",
        lambda rows, conn=None: batches.append(len(rows)) or len(rows),
    )
    monkeypatch.setattr(firehose.config, "BATCH_SIZE", 100)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[_event(i) for i in range(250)])

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        _, wrote, _ = firehose.poll_once(client, conn=None, etag=None)

    assert wrote == 250
    assert batches == [100, 100, 50]
