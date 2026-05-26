"""
Pure library for the bitmap-manifest join workflow.

All functions accept in-memory data structures so they can be driven either
from file paths (CLI) or from MCP tool call results (agentic workflow).

Key entry points
----------------
load_manifest(path)            -> dict[str, ClusterRecord]
load_manifest_from_dict(data)  -> dict[str, ClusterRecord]

load_bitmaps(path)             -> (dict[str, BitMap], list[str])
load_bitmaps_from_dict(data)   -> (dict[str, BitMap], list[str])

run_join(slice_path, manifest, bitmaps, output_prefix, output_slice)
    -> JoinSummary
"""

from __future__ import annotations

import base64
import binascii
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import NamedTuple

import anndata as ad
import pandas as pd
from pyroaring import BitMap


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class ClusterRecord:
    node_iri: str
    cluster_label: str | None
    author_label_column: str | None
    author_label: str | None
    author_synonym_columns: list[str]
    author_synonym_labels: dict[str, str]
    dataset_iri: str | None
    dataset_title: str | None
    dataset_publication_doi: str | None
    census_dataset_id: str | None
    bitmap_lookup_key: str


class JoinSummary(NamedTuple):
    slice_rows: int
    manifest_clusters: int
    decoded_bitmaps: int
    membership_rows: int
    matched_cells: int
    matched_clusters: int
    author_columns: list[str]
    output_slice: Path
    warnings: list[str]


# ---------------------------------------------------------------------------
# Bitmap decoding
# ---------------------------------------------------------------------------

def decode_bitmap_payload(payload: str) -> BitMap:
    cleaned = "".join(payload.split())
    if not cleaned:
        raise ValueError("bitmap payload is empty")
    try:
        raw = base64.b64decode(cleaned, validate=True)
    except binascii.Error as exc:
        raise ValueError("bitmap payload is not valid base64") from exc
    try:
        return BitMap.deserialize(raw)
    except Exception as exc:
        raise ValueError("payload decoded but is not a valid roaring bitmap") from exc


# ---------------------------------------------------------------------------
# Manifest loading
# ---------------------------------------------------------------------------

def _parse_cluster_entry(node_iri: str, entry: dict) -> tuple[str, ClusterRecord]:
    bitmap_lookup_key = entry.get("bitmap_lookup_key") or node_iri
    record = ClusterRecord(
        node_iri=entry.get("node_iri") or node_iri,
        cluster_label=entry.get("cluster_label"),
        author_label_column=entry.get("author_label_column"),
        author_label=entry.get("author_label"),
        author_synonym_columns=list(entry.get("author_synonym_columns") or []),
        author_synonym_labels=dict(entry.get("author_synonym_labels") or {}),
        dataset_iri=entry.get("dataset_iri"),
        dataset_title=entry.get("dataset_title"),
        dataset_publication_doi=entry.get("dataset_publication_doi"),
        census_dataset_id=entry.get("census_dataset_id"),
        bitmap_lookup_key=bitmap_lookup_key,
    )
    return bitmap_lookup_key, record


def load_manifest(path: Path) -> dict[str, ClusterRecord]:
    return load_manifest_from_dict(json.loads(path.read_text()))


def load_manifest_from_dict(data: dict) -> dict[str, ClusterRecord]:
    records: dict[str, ClusterRecord] = {}
    for node_iri, entry in (data.get("clusters") or {}).items():
        key, record = _parse_cluster_entry(node_iri, entry)
        records[key] = record
    return records


# ---------------------------------------------------------------------------
# Bitmap loading
# ---------------------------------------------------------------------------

def _parse_bitmap_result(entry: dict) -> tuple[str | None, BitMap | None, str | None]:
    """Returns (key, bitmap, warning_or_None)."""
    key = entry.get("bitmap_lookup_key")
    if not key:
        return None, None, "bitmap result missing bitmap_lookup_key"
    if not entry.get("ok"):
        return key, None, f"bitmap lookup failed for {key}: {entry.get('error')}"
    response = entry.get("response") or {}
    bitmap_b64 = response.get("bitmap_base64")
    if not bitmap_b64:
        return key, None, f"bitmap lookup succeeded but returned no payload for {key}"
    try:
        return key, decode_bitmap_payload(bitmap_b64), None
    except ValueError as exc:
        return key, None, f"failed to decode bitmap for {key}: {exc}"


def load_bitmaps(path: Path) -> tuple[dict[str, BitMap], list[str]]:
    return load_bitmaps_from_dict(json.loads(path.read_text()))


def load_bitmaps_from_dict(data: dict) -> tuple[dict[str, BitMap], list[str]]:
    bitmaps: dict[str, BitMap] = {}
    warnings: list[str] = []
    for entry in data.get("results", []):
        key, bitmap, warn = _parse_bitmap_result(entry)
        if warn:
            warnings.append(warn)
        if key and bitmap is not None:
            bitmaps[key] = bitmap
    return bitmaps, warnings


# ---------------------------------------------------------------------------
# Slice loading
# ---------------------------------------------------------------------------

