# Roadmap

## User story

As a biologist/bioinformatician I want to pull relevant data from CELLxGENE census, based on some combination of cell type, tissue, disease and stage
in order to carry out my analysis.
I want to specify what counts as relevant data in free text and have an agent generate code for me to query CELLxGENE or pull data directly for me.
I have limited prior knowledge of what data is in the Census and how it is annotated, so I want an agent to generate suitable filters with relevant ontology terms and to explore whether the resulting filters return sufficient numbers of cells in order to be useful for me.  If the filter returns no cells, I would like the agent to automatically explore relaxing those filters to find ones that do return cells. Examples could include choosing a broader age/stage filter, a more general tissue, cell type or disease term, or dropping one of the criteria.  This should be an initial exploration rather than an exhustive one.

I would like the agentic session to run quickly and efficiently.

---

## Implemented

### Core query generation (skill + agent)

- `/cxg-query` skill parses natural language into biological entities and constructs filter expressions
- `ontology-term-lookup` agent resolves terms via OLS4 MCP (CL, UBERON, MONDO, HsapDv, MmusDv) with alternative phrasing, synonym matching, and deprecation checks
- Three API modes auto-selected by intent: `get_obs()`, `get_anndata()`, `get_highly_variable_genes()`
- `is_primary_data == True` added automatically for de-duplication

### Ontology expansion

- `enhance()` expands terms via Ubergraph subclass + part_of closure, filtered to census-present terms
- Handles both label-based and ID-based expansion
- Formal EBNF grammar for filter expressions with double-quote convention (handles apostrophes in labels like `10x 3' v3`)

### Gene resolution

- `gene_resolver.py`: bidirectional mapping between gene symbols and Ensembl IDs
- Protein_coding disambiguation for ambiguous gene names
- Cached on disk (pickle) and in memory (LRU)
- `build_var_value_filter()` constructs var filter strings
- Unit tests (`tests/test_gene_resolver.py`)

### Assay, suspension type, and tissue type filtering

- `census_fields.json` cached lookup (~37 assays with cell counts, suspension types, tissue types)
- `refresh_census_fields.py` regenerates from live census
- Informal assay term mapping (e.g. "10x" → all `10x *` variants, "droplet-based" → 10x + Drop-seq + inDrop + ...)
- `suspension_type` (cell/nucleus) and `tissue_type` (tissue/organoid/cell culture) as controlled vocabulary columns

### Development stage handling

- Exact rdfs:label enforcement (agent warns about `"adult"` vs `"adult stage"`)
- Species-specific routing (HsapDv for human, MmusDv for mouse)
- Organism confirmation prompt when stage mentioned without species
- Static obsolete-term lookups (`data/obsolete_hsapdv.tsv`, `data/obsolete_mmusdv.tsv`) refreshed from Ubergraph
- Informal age terms (e.g. "pediatric", "child") mapped to year-based HsapDv stages

### Pre-flight validation and zero-results fallback

- Mandatory cell count before presenting final query
- Zero-results trigger automatic relaxation loop (broaden disease → cell type → tissue → stage)
- Categorical dtype handling (filter zero-count categories from census category columns)

### Size estimation and direct execution

- Download size estimate (sparse/dense) before large `get_anndata()` queries
- Warnings for >500 MB, strong warnings for >5 GB
- Auto-save to `outputs/` with descriptive filenames (.h5ad or .parquet)

### Multi-framework support

- **Claude Code**: full skill + agent setup (`.claude/skills/`, `.claude/agents/`, `.mcp.json`)
- **OpenAI Codex**: full support (`.codex/skills/`, `.codex/agents/`, `.codex/config.toml`)
- **GitHub Copilot**: context-only via `.github/copilot-instructions.md`
- `setup.sh` syncs configs from `.claude/` → `.codex/` and `CLAUDE.md` → `AGENTS.md`

### Setup and tooling

- `setup.sh`: one-command setup (venv, deps, import verification, census field refresh, OLS4 check, obsolete stage refresh, config sync)
- `Makefile`: setup, test, check-mcp, clean
- Worked examples in `examples/`

---

## In Progress

### Full Copilot support via MCP server

Expose core functionality as an MCP server so VS Code Copilot (agent mode) can use the same tools. See `planning/copilot-mcp-server.md` for implementation plan.

