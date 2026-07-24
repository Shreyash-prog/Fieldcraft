def parse_bool(s):
    v = s.strip().lower()
    if v in {"true", "yes", "1", "on"}:
        return True
    if v in {"false", "no", "0", "off"}:
        return False
    raise ValueError(f"cannot parse bool: {s!r}")
