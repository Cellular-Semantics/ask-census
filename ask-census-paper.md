# ask-census: An Ontology-Aware Agentic Interface to the CELLxGENE Census

## Abstract

ask-census is a natural-language query layer for the CELLxGENE Census, a uniformly processed corpus of single-cell RNA-seq data covering tens of millions of cells across hundreds of studies. It lets researchers describe a cohort of interest in plain English ("female T cells in lung tissue", "TP53 expression in fibroblasts from adult kidney") and receive either reviewable Python code or directly executed query results. The system is built as a small set of agent instructions, ontology lookup tools, and Python helpers that compose around an existing query expansion library (`cxg-query-enhancer`). Where most natural-language data interfaces hide their interpretation step behind an opaque LLM call, ask-census exposes every resolved ontology term, every expanded subtype, and the final filter expression for inspection. This paper describes the motivation, user-facing behaviour, and the technical design of the agent, with attention to how ontology-aware term expansion and pre-flight validation address recurring failure modes of LLM-generated database queries.

## 1. Motivation

The CELLxGENE Census provides programmatic access to harmonised single-cell data via a Python API in which cohorts are selected through `obs_value_filter` expressions over a fixed set of metadata columns (`cell_type`, `tissue`, `disease`, `development_stage`, `assay`, `sex`, `suspension_type`, and others). Two practical barriers limit who uses it.

The first is syntactic. A working query requires the user to know which columns exist, which operators are accepted, that string literals must be quoted in a particular way to survive labels containing apostrophes (`10x 3' v3`), and that `get_obs`, `get_anndata`, and `get_highly_variable_genes` take subtly different keyword arguments.

The second is semantic, and more consequential. Census metadata columns are populated with ontology labels: cell types from the Cell Ontology (CL), anatomical structures from Uberon, diseases from MONDO, and developmental stages from species-specific stage ontologies (HsapDv, MmusDv). A filter such as `cell_type == "T cell"` returns only the cells annotated with that exact parent label, ignoring the dozens of T cell subtypes (CD4-positive, CD8-positive, regulatory, gamma-delta, and so on) that contributors annotated with more specific terms. A naive query under-recovers by an order of magnitude. The fix, expanding to ontology descendants, is well understood and supported by tools such as Ubergraph and the `cxg-query-enhancer` library, but it requires the user to know the exact rdfs:label of every parent term ("adult stage", not "adult"; "kidney", not "renal tissue") because expansion is keyed off labels rather than free text.

ask-census addresses both barriers by treating query construction as a structured agentic task: parse intent, resolve terms against published ontologies, expand to census-present descendants, build a syntactically valid filter, and validate the result by running a cell count before committing to a download.

## 2. User-facing behaviour

The user interacts with ask-census through any agentic coding environment that supports Claude Code skill or OpenAI Codex agent definitions. A typical session begins with a free-text request:

> Get me female T cells in lung tissue.

The agent extracts the biological entities (sex, cell type, tissue), resolves each to an ontology term, expands them through Ubergraph filtered to terms present in Census, constructs the filter, runs a pre-flight count, and reports back with the resolved terms, the expansion size, the total cell count, and the generated code. For the example above, "T cell" expands to roughly 31 subtypes present in human Census data, "lung" expands to 13 anatomical substructures, and the cohort contains around 300,000 cells.

Several behaviours fall out of this design:

- A "how many" phrasing triggers the metadata-only `get_obs` API mode and skips loading the expression matrix.
- Gene names trigger gene resolution via a cached Census `var` lookup, returning Ensembl IDs and flagging ambiguous symbols (multiple loci, pseudogenes versus protein-coding entries) for user clarification.
- Informal terms for assays ("10x", "Smart-seq", "droplet-based") are mapped to the exact Census labels they cover, drawn from a cached enumeration of the assay column.
- Developmental stage requests force a species check, because shared labels such as "6-month-old stage" denote an infant in human and a mature adult in mouse.
- The agent always reports on the size of the dataset found by a query, so users can judge whether to download locally.
- If the cohort returns zero cells, the agent runs a relaxation loop, broadening one constraint at a time and reporting counts, so the user can choose how to widen rather than guess what failed.
- By default the agent generates reviewable code. A phrase such as "run it" or "fetch the data" triggers direct execution, with a download size estimate for `get_anndata` calls and automatic save to `outputs/`.

## 3. Architecture

ask-census is a thin orchestration layer over four components:

1. **The cxg-query skill** (`.claude/skills/cxg-query/SKILL.md`, mirrored to `.codex/skills/` for OpenAI Codex). A declarative instruction document that defines the parsing grammar, the six-step query construction protocol, the API mode selection rules, and the templates for code generation. The skill is loaded into the host agent's context on invocation and does not itself run code; it constrains how the host agent uses the tools below.

2. **The ontology-term-lookup subagent** (`.claude/agents/ontology-term-lookup.md`). A specialised agent invoked once per biological entity, in parallel where possible. It calls the OLS4 MCP server, applies alternative phrasings (singular/plural, "hepatic" ↔ "liver"), checks species-stage results against a static obsolete-term TSV file, and returns either an exact rdfs:label with CURIE or an explicit no-match report. Returning a wrong label here is the dominant failure mode for the whole system, so the subagent is tuned for precision over recall.

