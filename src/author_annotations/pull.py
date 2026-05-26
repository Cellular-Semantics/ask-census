"""Full-column pulls from a remote h5ad's obs group.

Extends the cheap schema+sample probe with a full-array read for one or more
picked columns. Same fsspec+h5py transport, same range-read mechanics — just
reads the whole dataset instead of a 20-row head.

A full obs column for a 1M-cell dataset is typically a few MB on the wire;
the categorical case (codes + categories table) is cheaper still.
"""
from __future__ import annotations

from typing import Dict, Iterable, List, Optional, Tuple

import fsspec
import h5py
import numpy as np

from .probe import _push_byte_counter, _pop_byte_counter


def _decode_array(node: h5py.Dataset) -> np.ndarray:
    """Read a non-categorical obs dataset in full, decoding bytes to str."""
    data = node[:]
    if data.dtype.kind in ("S", "O"):  # bytes / object (string)
        out = np.empty(len(data), dtype=object)
        for i, v in enumerate(data):
            if isinstance(v, bytes):
                out[i] = v.decode(errors="replace")
            else:
                out[i] = v
        return out
    return data


def _decode_categorical(group: h5py.Group) -> np.ndarray:
    """Materialise a categorical obs group into a 1-D array of decoded strings."""
    codes = group["codes"][:]
    cats = group["categories"][:]
    decoded_cats = np.array(
        [c.decode(errors="replace") if isinstance(c, bytes) else str(c) for c in cats],
        dtype=object,
    )
    out = np.empty(len(codes), dtype=object)
    valid = (codes >= 0) & (codes < len(decoded_cats))
    out[valid] = decoded_cats[codes[valid]]
    out[~valid] = None  # NaN-equivalent for missing categorical
    return out


def pull_full_column(
    url: str,
    column_names: Iterable[str],
    stats: Optional[Dict[str, int]] = None,
) -> Tuple[np.ndarray, Dict[str, np.ndarray]]:
    """Pull observation_joinid and one-or-more full obs columns from a remote h5ad.

    Parameters
    ----------
    url : full HTTPS URL to a CELLxGENE source h5ad
    column_names : obs column names to fetch in full (in addition to
                   observation_joinid, which is always returned).
    stats : optional dict updated with {"n": bytes_on_wire, "calls": n_gets}.

    Returns
    -------
    (joinids, columns) where
        joinids   : ndarray of observation_joinid strings, shape (n_cells,)
        columns   : dict {column_name: ndarray(n_cells,) of decoded values}.
                    Columns that don't exist or fail to decode are returned
                    as None (with a warning to stderr).
    """
    if stats is None:
        stats = {}
    stats["n"] = 0
    stats["calls"] = 0

    fs, path = fsspec.core.url_to_fs(url)
    cols: Dict[str, np.ndarray] = {}

    _push_byte_counter(stats)
    try:
        with fs.open(path, "rb", block_size=64 * 1024) as f:
            with h5py.File(f, "r") as h:
                obs = h["obs"]
                joinid_node = obs["observation_joinid"]
                joinids = _decode_array(joinid_node)

                for col in column_names:
                    if col not in obs:
                        cols[col] = None  # type: ignore[assignment]
                        continue
                    node = obs[col]
                    try:
                        if isinstance(node, h5py.Group) and "categories" in node:
                            cols[col] = _decode_categorical(node)
                        else:
                            cols[col] = _decode_array(node)
                    except Exception as e:
                        import sys
                        sys.stderr.write(f"[pull] {col}: {e}\n")
                        cols[col] = None  # type: ignore[assignment]
    finally:
        _pop_byte_counter(stats)

    return joinids, cols