- MCP server (`src/mcp_server.py`) with tools: `enhance_query`, `resolve_genes`, `count_cells`, `get_anndata`
- `.vscode/mcp.json` for Copilot agent mode
- Enriched `copilot-instructions.md` with domain knowledge from `SKILL.md`

---

## Future extensions

These are well-understood features with clear implementation paths.

### Support non-model organisms (marmoset, macaque, chimpanzee)

Census includes 3 additional species beyond human/mouse: *Callithrix jacchus* (1.7M cells), *Macaca mulatta* (2.9M cells), and *Pan troglodytes* (158K cells). These use generic UBERON life-stage terms (`prime adult stage`, `juvenile stage`, etc.) rather than species-specific ontologies (HsapDv/MmusDv). Requires updating `cxg_query_enhancer` to handle UBERON-based dev stages and routing to the correct organism collection.

### Dataset provenance in query output

Join query results against the census datasets table (`census["census_info"]["datasets"]`) to surface:
- `collection_name` (study name)
- `collection_doi` (paper DOI)
- `dataset_title`
- Portal URL: `https://cellxgene.cziscience.com/collections/{collection_id}`

**Implementation**: After any `get_obs()` or `get_anndata()` call, auto-join on `dataset_id` and display a provenance summary (unique datasets, DOIs). Could be a small utility function in `src/`.

### Assay and donor metadata in default column set

Add `assay`, `suspension_type`, and `donor_id` to the default `column_names` / `obs_column_names` in skill templates. These are commonly needed for downstream QC and batch-effect analysis.

---

## Experimental Proposals

These require further investigation and may not be feasible or practical.

### Author cell type annotations — IMPLEMENTED (2026-05-25)

Available via the `author-annotations` skill — see [`.claude/skills/author-annotations/SKILL.md`](../.claude/skills/author-annotations/SKILL.md) and the supporting `author_annotations` Python module under `src/`.

**Approach.** A cheaper variant of "targeted H5AD obs-only download" (proposal 1 below): instead of full file download + backed-mode obs read, we use **HTTPS range-reads** of the CELLxGENE datasets CDN to pull just the obs schema + a 20-row sample per column (median ~9 MB / ~13 s per dataset cross-region, independent of file size — a 14 GB h5ad costs the same order of bytes as a 138 MB one). Author cell-type columns are then identified by the `author-category-picker` sub-agent, full values are pulled for the picks, and assembled into a long-format Parquet table (and optionally written back into an h5ad's obs).

**Benchmark.** Against CL_KG hand curation across n=73 datasets stratified over 8 curation groups: mean Jaccard 0.81 (95% CI 0.75–0.87), recall 0.97, hit-rate 99 %, ~18× the random-pick null. See [agent_celltype_eval](https://github.com/Cellular-Semantics/agent_celltype_eval).

**Open questions from the original proposal — answered:**
- *Column naming consistency*: Highly inconsistent (`BICCN_subclass_label`, `celltype`, `cell_type_fine`, `Cell.class`, `author_cell_type`, etc.). This is why an LLM picker is used rather than a fixed column-name lookup.
- *Fraction of datasets with author annotations*: In the eval sample, only 1/73 datasets had no obvious author cell-type column.
- *Barcode / soma_joinid mapping stability*: `observation_joinid` is stable across Census releases and present in both the source h5ad's obs and the Census obs — used directly as the join key.

**Original proposals retained for reference:**
1. ~~Targeted H5AD obs-only download~~ → superseded by HTTPS range-read above.
2. gget meta_only — not pursued; the range-read path is lighter still.
3. Pre-built author annotation index — orthogonal; complementary to the on-demand path for hot queries.
4. Lobby for census schema change — still desirable long-term.

### Semantic query understanding

Move beyond keyword-based intent detection to understand more complex queries:
- "Compare T cells between healthy and diseased lung" (implies two queries + differential)
- "What cell types express TP53 in the brain?" (implies broad query + groupby)
- "Find datasets with at least 1000 neurons" (implies metadata aggregation)

This would require the skill to generate multi-step analysis workflows, not just single census API calls.

### Integration with scanpy/scvi workflows

Generate complete analysis pipelines beyond just data retrieval:
- QC filtering (mito%, gene counts)
- Normalization and log-transform
- Dimensionality reduction (PCA, UMAP)
- Clustering and marker gene identification

This would make the tool useful for end-to-end exploratory analysis, not just data access.
