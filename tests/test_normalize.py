"""Pure unit tests — no DB needed. These should pass right now (green CI)."""
from ingestor.firehose import normalize


def test_normalize_extracts_core_fields():
    raw = {
        "id": "12345",
        "type": "PushEvent",
        "actor": {"login": "octocat"},
        "repo": {"name": "octocat/hello"},
        "created_at": "2026-06-06T12:00:00Z",
    }
    out = normalize(raw)
    assert out["id"] == 12345          # note: id coerced to int
    assert out["event_type"] == "PushEvent"
    assert out["actor"] == "octocat"
    assert out["repo"] == "octocat/hello"


def test_normalize_handles_missing_nested_fields():
    out = normalize({"id": "1", "type": "WatchEvent"})
    assert out["actor"] == ""
    assert out["repo"] == ""
