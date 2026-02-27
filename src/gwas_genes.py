"""GWAS Gene Ranker — fetch associations from the GWAS Catalog and rank genes by composite score."""

from __future__ import annotations

import math
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from collections import defaultdict

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

GWAS_API = "https://www.ebi.ac.uk/gwas/rest/api"


def _session() -> requests.Session:
    s = requests.Session()
    retries = Retry(total=3, backoff_factor=0.5, status_forcelist=[429, 500, 502, 503, 504])
    s.mount("https://", HTTPAdapter(max_retries=retries))
    s.headers["Accept"] = "application/json"
    return s


def fetch_gwas_associations(efo_id: str) -> list[dict]:
    """Fetch all GWAS associations for an EFO trait (no study metadata yet).

    Returns flat list of dicts with keys: gene, ensembl_id, snp, risk_allele,
    pvalue, odds_ratio, beta, study_url (raw link for dedup/counting).
    """
    sess = _session()

    url = f"{GWAS_API}/efoTraits/{efo_id}/associations"
    params: dict = {"projection": "associationByEfoTrait"}
    raw_associations: list[dict] = []

    while url:
        resp = sess.get(url, params=params)
        resp.raise_for_status()
        data = resp.json()
        embedded = data.get("_embedded", {})
        raw_associations.extend(embedded.get("associations", []))
        next_link = data.get("_links", {}).get("next", {}).get("href")
        url = next_link
        params = {}

    results: list[dict] = []
    for assoc in raw_associations:
        pvalue = assoc.get("pvalue")
        or_val = assoc.get("orPerCopyNum")
        beta_val = assoc.get("betaNum")
        study_href = assoc.get("_links", {}).get("study", {}).get("href", "")

        snp_list = assoc.get("snps", [])
        snp_id = snp_list[0].get("rsId", "") if snp_list else ""

        genes: list[dict] = []
        for locus in assoc.get("loci", []):
            for gene in locus.get("authorReportedGenes", []):
                genes.append(gene)

        if not genes:
            continue

        for gene in genes:
            gene_name = gene.get("geneName", "")
            if not gene_name or gene_name.lower() in ("intergenic", "nr"):
                continue

            ensembl_ids = gene.get("ensemblGeneIds", [])
            ensembl_id = ensembl_ids[0] if ensembl_ids else ""

            results.append({
                "gene": gene_name,
                "ensembl_id": ensembl_id,
                "snp": snp_id,
                "pvalue": float(pvalue) if pvalue is not None else None,
                "odds_ratio": float(or_val) if or_val is not None else None,
                "beta": float(beta_val) if beta_val is not None else None,
                "study_url": study_href,
            })

    return results


@dataclass
class GeneRank:
    gene_name: str
    ensembl_id: str
    n_studies: int
    n_snps: int
    min_pvalue: float
    max_or: float | None
    composite_score: float
    supporting_snps: list[str] = field(default_factory=list)
    pubmed_ids: list[str] = field(default_factory=list)
    study_titles: list[str] = field(default_factory=list)


def rank_genes(associations: list[dict], top_n: int = 20) -> list[GeneRank]:
    """Group associations by gene and compute a composite ranking score.

    Score = n_studies * log(max_or) * -log10(min_pvalue)
    Falls back to n_studies * -log10(min_pvalue) when OR is absent or 1.0.

    Study count uses unique study_url as proxy — no HTTP needed.
    """
    by_gene: dict[str, list[dict]] = defaultdict(list)
    for a in associations:
        by_gene[a["gene"]].append(a)

    ranked: list[GeneRank] = []
    for gene_name, assocs in by_gene.items():
        study_urls = {a["study_url"] for a in assocs if a["study_url"]}
        snps = sorted({a["snp"] for a in assocs if a["snp"]})

        n_studies = len(study_urls)
        n_snps = len(snps)

        pvalues = [a["pvalue"] for a in assocs if a["pvalue"] is not None and a["pvalue"] > 0]
        min_pv = min(pvalues) if pvalues else 1.0

        ors = [a["odds_ratio"] for a in assocs if a["odds_ratio"] is not None and a["odds_ratio"] > 0]
        max_or = max(ors) if ors else None

        log_pv = -math.log10(min_pv) if min_pv > 0 else 0

        if max_or and max_or != 1.0:
            score = n_studies * math.log(max_or) * log_pv
        else:
            score = n_studies * log_pv

        ensembl_id = next((a["ensembl_id"] for a in assocs if a["ensembl_id"]), "")

        # Top SNPs by p-value
        sorted_assocs = sorted(
            [a for a in assocs if a["pvalue"] is not None],
            key=lambda a: a["pvalue"],
        )
        top_snps = []
        seen = set()
        for a in sorted_assocs:
            if a["snp"] and a["snp"] not in seen:
                top_snps.append(a["snp"])
                seen.add(a["snp"])
            if len(top_snps) >= 5:
                break

        ranked.append(GeneRank(
            gene_name=gene_name,
            ensembl_id=ensembl_id,
            n_studies=n_studies,
            n_snps=n_snps,
            min_pvalue=min_pv,
            max_or=max_or,
            composite_score=score,
            supporting_snps=top_snps,
        ))

    ranked.sort(key=lambda g: g.composite_score, reverse=True)
    return ranked[:top_n]


