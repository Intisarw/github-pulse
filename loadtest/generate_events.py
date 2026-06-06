"""
Generate synthetic GitHub-shaped events at high volume.

Use this to stress the writer and the DB far past what GitHub's rate limit would
allow. The goal of the whole project: turn the knob up until something breaks,
understand WHY, fix it, repeat. Record each breaking point in NOTES.md.

Usage:  python -m loadtest.generate_events --count 1000000 | your-writer
"""
from __future__ import annotations

import argparse
import json
import random
from datetime import datetime, timezone

EVENT_TYPES = ["PushEvent", "PullRequestEvent", "IssuesEvent", "WatchEvent",
               "ForkEvent", "CreateEvent", "IssueCommentEvent"]
REPOS = [f"org{n}/repo{m}" for n in range(50) for m in range(20)]  # 1000 repos
ACTORS = [f"user{n}" for n in range(5000)]


def gen_one(i: int) -> dict:
    return {
        "id": 10_000_000_000 + i,
        "type": random.choice(EVENT_TYPES),
        "actor": {"login": random.choice(ACTORS)},
        "repo": {"name": random.choice(REPOS)},
        "created_at": datetime.now(timezone.utc).isoformat(),  # noqa: UP017  works on 3.10+
        "public": True,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--count", type=int, default=10000)
    args = ap.parse_args()
    for i in range(args.count):
        print(json.dumps(gen_one(i)))


if __name__ == "__main__":
    main()
