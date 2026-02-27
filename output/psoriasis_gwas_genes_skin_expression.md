# GWAS Psoriasis Genes — Skin Expression Analysis

## Overview

We queried CELLxGENE Census for expression of the top 5 GWAS-ranked psoriasis vulgaris genes in skin tissue, comparing normal and psoriatic samples.

## Methods

### GWAS Gene Ranking

Using `src/gwas_genes.py`, we fetched all GWAS associations for psoriasis vulgaris (EFO:1001494) from the GWAS Catalog REST API and ranked genes by a composite score: `n_studies * log(max_OR) * -log10(min_pvalue)`. The top 5 genes were selected for expression analysis.

### CELLxGENE Census Query

- **Tissue filter**: `tissue == "skin of body"` (UBERON:0002097)
- **Disease filter**: `disease in ["normal", "psoriasis"]`
- **Primary data only**: `is_primary_data == True`
- **Gene filter**: 5 Ensembl IDs resolved via `gene_resolver`
- **API**: `cellxgene_census.get_anndata()` with `census_version="latest"`

Gene resolution:

| Gene  | Ensembl ID        |
|-------|-------------------|
| HLA-B | ENSG00000234745  |
| HLA-C | ENSG00000204525  |
| TNIP1 | ENSG00000145901  |
| IL12B | ENSG00000113302  |
| TYK2  | ENSG00000105397  |

### Expression Metrics

For each cell type × disease combination, we computed:
- **Mean expression** (raw counts)
- **Percent expressing** (% of cells with expression > 0)

## Results

**Total cells retrieved**: 259,782 (247,025 normal; 12,757 psoriasis)
**Cell types**: 134 unique cell type × disease combinations

Full results saved to `skin_psoriasis_gene_expression_by_celltype.csv`.

### Normal Skin (top 15 cell types by count)

| Cell type | n_cells | HLA-B % | HLA-C % | TNIP1 % | IL12B % | TYK2 % |
|-----------|--------:|--------:|--------:|--------:|--------:|-------:|
| fibroblast | 99,472 | 16.6 | 22.1 | 16.9 | 0.0 | 9.9 |
| skin fibroblast | 29,289 | 1.8 | 1.7 | 14.5 | 0.0 | 4.7 |
| macrophage | 22,117 | 85.8 | 71.1 | 28.7 | 0.0 | 13.1 |
| vascular associated smooth muscle cell | 9,414 | 48.8 | 54.8 | 16.7 | 0.0 | 6.8 |
| keratinocyte | 7,095 | 81.1 | 68.0 | 23.5 | 0.0 | 7.6 |
| monocyte | 6,015 | 97.3 | 91.9 | 33.9 | 0.1 | 18.7 |
| skeletal muscle satellite cell | 5,768 | 4.1 | 6.9 | 15.4 | 0.0 | 5.5 |
| myofibroblast cell | 5,228 | 13.2 | 7.1 | 13.5 | 0.0 | 10.7 |
| endothelial cell | 5,225 | 67.0 | 65.9 | 53.7 | 0.0 | 19.2 |
| natural killer cell | 5,101 | 98.8 | 97.7 | 31.4 | 0.0 | 7.7 |
| glial cell | 4,380 | 30.2 | 33.4 | 13.7 | 0.0 | 8.5 |
| stromal cell | 4,129 | 3.9 | 1.2 | 5.7 | 0.0 | 1.8 |
| dendritic cell | 3,964 | 94.6 | 90.1 | 32.2 | 0.1 | 24.1 |
| T cell | 3,561 | 98.2 | 92.9 | 28.1 | 0.0 | 6.5 |
| naive thymus-derived CD4+ alpha-beta T cell | 3,378 | 99.5 | 96.7 | 22.1 | 0.0 | 5.8 |

### Psoriasis Skin (top 15 cell types by count)

