# author-annotations templates

Minimal recipes the skill emits or executes. Pick the template that matches the user's mode.

---

## Template A — fresh dataset list, emit long table

```python
from datetime import datetime
from pathlib import Path

from author_annotations import (
    probe, build_prompt, pull_full_column, to_long_table,
    load_cache, save_cache, schema_hash,
)
import cellxgene_census

DATASET_IDS = [
    "9bb9596d-f23f-4558-912f-d4dc7d52721b",
    # ... add more ...
]
SLUG = "myquery"  # short readable summary

# Census version is part of the cache key.
with cellxgene_census.open_soma(census_version="latest") as census:
    census_version = census.get("census_info").get("summary").read().concat()["census_build_date"][0].as_py()

per_dataset = {}
for dsid in DATASET_IDS:
    url = f"https://datasets.cellxgene.cziscience.com/{dsid}.h5ad"
    cached = load_cache(dsid)
    if cached and cached.get("census_version") == census_version and cached.get("columns"):
        per_dataset[dsid] = {
            "joinids": cached["joinids"],
            "columns": cached["columns"],
        }
        continue

    result = probe(url)
    sh = schema_hash(result["schema"].keys())

    # Dispatch the picker sub-agent here — see Task tool invocation in SKILL.md.
    # Read its JSON output back into `picks`.
    picks = ...  # ["BICCN_subclass_label", ...]

    joinids, columns = pull_full_column(url, picks)
    per_dataset[dsid] = {"joinids": joinids.tolist(), "columns": {k: v.tolist() if v is not None else None for k, v in columns.items()}}

    save_cache(dsid, {
        "dataset_id": dsid,
        "census_version": census_version,
        "schema_hash": sh,
        "probe": result,
        "picks": {"picks": picks},
        "joinids": per_dataset[dsid]["joinids"],
        "columns": per_dataset[dsid]["columns"],
    })

df = to_long_table(per_dataset)
ts = datetime.now().strftime("%Y%m%d_%H%M%S")
out = Path("outputs") / f"{SLUG}_{ts}_author.parquet"
df.to_parquet(out, index=False)
print(f"Wrote {len(df):,} rows to {out}")
```

---

## Template B — augment an existing h5ad in place

```python
import anndata
from author_annotations import (
    probe, build_prompt, pull_full_column, augment_h5ad,
    load_cache, save_cache,
)

H5AD_PATH = "outputs/lung_Tcell_20260525_120000.h5ad"

obs = anndata.read_h5ad(H5AD_PATH, backed="r").obs
dataset_ids = obs["dataset_id"].astype(str).unique().tolist()

per_dataset = {}
for dsid in dataset_ids:
    url = f"https://datasets.cellxgene.cziscience.com/{dsid}.h5ad"
    # same probe + picker + pull + cache flow as Template A
    ...

augment_h5ad(H5AD_PATH, per_dataset)
```

After augment, the h5ad's `obs` has new `author__<col>` columns for any cell whose source h5ad had an author cell-type column picked. Cells from datasets without picks remain NaN in those columns.

---

## Template C — extract from an existing parquet

If the upstream cxg-query produced a parquet rather than an h5ad, the obs is already in pandas. Join is simple:

```python
import pandas as pd
from author_annotations import to_long_table

obs = pd.read_parquet("outputs/lung_Tcell_20260525_120000.parquet")
# ... probe + picker + pull as above ...
long = to_long_table(per_dataset)

# Wide-pivot the author columns for an obs-style flat table
wide = long.pivot_table(index="observation_joinid", columns="author_column",
                        values="value", aggfunc="first")
wide.columns = [f"author__{c}" for c in wide.columns]
merged = obs.merge(wide, how="left", left_on="observation_joinid", right_index=True)
merged.to_parquet("outputs/lung_Tcell_20260525_120000_with_author.parquet", index=False)
```

---

## Sub-agent dispatch (mirrors `ontology-term-lookup` pattern)

```
Task subagent_type=author-category-picker
     prompt="""Read /path/to/prompt.txt. Follow its instructions. Write your
     JSON answer to /path/to/picks/<dsid>.json. Output nothing else."""
```

Dispatch one Task per dataset, in parallel.
