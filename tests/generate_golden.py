"""Generate golden fixture files for integration tests.

Run once to create/update the baseline:
    uv run --with . python tests/generate_golden.py

Golden files are committed to git. Integration tests compare against them.
"""

from __future__ import annotations

import json
from pathlib import Path

from author_annotations import probe, pull_full_column

FIXTURES_DIR = Path(__file__).parent / "fixtures"
FIXTURES_DIR.mkdir(exist_ok=True)

DATASETS = [
    {
        "name": "tasic2016",
        "dataset_id": "3a15ab1c-c36c-4842-9a3e-47e6ffd0ba6f",
        "url": "https://datasets.cellxgene.cziscience.com/7c296570-f51b-41e4-b5b8-e89f5fc8f402.h5ad",
        "author_cols": ["BICCN_cluster_label", "BICCN_class_label"],
    },
    {
        "name": "muraro2016",
        "dataset_id": "b07e5164-baf6-43d2-bdba-5a249d0da879",
        "url": "https://datasets.cellxgene.cziscience.com/e4218427-f7ce-4506-a8fd-40607a652149.h5ad",
        "author_cols": ["cellular_classification"],
    },
]


def generate(ds: dict) -> dict:
    name = ds["name"]
    print(f"Probing {name} ...", flush=True)
    p = probe(ds["url"])
    mb = p["probe_bytes"] / 1e6
    print(f"  n_cells={p['n_cells']}  cols={p['n_obs_cols']}  {mb:.1f} MB")

    print(f"  Pulling {ds['author_cols']} ...", flush=True)
    joinids, cols = pull_full_column(ds["url"], ds["author_cols"])
    print(f"  joinids={joinids.shape[0]}")

    golden = {
        "dataset_id": ds["dataset_id"],
        "url": ds["url"],
        "n_cells": p["n_cells"],
        "n_obs_cols": p["n_obs_cols"],
        "schema_keys": sorted(p["schema"].keys()),
        "schema": p["schema"],
        "samples": p["samples"],
        "author_cols": ds["author_cols"],
        "pull": {
            "joinids_count": int(joinids.shape[0]),
            "first5_joinids": list(joinids[:5]),
            "first5_values": {
                c: list(cols[c][:5]) if cols[c] is not None else None
                for c in ds["author_cols"]
            },
        },
    }
    return golden


def main():
    for ds in DATASETS:
        out_path = FIXTURES_DIR / f"{ds['name']}_golden.json"
        golden = generate(ds)
        out_path.write_text(json.dumps(golden, indent=2))
        print(f"  Wrote {out_path}")
    print("\nDone. Commit tests/fixtures/ to lock the regression baseline.")


if __name__ == "__main__":
    main()
