---
name: author-annotations
description: Retrieve author-provided cell-type annotations from CELLxGENE source h5ads via cheap HTTPS range-reads, then return a long-format Parquet table and/or augment a Census-derived h5ad. Use when a query has produced dataset_ids and the user wants author labels beyond the CELLxGENE-standardised cell_type field.
user-invocable: true
---

# Author annotations

CELLxGENE Census strips dataset-specific author cell-type fields (e.g. `BICCN_subclass_label`, `celltype`, `cell_type_fine`, `Cell.class`) during ingest — they survive only in the per-dataset **source h5ads**. This skill recovers them on demand with no manual curation: a cheap HTTPS range-read probes each source h5ad's obs schema + a 20-row sample of every column, an LLM sub-agent picks the author cell-type columns from that probe, then full values are pulled for the picked columns and assembled into a long-format table (and optionally written back into an existing h5ad's `obs`).

Benchmark on n=73 datasets vs CL_KG hand curation: **Jaccard 0.81, recall 0.97, hit-rate 99 %** — see [agent_celltype_eval](https://github.com/Cellular-Semantics/agent_celltype_eval).

---

## When to invoke

- After a `cxg-query` execution that produced `dataset_id`s and the user asks for author labels, cell-type granularity beyond CL, marker-encoded cluster names, or "the original annotations".
- Standalone, when the user names dataset_ids directly.

If the user only wants the standardised CELLxGENE `cell_type` field, this skill is not needed — `cxg-query` already returns it.

## Modes

1. **Augment an existing query output** — pass a path to a previously-produced `outputs/*.h5ad` or `outputs/*.parquet`. The skill reads `dataset_id`s from the file, fetches author columns, writes a sibling `*_author.parquet` table, and (for h5ad inputs) writes the augmented `obs` back into the h5ad in place.
2. **Fresh dataset list** — pass one or more `dataset_id`s. The skill probes them and emits `outputs/{slug}_{timestamp}_author.parquet` with the long table.

## Instructions

### Step 1: Collect dataset_ids

Either parse the user's literal list, or read `obs['dataset_id'].unique()` from the supplied file. Deduplicate.

### Step 2: Probe each dataset

For each `dataset_id`:

- Compute `url = f"https://datasets.cellxgene.cziscience.com/{dsid}.h5ad"`.
- Check `.cache/author_annotations/{dsid}.json` — if present and `schema_hash` matches the current obs schema (or the cache is younger than the current Census release), reuse it; skip to Step 4.
- Otherwise run the probe:

  ```python
  from author_annotations import probe
  result = probe(url)   # ~9 MB / ~13 s cross-region
  ```

  `result` is a dict with `schema`, `samples`, `n_obs_cols`, `n_cells`, `probe_bytes`, `probe_gets`, `probe_time_s`.

Run probes in parallel where possible (each call is independent).

### Step 3: Pick author cell-type columns (sub-agent)

For each newly-probed dataset:

```python
from author_annotations import build_prompt
prompt_text = build_prompt(dsid, result)
# write to a transient path under .cache/author_annotations/_prompts/
```

Then dispatch the `author-category-picker` sub-agent via the **`Task` tool** with `subagent_type=author-category-picker`. Tell the sub-agent the path to its prompt file and the path it must write its JSON answer to. Launch dispatches **in parallel** — same pattern as `cxg-query` uses for `ontology-term-lookup`.

The sub-agent's output is `{"picks": ["col1", ...], "reasoning": "<sentence>"}` written to disk. Read it back and store in cache.

### Step 4: Pull picked-column values

For each `(dataset_id, picks)`:

```python
from author_annotations import pull_full_column
joinids, columns = pull_full_column(url, picks)
```

`columns` is `{col_name: ndarray[str] | None}`. None means the column was missing or failed to decode — log and continue.

Cache the pulled values keyed by `(dataset_id, picks, census_version)` so repeat queries are free.

### Step 5: Emit outputs

For breakdown deliverable (d) — **long-format table**:

```python
from author_annotations import to_long_table
df = to_long_table(per_dataset)   # cols: observation_joinid, dataset_id, author_column, value
df.to_parquet(f"outputs/{slug}_{ts}_author.parquet", index=False)
```

For breakdown deliverable (e) — **augment h5ad in place** (only if input was an h5ad):

```python
from author_annotations import augment_h5ad
augment_h5ad("outputs/<file>.h5ad", per_dataset)
```

This adds `author__<column>` fields to `adata.obs`, joined on `observation_joinid`. The double-underscore separator avoids ambiguity when the source column is already prefixed with `author_` (e.g. `author_cell_type` → `author__author_cell_type`). Cells from datasets where no author cell-type column was picked receive NaN — cell count is unchanged.

### Step 6: Report to the user

Always summarise:

- Datasets probed (N successful / N attempted)
- Total wire transfer + median per-dataset cost
- Picks per dataset (`{dsid}: [col1, col2]`)
- Output paths
- Any datasets with empty picks (note these are potential curation gaps)

---

## Important notes

- The CELLxGENE datasets CDN (`https://datasets.cellxgene.cziscience.com/{dsid}.h5ad`) is used directly, not the Census S3 mirror — Census `dataset_id`s drift across releases but the CDN URL is stable for any dataset_id that has been ingested.
- This skill does **not** download the expression matrix. Bandwidth scales with obs size, not file size: a 14 GB source h5ad still probes in ~7 min cross-region.
- The `author-category-picker` sub-agent is a fresh context per dataset — no cross-dataset leakage. Its only inputs are the prompt file and its output path.
- For deployment with no AWS credentials (e.g. an external user), the HTTPS approach works as-is. In-region (us-west-2) access drops latency ~5–10× but is not required.

## Output naming

Mirrors `cxg-query`:

- `outputs/{slug}_{timestamp}_author.parquet` for the long table
- `outputs/{slug}_{timestamp}.h5ad` for the augmented h5ad (overwritten in place when in augment mode)

Where `slug` is a short summary (e.g. `lung_Tcell_author`) and `timestamp` is `%Y%m%d_%H%M%S`.

## References

- [`references/templates.md`](references/templates.md) — minimal code recipes for each mode.
- [agent_celltype_eval paper](https://github.com/Cellular-Semantics/agent_celltype_eval/blob/main/paper.md) — benchmark methodology and limitations.
