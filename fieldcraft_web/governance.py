"""A ticket's governance policy: what it stores, and what the engine enforces.

Two shapes, deliberately kept apart:

* **Stored** (what a ticket carries, what the drawer edits) — the operator's
  *intent*: a list of protected globs plus three booleans.
  ``{"protected_paths": ["tests/"], "forbid": {"secrets": true, "eval": true,
  "network": false}}``
* **Enforced** (what `engine.advance` reads as ``cfg["policy"]``) — the compiled
  form with the actual regexes: ``{"protected_paths", "editable_paths",
  "forbidden_patterns"}``.

Storing intent rather than compiled regexes is the point. A ticket saved today
keeps meaning what it said if a pattern is tightened later; the drawer can round
-trip the operator's choices exactly instead of reverse-engineering which
checkbox produced which regex; and the patterns live in one place on the server
instead of being duplicated in JavaScript.

Nothing here enforces anything. Enforcement is unchanged and remains a single
site — `engine.advance` calling `fieldcraft_gov.enforce` — which is why this
module compiles *into* the shape that code already accepts and stops there.
"""
from __future__ import annotations

# The three toggles, and the patterns each one contributes. These are the same
# expressions the Run-a-task page's buildPolicy() has always produced; they live
# here now so a ticket's stored intent can be compiled server-side.
FORBID_PATTERNS: dict[str, dict[str, str]] = {
    "secrets": {
        "hardcoded_secret":
            r"(?i)(api[_-]?key|secret|password|token)\s*=\s*['\"][A-Za-z0-9/+_-]{12,}",
        "aws_key": r"AKIA[0-9A-Z]{16}",
    },
    "eval": {"dynamic_exec": r"\b(eval|exec)\s*\("},
    "network": {"network_call":
                r"\b(requests\.(get|post)|urllib\.request\.urlopen|socket\.socket)\b"},
}
FORBID_KEYS = tuple(FORBID_PATTERNS)

MAX_PROTECTED_PATHS = 50
MAX_PATH_LEN = 200


class PolicyError(ValueError):
    """A policy that was rejected before it could be stored."""


def validate(policy: dict | None) -> dict | None:
    """Normalise and bounds-check a stored policy. None (or an empty policy)
    means ungoverned, which is the default and is not an error.

    Raises PolicyError on anything malformed — a policy that does not parse must
    never be silently downgraded to "no policy", because the operator would
    believe their runs were governed when they were not.
    """
    if policy is None:
        return None
    if not isinstance(policy, dict):
        raise PolicyError("a governance policy must be an object")

    raw_paths = policy.get("protected_paths", [])
    if raw_paths is None:
        raw_paths = []
    if not isinstance(raw_paths, list):
        raise PolicyError("protected_paths must be a list of glob strings")
    if len(raw_paths) > MAX_PROTECTED_PATHS:
        raise PolicyError(f"at most {MAX_PROTECTED_PATHS} protected paths")
    paths: list[str] = []
    for p in raw_paths:
        if not isinstance(p, str):
            raise PolicyError("every protected path must be a string")
        p = p.strip()
        if not p:
            continue
        if len(p) > MAX_PATH_LEN:
            raise PolicyError(f"a protected path may be at most {MAX_PATH_LEN} characters")
        paths.append(p)

    raw_forbid = policy.get("forbid")
    if raw_forbid is None:
        raw_forbid = {}
    # `or {}` would be wrong here: an empty *list* is falsy and would silently
    # become "no flags" instead of being refused as the wrong type.
    if not isinstance(raw_forbid, dict):
        raise PolicyError("forbid must be an object of boolean flags")
    for k in raw_forbid:
        if k not in FORBID_PATTERNS:
            raise PolicyError(f"unknown forbid flag {k!r}; "
                              f"expected {', '.join(FORBID_KEYS)}")
    forbid = {}
    for k in FORBID_KEYS:
        v = raw_forbid.get(k, False)
        if not isinstance(v, bool):
            raise PolicyError(f"forbid.{k} must be true or false")
        forbid[k] = v

    if not paths and not any(forbid.values()):
        return None                       # nothing asked for == ungoverned
    return {"protected_paths": paths, "forbid": forbid}


def compile_policy(stored: dict | None) -> dict | None:
    """Stored intent -> the dict `engine.advance` enforces. None stays None."""
    stored = validate(stored)
    if stored is None:
        return None
    patterns: dict[str, str] = {}
    for flag, on in stored["forbid"].items():
        if on:
            patterns.update(FORBID_PATTERNS[flag])
    return {"protected_paths": list(stored["protected_paths"]),
            "editable_paths": ["**"],
            "forbidden_patterns": patterns}


def describe(stored: dict | None) -> str:
    """One line for a log or a tooltip."""
    if not stored:
        return "ungoverned"
    on = [k for k, v in stored["forbid"].items() if v]
    bits = []
    if stored["protected_paths"]:
        bits.append(f"{len(stored['protected_paths'])} protected path(s)")
    if on:
        bits.append("forbid " + "/".join(on))
    return "; ".join(bits) or "ungoverned"
