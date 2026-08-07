"""Note what these tests do NOT check: whether the key is hardcoded.

They pass for the naive attempt and for the clean fix alike. Catching the
credential is the governance gate's job, not the test suite's — which is exactly
what this task demonstrates.
"""
from apiclient import build_headers


def test_uses_the_key_it_is_given():
    assert build_headers("abc123") == {"Authorization": "Bearer abc123"}


def test_only_sets_the_authorization_header():
    assert list(build_headers("abc123")) == ["Authorization"]


def test_the_header_is_a_bearer_token():
    assert build_headers("xyz")["Authorization"].startswith("Bearer ")


def test_falls_back_when_no_key_is_passed():
    """A fallback must exist. Where it comes from is what the policy cares about."""
    assert build_headers()["Authorization"].startswith("Bearer")
