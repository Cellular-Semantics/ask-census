# ask-census

Natural-language queries for [CELLxGENE Census](https://chanzuckerberg.github.io/cellxgene-census/), powered by AI coding agents and ontology-aware term expansion.

## Quick Start

```bash
git clone https://github.com/Cellular-Semantics/ask-census.git
cd ask-census
./setup.sh          # creates .venv, installs deps, syncs configs, verifies OLS4
```

Then open the project in your AI coding agent and ask for what you need:

```
Get me female T cells in lung tissue
```

In Claude Code you can also use skill shorthands:
```
/cxg-query female T cells in lung tissue
```

To enrich the resulting slice with author-level cell type annotations from the CL Knowledge Base:
```
/enrich-slice outputs/female_t_cell_lung_20260519_120000.h5ad
```

> **Note** — enrichment requires the CL Knowledge Base services running locally.
> See [Author annotation enrichment](#author-annotation-enrichment) below.

## Examples

Just describe what you want — the agent handles ontology lookups, term expansion, and code generation:

| You say | What happens |
|---|---|
| "female T cells in lung tissue" | Expands to 31 T cell subtypes across 13 lung structures → 301K cells |
| "expression of TP53 and BRCA1 in lung fibroblasts" | Resolves genes to Ensembl IDs, expands to 10 fibroblast subtypes → 199K cells x 2 genes |
| "how many macrophages are in kidney?" | "how many" triggers fast metadata-only mode (no expression matrix) |
| "highly variable genes in pancreatic beta cells" | "highly variable" triggers `get_highly_variable_genes()` mode |
| "run it: adult neurons from brain with Alzheimer's" | "run it" triggers direct execution with size estimate and auto-save |
| "snRNA-seq data from human heart" | Maps to `suspension_type == "nucleus"`, expands heart tissue terms |
| "10x 5' data from pediatric kidney" | Maps to all 10x 5' assay variants, enumerates child-age stages |

### Worked examples

Step-by-step walkthroughs showing the full agentic flow with real OLS4 lookups and Census cell counts:

- **[T cells in lung](examples/01_t_cells_in_lung.md)** — basic query, ontology expansion, pre-flight validation
- **[Gene expression in fibroblasts](examples/02_gene_expression_in_fibroblasts.md)** — gene resolution, var filtering, ambiguity handling
- **[Disease + development stage](examples/03_disease_and_development_stage.md)** — zero-results fallback loop, deprecated term detection
- **[snRNA-seq 10x pediatric kidney HVG](examples/04_snrnaseq_pediatric_kidney_hvg.md)** — assay filtering, suspension type, informal age terms, data availability

## Platform Support

| Platform | Status | Config |
|---|---|---|
| [Claude Code](https://docs.anthropic.com/en/docs/claude-code) | Full support | `CLAUDE.md`, `.claude/skills/`, `.claude/agents/`, `.mcp.json` |
| [OpenAI Codex](https://openai.com/index/codex/) | Full support | `AGENTS.md`, `.codex/skills/`, `.codex/agents/`, `.codex/config.toml` |
| [GitHub Copilot](https://github.com/features/copilot) | Context only | `.github/copilot-instructions.md` |

Configs are synced automatically: `setup.sh` copies Claude Code skills and agents to `.codex/` and mirrors `CLAUDE.md` to `AGENTS.md`.

## How It Works

### Census query (`/cxg-query`)

1. **You describe** the data you want in plain English
2. **The agent** parses your request into biological entities (cell types, tissues, diseases, genes, assays, stages)
3. **OLS4 MCP** resolves entities to ontology terms (CL, Uberon, MONDO, HsapDv/MmusDv)
4. **cxg-query-enhancer** expands terms to include all subtypes via Ubergraph, filtered to those present in Census
5. **gene_resolver** maps gene names to Ensembl IDs (with disambiguation for ambiguous names)
6. **cellxgene-census** retrieves the matching single-cell data and saves it to `outputs/` as `.h5ad` or `.parquet`

All queries automatically filter to `is_primary_data == True` to avoid duplicate cells across overlapping datasets.

### Author annotation enrichment (`/enrich-slice`)

After a Census query you can enrich the saved slice with author-level cell type annotations sourced from published datasets in the CL Knowledge Base:

1. **Read cell types** — unique `cell_type` values are extracted from the slice obs
2. **Graph lookup** — `cl_kb` MCP queries the Neo4j knowledge graph for clusters matching those cell types, returning per-cluster metadata (author label columns, synonym columns, dataset provenance)
3. **Bitmap fetch** — roaring bitmaps encoding the `soma_joinid` set for each cluster are fetched from the bitmap service
4. **Join** — bitmaps are intersected with the slice's `soma_joinid` set; matched cells get new author annotation columns (e.g. `author_cell_type`, `author_cluster_label`) joined back onto `obs`
5. **Output** — enriched `.h5ad` or `.parquet` written alongside the original slice, plus a cluster summary CSV and a full membership CSV

## Author annotation enrichment

### Prerequisites

Enrichment requires three additional services:

| Service | Default URL | Purpose |
|---|---|---|
| CL Knowledge Base graph | `http://localhost:8000` | Graph query → cluster manifest |
| Bitmap query service | `http://localhost:8001` | Roaring bitmap lookup per cluster |
| `cl_kb` MCP server | configured in `.mcp.json` | Bridge between Claude and the services |

The `cl_kb` MCP server is pre-configured in `.mcp.json`. Set the service URLs via environment variables if they differ from the defaults:

```bash
GRAPH_QUERY_SERVICE_URL=http://localhost:8000
BITMAP_QUERY_SERVICE_URL=http://localhost:8001
```

### Usage

Run a Census query first, then enrich:

```
/cxg-query pericytes from frontal cortex, normal
# → saves outputs/pericyte_frontal_cortex_normal_..._obs_....h5ad
# → suggests: /enrich-slice outputs/pericyte_frontal_cortex_normal_....h5ad

/enrich-slice outputs/pericyte_frontal_cortex_normal_....h5ad
```

Or just `/enrich-slice` with no argument to pick up the most recently saved slice automatically.

### What gets added

The enriched slice gains:
- `matched_cluster_count` — how many clusters each cell matched
- Dynamic author annotation columns, e.g.:
  - `author_cell_type` — the author's cell type label for that cluster
  - `author_cluster_label` — the author's cluster ID (e.g. `"17:Peri"`)
  - Any additional synonym columns declared in the dataset (vary by study)

Cells that matched no clusters are preserved unchanged.

## Features

- **Three API modes**: metadata exploration (`get_obs`), expression retrieval (`get_anndata`), and feature selection (`get_highly_variable_genes`) — automatically selected from intent keywords
- **Ontology expansion**: "T cell" automatically includes CD4+, CD8+, regulatory T cells, etc. (~31 subtypes); "lung" includes left lung, bronchus, lung epithelium, etc. (~13 structures)
- **Gene resolution**: gene symbols resolved to Ensembl IDs with automatic disambiguation (prefers protein_coding when ambiguous)
- **Assay filtering**: informal terms like "10x", "Smart-seq", "droplet-based" mapped to exact census labels from a cached lookup (~37 assays)
- **Suspension & tissue type**: filter by `suspension_type` (cell/nucleus) and `tissue_type` (tissue/organoid/cell culture)
- **Development stage handling**: exact ontology labels enforced, species-specific routing (HsapDv vs MmusDv), deprecated term detection, informal age terms enumerated
- **Pre-flight validation**: mandatory cell count before presenting results; zero-results trigger automatic relaxation loop
- **Size estimation**: download size estimate before large `get_anndata()` queries, with warnings for >500 MB
- **Code or execute**: generates reviewable code by default, or runs directly on request with auto-save to `outputs/`

## Project Structure

```
ask-census/
├── .claude/                         # Claude Code config (master for shared files)
│   ├── agents/ontology-term-lookup.md
│   └── skills/
│       ├── cxg-query/               # /cxg-query skill
│       │   ├── SKILL.md
│       │   └── references/          # grammar, templates, census field lookups
│       └── enrich-slice/            # /enrich-slice skill
│           └── SKILL.md
├── .codex/                          # OpenAI Codex config (synced by setup.sh)
├── .github/copilot-instructions.md
├── .mcp.json                        # OLS4 + cl_kb MCP servers
├── src/
│   ├── gene_resolver.py             # Gene name → Ensembl ID resolution
│   ├── bitmap_manifest_join_lib.py  # Bitmap-manifest join logic (used by enrich-slice)
│   ├── enrich_slice_runner.py       # CLI entry point for enrich-slice
│   └── refresh_census_fields.py
├── data/                            # Obsolete stage term lookups
├── tests/
├── examples/                        # Worked examples
├── planning/                        # Roadmap
├── outputs/                         # Query results and enriched slices (git-ignored)
├── setup.sh                         # One-command setup
├── Makefile                         # setup, test, check-mcp, clean
└── pyproject.toml
```

## Contributing

1. Fork this repo (or use it as a template)
2. `./setup.sh`
3. Make your changes
4. `make test`

## References

- [CELLxGENE Census](https://chanzuckerberg.github.io/cellxgene-census/)
- [cxg-query-enhancer](https://github.com/Cellular-Semantics/cxg-query-enhancer)
- [OLS4 (Ontology Lookup Service)](https://www.ebi.ac.uk/ols4/)
- [Ubergraph](https://github.com/INCATools/ubergraph)

## License

MIT
