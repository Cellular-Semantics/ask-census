"""Tests for the gene_resolver module."""

from unittest.mock import MagicMock, patch

import pytest

from gene_resolver import (
    GeneDict,
    GeneMatch,
    _get_gene_dict,
    build_var_value_filter,
    resolve_genes,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def clear_gene_dict_cache():
    """Clear the LRU cache before and after each test."""
    _get_gene_dict.cache_clear()
    yield
    _get_gene_dict.cache_clear()


@pytest.fixture
def sample_gene_dict():
    """A small GeneDict for unit testing."""
    gd = GeneDict()
    # Unambiguous genes
    gd.name_to_ids["TP53"] = ["ENSG00000141510"]
    gd.id_to_name["ENSG00000141510"] = "TP53"
    gd.id_to_feature_type["ENSG00000141510"] = "protein_coding"

    gd.name_to_ids["BRCA1"] = ["ENSG00000012048"]
    gd.id_to_name["ENSG00000012048"] = "BRCA1"
    gd.id_to_feature_type["ENSG00000012048"] = "protein_coding"

    # Ambiguous gene: two Ensembl IDs, one protein_coding
    gd.name_to_ids["AMBIG"] = ["ENSG00000000001", "ENSG00000000002"]
    gd.id_to_name["ENSG00000000001"] = "AMBIG"
    gd.id_to_name["ENSG00000000002"] = "AMBIG"
    gd.id_to_feature_type["ENSG00000000001"] = "protein_coding"
    gd.id_to_feature_type["ENSG00000000002"] = "lncRNA"

    # Ambiguous gene: two protein_coding (cannot disambiguate)
    gd.name_to_ids["DUALPC"] = ["ENSG00000000003", "ENSG00000000004"]
    gd.id_to_name["ENSG00000000003"] = "DUALPC"
    gd.id_to_name["ENSG00000000004"] = "DUALPC"
    gd.id_to_feature_type["ENSG00000000003"] = "protein_coding"
    gd.id_to_feature_type["ENSG00000000004"] = "protein_coding"

    return gd


# ---------------------------------------------------------------------------
# build_var_value_filter
# ---------------------------------------------------------------------------


class TestBuildVarValueFilter:
    def test_single_id(self):
        assert (
            build_var_value_filter(["ENSG00000141510"])
            == "feature_id in ['ENSG00000141510']"
        )

    def test_multiple_ids_sorted(self):
        result = build_var_value_filter(["ENSG00000012048", "ENSG00000141510"])
        assert result == "feature_id in ['ENSG00000012048', 'ENSG00000141510']"

    def test_deduplicates(self):
        result = build_var_value_filter(["ENSG00000141510", "ENSG00000141510"])
        assert result == "feature_id in ['ENSG00000141510']"

    def test_empty_list(self):
        assert build_var_value_filter([]) == ""


# ---------------------------------------------------------------------------
# resolve_genes
# ---------------------------------------------------------------------------


class TestResolveGenes:
    def test_unambiguous_name(self, sample_gene_dict):
        with patch("gene_resolver._get_gene_dict", return_value=sample_gene_dict):
            results = resolve_genes(["TP53"])
        assert len(results) == 1
        m = results[0]
        assert m.query == "TP53"
        assert m.ensembl_ids == ["ENSG00000141510"]
        assert m.is_ambiguous is False

    def test_case_insensitive(self, sample_gene_dict):
        with patch("gene_resolver._get_gene_dict", return_value=sample_gene_dict):
            results = resolve_genes(["tp53"])
        assert results[0].ensembl_ids == ["ENSG00000141510"]

    def test_ensembl_id_passthrough(self, sample_gene_dict):
        with patch("gene_resolver._get_gene_dict", return_value=sample_gene_dict):
            results = resolve_genes(["ENSG00000141510"])
        m = results[0]
        assert m.ensembl_ids == ["ENSG00000141510"]
        assert m.canonical_name == "TP53"
        assert m.is_ambiguous is False

    def test_unknown_ensembl_id(self, sample_gene_dict):
        with patch("gene_resolver._get_gene_dict", return_value=sample_gene_dict):
            results = resolve_genes(["ENSG99999999999"])
        m = results[0]
        assert m.ensembl_ids == ["ENSG99999999999"]
        assert m.canonical_name is None

    def test_gene_not_found(self, sample_gene_dict):
        with patch("gene_resolver._get_gene_dict", return_value=sample_gene_dict):
            results = resolve_genes(["NOTREAL"])
        m = results[0]
        assert m.ensembl_ids == []
        assert m.is_ambiguous is False

    def test_ambiguous_prefers_protein_coding(self, sample_gene_dict):
        with patch("gene_resolver._get_gene_dict", return_value=sample_gene_dict):
            results = resolve_genes(["AMBIG"], prefer_protein_coding=True)
        m = results[0]
        assert m.ensembl_ids == ["ENSG00000000001"]
        assert m.is_ambiguous is False

    def test_ambiguous_no_preference(self, sample_gene_dict):
        with patch("gene_resolver._get_gene_dict", return_value=sample_gene_dict):
            results = resolve_genes(["AMBIG"], prefer_protein_coding=False)
        m = results[0]
        assert len(m.ensembl_ids) == 2
        assert m.is_ambiguous is True

    def test_ambiguous_dual_protein_coding(self, sample_gene_dict):
        """Two protein_coding hits — cannot disambiguate."""
        with patch("gene_resolver._get_gene_dict", return_value=sample_gene_dict):
            results = resolve_genes(["DUALPC"], prefer_protein_coding=True)
        m = results[0]
        assert len(m.ensembl_ids) == 2
        assert m.is_ambiguous is True

    def test_multiple_genes(self, sample_gene_dict):
        with patch("gene_resolver._get_gene_dict", return_value=sample_gene_dict):
            results = resolve_genes(["TP53", "BRCA1"])
        assert len(results) == 2
        assert results[0].ensembl_ids == ["ENSG00000141510"]
        assert results[1].ensembl_ids == ["ENSG00000012048"]

    def test_whitespace_stripped(self, sample_gene_dict):
        with patch("gene_resolver._get_gene_dict", return_value=sample_gene_dict):
            results = resolve_genes(["  TP53  "])
        assert results[0].ensembl_ids == ["ENSG00000141510"]