def _enrich_with_studies(genes: list[GeneRank], associations: list[dict]) -> None:
    """Fetch study metadata (PMID, title) only for the top-ranked genes."""
    # Collect study URLs needed for just these genes
    gene_names = {g.gene_name for g in genes}
    gene_study_urls: dict[str, set[str]] = defaultdict(set)
    for a in associations:
        if a["gene"] in gene_names and a["study_url"]:
            gene_study_urls[a["gene"]].add(a["study_url"])

    all_urls = set()
    for urls in gene_study_urls.values():
        all_urls.update(urls)

    if not all_urls:
        return

    sess = _session()
    study_cache: dict[str, dict] = {}

    def _fetch_study(study_url: str) -> tuple[str, dict]:
        try:
            r = sess.get(study_url)
            r.raise_for_status()
            sdata = r.json()
            return study_url, {
                "pubmed_id": str(sdata.get("publicationInfo", {}).get("pubmedId", "")),
                "title": sdata.get("publicationInfo", {}).get("title", ""),
            }
        except requests.RequestException:
            return study_url, {"pubmed_id": "", "title": ""}

    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = {executor.submit(_fetch_study, u): u for u in all_urls}
        for future in as_completed(futures):
            url_key, meta = future.result()
            study_cache[url_key] = meta

    for g in genes:
        urls = gene_study_urls.get(g.gene_name, set())
        pmids = sorted({study_cache[u]["pubmed_id"] for u in urls if study_cache.get(u, {}).get("pubmed_id")})
        titles = sorted({study_cache[u]["title"] for u in urls if study_cache.get(u, {}).get("title")})
        g.pubmed_ids = pmids
        g.study_titles = titles


def get_top_gwas_genes(efo_id: str, top_n: int = 20) -> list[GeneRank]:
    """Fetch GWAS associations → rank genes → enrich top N with study refs."""
    associations = fetch_gwas_associations(efo_id)
    top_genes = rank_genes(associations, top_n=top_n)
    _enrich_with_studies(top_genes, associations)
    return top_genes


if __name__ == "__main__":
    import sys

    trait = sys.argv[1] if len(sys.argv) > 1 else "EFO_0000676"
    n = int(sys.argv[2]) if len(sys.argv) > 2 else 20

    print(f"Fetching GWAS associations for {trait}...")
    results = get_top_gwas_genes(trait, top_n=n)
    print(f"\nTop {len(results)} genes by composite score:\n")
    for i, g in enumerate(results, 1):
        or_str = f"{g.max_or:.2f}" if g.max_or else "N/A"
        print(
            f"{i:>2}. {g.gene_name:<12} score={g.composite_score:>8.1f}  "
            f"studies={g.n_studies}  snps={g.n_snps}  "
            f"min_p={g.min_pvalue:.1e}  max_OR={or_str}  "
            f"top_snps={g.supporting_snps[:3]}"
        )
    print()
    print("Top gene references:")
    for g in results[:3]:
        print(f"\n  {g.gene_name}: {len(g.pubmed_ids)} PMIDs, {len(g.study_titles)} studies")
        for t in g.study_titles[:3]:
            print(f"    - {t}")
