"""Unit test for the synthetic generator — keeps load-test data well-formed."""
from loadtest.generate_events import gen_one


def test_generated_event_shape():
    e = gen_one(0)
    assert set(e) >= {"id", "type", "actor", "repo", "created_at"}
    assert isinstance(e["id"], int)
    assert e["actor"]["login"].startswith("user")
