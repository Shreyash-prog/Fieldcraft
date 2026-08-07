"""Turn-1 attempt: works perfectly and ships a live credential in the source.

Every test passes. That is the point of this task — a test suite checks whether
the code runs, not whether it is safe to commit.
"""

DEFAULT_KEY = "AKIA1234567890ABCDEF"


def build_headers(api_key=None):
    key = api_key or DEFAULT_KEY
    return {"Authorization": f"Bearer {key}"}
