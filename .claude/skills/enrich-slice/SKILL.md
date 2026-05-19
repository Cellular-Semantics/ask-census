---
name: enrich-slice
description: Enrich a Census obs slice (.h5ad or .parquet) with author cell type annotations — queries the CL Knowledge Base graph for matching clusters, fetches roaring bitmaps, and joins author labels back onto the slice by soma_joinid
user-invocable: true
---

# Enrich Slice with Author Annotations

Takes a Census obs slice (`.h5ad` or `.parquet`) and enriches it with author-level
cell type annotations from the CL Knowledge Base.

Flow:
1. Read unique `cell_type` values from the slice
2. Query the CL KB graph → cluster metadata manifest
3. Fetch roaring bitmaps for each cluster → `soma_joinid` sets
4. Intersect bitmaps with the slice → join author labels back by `soma_joinid`

Requires the `cl_kb` MCP server (graph service on `localhost:8000`, bitmap service on `localhost:8001`).

---

## Instructions

### Step 1: Resolve the slice path

The user invokes this skill as `/enrich-slice <path>` or `/enrich-slice` (no argument).

- If a path argument was given, use it. Resolve `~` if present.
- If no path was given, find the most recently modified `.h5ad` or `.parquet` in `outputs/`:

```python
import glob, os
from pathlib import Path

files = sorted(
    glob.glob("outputs/*.h5ad") + glob.glob("outputs/*.parquet"),
    key=os.path.getmtime,
    reverse=True,
)
if not files:
    print("No slice files found in outputs/")
else:
    print(f"Most recent slice: {Path(files[0]).resolve()}")
```

Confirm the resolved path with the user before continuing.

### Step 2: Extract unique cell type labels from the slice

These are passed to the graph query. Run via Bash:

```python
import json
from pathlib import Path

slice_path = Path("<absolute path from Step 1>")

if slice_path.suffix == ".parquet":
    import pandas as pd
    obs = pd.read_parquet(slice_path, columns=["cell_type"])
    cell_types = sorted(obs["cell_type"].dropna().unique().tolist())
else:
    import anndata as ad
    adata = ad.read_h5ad(slice_path, backed="r")
    cell_types = sorted(adata.obs["cell_type"].dropna().unique().tolist())

print(f"Unique cell types in slice: {len(cell_types)}")
print(json.dumps(cell_types))
```

### Step 3: Query the graph for matching cluster metadata

Call the `query_clusters` tool from the `cl_kb` MCP server:
- `cell_labels` = the list from Step 2

The result is a manifest dict with shape:
```json
{
  "cluster_count": 121,
  "clusters": {
    "http://example.org/...": {
      "node_iri": "...",
      "cluster_label": "...",
      "author_label_column": "...",
      "author_label": "...",
      "author_synonym_labels": { "col_name": "label_value", ... },
      "census_dataset_id": "...",
      "bitmap_lookup_key": "http://example.org/..."
    }
  }
}
```

If `cluster_count == 0` or `clusters` is empty, tell the user no matching clusters were found and stop.

### Step 4: Extract bitmap lookup keys

Run via Bash with the manifest dict pasted in:

```python
import json

manifest_dict = <paste query_clusters result>

keys = [
    c["bitmap_lookup_key"]
    for c in manifest_dict.get("clusters", {}).values()
    if c.get("bitmap_lookup_key")
]
print(f"Clusters in manifest : {manifest_dict.get('cluster_count', 0)}")
print(f"Bitmap lookup keys   : {len(keys)}")
print(json.dumps(keys))
```

### Step 5: Fetch bitmaps

Call the `fetch_bitmaps_bulk` tool from the `cl_kb` MCP server:
- `cluster_iris` = the key list from Step 4
- `census_version` = `"latest"`

Each successful result contains a `bitmap_base64` — a roaring bitmap encoding the `soma_joinid` set for that cluster in the given census version.

### Step 6: Write temp files and run the join

Run via Bash from the ask-census directory. All paths must be absolute.

```python
import json, subprocess
from pathlib import Path

slice_path = Path("<absolute path from Step 1>")
out_dir    = slice_path.parent   # outputs land alongside the slice
stem       = slice_path.stem     # e.g. "contractile_cell_normal_all_obs_20260519_114656"

manifest_dict = <paste query_clusters result>
bitmaps_dict  = <paste fetch_bitmaps_bulk result>

manifest_json = out_dir / f"{stem}_manifest.json"
bitmaps_json  = out_dir / f"{stem}_bitmaps.json"
output_prefix = out_dir / f"{stem}_enriched"

manifest_json.write_text(json.dumps(manifest_dict, ensure_ascii=False))
bitmaps_json.write_text(json.dumps(bitmaps_dict, ensure_ascii=False))
print(f"Manifest : {manifest_json}")
print(f"Bitmaps  : {bitmaps_json}")

cmd = [
    ".venv/bin/python", "src/enrich_slice_runner.py",
    "--obs-file",       str(slice_path),
    "--manifest",       str(manifest_json),
    "--bitmap-results", str(bitmaps_json),
    "--output-prefix",  str(output_prefix),
]
result = subprocess.run(cmd, capture_output=True, text=True)
print(result.stdout)
if result.returncode != 0:
    print("STDERR:", result.stderr)
```

### Step 7: Report results

After the join script finishes, summarise for the user:

- **Slice rows**: total cells in the input slice
- **Matched cells**: cells with ≥1 cluster hit
- **Matched clusters**: number of clusters that overlapped the slice
- **Author columns added**: list the dynamic annotation columns (e.g. `author_cell_type`, `author_cluster_label`, ...)
- **Output files**:
  - `{stem}_enriched__enriched.h5ad` or `.parquet` — main enriched slice
  - `{stem}_enriched__cluster_summary.csv` — per-cluster match counts
  - `{stem}_enriched__membership.csv` — full many-to-many join table

If `matched_cells == 0`, tell the user the bitmaps did not overlap the slice (mismatched census version is the most common cause).

---

## Edge cases

- **No clusters from graph**: manifest is empty → skip bitmap fetch, tell user.
- **All bitmaps failed**: `success_count == 0` in the bitmap result → skip join, report errors.
- **Zero overlap**: join runs cleanly but `matched_cells == 0` → output is still written, just without author columns.
- **Multiple cluster hits per cell**: handled automatically — values are deduplicated and joined with `|`.
