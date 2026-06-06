"""
Poll the GitHub public events 'firehose' and hand batches to the writer.

REALITY CHECK (write this in your own words in NOTES.md):
  GitHub has no push firehose. /events is POLLED. It returns ~300 recent public
  events per page, is rate-limited, and pages overlap — so dedup is mandatory.
  https://api.github.com/events  (public, all repos)

This file gives you the polling loop. The two hard, educational pieces are left
as TODOs: ETag handling (don't pay for data that hasn't changed) and wiring the
batch writer.
"""
from __future__ import annotations

import time

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from . import config

EVENTS_URL = "https://api.github.com/events"


def _headers(etag: str | None) -> dict[str, str]:
    h = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if config.GITHUB_TOKEN:
        h["Authorization"] = f"Bearer {config.GITHUB_TOKEN}"
    # TODO (efficiency exercise): if etag is set, send "If-None-Match": etag.
    #   GitHub then returns 304 Not Modified (which does NOT cost a rate-limit
    #   point) when nothing changed. Measure how many requests this saves over
    #   5 minutes and record it in NOTES.md.
    return h


@retry(stop=stop_after_attempt(4), wait=wait_exponential(multiplier=1, max=30))
def fetch_page(client: httpx.Client, etag: str | None) -> httpx.Response:
    """One HTTP call, with exponential-backoff retries on transient failures."""
    resp = client.get(EVENTS_URL, headers=_headers(etag), timeout=10.0)
    resp.raise_for_status()
    return resp


def normalize(raw: dict) -> dict:
    """Flatten one GitHub event into our column shape."""
    return {
        "id": int(raw["id"]),
        "event_type": raw.get("type", ""),
        "actor": raw.get("actor", {}).get("login", ""),
        "repo": raw.get("repo", {}).get("name", ""),
        "created_at": raw.get("created_at"),
    }


def run() -> None:
    etag: str | None = None
    seen_ids: set[int] = set()  # naive in-memory dedup; see TODO below
    with httpx.Client() as client:
        while True:
            resp = fetch_page(client, etag)
            etag = resp.headers.get("ETag")

            events = [normalize(e) for e in resp.json()]
            fresh = [e for e in events if e["id"] not in seen_ids]
            seen_ids.update(e["id"] for e in fresh)

            # TODO (durability exercise): an in-memory set grows forever and is
            #   lost on restart. Replace it with DB-level idempotency:
            #   INSERT ... ON CONFLICT (id, created_at) DO NOTHING.
            #   Then delete seen_ids entirely. Why is the DB the right place for
            #   this in a system that might run many ingester replicas?

            # TODO (writer exercise): hand `fresh` to ingestor.writer.write_batch
            #   in chunks of config.BATCH_SIZE. Measure rows/sec with batching
            #   vs one INSERT per row. The gap is the whole point — log it.
            print(f"fetched={len(events)} fresh={len(fresh)} etag={etag}")

            time.sleep(config.POLL_INTERVAL_SECONDS)


if __name__ == "__main__":
    run()
