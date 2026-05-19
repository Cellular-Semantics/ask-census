# CELLxGENE Census Skills — Overview

This project provides two Claude Code skills invokable with `/skill-name`.

| Skill | Purpose |
|---|---|
| `/cxg-query` | Generate and execute a Census query from natural language |
| `/enrich-slice` | Enrich a saved slice with author-level cell type annotations from the CL Knowledge Base |

---

## `/cxg-query` — What Was Created

I've created a Claude Code skill (`/cxg-query`) that generates CELLxGENE census query filters from natural language descriptions. The skill integrates:

1. **OLS4 MCP**: For looking up ontology terms
2. **cxg-query-enhancer**: For automatic term expansion
3. **cellxgene-census**: For data retrieval

### Files Created/Modified

#### New Files

1. **`.claude/skills/cxg-query/SKILL.md`** - The skill definition that guides Claude in generating query filters
2. **`README.md`** - Complete project documentation
3. **`example_query.py`** - Working examples showing how to use the enhancer
4. **`SKILL_OVERVIEW.md`** - This file

#### Modified Files

1. **`pyproject.toml`** - Added dependencies (cxg-query-enhancer, cellxgene-census)
2. **`CLAUDE.md`** - Updated project instructions with skill information

### How to Use the Skill

#### Basic Usage

```bash
# In Claude Code, simply type:
/cxg-query female T cells in lung tissue
```

The skill will:
1. Parse your natural language description
2. Find appropriate ontology terms using OLS4
3. Generate a valid Python expression for the query filter
4. Show you how to use it with cellxgene_census
5. Explain what the enhanced query will retrieve

#### Example Queries

```bash
/cxg-query medium spiny neurons from adult human brain
/cxg-query macrophages from kidney with diabetes mellitus
/cxg-query CD4+ T cells from blood
/cxg-query embryonic neurons from mouse cortex
```

### How It Works

#### Query Filter Syntax

The skill generates Python expressions compatible with cellxgene_census:

```python
# Simple equality
"sex == 'female'"

# List membership
"cell_type in ['T cell', 'B cell']"

# Multiple conditions
"sex == 'female' and cell_type in ['T cell'] and tissue in ['lung']"
```

#### Automatic Expansion

When you use the `enhance()` function, it automatically expands terms:

```python
from cxg_query_enhancer import enhance

# Original query
query = "cell_type in ['T cell'] and tissue in ['lung']"

# Enhanced query expands:
# - 'T cell' → CD4+ T cell, CD8+ T cell, regulatory T cell, etc. (76 terms)
# - 'lung' → left lung, right lung, bronchus, etc. (15 terms)
enhanced = enhance(query, organism="homo_sapiens")
```

#### Full Example

```python
import cellxgene_census
from cxg_query_enhancer import enhance

# Your natural language description becomes:
query = "sex == 'female' and cell_type in ['T cell'] and tissue in ['lung']"

# Use with census
with cellxgene_census.open_soma(census_version="latest") as census:
    adata = cellxgene_census.get_anndata(
        census=census,
        organism="Homo sapiens",
        obs_value_filter=enhance(query, organism="homo_sapiens"),
        obs_column_names=["cell_type", "tissue", "sex"]
    )

print(f"Retrieved {len(adata)} cells")
# Without enhance: ~71,000 cells
# With enhance: ~700,000 cells
```

### Supported Categories

| Category | Ontology | Column Name | Example Terms |
|----------|----------|-------------|---------------|
| Cell type | Cell Ontology (CL) | `cell_type` | T cell, neuron, macrophage |
| Tissue | Uberon | `tissue` | lung, kidney, brain |
| Disease | MONDO | `disease` | diabetes mellitus, cancer |
| Dev stage | HsapDv/MmusDv | `development_stage` | adult, embryonic |
| Sex | N/A | `sex` | male, female |

### Testing the Setup

Run the example script to see the enhancer in action:

```bash
python example_query.py
```

This will show you three examples of query enhancement without actually downloading census data.

### Key Concepts

#### 1. Ontology-Aware Expansion

The enhancer uses Ubergraph (a knowledge graph of biomedical ontologies) to find:
- **Subclasses**: "macrophage" → "alveolar macrophage", "Kupffer cell"
- **Part-of relationships**: "kidney" → "renal cortex", "nephron"

#### 2. Census Filtering

Only terms that actually exist in the CELLxGENE census dataset are included in the expanded query. This ensures your query will return results.

#### 3. Organism-Specific

The `organism` parameter is critical for:
- Development stage queries (HsapDv vs MmusDv)
- Census filtering (ensuring terms exist for the target species)

### Advanced Usage

#### Using Ontology IDs Directly

```python
query = "cell_type_ontology_term_id in ['CL:0000084']"
enhanced = enhance(query, organism="homo_sapiens")
```

#### Disabling Census Filtering

```python
# Get pure ontology expansion without census filtering
enhanced = enhance(query, census_version=None)
```

#### Specifying Categories

```python
# Only expand specific categories
enhanced = enhance(
    query,
    categories=["cell_type", "tissue"],
    organism="homo_sapiens"
)
```

