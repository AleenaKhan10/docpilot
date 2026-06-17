import re
import uuid


def make_org_slug(name: str) -> str:
    """Lowercase, hyphenated, plus a short random suffix to avoid collisions."""
    base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "org"
    return f"{base}-{uuid.uuid4().hex[:8]}"
