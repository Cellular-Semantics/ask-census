---
name: cxg-query
description: Generate CELLxGENE census queries from natural language — supports gene filtering, multiple API modes, and direct execution
user-invocable: true
---

# CELLxGENE Census Query Generator

Generate CELLxGENE census queries from natural language. Constructs valid query filters with automatic ontology term expansion (`enhance()`) and gene name resolution (`resolve_genes()`), supporting `get_obs()`, `get_anndata()`, and `get_highly_variable_genes()`.

---

## Instructions

### Step 1: Parse input

Extract from the user's request:

- **Sex**: female, male
- **Cell type**: e.g. "T cells", "neurons"
- **Tissue**: e.g. "lung", "brain"
- **Disease**: e.g. "diabetes", "Crohn's disease"
- **Development stage**: e.g. "adult", "embryonic"
- **Assay**: e.g. "10x", "Smart-seq", "droplet-based"
- **Suspension type**: cell, nucleus (snRNA vs scRNA)
- **Tissue type**: tissue, organoid, cell culture
- **Organism**: human (default) or mouse — **if a development stage or age is mentioned but organism is not, you MUST ask the user to confirm species before proceeding**. Many stage labels are shared between human (HsapDv) and mouse (MmusDv) but mean very different things (e.g. `"6-month-old stage"` = infant in human, mature adult in mouse). Use `AskUserQuestion` to confirm.
- **Genes**: gene names or Ensembl IDs
- **API mode** (infer from intent):
  | Clues | Mode |
  |---|---|
  | "metadata", "cell count", "how many" | `get_obs()` |
  | gene names, "expression", "matrix" | `get_anndata()` |
  | "HVG", "highly variable" | `get_highly_variable_genes()` |
  | unclear | default to `get_anndata()` |

### Step 2: Resolve ontology terms

**Mandatory for**: cell_type, tissue, disease, development_stage. Use the `ontology-term-lookup` subagent (`Task` tool, `subagent_type=ontology-term-lookup`). Launch independent lookups **in parallel**.

**Skip lookup for**: `sex` (only `"male"`/`"female"`) and `is_primary_data` — these are fixed values, not ontology terms.

Ontology targets: CL (cell types), UBERON (tissues), MONDO (diseases), HsapDv (human dev stages), MmusDv (mouse dev stages).

Use the **exact label** returned by the subagent. Never paraphrase or add prefixes. `enhance()` matches on exact `rdfs:label` — a wrong label silently fails (zero subtypes, no error).

**Critical example** — development stages:
- `"adult"` — wrong (not an rdfs:label) → no expansion
- `"human adult stage"` — wrong → no expansion
- `"adult stage"` — correct (HsapDv:0000258) → 103 terms

If the subagent returns a deprecated term, use the non-deprecated alternative it provides.

### Step 3: Resolve genes (if any)

```python
from gene_resolver import resolve_genes, build_var_value_filter

matches = resolve_genes(["TP53", "BRCA1"], organism="homo_sapiens")
all_ids = [eid for m in matches for eid in m.ensembl_ids]
var_filter = build_var_value_filter(all_ids)
```

Check `is_ambiguous` (inform user) and empty `ensembl_ids` (gene not found).

### Step 4: Construct obs_value_filter

**Always include** `is_primary_data == True` (tell the user). Omit only if user explicitly requests duplicates.

Valid columns: `sex`, `cell_type`, `tissue`, `tissue_general`, `disease`, `development_stage` (and their `_ontology_term_id` variants), `assay`, `suspension_type`, `tissue_type`.

For `assay`, read `references/census_fields.json` to find exact census labels. Use latent knowledge to map informal terms (e.g. "10x" → all `10x *` variants, "Smart-seq" → Smart-seq family) to the exact labels from the lookup. Construct `assay in [...]` with matched labels. See `references/grammar.md` for the full synonym mapping table.

For `suspension_type` and `tissue_type`, use fixed values directly — no lookup needed. See `references/grammar.md` for valid values.

Syntax: `==` for single values, `in [...]` for multiple, `and`/`or` to combine, **double quotes for all string literals** (avoids breakage from apostrophes in labels like `10x 3' v3`). Prefer labels over IDs. Use parentheses around `or` groups. See `references/grammar.md` for the full formal grammar, column reference, and anti-patterns.

### Step 5: Validate cell count (zero-results fallback — MANDATORY)

**You MUST run a pre-flight cell count** before presenting the final query. Execute this via the Bash tool with Python:

```python
from cxg_query_enhancer import enhance
import cellxgene_census

obs_filter = enhance("is_primary_data == True and ...", organism="homo_sapiens")
with cellxgene_census.open_soma(census_version="latest") as census:
    obs_df = cellxgene_census.get_obs(census, organism="Homo sapiens",
        value_filter=obs_filter,
        column_names=["cell_type", "tissue", "disease"])
print(f"{len(obs_df):,} cells")
for col in ["cell_type", "tissue", "disease"]:
    if col in obs_df.columns:
        counts = obs_df[col].value_counts()
        counts = counts[counts > 0]  # drop zero-count categories
        print(f"\n{col} ({len(counts)} unique):")
        print(counts.to_string())
```

**Categorical dtype warning**: Census returns `category`-typed columns containing all possible values across the entire census (~400+ tissues, ~600+ cell types). `value_counts()` and `groupby()` will include hundreds of zero-count entries by default. **Always filter**: `counts = counts[counts > 0]`, or use `groupby(..., observed=True)`.

**If zero cells are returned, you MUST execute the relaxation loop** — do not just suggest relaxations. Actually run each variant and report the counts:

1. Broaden disease (use parent term) → **run count** → report result
2. Broaden cell type (use parent term) → **run count** → report result
3. Broaden tissue (use parent term) → **run count** → report result
4. Broaden development_stage (use parent term) → **run count** → report result

Stop relaxing once you find a combination with >0 cells. Present the user with a table of what worked and the cell counts, then let them choose which relaxed filter to use.

### Step 6: Generate output

- Default to **generating code** unless user says "run it"/"execute"/"fetch".
- Use the appropriate template from `references/templates.md`.
- For direct execution: do pre-flight size estimate (for `get_anndata()`), execute, show preview, auto-save to `outputs/`.
- **Always filter zero-count categories** in any breakdown or summary (see Step 5 warning).
- **Size warning**: If broad `get_anndata()` with no gene filter, warn the user. Suggest `get_obs()` first.
- After saving the slice, suggest: `Run /enrich-slice <saved_path> to add author cell type annotations.`

Always list resolved terms in output:
```
Resolved terms:
- Cell type: T cell (CL:0000084)
- Tissue: lung (UBERON:0002048)
```

---

## Important Notes

- **Organism parameter**: Always include in `enhance()`, especially for dev stages.
- **`get_obs()` uses `value_filter=`**, not `obs_value_filter=`. The other two use `obs_value_filter=`.
- **Enhancement**: `enhance()` expands terms to all subtypes + related terms, filtered to those present in CELLxGENE Census.
- **Ambiguous terms**: Ask user to clarify. For genes, report matching Ensembl IDs and biotypes.
