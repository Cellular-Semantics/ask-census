"""Assemble pulled author annotations into a long table or augment an h5ad.

Long-format schema:
    observation_joinid : str
    dataset_id         : str
    author_column      : str
    value              : str  (NaN for cells where the column is missing)

Augment-h5ad path:
    Adds picked columns into existing AnnData.obs, prefixed `author_<col>`,
    joining on `observation_joinid`. Cells whose dataset has no author pick
    receive NaN — cell count is unchanged.
"""
from __future__ import annotations

from pathlib import Path
from typing import Dict, Iterable, List, Mapping

import numpy as np
import pandas as pd

# Per-dataset author-column pull result shape:
#   {dataset_id: {"joinids": np.ndarray[str],
#                 "columns": {col_name: np.ndarray[str] | None}}}
PerDataset = Mapping[str, Mapping[str, object]]


def to_long_table(per_dataset: PerDataset) -> pd.DataFrame:
    """Build the long-format author-annotation table.

    Returns a DataFrame with columns:
        observation_joinid, dataset_id, author_column, value
    """
    frames: List[pd.DataFrame] = []
    for dsid, payload in per_dataset.items():
        joinids = payload.get("joinids")  # type: ignore[assignment]
        columns = payload.get("columns") or {}  # type: ignore[assignment]
        if joinids is None or len(joinids) == 0:
            continue
        for col_name, values in columns.items():  # type: ignore[union-attr]
            if values is None:
                continue
            df = pd.DataFrame(
                {
                    "observation_joinid": joinids,
                    "dataset_id": dsid,
                    "author_column": col_name,
                    "value": values,
                }
            )
            # Drop rows where value is None / NaN — they add no information
            df = df[df["value"].notna()]
            frames.append(df)
    if not frames:
        return pd.DataFrame(
            columns=["observation_joinid", "dataset_id", "author_column", "value"]
        )
    out = pd.concat(frames, ignore_index=True)
    # Stringify for portability across category dtypes
    out["observation_joinid"] = out["observation_joinid"].astype(str)
    out["value"] = out["value"].astype(str)
    return out


def augment_h5ad(h5ad_path: str | Path, per_dataset: PerDataset) -> None:
    """Add picked author columns to an existing h5ad's obs in-place.

    Each picked column becomes ``author_<col_name>`` in ``adata.obs``,
    joined on ``observation_joinid``. Cells from datasets without a pick
    receive NaN.

    Requires ``observation_joinid`` to be present in ``adata.obs`` (it
    is for any Census-derived AnnData).
    """
    import anndata  # noqa: WPS433 — heavy import deferred

    h5ad_path = Path(h5ad_path)
    adata = anndata.read_h5ad(h5ad_path)
    if "observation_joinid" not in adata.obs.columns:
        raise ValueError(
            f"{h5ad_path}: obs has no observation_joinid; cannot join author "
            "annotations."
        )

    # Build a long table indexed by observation_joinid for fast lookup.
    long = to_long_table(per_dataset)
    if long.empty:
        return  # nothing to add

    # Pivot wide: one column per (author_column) across all datasets.
    # If the same column name appears in multiple datasets, values from the
    # dataset of the relevant cells will populate that cell's row — joins
    # don't collide because each joinid is unique.
    wide = long.pivot_table(
        index="observation_joinid",
        columns="author_column",
        values="value",
        aggfunc="first",
    )
    wide.columns = [f"author_{c}" for c in wide.columns]

    # Left-join into obs on observation_joinid.
    obs = adata.obs.copy()
    obs["observation_joinid"] = obs["observation_joinid"].astype(str)
    obs = obs.merge(wide, how="left", left_on="observation_joinid", right_index=True)
    adata.obs = obs

    adata.write_h5ad(h5ad_path)
