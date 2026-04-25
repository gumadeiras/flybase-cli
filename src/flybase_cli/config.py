from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


BASE_BUCKET = "https://s3ftp.flybase.org/releases/current/"
BASE_API = "https://api.flybase.org/api/v1.0/"
DEFAULT_ROOT = Path("data/flybase")
DEFAULT_DB = DEFAULT_ROOT / "flybase.sqlite"
DEFAULT_MANIFEST = DEFAULT_ROOT / "manifest.json"
BATCH_SIZE = 1000
INGEST_SUFFIXES = (".tsv", ".csv", ".tsv.gz", ".csv.gz")


@dataclass(frozen=True)
class SyncPreset:
    name: str
    description: str
    prefix: str
    includes: tuple[str, ...]
    excludes: tuple[str, ...] = ()


SYNC_PRESETS: dict[str, SyncPreset] = {
    "gene-core": SyncPreset(
        name="gene-core",
        description="Gene summaries plus core identifier/link tables.",
        prefix="precomputed_files/genes/",
        includes=(
            r"best_gene_summary",
            r"fbgn_fbtr_fbpp_fb_",
            r"fbgn_annotation_ID",
            r"dmel_gene_sequence_ontology_annotations",
        ),
    ),
    "gene-expression": SyncPreset(
        name="gene-expression",
        description="Expression-oriented gene reports.",
        prefix="precomputed_files/genes/",
        includes=(
            r"curated_expression",
            r"high-throughput_gene_expression",
            r"gene_rpkm_report",
            r"FlyCellAtlas_slimmed_gene_expression",
            r"scRNA",
        ),
    ),
    "references": SyncPreset(
        name="references",
        description="Publication and cross-reference tables.",
        prefix="precomputed_files/references/",
        includes=(
            r"fbrf_pmid_pmcid_doi",
            r"entity_publication",
            r"representative_publications",
        ),
    ),
}
