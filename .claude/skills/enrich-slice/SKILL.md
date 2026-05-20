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
2. POST to the graph query service → cluster metadata manifest
3. POST to the bitmap query service for each cluster → `soma_joinid` sets
4. Intersect bitmaps with the slice → join author labels back by `soma_joinid`

Requires two backend services, configured via environment variables:
- `GRAPH_QUERY_SERVICE_URL` (default: `http://localhost:8011`)
- `BITMAP_QUERY_SERVICE_URL` (default: `http://localhost:8010`)

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

### Step 3: Query the graph service for matching cluster metadata

POST directly to the graph query service. Run via Bash:

```python
import json, os, requests

GRAPH_URL = os.getenv("GRAPH_QUERY_SERVICE_URL", "http://localhost:8011")
cell_types = <list from Step 2>

resp = requests.post(
    f"{GRAPH_URL}/graph/query",
    json={"cell_labels": cell_types},
    timeout=30,
)
resp.raise_for_status()
manifest = resp.json()

print(f"Clusters found: {manifest.get('cluster_count', 0)}")
```

The manifest has this shape:
```json
{
  "cluster_count": 5,
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

### Step 4: Fetch bitmaps and run the join

Fetch bitmaps for each cluster concurrently, write all intermediate files, and run the join — all in one Bash step. Use the `CENSUS_VERSION` resolved in `/cxg-query` (the same version the slice was fetched with). All paths must be absolute.

```python
import json, os, requests, subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

BITMAP_URL    = os.getenv("BITMAP_QUERY_SERVICE_URL", "http://localhost:8010")
CENSUS_VERSION = "<version used to fetch the slice, e.g. 2025-11-08>"

slice_path    = Path("<absolute path from Step 1>")
out_dir       = slice_path.parent
stem          = slice_path.stem
manifest      = <manifest dict from Step 3>

# --- fetch bitmaps ---
keys = [
    c["bitmap_lookup_key"]
    for c in manifest.get("clusters", {}).values()
    if c.get("bitmap_lookup_key")
]

def _fetch_one(iri: str) -> dict:
    try:
        resp = requests.post(
            f"{BITMAP_URL}/bitmap/query",
            json={"operation": "lookup", "clusters": [iri], "census_version": CENSUS_VERSION},
            timeout=60,
        )
        resp.raise_for_status()
        return {"bitmap_lookup_key": iri, "ok": True, "response": resp.json()}
    except Exception as exc:
        return {"bitmap_lookup_key": iri, "ok": False, "error": str(exc)}

with ThreadPoolExecutor() as pool:
    results = list(pool.map(_fetch_one, keys))

success = sum(1 for r in results if r["ok"])
bitmaps = {
    "count": len(keys),
    "success_count": success,
    "failure_count": len(keys) - success,
    "results": results,
}
print(f"Bitmaps: {success}/{len(keys)} succeeded")

# --- write intermediate files ---
manifest_json  = out_dir / f"{stem}_manifest.json"
bitmaps_json   = out_dir / f"{stem}_bitmaps.json"
output_prefix  = out_dir / f"{stem}_enriched"

manifest_json.write_text(json.dumps(manifest, ensure_ascii=False))
bitmaps_json.write_text(json.dumps(bitmaps, ensure_ascii=False))

# --- run join ---
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

### Step 5: Report results

After the join script finishes, summarise for the user:

- **Slice rows**: total cells in the input slice
- **Matched cells**: cells with ≥1 cluster hit
- **Matched clusters**: number of clusters that overlapped the slice
- **Author columns added**: list the dynamic annotation columns (e.g. `author_cell_type`, `author_cluster_label`, ...)
- **Output files**:
  - `{stem}_enriched__enriched.parquet` or `.h5ad` — main enriched slice
  - `{stem}_enriched__cluster_summary.csv` — per-cluster match counts
  - `{stem}_enriched__membership.csv` — full many-to-many join table

If `matched_cells == 0`, tell the user the bitmaps did not overlap the slice (mismatched census version is the most common cause — ensure the same version was used for both the slice fetch and the bitmap query).

---

## Edge cases

- **No clusters from graph**: manifest is empty → skip bitmap fetch, tell user.
- **All bitmaps failed**: `success_count == 0` → skip join, report errors. Check that `BITMAP_QUERY_SERVICE_URL` is reachable and `CENSUS_VERSION` matches a version the bitmap service has indexed.
- **Zero overlap**: join runs cleanly but `matched_cells == 0` → output is still written, just without author columns.
- **Multiple cluster hits per cell**: handled automatically — values are deduplicated and joined with `|`.
