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
class ManifestSelection:
    prefix: str
    includes: tuple[str, ...]
    excludes: tuple[str, ...] = ()


@dataclass(frozen=True)
class SyncPreset:
    name: str
    description: str
    selections: tuple[ManifestSelection, ...]

    @property
    def prefixes(self) -> tuple[str, ...]:
        return tuple(selection.prefix for selection in self.selections)

    @property
    def includes(self) -> tuple[str, ...]:
        return tuple(
            pattern
            for selection in self.selections
            for pattern in selection.includes
        )

    @property
    def excludes(self) -> tuple[str, ...]:
        return tuple(
            pattern
            for selection in self.selections
            for pattern in selection.excludes
        )


@dataclass(frozen=True)
class GenomeSyncPreset:
    name: str
    description: str
    section: str
    asset: str | None = None
    includes: tuple[str, ...] = ()
    excludes: tuple[str, ...] = ()


SYNC_PRESETS: dict[str, SyncPreset] = {
    "gene-core": SyncPreset(
        name="gene-core",
        description="Gene summaries plus core identifier/link tables.",
        selections=(
            ManifestSelection(
                prefix="precomputed_files/genes/",
                includes=(
                    r"best_gene_summary",
                    r"fbgn_fbtr_fbpp_fb_",
                    r"fbgn_annotation_ID",
                    r"dmel_gene_sequence_ontology_annotations",
                ),
            ),
        ),
    ),
    "gene-expression": SyncPreset(
        name="gene-expression",
        description="Expression-oriented gene reports.",
        selections=(
            ManifestSelection(
                prefix="precomputed_files/genes/",
                includes=(
                    r"curated_expression",
                    r"high-throughput_gene_expression",
                    r"gene_rpkm_report",
                    r"FlyCellAtlas_slimmed_gene_expression",
                    r"scRNA",
                ),
            ),
        ),
    ),
    "references": SyncPreset(
        name="references",
        description="Publication and cross-reference tables.",
        selections=(
            ManifestSelection(
                prefix="precomputed_files/references/",
                includes=(
                    r"fbrf_pmid_pmcid_doi",
                    r"entity_publication",
                    r"representative_publications",
                ),
            ),
        ),
    ),
    "gene-knowledge": SyncPreset(
        name="gene-knowledge",
        description="Core gene facts plus representative publications and orthology tables.",
        selections=(
            ManifestSelection(
                prefix="precomputed_files/genes/",
                includes=(
                    r"best_gene_summary",
                    r"fbgn_fbtr_fbpp_fb_",
                    r"fbgn_annotation_ID",
                    r"dmel_gene_sequence_ontology_annotations",
                ),
            ),
            ManifestSelection(
                prefix="precomputed_files/references/",
                includes=(
                    r"entity_publication",
                    r"representative_publications",
                ),
            ),
            ManifestSelection(
                prefix="precomputed_files/orthologs/",
                includes=(
                    r"orthologs",
                    r"paralogs",
                    r"disease",
                ),
            ),
        ),
    ),
    "orthology": SyncPreset(
        name="orthology",
        description="Ortholog, paralog, and disease-association support tables.",
        selections=(
            ManifestSelection(
                prefix="precomputed_files/orthologs/",
                includes=(
                    r"orthologs",
                    r"paralogs",
                    r"disease",
                ),
            ),
        ),
    ),
    "interactions": SyncPreset(
        name="interactions",
        description="Gene- and allele-level interaction tables.",
        selections=(
            ManifestSelection(
                prefix="precomputed_files/genes/",
                includes=(r"gene_genetic_interactions",),
            ),
            ManifestSelection(
                prefix="precomputed_files/alleles/",
                includes=(r"allele_genetic_interactions",),
            ),
        ),
    ),
}


GENOME_SYNC_PRESETS: dict[str, GenomeSyncPreset] = {
    "mirna-fasta": GenomeSyncPreset(
        name="mirna-fasta",
        description="miRNA FASTA sequences for a genome build.",
        section="fasta",
        asset="mirna",
    ),
    "transcript-fasta": GenomeSyncPreset(
        name="transcript-fasta",
        description="Transcript FASTA sequences for a genome build.",
        section="fasta",
        asset="transcript",
    ),
    "translation-fasta": GenomeSyncPreset(
        name="translation-fasta",
        description="Protein translation FASTA sequences for a genome build.",
        section="fasta",
        asset="translation",
    ),
    "gene-fasta": GenomeSyncPreset(
        name="gene-fasta",
        description="Gene FASTA sequences for a genome build.",
        section="fasta",
        asset="gene",
    ),
    "chromosome-fasta": GenomeSyncPreset(
        name="chromosome-fasta",
        description="Chromosome FASTA sequences for a genome build.",
        section="fasta",
        asset="chromosome",
    ),
    "ncrna-fasta": GenomeSyncPreset(
        name="ncrna-fasta",
        description="ncRNA FASTA sequences for a genome build.",
        section="fasta",
        asset="ncrna",
    ),
    "gff-all": GenomeSyncPreset(
        name="gff-all",
        description="Primary GFF annotation file for a genome build.",
        section="gff",
        asset="gff",
    ),
    "gtf-all": GenomeSyncPreset(
        name="gtf-all",
        description="Primary GTF annotation file for a genome build.",
        section="gtf",
        asset="gtf",
    ),
}