### Troubleshooting

#### Issue: "No ontology term found"

**Solution**: Try alternative phrasings:
- "T cell" vs "T lymphocyte"
- "lung" vs "pulmonary"
- "kidney" vs "renal"

#### Issue: "Organism parameter required"

**Solution**: Always specify organism when using development_stage:
```python
enhance(query, organism="homo_sapiens")  # or "mus_musculus"
```

#### Issue: Query returns no results

**Possible causes**:
1. Terms don't exist in census for that organism
2. Try removing one constraint at a time to identify the issue
3. Use `census_version=None` to see the full ontology expansion

### Next Steps

1. **Try the skill**: Use `/cxg-query` with your own descriptions
2. **Run examples**: Execute `python example_query.py`
3. **Build queries**: Start retrieving data from CELLxGENE census
4. **Explore examples**: See `example_query.py` for usage patterns

---

## `/enrich-slice` — What Was Created

A second skill that enriches a Census obs slice with author-level cell type annotations
from the CL Knowledge Base, joining roaring bitmaps onto `soma_joinid`.

### Files Created/Modified

#### New Files

1. **`.claude/skills/enrich-slice/SKILL.md`** - The skill definition
2. **`src/bitmap_manifest_join_lib.py`** - Pure join logic: bitmap decoding, manifest parsing, membership table, author column materialisation
3. **`src/enrich_slice_runner.py`** - CLI entry point called by the skill

#### Modified Files

1. **`pyproject.toml`** - Added `pyroaring`, `anndata`, `pandas`; registered new modules
2. **`setup.sh`** - Switched to `python -m pip` for robustness; added import verification for the new modules
3. **`.mcp.json`** - Added `cl_kb` MCP server (graph + bitmap services)

### How to Use the Skill

```bash
# After a /cxg-query run:
/enrich-slice outputs/pericyte_frontal_cortex_normal_obs_20260519.h5ad

# Or pick up the most recently saved slice automatically:
/enrich-slice
```

### How It Works

1. Reads unique `cell_type` values from the slice obs
2. Calls `cl_kb` MCP → `query_clusters` with those labels → cluster manifest
3. Calls `cl_kb` MCP → `fetch_bitmaps_bulk` → roaring bitmap per cluster
4. Writes manifest + bitmaps as temp JSON files alongside the slice
5. Runs `src/enrich_slice_runner.py` which intersects each bitmap with the slice `soma_joinid` set and joins author annotation columns back onto obs

### Prerequisites

| Service | Default URL | Purpose |
|---|---|---|
| CL Knowledge Base graph | `http://localhost:8000` | Graph query → cluster manifest |
| Bitmap query service | `http://localhost:8001` | Roaring bitmap lookup per cluster |

Override defaults via environment variables:
```bash
GRAPH_QUERY_SERVICE_URL=http://localhost:8000
BITMAP_QUERY_SERVICE_URL=http://localhost:8001
```

### Output Files

| File | Contents |
|---|---|
| `{stem}_enriched__enriched.h5ad/.parquet` | Enriched slice with new author columns |
| `{stem}_enriched__cluster_summary.csv` | One row per matched cluster with cell counts |
| `{stem}_enriched__membership.csv` | Full many-to-many join table |

### New Columns Added to obs

- `matched_cluster_count` — how many clusters each cell matched
- `author_cell_type`, `author_cluster_label`, and any study-specific synonym columns declared in the dataset

Cells that matched no clusters are preserved unchanged.

### Troubleshooting

#### Issue: `matched_cells == 0` despite clusters in manifest

Most likely cause: the bitmaps were built against a different Census version than the one
used to generate the slice. Ensure both services target the same Census release.

#### Issue: `cl_kb` MCP tools not found

Check that the graph and bitmap services are running on the expected ports, and that
`.mcp.json` contains the `cl_kb` entry with the correct `cwd` path.

---

## Skill files

Skills are Markdown files read by Claude at invocation time — they are prompts, not code.
`setup.sh` automatically mirrors `.claude/skills/` to `.codex/skills/` for OpenAI Codex compatibility.

```
.claude/skills/
├── cxg-query/
│   ├── SKILL.md               # step-by-step instructions Claude follows
│   └── references/
│       ├── grammar.md         # obs_value_filter syntax rules
│       ├── templates.md       # code templates (get_obs, get_anndata, HVG)
│       └── census_fields.json # cached census column → label mapping
└── enrich-slice/
    └── SKILL.md               # step-by-step instructions Claude follows
```

## Resources

- [CELLxGENE Census Documentation](https://chanzuckerberg.github.io/cellxgene-census/)
- [cxg-query-enhancer GitHub](https://github.com/Cellular-Semantics/cxg-query-enhancer)
- [Cell Ontology (CL)](http://obofoundry.org/ontology/cl.html)
- [Uberon Anatomy Ontology](http://obofoundry.org/ontology/uberon.html)
- [MONDO Disease Ontology](http://obofoundry.org/ontology/mondo.html)

## Feedback

If you encounter issues or have suggestions for improving the skills, please let me know!