3. **cxg-query-enhancer** (an existing library, called as a Python dependency). Takes a filter expression and an organism, resolves each label to its ontology IRI, walks Ubergraph for subclass and part-of descendants, and intersects the result with the set of labels actually present in the current Census release. The intersection step is what keeps expansion useful: ontologies contain terms that no Census contributor has ever annotated, and including them in the filter would only enlarge the expression without changing recall.

4. **gene_resolver** ([src/gene_resolver.py](src/gene_resolver.py)). Builds a bidirectional symbol-to-Ensembl-ID map from the Census `var` table, cached to disk as a pickle, and exposes a `resolve_genes()` function that returns a list of `GeneMatch` records flagging ambiguity and feature biotype. A companion `build_var_value_filter()` constructs the `var_value_filter` string passed to `get_anndata` or `get_highly_variable_genes`.

The host agent (Claude Code, OpenAI Codex, or any other MCP-aware coding agent) supplies general-purpose tool use, file I/O, Python execution via Bash, and the user-facing chat loop. ask-census itself contributes the prompts, the subagent, the gene resolver, and the cached enumerations of Census assay and stage values.

## 4. Query construction protocol

The skill prescribes a six-step protocol, executed by the host agent on every request:

**Step 1, parse.** The agent extracts a fixed set of slots (sex, cell type, tissue, disease, stage, assay, suspension type, tissue type, organism, genes, intent). API mode is chosen from intent keywords: "how many" or "metadata" routes to `get_obs`; "highly variable" routes to `get_highly_variable_genes`; gene mentions or "expression" route to `get_anndata`. Ambiguous input defaults to `get_anndata`.

**Step 2, resolve.** Each slot that maps to an ontology is dispatched to ontology-term-lookup. Lookups for independent slots run in parallel. The skill mandates that the exact rdfs:label be used downstream, because expansion is label-keyed and silently fails on near-misses.

**Step 3, resolve genes.** Gene symbols pass through `gene_resolver.resolve_genes()`. Ambiguous symbols are surfaced to the user before query construction continues.

**Step 4, construct filter.** The agent assembles an `obs_value_filter` expression following a formal grammar (`references/grammar.md`) that pins down operator usage, quoting rules, and the closed list of valid columns. `is_primary_data == True` is always included unless the user explicitly asks for duplicate cells, because Census overlapping datasets otherwise double-count.

**Step 5, validate.** Before returning anything, the agent runs a pre-flight `get_obs` count against Census and reports cell totals and per-column breakdowns. Zero-result queries trigger the relaxation loop described above. Categorical dtype columns are filtered to non-zero counts before summary, because Census returns the full enumeration of every value ever seen across the corpus.

**Step 6, generate output.** Either reviewable code (default) using one of three templates, or direct execution with size estimation and auto-save.

## 5. Design choices worth flagging

**Labels over IRIs in filter expressions.** Census stores both `cell_type` (label) and `cell_type_ontology_term_id` (CURIE) columns. ask-census filters on labels because that is what `enhance()` expands and what makes generated code legible to a biologist reading the diff. CURIE filtering is supported but discouraged.

**Precision-first ontology matching.** The lookup subagent is instructed to return no match rather than a low-confidence one. Wrong-label expansion produces a syntactically valid filter that returns the wrong cohort, often with a plausible cell count, and is therefore the most dangerous error class. A null match surfaces immediately as a missing slot in the resolved-terms list shown to the user.

**Mandatory pre-flight count.** Running the count is cheap (a metadata query, no expression matrix), and the result is essential context for the user. Skipping validation is the standard LLM failure mode where a confident-looking query silently returns nothing or returns the wrong cohort; the protocol forecloses this by treating the count as part of the answer rather than an optional sanity check.

**Static enumerations cached locally.** Census has a fixed (and small) set of `assay`, `suspension_type`, and `tissue_type` values. These are cached as JSON (`references/census_fields.json`) so the agent can map informal terms ("10x", "snRNA-seq") to the exact label set without round-tripping the Census API.

**Multi-platform skill packaging.** The skill is authored once in `.claude/` and synchronised to `.codex/` and a Copilot instructions file by `setup.sh`. The same prompt, subagent, and helper code run under Claude Code or OpenAI Codex without modification.

## 6. Limitations and ongoing work

The agent depends on the host LLM correctly recognising the biological intent in free text. Edge cases include compound conditions ("T cells but not Tregs"), which the current grammar can express as `cell_type in [...] and cell_type not in [...]` but which the parsing step does not always identify. Stage-organism coupling is enforced for stage queries but not yet for organism-specific cell type or tissue terms (which exist in CL and Uberon for both species). Ontology expansion currently traverses subclass and part-of relations; expansion through develops-from, has-part, and other relations is a candidate extension and would change recall for developmental and anatomical queries. Finally, the relaxation loop broadens one slot at a time; a smarter strategy would model which slot is most likely responsible for zero cells given Census annotation density.

## 7. Availability

ask-census is open source under MIT license at https://github.com/Cellular-Semantics/ask-census. Setup is a single command (`./setup.sh`) that creates a virtual environment, installs `cellxgene-census`, `cxg-query-enhancer`, and the gene resolver, synchronises skills across platforms, and verifies that the OLS4 MCP server is reachable. Worked examples covering basic queries, gene expression retrieval, disease and stage filtering, and assay-specific queries are included in the `examples/` directory.
