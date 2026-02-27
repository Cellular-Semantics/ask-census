# Plan: Combined GWAS + CxG Skill (`/gwas-cxg`)

## Context

We built `src/gwas_genes.py` (GWAS Catalog fetcher + gene ranker) and tested a manual pipeline: disease → GWAS top genes → resolve to Ensembl IDs → query CxG Census for expression by cell type. This worked end-to-end for psoriasis but required several manual steps and workarounds. The goal is a new skill that orchestrates this pipeline automatically, handling the ontology mapping gaps we discovered.

### Key lessons from the experiment
- GWAS uses **EFO** trait IDs; CxG Census uses **MONDO-derived** disease labels. These don't always align (e.g. "psoriasis vulgaris" = EFO:1001494, no MONDO equivalent).
- CxG tissue labels are specific (e.g. `"skin of body"` not `"skin"`). The `enhance()` expansion of `"skin"` produced sub-regions that returned zero cells; `tissue_general` or the exact census label was needed.
- Disease → tissue mapping is implicit (psoriasis → skin) — currently requires the user to specify tissue.
- Gene symbols from GWAS resolve cleanly to Ensembl IDs via `resolve_genes()`.
- Some GWAS genes (e.g. IL12B) show near-zero scRNA-seq expression due to transient/activation-dependent expression — needs flagging.
- Dataset-level artifacts (HLA-B/C = 0% in all psoriasis cells) need QC detection.

## New skill: `.claude/skills/gwas-cxg/SKILL.md`

### What it does
Given a disease name, the skill:
1. Resolves disease to EFO ID (for GWAS) and MONDO/CxG disease label (for Census)
2. Fetches GWAS associations and ranks genes
3. Resolves top gene symbols to Ensembl IDs
4. Identifies the relevant tissue from disease ontology relationships
5. Queries CxG Census for expression of those genes by cell type (disease vs normal)
6. Flags QC issues (zero-expression artifacts, transient-expression genes)
7. Outputs a summary table + CSV

### Skill instructions outline

**Step 1: Disease resolution**
- Use `ontology-term-lookup` agent to find:
  - **EFO ID** for GWAS Catalog lookup (search EFO ontology)
  - **CxG disease label** — search MONDO, then check what label CxG Census actually uses. Run a quick `get_obs()` with `disease == "<label>"` to confirm non-zero cells.
- If EFO and MONDO terms don't align, use cross-references: OLS4 terms often carry `hasDbXref` linking EFO ↔ MONDO. The agent can check both.
- Fallback: if no exact CxG disease match, use the parent MONDO term or just `"normal"` tissue for baseline expression.

**Step 2: Disease → tissue mapping**
- Use OLS4 to look up anatomical relationships on the disease term. MONDO diseases often have:
  - `disease_has_location` → UBERON term (e.g. psoriasis → skin)
  - Or infer from EFO hierarchy / definition text
- Map the UBERON term to the CxG Census tissue label. Since Census uses specific labels (e.g. `"skin of body"`), do a pre-flight: query `get_obs()` with the UBERON label, and if zero cells, try `tissue_general` or the parent UBERON term.
- If no anatomical relationship found in the ontology, ask the user to specify tissue.

**Step 3: GWAS gene ranking**
- Call `gwas_genes.get_top_gwas_genes(efo_id, top_n=20)` (existing module)
- Present ranked gene table to user before proceeding to CxG query

**Step 4: Gene resolution + CxG query**
- Call `resolve_genes()` on the top gene symbols → Ensembl IDs
- Build `var_value_filter` from Ensembl IDs
- Build `obs_value_filter`: `is_primary_data == True and tissue == "<tissue_label>" and disease in ["normal", "<disease_label>"]`
- Fetch via `get_anndata()` (size is small: N_cells x top_N genes)
- Compute per cell_type x disease: mean expression, % expressing

**Step 5: QC flagging**
- **Zero-expression artifact**: If a gene shows >10% expression in normal but 0% across ALL disease cell types (or vice versa), flag as likely dataset artifact
- **Transient expression**: If a gene shows <1% expression in all cell types across both conditions, note that GWAS risk variants may affect expression capacity rather than steady-state levels (e.g. cytokine genes like IL12B)

**Step 6: Output**
- Summary markdown table: cell_type x gene matrix with % expressing, split by disease vs normal
- CSV saved to `output/`
- Markdown report saved to `output/`

## New file: `src/disease_tissue_map.py`

Helper module for Steps 1-2 that wraps the ontology lookups into reusable functions.

### Functions

1. **`resolve_disease(disease_name: str) -> DiseaseMapping`**
   - Uses OLS4 REST API (not MCP, for reliability) to search EFO and MONDO
   - Returns dataclass: `efo_id`, `efo_label`, `mondo_id`, `mondo_label`, `cxg_disease_label` (validated against Census)
   - Cross-reference lookup: if only one of EFO/MONDO found, check `hasDbXref` for the other

2. **`get_disease_tissue(disease_id: str, ontology: str = "mondo") -> list[str]`**
   - Queries OLS4 for `disease_has_location` relationships → returns UBERON IDs/labels
   - Fallback: parse definition text for anatomical keywords
   - Returns list of UBERON labels

3. **`map_tissue_to_census(uberon_label: str) -> str | None`**
   - Checks if the UBERON label matches a CxG Census tissue value
   - If not, tries `tissue_general` column
   - Uses a quick `get_obs()` count to validate (cached)

4. **`DiseaseMapping` dataclass**
   - `efo_id`, `efo_label`, `mondo_id`, `mondo_label`
   - `cxg_disease_label` — validated Census disease string
   - `tissue_labels` — list of Census tissue strings
   - `warnings` — list of mapping issues encountered

### Dependencies
- `requests` (already in pyproject.toml)
- `cellxgene_census` (already in pyproject.toml)
- OLS4 REST API: `https://www.ebi.ac.uk/ols4/api/search`, `https://www.ebi.ac.uk/ols4/api/classes` (no MCP needed)

## Files to create/modify

| Action | File | Purpose |
|--------|------|---------|
| Create | `src/disease_tissue_map.py` | Disease → EFO/MONDO resolution + tissue mapping |
| Create | `.claude/skills/gwas-cxg/SKILL.md` | Skill instructions for the combined pipeline |
| Edit | `pyproject.toml` | Add `disease_tissue_map` to py-modules |

Existing files reused as-is:
- `src/gwas_genes.py` — GWAS fetcher + gene ranker
- `src/gene_resolver.py` — gene symbol → Ensembl ID resolution

## Verification

1. **Unit test `disease_tissue_map.py`**: `resolve_disease("psoriasis")` should return EFO:1001494 or EFO:0000676, MONDO:0005083, `cxg_disease_label="psoriasis"`, `tissue_labels=["skin of body"]`
2. **End-to-end**: invoke `/gwas-cxg psoriasis` — should produce the same results we got manually (HLA-B, HLA-C, TNIP1 in top genes; skin cell type expression matrix)
3. **Edge case**: try a disease with no CxG data (rare disease) — should gracefully report no Census cells and still show GWAS results
4. **Edge case**: disease with no `disease_has_location` — should ask user for tissue

## Implementation status
- [ ] `src/disease_tissue_map.py`
- [ ] `.claude/skills/gwas-cxg/SKILL.md`
- [ ] `pyproject.toml` update
- [ ] Verification tests

## Session reference
Original planning transcript: `/Users/do12/.claude/projects/-Users-do12-Documents-GitHub-Agentic-CxG-query-enhance/ce7f70da-4ce1-43e3-8ac8-d2e2b244df93.jsonl`
