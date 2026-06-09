"""Author-annotation retrieval for CELLxGENE source h5ads.

Probes obs schema + 20-row samples from any dataset's source h5ad via HTTPS
range-read, then (externally) hands the probe to an LLM sub-agent that
identifies author cell-type columns. Pulls full values for picked columns
and emits a long-format table or augments an existing h5ad.

Public API:
    probe(url, stats=None) -> dict
    build_prompt(dataset_id, probe_entry) -> str
    pull_full_column(url, column_name) -> (joinids, values)
    to_long_table(per_dataset_columns) -> pd.DataFrame
    augment_h5ad(h5ad_path, per_dataset_columns) -> None

Cache helpers:
    cache_path(dataset_id) -> Path
    load_cache(dataset_id) -> dict | None
    save_cache(dataset_id, entry) -> None
    schema_hash(schema_keys) -> str
    is_fresh(entry, schema_keys, census_version, picks=None) -> bool
"""

from .assemble import augment_h5ad, to_long_table
from .cache import cache_path, is_fresh, load_cache, save_cache, schema_hash
from .probe import describe_column, head_sample, probe
from .prompt import build_prompt
from .pull import pull_full_column

__all__ = [
    "probe",
    "describe_column",
    "head_sample",
    "build_prompt",
    "pull_full_column",
    "to_long_table",
    "augment_h5ad",
    "cache_path",
    "load_cache",
    "save_cache",
    "schema_hash",
    "is_fresh",
]
