import re
def to_snake(name):
    s = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", name)
    return re.sub(r"[-\s]+", "_", s).lower()

def to_camel(name):
    parts = re.split(r"[_\-\s]+", name)
    return parts[0].lower() + "".join(p.capitalize() for p in parts[1:])
