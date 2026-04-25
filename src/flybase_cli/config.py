from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


BASE_RELEASES = "https://s3ftp.flybase.org/releases/"
BASE_API = "https://api.flybase.org/api/v1.0/"
DEFAULT_RELEASE = "current"
DEFAULT_ROOT = Path("data/flybase")
DEFAULT_DB = DEFAULT_ROOT / "flybase.sqlite"
DEFAULT_MANIFEST = DEFAULT_ROOT / "manifest.json"
DEFAULT_POSTGRES_DIR = DEFAULT_ROOT / "postgres"
BATCH_SIZE = 1000
DELIMITED_SUFFIXES = (".tsv", ".csv", ".tsv.gz", ".csv.gz")
FASTA_SUFFIXES = (
    ".fasta",
    ".fa",
    ".fna",
    ".faa",
    ".fasta.gz",
    ".fa.gz",
    ".fna.gz",
    ".faa.gz",
)
GFF_SUFFIXES = (".gff", ".gff3", ".gff.gz", ".gff3.gz")
GTF_SUFFIXES = (".gtf", ".gtf.gz")
JSON_SUFFIXES = (".json", ".json.gz")
INGEST_SUFFIXES = DELIMITED_SUFFIXES + FASTA_SUFFIXES + GFF_SUFFIXES + GTF_SUFFIXES + JSON_SUFFIXES
SEARCH_ID_CANDIDATES = (
    "fbgn_id",
    "primary_fbgn",
    "flybase_fbgn",
    "gene_primary_id",
    "annotation_id",
    "gene_symbol",
    "flybase_fbtr",
    "flybase_fbpp",
)
JSON_ID_CANDIDATES = (
    "primaryId",
    "primary_id",
    "id",
    "fbid",
    "fbgn_id",
    "gene_symbol",
    "symbol",
    "name",
)
JSON_MAX_INFERRED_COLUMNS = 24
GENOME_SECTIONS = ("fasta", "gff", "gtf", "dna", "chado-xml")
GENOME_ASSET_PATTERNS = {
    "mirna": r"miRNA",
    "transcript": r"transcript",
    "translation": r"translation",
    "gene": r"all-gene-",
    "gene-extended": r"gene_extended2000",
    "chromosome": r"chromosome",
    "cds": r"CDS",
    "ncrna": r"ncRNA",
    "gff": r"\.gff(\.gz)?$",
    "gtf": r"\.gtf(\.gz)?$",
}


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
