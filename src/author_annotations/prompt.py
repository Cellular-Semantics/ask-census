"""Render a self-contained prompt for the `author-category-picker` sub-agent.

Vendored verbatim (minus the file-writing wrapper) from
agent_celltype_eval/src/03_make_prompts.py — see the eval repo for the
benchmark this prompt was tuned against (n=73, Jaccard 0.81 against CL_KG).
"""
from __future__ import annotations

from typing import Any, Dict


def build_prompt(dataset_id: str, probe_entry: Dict[str, Any]) -> str:
    """Build the picker prompt for one dataset.

    Parameters
    ----------
    dataset_id : the CELLxGENE dataset_id (informational; included for context)
    probe_entry : dict from ``probe(url)`` — must contain ``schema`` and ``samples``;
                  ``n_obs_cols`` and ``n_cells`` are optional but used in the header.

    Returns
    -------
    str — the full prompt body. Caller is responsible for delivery (writing
    to disk, sending via Task tool, etc.) and for telling the sub-agent
    where to write its answer.
    """
    schema = probe_entry["schema"]
    samples = probe_entry["samples"]
    n_obs_cols = probe_entry.get("n_obs_cols", len(schema))
    n_cells = probe_entry.get("n_cells", "?")

    lines = []
    lines.append("You are evaluating an obs schema from a CELLxGENE dataset (h5ad).")
    lines.append(
        "Your task: pick the obs column(s) that contain AUTHOR-PROVIDED "
        "cell-type-like annotations."
    )
    lines.append("")
    lines.append(f"Dataset id: {dataset_id}")
    lines.append(f"Dataset has {n_obs_cols} obs columns, {n_cells} cells.")
    lines.append("")
    lines.append("RULES:")
    lines.append(
        "- Pick columns whose VALUES are cell-type / cell-class / cell-state labels "
        "(free-text, named clusters, marker-encoded names, hierarchies)."
    )
    lines.append(
        "- Multiple picks are fine if the dataset has labels at several "
        "granularities (e.g. broad + fine + cluster)."
    )
    lines.append(
        "- DO NOT pick CELLxGENE-standardised fields: cell_type, "
        "cell_type_ontology_term_id, etc. (already in Census)."
    )
    lines.append(
        "- DO NOT pick fields that are sample/donor/tissue/assay/QC/embedding/"
        "numeric metadata."
    )
    lines.append(
        "- If you genuinely cannot identify any author cell-type column, "
        "return an empty list."
    )
    lines.append("")
    lines.append("OBS COLUMNS (name | kind | sample values):")
    lines.append("")
    for name in sorted(schema.keys()):
        s = schema[name]
        kind = s.get("kind", "?")
        if kind == "categorical":
            meta = f"categorical[{s.get('n_categories', '?')} cats]"
        elif kind == "array":
            meta = f"array {s.get('dtype', '?')}"
        else:
            meta = kind
        sv = samples.get(name)
        if isinstance(sv, list):
            preview = ", ".join(repr(x) for x in sv[:10])
            if len(sv) > 10:
                preview += ", ..."
        else:
            preview = str(sv)
        lines.append(f"  {name}  |  {meta}  |  {preview}")
    lines.append("")
    lines.append(
        "OUTPUT FORMAT: return ONLY a JSON object on a single line, no prose, "
        "no markdown:"
    )
    lines.append('  {"picks": ["col1", "col2"], "reasoning": "one-sentence justification"}')
    lines.append("If no valid columns, picks should be [].")
    return "\n".join(lines)