def load_slice_obs(path: Path) -> pd.DataFrame:
    if path.suffix == ".h5ad":
        adata = ad.read_h5ad(path, backed="r")
        obs = adata.obs.copy()
    elif path.suffix == ".parquet":
        obs = pd.read_parquet(path)
    else:
        raise ValueError(f"unsupported slice format: {path.suffix}")

    missing = {"soma_joinid", "dataset_id"}.difference(obs.columns)
    if missing:
        raise ValueError(f"slice missing required obs columns: {', '.join(sorted(missing))}")

    obs["soma_joinid"] = obs["soma_joinid"].astype("int64")
    obs["dataset_id"] = obs["dataset_id"].astype(str)
    return obs


# ---------------------------------------------------------------------------
# Enriched slice writer
# ---------------------------------------------------------------------------

def write_enriched_slice(
    source_path: Path,
    enriched_obs: pd.DataFrame,
    output_path: Path,
) -> None:
    if source_path.suffix == ".h5ad":
        adata = ad.read_h5ad(source_path)
        if len(adata.obs) != len(enriched_obs):
            raise ValueError(
                f"cannot write enriched h5ad: obs row count changed "
                f"({len(adata.obs)} != {len(enriched_obs)})"
            )
        obs_to_write = enriched_obs.copy()
        obs_to_write.index = adata.obs.index
        adata.obs = obs_to_write
        tmp = output_path.with_name(f"{output_path.stem}.__tmp__.h5ad")
        if tmp.exists():
            tmp.unlink()
        adata.write_h5ad(tmp)
        os.replace(tmp, output_path)
        return

    if source_path.suffix == ".parquet":
        enriched_obs.to_parquet(output_path, index=False)
        return

    raise ValueError(f"unsupported slice output format for source: {source_path.suffix}")


# ---------------------------------------------------------------------------
# Membership table
# ---------------------------------------------------------------------------

def build_membership_table(
    obs: pd.DataFrame,
    manifest: dict[str, ClusterRecord],
    bitmaps: dict[str, BitMap],
) -> tuple[pd.DataFrame, list[str]]:
    slice_ids = BitMap(obs["soma_joinid"].tolist())
    slice_dataset_ids = set(obs["dataset_id"].astype(str))
    rows: list[dict] = []
    warnings: list[str] = []

    for key, bitmap in bitmaps.items():
        cluster = manifest.get(key)
        if cluster is None:
            warnings.append(f"bitmap result {key} has no matching manifest entry")
            continue

        if cluster.census_dataset_id and cluster.census_dataset_id not in slice_dataset_ids:
            continue

        hits = bitmap & slice_ids
        if not hits:
            continue

        synonym_columns = "|".join(cluster.author_synonym_columns)
        synonym_labels = "|".join(
            f"{col}:{lbl}"
            for col, lbl in sorted(cluster.author_synonym_labels.items())
        )

        for soma_joinid in hits:
            rows.append({
                "soma_joinid": int(soma_joinid),
                "node_iri": cluster.node_iri,
                "bitmap_lookup_key": cluster.bitmap_lookup_key,
                "cluster_label": cluster.cluster_label,
                "author_label_column": cluster.author_label_column,
                "author_label": cluster.author_label,
                "author_synonym_columns": synonym_columns,
                "author_synonym_labels": synonym_labels,
                "author_synonym_columns_json": json.dumps(
                    cluster.author_synonym_columns, ensure_ascii=False
                ),
                "author_synonym_labels_json": json.dumps(
                    cluster.author_synonym_labels, ensure_ascii=False
                ),
                "dataset_id": cluster.census_dataset_id,
                "dataset_title": cluster.dataset_title,
                "dataset_publication_doi": cluster.dataset_publication_doi,
            })

    membership = pd.DataFrame(rows)
    if len(membership) == 0:
        return membership, warnings

    membership = membership.sort_values(
        ["soma_joinid", "cluster_label", "node_iri"], kind="stable"
    ).reset_index(drop=True)
    return membership, warnings


# ---------------------------------------------------------------------------
# Aggregation helpers
# ---------------------------------------------------------------------------

def aggregate_membership(membership: pd.DataFrame) -> pd.DataFrame:
    if len(membership) == 0:
        return pd.DataFrame(columns=["soma_joinid", "matched_cluster_count"])
    return (
        membership.groupby("soma_joinid", sort=False)
        .agg(matched_cluster_count=("node_iri", "count"))
        .reset_index()
    )


