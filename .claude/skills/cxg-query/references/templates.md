# Code Templates

## Template A: `get_obs()` (metadata only)

```python
import cellxgene_census
from cxg_query_enhancer import enhance

# Pin to an explicit census build — keeps results reproducible and ensures
# soma_joinids align with the bitmap service (which uses a fixed version).
# Replace "stable" with a specific date string (e.g. "2025-11-08") if needed.
CENSUS_VERSION = cellxgene_census.get_census_version_description("stable")["release_build"]

obs_filter = enhance(
    "is_primary_data == True and [obs_value_filter]",
    organism="[homo_sapiens or mus_musculus]"
)

with cellxgene_census.open_soma(census_version=CENSUS_VERSION) as census:
    obs_df = cellxgene_census.get_obs(
        census,
        organism="[Homo sapiens or Mus musculus]",
        value_filter=obs_filter,
        column_names=[
            "cell_type", "tissue", "disease",
            "development_stage", "sex", "dataset_id"
        ]
    )

print(f"Found {len(obs_df):,} cells")
for col in ["cell_type", "tissue", "disease"]:
    if col in obs_df.columns:
        counts = obs_df[col].value_counts()
        counts = counts[counts > 0]  # census categories include all possible values
        print(f"\n{col} ({len(counts)} unique):")
        print(counts.to_string())
```

**Note**: `get_obs()` uses the parameter name `value_filter=` (not `obs_value_filter`).

---

## Template B: `get_anndata()` (expression data)

```python
import cellxgene_census
from cxg_query_enhancer import enhance

CENSUS_VERSION = cellxgene_census.get_census_version_description("stable")["release_build"]

obs_filter = enhance(
    "is_primary_data == True and [obs_value_filter]",
    organism="[homo_sapiens or mus_musculus]"
)

with cellxgene_census.open_soma(census_version=CENSUS_VERSION) as census:
    adata = cellxgene_census.get_anndata(
        census,
        organism="[Homo sapiens or Mus musculus]",
        obs_value_filter=obs_filter,
        var_value_filter="[var_value_filter or omit if no genes]",
        obs_column_names=[
            "cell_type", "tissue", "disease",
            "development_stage", "sex"
        ]
    )

print(f"Retrieved {adata.shape[0]:,} cells x {adata.shape[1]:,} genes")
print(adata.obs.head())
```

If no genes were specified, omit the `var_value_filter` parameter entirely.

---

## Template C: `get_highly_variable_genes()` (HVG)

```python
import cellxgene_census
from cxg_query_enhancer import enhance

CENSUS_VERSION = cellxgene_census.get_census_version_description("stable")["release_build"]

obs_filter = enhance(
    "is_primary_data == True and [obs_value_filter]",
    organism="[homo_sapiens or mus_musculus]"
)

with cellxgene_census.open_soma(census_version=CENSUS_VERSION) as census:
    hvg_df = cellxgene_census.get_highly_variable_genes(
        census,
        organism="[Homo sapiens or Mus musculus]",
        obs_value_filter=obs_filter,
        n_top_genes=2000
    )

print(f"Found {len(hvg_df)} highly variable genes")
print(hvg_df.head(20))
```

---

## Direct Execution

When the user wants you to run the query directly:

### 1. Pre-flight size estimate (for `get_anndata()` only)

Before fetching expression data, always run a quick `get_obs()` count first:

```python
import cellxgene_census
from cxg_query_enhancer import enhance

obs_filter = enhance("is_primary_data == True and [obs_value_filter]", organism="[homo_sapiens or mus_musculus]")

with cellxgene_census.open_soma(census_version=CENSUS_VERSION) as census:
    obs_df = cellxgene_census.get_obs(
        census,
        organism="[Homo sapiens or Mus musculus]",
        value_filter=obs_filter,
        column_names=["cell_type"]
    )

n_cells = len(obs_df)
n_genes_total = 60664  # approx total genes in census (human)
n_genes_filtered = [number of genes in var_value_filter, or n_genes_total if none]

est_mb = (n_cells * n_genes_filtered * 4) / (1024 ** 2)  # dense upper bound
est_sparse_mb = est_mb * 0.2  # sparse data is typically 10-30% of dense

print(f"Estimated: {n_cells:,} cells x {n_genes_filtered:,} genes")
print(f"Estimated download size: ~{est_sparse_mb:,.0f} MB (sparse), up to ~{est_mb:,.0f} MB (dense)")
```

- If estimated sparse size > 500 MB, warn and ask for confirmation.
- If > 5 GB, strongly recommend adding gene filters or narrowing the query.

### 2. Execute and preview

Run the full query, show shape and summary. **Always filter zero-count categories** — census `category` columns contain all possible values:

```python
for col in ["cell_type", "tissue", "disease"]:
    if col in obs_df.columns:
        counts = obs_df[col].value_counts()
        counts = counts[counts > 0]
        print(f"\n{col} ({len(counts)} unique):")
        print(counts.to_string())
```

### 3. Auto-save results

```python
import os
from datetime import datetime

os.makedirs("outputs", exist_ok=True)
timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
filename = f"outputs/{slug}_{timestamp}.h5ad"  # .h5ad for anndata, .parquet for obs/hvg
adata.write_h5ad(filename)  # or df.to_parquet(filename) for get_obs/HVG
print(f"Saved to {filename}")
```

Filename conventions:
- `get_anndata()` → `.h5ad`
- `get_obs()` / `get_highly_variable_genes()` → `.parquet`
- Slug: short readable summary of key filters (e.g. `female_Tcell_lung`), max ~40 chars
