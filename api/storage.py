"""Raw-payload object storage on the VPS volume (§5.1). Postgres keeps only
the relative URI; the envelope holds the request, the full provider response,
and the parsed convenience view."""

import json
from pathlib import Path
from typing import Any

from api.config import get_settings


def write_raw_envelope(tenant_slug: str, run_id: int, name: str, envelope: dict[str, Any]) -> str:
    """Returns the URI stored in results.raw_uri — a path relative to
    RAW_STORAGE_DIR, so the volume can move without rewriting rows."""
    rel = f"{tenant_slug}/run-{run_id}/{name}.json"
    path = Path(get_settings().raw_storage_dir) / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(envelope, ensure_ascii=False, indent=2), encoding="utf-8")
    return rel


def read_raw_envelope(raw_uri: str) -> dict[str, Any] | None:
    root = Path(get_settings().raw_storage_dir).resolve()
    path = (root / raw_uri).resolve()
    # raw_uri comes from our own DB, but never let a crafted value escape the
    # storage root.
    if not path.is_relative_to(root) or not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))
