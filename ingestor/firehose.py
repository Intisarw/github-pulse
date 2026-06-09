"""
Poll the GitHub public events "firehose" and hand batches to the writer.

Reality check: GitHub has no push firehose. /events is POLLED. It returns
~300 recent public events per page, is rate-limited, and consecutive pages
overlap — so dedup is mandatory (it lives in the DB, not here).
https://api.github.com/events

Efficiency: we send If-None-Match with the last ETag. When nothing changed,
GitHub answers 304 Not Modified, which costs no rate-limit point and no
bandwidth. We also honor the X-Poll-Interval header GitHub returns.
"""
from __future__ import annotations

import time

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from . import config, writer

EVENTS_URL = "https://api.github.com/events"


def _headers(etag: str | None) -> dict[str, str]:
    h = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if config.GITHUB_TOKEN:
        h["Authorization"] = f"Bearer {config.GITHUB_TOKEN}"
    if etag:
        h["If-None-Match"] = etag
    return h


@retry(stop=stop_after_attempt(4), wait=wait_exponential(multiplier=1, max=30))
def fetch_page(client: httpx.Client, etag: str | None) -> httpx.Response:
    """One HTTP call, with exponential-backoff retries on transient failures."""
    resp = client.get(EVENTS_URL, headers=_headers(etag), timeout=10.0)
    if resp.status_code != 304:  # 304 Not Modified is a success, not an error
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


def _chunks(items: list, size: int):
    for i in range(0, len(items), size):
        yield items[i : i + size]


def poll_once(client: httpx.Client, conn, etag: str | None) -> tuple[str | None, int, float]:
    """One poll cycle. Returns (new_etag, rows_written, seconds_to_sleep).

    Dedup is NOT done here. The events PK + ON CONFLICT DO NOTHING makes
    writes idempotent in the database, which survives restarts and stays
    correct when several ingester replicas run at once — an in-memory
    seen-ids set does neither.
    """
    resp = fetch_page(client, etag)

    if resp.status_code == 304:  # nothing changed; costs no rate-limit point
        wrote = 0
    else:
        etag = resp.headers.get("ETag")
        events = [normalize(e) for e in resp.json()]
        wrote = sum(
            writer.write_batch(chunk, conn=conn)
            for chunk in _chunks(events, config.BATCH_SIZE)
        )

    remaining = resp.headers.get("X-RateLimit-Remaining")
    print(f"status={resp.status_code} wrote={wrote} rate_remaining={remaining}")

    # GitHub tells us how often we're allowed to poll.
    interval = float(resp.headers.get("X-Poll-Interval", config.POLL_INTERVAL_SECONDS))
    return etag, wrote, max(interval, config.POLL_INTERVAL_SECONDS)


def run() -> None:
    etag: str | None = None
    with httpx.Client() as client, writer._connect() as conn:
        while True:
            etag, _, sleep_s = poll_once(client, conn, etag)
            time.sleep(sleep_s)


if __name__ == "__main__":
    run()
