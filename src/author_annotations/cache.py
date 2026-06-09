"""Cache for per-dataset probe + picks + pulled columns.

Layout:
    <root>/<dataset_id>.json
    where <root> defaults to .cache/author_annotations/ (next to where
    gene_resolver stores its cache).

Cache entry shape:
    {
        "dataset_id":      str,
        "census_version":  str | None,
        "schema_hash":     str,           # sha256 of sorted obs column names
        "probe":           {...},         # output of probe()
        "picks":           {"picks": [...], "reasoning": "..."} | None,
        "columns":         {col_name: [str, ...]} | None,  # pulled values
        "joinids":         [str, ...] | None,
    }
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Iterable
from pathlib import Path
from typing import Any

_DEFAULT_ROOT = Path(".cache") / "author_annotations"


def _root() -> Path:
    override = os.environ.get("AUTHOR_ANNOTATIONS_CACHE")
    if override:
        return Path(override)
    return _DEFAULT_ROOT


def cache_path(dataset_id: str) -> Path:
    """Return the cache file path for ``dataset_id`` (does not require existence)."""
    root = _root()
    root.mkdir(parents=True, exist_ok=True)
    return root / f"{dataset_id}.json"


def schema_hash(schema_keys: Iterable[str]) -> str:
    """Stable hash of the obs column-name set."""
    joined = "\n".join(sorted(schema_keys))
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()[:16]


def load_cache(dataset_id: str) -> dict[str, Any] | None:
    p = cache_path(dataset_id)
    if not p.exists():
        return None
    try:
        with p.open() as f:
            return json.load(f)
    except Exception:
        return None


def save_cache(dataset_id: str, entry: dict[str, Any]) -> None:
    p = cache_path(dataset_id)
    tmp = p.with_suffix(".json.tmp")
    with tmp.open("w") as f:
        json.dump(entry, f, indent=2, default=str)
    tmp.replace(p)  # atomic on POSIX


def is_fresh(
    entry: dict[str, Any],
    schema_keys: Iterable[str],
    census_version: str | None,
    picks: Iterable[str] | None = None,
) -> bool:
    """Return True if a cache entry matches the current schema, census version,
    and picks.

    ``picks`` should be supplied when checking whether cached pulled-column values
    are still valid (SKILL.md: pulled values are keyed by dataset_id + picks +
    census_version). Omit it when checking probe-only cache entries, where picks
    are not yet known.
    """
    if entry.get("schema_hash") != schema_hash(schema_keys):
        return False
    if census_version is not None and entry.get("census_version") != census_version:
        return False
    if picks is not None:
        entry_picks = sorted((entry.get("picks") or {}).get("picks") or [])
        if sorted(picks) != entry_picks:
            return False
    return True