| Cell type | n_cells | HLA-B % | HLA-C % | TNIP1 % | IL12B % | TYK2 % |
|-----------|--------:|--------:|--------:|--------:|--------:|-------:|
| suprabasal keratinocyte | 2,355 | 0.0 | 0.0 | 24.8 | 0.2 | 25.5 |
| pericyte | 2,140 | 0.0 | 0.0 | 40.5 | 0.0 | 14.1 |
| endothelial cell | 1,923 | 0.0 | 0.0 | 51.2 | 0.3 | 30.4 |
| spinous cell of epidermis | 1,341 | 0.0 | 0.0 | 25.2 | 0.1 | 22.3 |
| fibroblast of papillary layer of dermis | 917 | 0.0 | 0.0 | 32.0 | 0.0 | 12.4 |
| granular cell of epidermis | 706 | 0.0 | 0.0 | 25.6 | 0.0 | 29.7 |
| cytotoxic T cell | 697 | 0.0 | 0.0 | 29.7 | 0.0 | 10.2 |
| skin fibroblast | 495 | 0.0 | 0.0 | 40.0 | 0.0 | 12.5 |
| fibroblast | 442 | 0.0 | 0.0 | 31.9 | 0.0 | 14.7 |
| hair follicular keratinocyte | 409 | 0.0 | 0.0 | 30.6 | 0.0 | 14.2 |
| dendritic cell, human | 237 | 0.0 | 0.0 | 40.9 | 0.0 | 37.6 |
| basal cell of epidermis | 207 | 0.0 | 0.0 | 34.3 | 0.5 | 38.6 |
| monocyte | 187 | 0.0 | 0.0 | 43.9 | 0.0 | 24.1 |
| endothelial cell of lymphatic vessel | 163 | 0.0 | 0.0 | 19.0 | 0.0 | 14.7 |
| helper T cell | 163 | 0.0 | 0.0 | 47.9 | 0.0 | 20.9 |

## Key Observations

### HLA-B & HLA-C
In normal skin, HLA-B and HLA-C are highly expressed in immune cells — monocytes (97%/92%), NK cells (99%/98%), T cells (98%/93%), dendritic cells (95%/90%), and macrophages (86%/71%). Keratinocytes also show strong expression (81%/68%), consistent with MHC class I presentation on epithelial surfaces.

**Technical artifact in psoriasis data**: HLA-B and HLA-C show 0% expression across all psoriasis cell types. This is likely a dataset-level artifact (e.g. different gene annotation versions or capture protocols in the psoriasis-specific datasets) rather than a biological signal, since MHC-I genes are constitutively expressed and known to be upregulated in psoriatic lesions.

### TNIP1
Broadly expressed at moderate levels (15–54%) across both conditions. Highest in endothelial cells (54% normal, 51% psoriasis), monocytes (34%/44%), and helper T cells (—/48%). As a negative regulator of NF-kB signalling, TNIP1's widespread expression is consistent with its role in restraining inflammatory responses across multiple cell lineages.

### IL12B
Essentially absent from both normal and psoriatic skin (<0.5% in all cell types). This is expected — IL-12/IL-23 p40 is produced transiently by activated antigen-presenting cells and would not be captured at appreciable levels in steady-state single-cell snapshots. The GWAS signal at IL12B reflects germline risk variants affecting cytokine production capacity, not constitutive expression levels.

### TYK2
Moderately expressed in normal skin, highest in dendritic cells (24%) and endothelial cells (19%). In psoriasis, TYK2 expression appears elevated in several cell types compared to normal: dendritic cells (38% vs 24%), basal keratinocytes (39%), endothelial cells (30% vs 19%), and granular keratinocytes (30%). This is consistent with JAK-STAT pathway activation in psoriatic inflammation and supports the therapeutic rationale for selective TYK2 inhibitors such as deucravacitinib.

## References

- Stuart PE et al. (2015) Genome-wide Association Analysis of Psoriatic Arthritis and Cutaneous Psoriasis Reveals Differences in Their Genetic Architecture. *Am J Hum Genet* 97(6):816–836. PMID: 26626624.
- Hirata J et al. (2018) Variants at HLA-A, HLA-C, and HLA-DQB1 Confer Risk of Psoriasis Vulgaris in Japanese. *J Dermatol Sci* 90(2):148–150. PMID: 29031612.
- GWAS gene ranking: `src/gwas_genes.py` with EFO:1001494 (psoriasis vulgaris)
- Expression data: CELLxGENE Census (latest version), primary data only