def build_author_annotation_columns(membership: pd.DataFrame) -> pd.DataFrame:
    if len(membership) == 0:
        return pd.DataFrame(columns=["soma_joinid"])

    values_by_cell: dict[int, dict[str, list[str]]] = {}

    for _, row in membership.iterrows():
        soma_joinid = int(row["soma_joinid"])
        cell_columns = values_by_cell.setdefault(soma_joinid, {})

        author_label_column = row.get("author_label_column")
        author_label = row.get("author_label")
        if pd.notna(author_label_column) and pd.notna(author_label):
            col, val = str(author_label_column), str(author_label)
            if col and val:
                cell_columns.setdefault(col, []).append(val)

        synonym_labels_json = row.get("author_synonym_labels_json")
        if pd.notna(synonym_labels_json) and synonym_labels_json:
            for col, val in json.loads(synonym_labels_json).items():
                if col and val is not None and str(val) != "":
                    cell_columns.setdefault(str(col), []).append(str(val))

    records = [
        {"soma_joinid": jid, **{col: "|".join(dict.fromkeys(vals)) for col, vals in cols.items()}}
        for jid, cols in values_by_cell.items()
    ]
    return pd.DataFrame(records).sort_values("soma_joinid", kind="stable").reset_index(drop=True)


def build_doi_column(membership: pd.DataFrame) -> pd.DataFrame:
    """Return a DataFrame with soma_joinid and kb_publication_doi (|‑joined unique DOIs per cell)."""
    if len(membership) == 0:
        return pd.DataFrame(columns=["soma_joinid", "kb_publication_doi"])
    doi_series = (
        membership[membership["dataset_publication_doi"].notna()]
        .groupby("soma_joinid")["dataset_publication_doi"]
        .agg(lambda vals: "|".join(dict.fromkeys(vals)))
        .rename("kb_publication_doi")
        .reset_index()
    )
    return doi_series


def build_cluster_summary(membership: pd.DataFrame) -> pd.DataFrame:
    if len(membership) == 0:
        return pd.DataFrame(columns=[
            "node_iri", "cluster_label", "author_label_column", "author_label",
            "dataset_id", "dataset_title", "dataset_publication_doi", "matched_cells_in_slice",
        ])
    return (
        membership.groupby(
            ["node_iri", "cluster_label", "author_label_column", "author_label",
             "dataset_id", "dataset_title", "dataset_publication_doi"],
            dropna=False, sort=False,
        )
        .agg(matched_cells_in_slice=("soma_joinid", "nunique"))
        .reset_index()
        .sort_values(["matched_cells_in_slice", "cluster_label"], ascending=[False, True], kind="stable")
        .reset_index(drop=True)
    )


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

def run_join(
    slice_path: Path,
    manifest: dict[str, ClusterRecord],
    bitmaps: dict[str, BitMap],
    output_prefix: Path | str,
    output_slice: Path | str | None = None,
    bitmap_warnings: list[str] | None = None,
) -> JoinSummary:
    """Run the full join and write all outputs. Returns a JoinSummary."""
    slice_path = Path(slice_path)
    prefix = Path(output_prefix)

    obs = load_slice_obs(slice_path)
    membership, membership_warnings = build_membership_table(obs, manifest, bitmaps)
    aggregated = aggregate_membership(membership)
    author_cols_df = build_author_annotation_columns(membership)

    cell_level = obs.join(
        aggregated.set_index("soma_joinid"),
        on="soma_joinid",
        how="left",
        validate="one_to_one",
    )
    if "matched_cluster_count" in cell_level.columns:
        cell_level["matched_cluster_count"] = cell_level["matched_cluster_count"].astype("Int64")
    if len(author_cols_df) > 0:
        author_cols_df = author_cols_df.set_index("soma_joinid")
        for col in author_cols_df.columns:
            cell_level[col] = cell_level["soma_joinid"].map(author_cols_df[col])

    doi_df = build_doi_column(membership)
    if len(doi_df) > 0:
        cell_level["kb_publication_doi"] = cell_level["soma_joinid"].map(
            doi_df.set_index("soma_joinid")["kb_publication_doi"]
        )

    cluster_summary = build_cluster_summary(membership)

    membership_path = prefix.with_name(f"{prefix.name}__membership.csv")
    cells_path = prefix.with_name(f"{prefix.name}__cells.csv")
    summary_path = prefix.with_name(f"{prefix.name}__cluster_summary.csv")

    if output_slice:
        enriched_path = Path(output_slice)
    elif slice_path.suffix == ".h5ad":
        enriched_path = prefix.with_name(f"{prefix.name}__enriched.h5ad")
    elif slice_path.suffix == ".parquet":
        enriched_path = prefix.with_name(f"{prefix.name}__enriched.parquet")
    else:
        raise ValueError(f"unsupported slice format: {slice_path.suffix}")

    membership.to_csv(membership_path, index=False)
    cell_level.to_csv(cells_path, index=False)
    cluster_summary.to_csv(summary_path, index=False)
    write_enriched_slice(slice_path, cell_level, enriched_path)

    author_columns = sorted(
        col for col in cell_level.columns
        if col not in obs.columns and col != "matched_cluster_count"
    )

    all_warnings = list(bitmap_warnings or []) + membership_warnings

    return JoinSummary(
        slice_rows=len(obs),
        manifest_clusters=len(manifest),
        decoded_bitmaps=len(bitmaps),
        membership_rows=len(membership),
        matched_cells=int(cell_level["matched_cluster_count"].notna().sum()),
        matched_clusters=len(cluster_summary),
        author_columns=author_columns,
        output_slice=enriched_path,
        warnings=all_warnings,
    )
