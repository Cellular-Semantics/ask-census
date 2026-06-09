"""Integration tests for the author_annotations pipeline against real CXG CDN URLs.

These tests require network access and are NOT run in CI by default.
Run them explicitly with:

    uv run pytest -m integration -v

Golden fixtures in tests/fixtures/ record the expected output of the current
implementation. To regenerate after an intentional change:

    uv run --with . python tests/generate_golden.py

then commit the updated fixtures alongside the code change.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from author_annotations import probe, pull_full_column, to_long_table

pytestmark = pytest.mark.integration

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def load_golden(name: str) -> dict:
    return json.loads((FIXTURES_DIR / f"{name}_golden.json").read_text())


# ---------------------------------------------------------------------------
# Tasic 2016 — mouse cortex, 1 679 cells, rich BICCN author columns
# ---------------------------------------------------------------------------


class TestTasic2016:
    GOLDEN_NAME = "tasic2016"

    @pytest.fixture(scope="class")
    def golden(self):
        return load_golden(self.GOLDEN_NAME)

    @pytest.fixture(scope="class")
    def probe_result(self, golden):
        return probe(golden["url"])

    @pytest.fixture(scope="class")
    def pull_result(self, golden):
        joinids, cols = pull_full_column(golden["url"], golden["author_cols"])
        return joinids, cols

    def test_probe_cell_count(self, probe_result, golden):
        assert probe_result["n_cells"] == golden["n_cells"]

    def test_probe_column_count(self, probe_result, golden):
        assert probe_result["n_obs_cols"] == golden["n_obs_cols"]

    def test_probe_schema_keys_unchanged(self, probe_result, golden):
        assert sorted(probe_result["schema"].keys()) == golden["schema_keys"]

    def test_probe_author_cols_are_categorical(self, probe_result, golden):
        for col in golden["author_cols"]:
            entry = probe_result["schema"][col]
            assert entry["kind"] == "categorical", f"{col} should be categorical"
            expected = golden["schema"][col]["n_categories"]
            assert entry["n_categories"] == expected, (
                f"{col}: n_categories {entry['n_categories']} != {expected}"
            )

    def test_pull_joinid_count(self, pull_result, golden):
        joinids, _ = pull_result
        assert joinids.shape[0] == golden["pull"]["joinids_count"]

    def test_pull_joinid_order_stable(self, pull_result, golden):
        joinids, _ = pull_result
        assert list(joinids[:5]) == golden["pull"]["first5_joinids"]

    def test_pull_author_col_values_stable(self, pull_result, golden):
        _, cols = pull_result
        for col in golden["author_cols"]:
            expected = golden["pull"]["first5_values"][col]
            actual = list(cols[col][:5])
            assert actual == expected, f"{col}: {actual} != {expected}"

    def test_to_long_table_shape(self, pull_result, golden):
        joinids, cols = pull_result
        per_dataset = {golden["dataset_id"]: {"joinids": joinids, "columns": cols}}
        df = to_long_table(per_dataset)
        assert list(df.columns) == [
            "observation_joinid",
            "dataset_id",
            "author_column",
            "value",
        ]
        # One row per (cell × author_col), minus any Nones
        assert len(df) > 0
        # All rows reference the correct dataset_id
        assert (df["dataset_id"] == golden["dataset_id"]).all()
        # Both author columns present
        for col in golden["author_cols"]:
            assert col in df["author_column"].values


# ---------------------------------------------------------------------------
# Muraro 2016 — human pancreas, 2 126 cells, single author column
# ---------------------------------------------------------------------------


class TestMuraro2016:
    GOLDEN_NAME = "muraro2016"

    @pytest.fixture(scope="class")
    def golden(self):
        return load_golden(self.GOLDEN_NAME)

    @pytest.fixture(scope="class")
    def probe_result(self, golden):
        return probe(golden["url"])

    @pytest.fixture(scope="class")
    def pull_result(self, golden):
        joinids, cols = pull_full_column(golden["url"], golden["author_cols"])
        return joinids, cols

    def test_probe_cell_count(self, probe_result, golden):
        assert probe_result["n_cells"] == golden["n_cells"]

    def test_probe_column_count(self, probe_result, golden):
        assert probe_result["n_obs_cols"] == golden["n_obs_cols"]

    def test_probe_schema_keys_unchanged(self, probe_result, golden):
        assert sorted(probe_result["schema"].keys()) == golden["schema_keys"]

    def test_probe_author_col_is_categorical(self, probe_result, golden):
        for col in golden["author_cols"]:
            entry = probe_result["schema"][col]
            assert entry["kind"] == "categorical"
            expected = golden["schema"][col]["n_categories"]
            assert entry["n_categories"] == expected

    def test_pull_joinid_count(self, pull_result, golden):
        joinids, _ = pull_result
        assert joinids.shape[0] == golden["pull"]["joinids_count"]

    def test_pull_joinid_order_stable(self, pull_result, golden):
        joinids, _ = pull_result
        assert list(joinids[:5]) == golden["pull"]["first5_joinids"]

    def test_pull_author_col_values_stable(self, pull_result, golden):
        _, cols = pull_result
        for col in golden["author_cols"]:
            expected = golden["pull"]["first5_values"][col]
            actual = list(cols[col][:5])
            assert actual == expected

    def test_to_long_table_shape(self, pull_result, golden):
        joinids, cols = pull_result
        per_dataset = {golden["dataset_id"]: {"joinids": joinids, "columns": cols}}
        df = to_long_table(per_dataset)
        assert list(df.columns) == [
            "observation_joinid",
            "dataset_id",
            "author_column",
            "value",
        ]
        assert len(df) == golden["n_cells"]  # one author col, no Nones expected
        assert (df["dataset_id"] == golden["dataset_id"]).all()
