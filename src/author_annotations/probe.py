"""HTTPS range-read probe of a CELLxGENE source h5ad's obs schema + samples.

Median cost ~9 MB / 13 s cross-region (UK -> us-east) per dataset, independent
of dataset size — wire transfer is bounded by obs structure, not file size.

The probe enumerates every obs column and returns each column's kind / dtype /
n_categories plus a 20-row head sample. The expression matrix and other obs*
groups are not touched.

Vendored from https://github.com/Cellular-Semantics/agent_celltype_eval
(src/02_sample_and_probe.py). Refactored to remove the module-level monkey
patch: byte counting is done by attaching a per-call counter to the open
HTTPFile via _fetch_range wrapping.
"""

from __future__ import annotations

import threading
import time
import warnings
from typing import Any

import fsspec
import h5py
from fsspec.implementations.http import HTTPFile


def describe_column(node: Any) -> dict[str, Any]:
    """Return a schema descriptor for an obs column (no data read).

    AnnData encodes a categorical column as an HDF5 *group* with `codes` +
    `categories` datasets; non-categoricals are plain datasets.
    """
    if isinstance(node, h5py.Group):
        if "categories" in node and "codes" in node:
            try:
                return {
                    "kind": "categorical",
                    "dtype": str(node["codes"].dtype),
                    "n_categories": int(node["categories"].shape[0]),
                }
            except Exception:
                return {"kind": "categorical", "dtype": "?", "n_categories": None}
        return {"kind": "group"}
    try:
        return {
            "kind": "array",
            "dtype": str(node.dtype),
            "shape": list(node.shape),
        }
    except Exception:
        return {"kind": "array"}


def head_sample(node: Any, n: int = 20):
    """Return the first n values of an obs column, decoding categoricals."""
    if isinstance(node, h5py.Group) and "categories" in node:
        try:
            codes = node["codes"][:n]
            cats = node["categories"][:]
            return [
                cats[c].decode() if isinstance(cats[c], bytes) else str(cats[c])
                for c in codes
                if 0 <= c < len(cats)
            ]
        except Exception as e:
            return f"ERR: {e}"
    try:
        head = node[:n]
        out = []
        for v in head:
            if isinstance(v, bytes):
                out.append(v.decode(errors="replace"))
            else:
                try:
                    out.append(v.item())
                except Exception:
                    out.append(str(v))
        return out
    except Exception as e:
        return f"ERR: {e}"


_PATCH_LOCK = threading.Lock()
_PATCH_LOCK_HOLDERS = 0
_PATCH_ORIG = None
_PATCH_STATS_STACK: list = []


def _push_byte_counter(stats: dict[str, int]) -> None:
    """Class-level monkey-patch of HTTPFile._fetch_range that updates `stats`.

    fsspec drives reads through an asyncio loop and looks up `_fetch_range`
    on the class — instance-level wrapping doesn't intercept the path that
    actually fetches bytes. So patch at the class level, with a stack of
    active counters to support nested / concurrent probes.
    """
    global _PATCH_LOCK_HOLDERS, _PATCH_ORIG
    with _PATCH_LOCK:
        _PATCH_STATS_STACK.append(stats)
        if _PATCH_LOCK_HOLDERS == 0:
            _PATCH_ORIG = HTTPFile._fetch_range

            def counting(self, start, end, *args, **kwargs):
                data = _PATCH_ORIG(self, start, end, *args, **kwargs)
                for s in _PATCH_STATS_STACK:
                    s["n"] += len(data)
                    s["calls"] += 1
                return data

            HTTPFile._fetch_range = counting  # type: ignore[method-assign]
        _PATCH_LOCK_HOLDERS += 1


def _pop_byte_counter(stats: dict[str, int]) -> None:
    global _PATCH_LOCK_HOLDERS, _PATCH_ORIG
    with _PATCH_LOCK:
        if stats in _PATCH_STATS_STACK:
            _PATCH_STATS_STACK.remove(stats)
        _PATCH_LOCK_HOLDERS -= 1
        if _PATCH_LOCK_HOLDERS == 0 and _PATCH_ORIG is not None:
            HTTPFile._fetch_range = _PATCH_ORIG  # type: ignore[method-assign]
            _PATCH_ORIG = None


def probe(url: str, stats: dict[str, int] | None = None) -> dict[str, Any]:
    """Probe a remote h5ad's obs schema + samples via HTTPS range-read.

    Parameters
    ----------
    url : full HTTPS URL to a CELLxGENE source h5ad
          (e.g. https://datasets.cellxgene.cziscience.com/<dsid>.h5ad)
    stats : optional dict updated with {"n": bytes_on_wire, "calls": n_gets}.
            If supplied, must be writeable.

    Returns
    -------
    dict with keys:
        schema, samples, n_obs_cols, n_cells,
        probe_bytes, probe_gets, probe_time_s
    """
    if stats is None:
        stats = {}
    stats["n"] = 0
    stats["calls"] = 0

    fs, path = fsspec.core.url_to_fs(url)
    t0 = time.time()
    _push_byte_counter(stats)
    try:
        with fs.open(path, "rb", block_size=64 * 1024) as f:
            with h5py.File(f, "r") as h:
                if "obs" not in h:
                    return {
                        "error": "no obs group",
                        "probe_time_s": round(time.time() - t0, 2),
                    }
                obs = h["obs"]
                schema: dict[str, Any] = {}
                samples: dict[str, Any] = {}
                for k in obs.keys():
                    try:
                        schema[k] = describe_column(obs[k])
                        samples[k] = head_sample(obs[k])
                    except Exception as e:
                        warnings.warn(f"[probe] {k}: {e}", RuntimeWarning)
                        schema[k] = {"kind": "ERR", "error": str(e)}
                        samples[k] = f"ERR: {e}"
                n_cells = (
                    int(obs["observation_joinid"].shape[0])
                    if "observation_joinid" in obs
                    else None
                )
    finally:
        _pop_byte_counter(stats)

    return {
        "schema": schema,
        "samples": samples,
        "n_obs_cols": len(schema),
        "n_cells": n_cells,
        "probe_bytes": stats["n"],
        "probe_gets": stats["calls"],
        "probe_time_s": round(time.time() - t0, 2),
    }
