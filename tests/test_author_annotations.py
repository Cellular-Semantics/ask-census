"""End-to-end test for the author_annotations pipeline using a synthetic local h5ad.

Covers probe -> build_prompt -> pull_full_column -> to_long_table -> augment_h5ad
without any network access. The picker sub-agent step is not exercised (it lives
outside Python — it's a Claude Code Task invocation).
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from author_annotations import (
    augment_h5ad,
    build_prompt,
    probe,
    pull_full_column,
    to_long_table,
)
from author_annotations.cache import is_fresh, schema_hash


# ---------------------------------------------------------------------------
# Fixture: tiny synthetic AnnData written as h5ad. Shape mirrors a Census-
# derived source h5ad: standardised cell_type, an author cell-type column
# stored as pandas categorical, observation_joinid, a few sample/donor
# columns. AnnData writes categoricals as HDF5 groups with codes+categories,
# matching the structure probe() decodes.
# ---------------------------------------------------------------------------

@pytest.fixture
def synthetic_h5ad(tmp_path: Path) -> Path:
    import anndata as ad

    n = 10
    obs = pd.DataFrame(
        {
            "observation_joinid": [f"J{i:03d}" for i in range(n)],
            "cell_type": pd.Categorical(
                ["T cell", "B cell", "NK cell", "T cell", "B cell",
                 "T cell", "monocyte", "monocyte", "T cell", "B cell"]
            ),
            "author_cell_type": pd.Categorical(
                ["CD4-naive", "B-mem", "NK-bright", "CD4-EM", "B-naive",
                 "CD8-EM", "cMono", "ncMono", "CD8-CM", "B-mem"]
            ),
            "broad_celltype": pd.Categorical(
                ["T", "B", "NK", "T", "B", "T", "Mono", "Mono", "T", "B"]
            ),
            "donor_id": pd.Categorical([f"d{i % 3}" for i in range(n)]),
            "n_counts": np.arange(n, dtype=np.int32) * 100,
        },
        index=[f"cell_{i}" for i in range(n)],
    )
    var = pd.DataFrame(index=["g1", "g2", "g3"])
    X = np.zeros((n, 3), dtype=np.float32)
    adata = ad.AnnData(X=X, obs=obs, var=var)

    path = tmp_path / "synthetic.h5ad"
    adata.write_h5ad(path)
    return path


# ---------------------------------------------------------------------------
# probe()
# ---------------------------------------------------------------------------

def test_probe_recovers_schema_and_samples(synthetic_h5ad: Path):
    url = f"file://{synthetic_h5ad}"
    stats: dict = {}
    result = probe(url, stats)

    # Standard top-level shape
    assert result["n_cells"] == 10
    assert result["probe_time_s"] >= 0
    assert "schema" in result and "samples" in result

    # Every obs column we wrote should be discoverable
    expected_cols = {
        "observation_joinid",
        "cell_type",
        "author_cell_type",
        "broad_celltype",
        "donor_id",
        "n_counts",
    }
    assert expected_cols.issubset(result["schema"].keys())

    # Categoricals get decoded as categorical kind with cat count
    ct = result["schema"]["author_cell_type"]
    assert ct["kind"] == "categorical"
    assert ct["n_categories"] == 9  # 10 cells, B-mem appears twice
    # The 20-row head sample should pull (and decode) values
    assert result["samples"]["author_cell_type"][:3] == ["CD4-naive", "B-mem", "NK-bright"]

    # Numeric column is an array, not a categorical
    assert result["schema"]["n_counts"]["kind"] == "array"


# ---------------------------------------------------------------------------
# build_prompt()
# ---------------------------------------------------------------------------

def test_build_prompt_lists_columns_with_samples(synthetic_h5ad: Path):
    result = probe(f"file://{synthetic_h5ad}")
    prompt = build_prompt("test-dsid", result)

    # Self-contained — has the rules + the dataset id + every obs column
    assert "test-dsid" in prompt
    assert "AUTHOR-PROVIDED" in prompt
    assert "DO NOT pick CELLxGENE-standardised fields" in prompt
    for col in ("observation_joinid", "author_cell_type", "donor_id", "n_counts"):
        assert col in prompt
    # JSON output contract reminded
    assert '{"picks":' in prompt


# ---------------------------------------------------------------------------
# pull_full_column()
# ---------------------------------------------------------------------------

def test_pull_full_column_returns_joinids_and_values(synthetic_h5ad: Path):
    url = f"file://{synthetic_h5ad}"
    joinids, cols = pull_full_column(url, ["author_cell_type", "broad_celltype"])

    assert joinids.shape == (10,)
    assert joinids[0] == "J000"
    assert cols["author_cell_type"][0] == "CD4-naive"
    assert cols["broad_celltype"][0] == "T"
    # Both columns fully materialised, no missing
    assert all(v is not None for v in cols["author_cell_type"])
    # Asking for a missing column yields None, doesn't raise
    _, cols2 = pull_full_column(url, ["nonexistent_column"])
    assert cols2["nonexistent_column"] is None


# ---------------------------------------------------------------------------
# to_long_table()
# ---------------------------------------------------------------------------

def test_to_long_table_emits_canonical_schema():
    per_dataset = {
        "ds1": {
            "joinids": np.array(["A", "B", "C"], dtype=object),
            "columns": {
                "celltype": np.array(["T", "B", "NK"], dtype=object),
                "cluster": np.array(["c1", "c2", "c1"], dtype=object),
            },
        },
        "ds2": {
            "joinids": np.array(["X", "Y"], dtype=object),
            "columns": {"celltype": np.array(["mono", "mac"], dtype=object)},
        },
    }
    df = to_long_table(per_dataset)
    assert list(df.columns) == ["observation_joinid", "dataset_id", "author_column", "value"]
    assert len(df) == 8  # 3*2 + 2*1
    # Per-cell, per-column entries are correct
    row = df[(df.dataset_id == "ds1") & (df.observation_joinid == "B")]
    assert set(row.author_column) == {"celltype", "cluster"}
    assert row.set_index("author_column").loc["celltype", "value"] == "B"


def test_to_long_table_drops_missing_values():
    per_dataset = {
        "ds1": {
            "joinids": np.array(["A", "B", "C"], dtype=object),
            "columns": {
                # Simulate a categorical with one missing code
                "celltype": np.array(["T", None, "NK"], dtype=object),
            },
        }
    }
    df = to_long_table(per_dataset)
    assert len(df) == 2  # the None row dropped
    assert "B" not in df.observation_joinid.values


# ---------------------------------------------------------------------------
# augment_h5ad()
# ---------------------------------------------------------------------------

def test_augment_h5ad_adds_author_columns_in_place(synthetic_h5ad: Path):
    import anndata as ad

    url = f"file://{synthetic_h5ad}"
    joinids, cols = pull_full_column(url, ["author_cell_type"])
    per_dataset = {
        "test-dsid": {
            "joinids": joinids,
            "columns": {"author_cell_type": cols["author_cell_type"]},
        }
    }

    augment_h5ad(synthetic_h5ad, per_dataset)

    # Re-open and inspect — cell count preserved, new column added with prefix
    after = ad.read_h5ad(synthetic_h5ad)
    assert after.n_obs == 10
    assert "author_author_cell_type" in after.obs.columns
    # Values joined correctly on observation_joinid
    after.obs["observation_joinid"] = after.obs["observation_joinid"].astype(str)
    paired = dict(zip(after.obs["observation_joinid"], after.obs["author_author_cell_type"]))
    assert paired["J000"] == "CD4-naive"
    assert paired["J007"] == "ncMono"


def test_augment_h5ad_tolerates_cells_with_no_pick(synthetic_h5ad: Path, tmp_path: Path):
    """Cells whose dataset has no author column should get NaN, not be dropped."""
    import anndata as ad
    import shutil

    h5_copy = tmp_path / "to_augment.h5ad"
    shutil.copy(synthetic_h5ad, h5_copy)

    # Pick only partial set of joinids — simulating cells from another dataset
    # in a multi-dataset query.
    per_dataset = {
        "dsX": {
            "joinids": np.array(["J000", "J001"], dtype=object),
            "columns": {"author_cell_type": np.array(["alpha", "beta"], dtype=object)},
        }
    }
    augment_h5ad(h5_copy, per_dataset)

    after = ad.read_h5ad(h5_copy)
    assert after.n_obs == 10  # nothing dropped
    obs = after.obs.copy()
    obs["observation_joinid"] = obs["observation_joinid"].astype(str)
    obs = obs.set_index("observation_joinid")
    assert obs.loc["J000", "author_author_cell_type"] == "alpha"
    assert obs.loc["J001", "author_author_cell_type"] == "beta"
    assert pd.isna(obs.loc["J005", "author_author_cell_type"])  # untouched cell


# ---------------------------------------------------------------------------
# cache utilities — pure, no IO needed for the freshness check
# ---------------------------------------------------------------------------

def test_schema_hash_is_order_independent():
    a = schema_hash(["b", "a", "c"])
    b = schema_hash(["a", "b", "c"])
    c = schema_hash(["a", "b", "d"])
    assert a == b
    assert a != c


def test_is_fresh_checks_schema_and_version():
    entry = {
        "schema_hash": schema_hash(["a", "b"]),
        "census_version": "2026-05-25",
    }
    assert is_fresh(entry, ["b", "a"], "2026-05-25")
    assert not is_fresh(entry, ["a", "b", "c"], "2026-05-25")  # schema drift
    assert not is_fresh(entry, ["a", "b"], "2026-06-01")  # version drift
    # census_version=None means caller doesn't care; only schema matters
    assert is_fresh(entry, ["a", "b"], None)
