"""Same behaviour, no credential in the source: the fallback comes from the
environment, where it can be rotated without touching the code."""
import os

ENV_VAR = "FIELDCRAFT_API_KEY"


def build_headers(api_key=None):
    key = api_key or os.environ.get(ENV_VAR, "")
    return {"Authorization": f"Bearer {key}"}
