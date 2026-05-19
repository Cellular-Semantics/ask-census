"""
CLI entry point for the enrich-slice workflow.

Accepts pre-fetched manifest and bitmap result JSON files (written by the
enrich-slice skill after calling the cl_kb MCP tools) and runs the full
bitmap-manifest join, writing enriched outputs alongside the slice.

Usage (from ask-census directory):
  uv run python src/enrich_slice_runner.py \
    --obs-file outputs/my_slice.h5ad \
    --manifest outputs/my_slice_manifest.json \
    --bitmap-results outputs/my_slice_bitmaps.json \
    --output-prefix outputs/my_slice_enriched
"""

from __future__ import annotations

import argparse
from pathlib import Path

from bitmap_manifest_join_lib import JoinSummary, load_bitmaps, load_manifest, run_join


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--obs-file", required=True, help=".h5ad or .parquet slice to enrich")
    p.add_argument("--manifest", required=True, help="Graph query response JSON")
    p.add_argument("--bitmap-results", required=True, help="Bitmap lookup results JSON")
    p.add_argument("--output-prefix", required=True, help="Prefix for output files")
    p.add_argument("--output-slice", help="Override path for the enriched slice output")
    return p.parse_args()


def main() -> int:
    args = parse_args()

    manifest = load_manifest(Path(args.manifest))
    bitmaps, bitmap_warnings = load_bitmaps(Path(args.bitmap_results))

    summary: JoinSummary = run_join(
        slice_path=Path(args.obs_file),
        manifest=manifest,
        bitmaps=bitmaps,
        output_prefix=args.output_prefix,
        output_slice=args.output_slice,
        bitmap_warnings=bitmap_warnings,
    )

    print("=== Enrichment summary ===")
    print(f"Slice rows            : {summary.slice_rows:,}")
    print(f"Manifest clusters     : {summary.manifest_clusters:,}")
    print(f"Decoded bitmaps       : {summary.decoded_bitmaps:,}")
    print(f"Matched cells         : {summary.matched_cells:,}")
    print(f"Matched clusters      : {summary.matched_clusters:,}")
    if summary.author_columns:
        print(f"Author columns added  : {', '.join(summary.author_columns)}")
    print(f"Enriched output       : {summary.output_slice}")

    if summary.warnings:
        print()
        for w in summary.warnings[:20]:
            print(f"  WARNING: {w}")
        if len(summary.warnings) > 20:
            print(f"  ... {len(summary.warnings) - 20} more warnings")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
