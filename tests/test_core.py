from __future__ import annotations

import gzip
import json
import sqlite3
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from flybase_cli.config import GENOME_SYNC_PRESETS, SYNC_PRESETS
from flybase_cli.core import (
    extract_genomes,
    build_manifest_from_url,
    find_genome,
    genome_asset_pattern,
    genome_section_url,
    list_genomes,
    list_tables,
    normalize_bucket_href,
    open_db,
    path_from_root_url,
    rebuild_search_index,
    release_base_url,
    search_index,
    sync_manifest,
)
from flybase_cli.loaders import (
    flatten_json_record,
    ingest_delimited,
    ingest_fasta,
    ingest_feature_file,
    ingest_json,
    sanitize_columns,
)


class FlybaseCoreTests(unittest.TestCase):
    def test_normalize_bucket_href(self) -> None:
        self.assertEqual(
            normalize_bucket_href("/releases/current/precomputed_files/genes/foo.tsv.gz", "current"),
            "precomputed_files/genes/foo.tsv.gz",
        )

    def test_release_base_url(self) -> None:
        self.assertEqual(
            release_base_url("FB2026_01"),
            "https://s3ftp.flybase.org/releases/FB2026_01/",
        )

    def test_path_from_root_url(self) -> None:
        self.assertEqual(
            path_from_root_url(
                "https://s3ftp.flybase.org/genomes/Drosophila_melanogaster/dmel_r6.67_FB2026_01/fasta/",
                "https://s3ftp.flybase.org/genomes/Drosophila_melanogaster/dmel_r6.67_FB2026_01/fasta/dmel-all-miRNA-r6.67.fasta.gz",
            ),
            "dmel-all-miRNA-r6.67.fasta.gz",
        )

    def test_extract_genomes(self) -> None:
        genomes = extract_genomes(
            [
                {"href": "/genomes/Drosophila_melanogaster/dmel_r6.67_FB2026_01", "text": "dmel_r6.67"},
                {"href": "/releases/FB2026_01/precomputed_files/index.html", "text": "precomputed_files"},
            ]
        )
        self.assertEqual(
            genomes,
            [
                {
                    "label": "dmel_r6.67",
                    "species": "Drosophila_melanogaster",
                    "genome_build": "dmel_r6.67_FB2026_01",
                    "url": "https://s3ftp.flybase.org/genomes/Drosophila_melanogaster/dmel_r6.67_FB2026_01",
                }
            ],
        )

    def test_genome_section_url(self) -> None:
        self.assertEqual(
            genome_section_url(
                "https://s3ftp.flybase.org/genomes/Drosophila_melanogaster/dmel_r6.67_FB2026_01",
                "fasta",
            ),
            "https://s3ftp.flybase.org/genomes/Drosophila_melanogaster/dmel_r6.67_FB2026_01/fasta/",
        )

    def test_genome_asset_pattern(self) -> None:
        self.assertEqual(genome_asset_pattern("mirna"), ["miRNA"])

    def test_genome_sync_presets_shape(self) -> None:
        self.assertIn("mirna-fasta", GENOME_SYNC_PRESETS)
        self.assertEqual(GENOME_SYNC_PRESETS["mirna-fasta"].section, "fasta")

    def test_find_genome_exact_match(self) -> None:
        original = list_genomes
        try:
            import flybase_cli.core as core

            core.list_genomes = lambda release: [
                {
                    "label": "dmel_r6.67",
                    "species": "Drosophila_melanogaster",
                    "genome_build": "dmel_r6.67_FB2026_01",
                    "url": "https://example.test/dmel",
                }
            ]
            match = find_genome(release="FB2026_01", genome="dmel_r6.67")
            self.assertEqual(match["genome_build"], "dmel_r6.67_FB2026_01")
        finally:
            core.list_genomes = original

    def test_find_genome_ambiguous_match(self) -> None:
        original = list_genomes
        try:
            import flybase_cli.core as core

            core.list_genomes = lambda release: [
                {"label": "dmel_r6.67", "species": "dmel", "genome_build": "a", "url": "https://example.test/a"},
                {"label": "dmel_r6.68", "species": "dmel", "genome_build": "b", "url": "https://example.test/b"},
            ]
            with self.assertRaisesRegex(ValueError, "multiple genomes matched"):
                find_genome(release="FB2026_01", species="dmel")
        finally:
            core.list_genomes = original

    def test_sanitize_columns(self) -> None:
        self.assertEqual(
            sanitize_columns(["#FBgn ID", "Gene Symbol", "Gene Symbol", ""]),
            ["fbgn_id", "gene_symbol", "gene_symbol_2", "col_4"],
        )

    def test_ingest_skips_comment_preamble(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            source = tmp / "best_gene_summary.tsv.gz"
            source.write_bytes(
                gzip.compress(
                    (
                        "## report\n"
                        "## generated\n"
                        "#FBgn_ID\tGene_Symbol\tSummary_Source\tSummary\n"
                        "FBgn1\tgene1\tFlyBase\ttext one\n"
                        "FBgn2\tgene2\tAlliance\ttext two\n"
                    ).encode("utf-8")
                )
            )
            conn = sqlite3.connect(":memory:")
            try:
                row_count = ingest_delimited(conn, source, "fb_best_gene_summary")
                self.assertEqual(row_count, 2)
                rows = conn.execute(
                    "select fbgn_id, gene_symbol, summary_source from fb_best_gene_summary order by fbgn_id"
                ).fetchall()
                self.assertEqual(
                    rows,
                    [("FBgn1", "gene1", "FlyBase"), ("FBgn2", "gene2", "Alliance")],
                )
            finally:
                conn.close()

    def test_ingest_fasta(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            source = tmp / "mirna.fasta.gz"
            source.write_bytes(
                gzip.compress(
                    (
                        ">FBtr1 first record\n"
                        "ACGT\n"
                        "TTAA\n"
                        ">FBtr2\n"
                        "GGCC\n"
                    ).encode("utf-8")
                )
            )
            conn = sqlite3.connect(":memory:")
            try:
                row_count = ingest_fasta(conn, source, "fb_mirna")
                self.assertEqual(row_count, 2)
                rows = conn.execute(
                    "select record_id, description, sequence, sequence_length from fb_mirna order by record_id"
                ).fetchall()
                self.assertEqual(
                    rows,
                    [("FBtr1", "first record", "ACGTTTAA", "8"), ("FBtr2", "", "GGCC", "4")],
                )
            finally:
                conn.close()

    def test_ingest_feature_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            source = tmp / "mini.gff"
            source.write_text(
                "##gff-version 3\n"
                "2L\tFlyBase\tgene\t7529\t9484\t.\t+\t.\tID=FBgn0002121;Name=amx\n"
                "2L\tFlyBase\tmRNA\t7529\t9484\t.\t+\t.\tID=FBtr1;Parent=FBgn0002121;Name=amx-RA\n",
                encoding="utf-8",
            )
            conn = sqlite3.connect(":memory:")
            try:
                row_count = ingest_feature_file(conn, source, "fb_gff")
                self.assertEqual(row_count, 2)
                rows = conn.execute(
                    "select feature_type, feature_id, parent_id, feature_name from fb_gff order by feature_type"
                ).fetchall()
                self.assertEqual(
                    rows,
                    [("gene", "FBgn0002121", "", "amx"), ("mRNA", "FBtr1", "FBgn0002121", "amx-RA")],
                )
            finally:
                conn.close()

    def test_ingest_feature_file_from_tar_gz(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            inner = tmp / "mini.gff"
            archive_path = tmp / "mini.gff.gz"
            inner.write_text(
                "##gff-version 3\n"
                "2L\tFlyBase\tgene\t7529\t9484\t.\t+\t.\tID=FBgn0002121;Name=amx\n",
                encoding="utf-8",
            )
            with tarfile.open(archive_path, "w:gz") as archive:
                archive.add(inner, arcname="mini.gff")
            conn = sqlite3.connect(":memory:")
            try:
                row_count = ingest_feature_file(conn, archive_path, "fb_gff_archive")
                self.assertEqual(row_count, 1)
                row = conn.execute(
                    "select feature_type, feature_id, feature_name from fb_gff_archive"
                ).fetchone()
                self.assertEqual(row, ("gene", "FBgn0002121", "amx"))
            finally:
                conn.close()

    def test_ingest_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            source = tmp / "genes.json.gz"
            source.write_bytes(
                gzip.compress(
                    json.dumps(
                        [
                            {"primaryId": "FBgn1", "symbol": "gene1"},
                            {"primaryId": "FBgn2", "symbol": "gene2"},
                        ]
                    ).encode("utf-8")
                )
            )
            conn = sqlite3.connect(":memory:")
            try:
                tables = ingest_json(conn, source, "fb_json")
                self.assertEqual(tables[0], ("fb_json", 2))
                rows = conn.execute("select record_id, symbol from fb_json order by record_id").fetchall()
                self.assertEqual(rows, [("FBgn1", "gene1"), ("FBgn2", "gene2")])
            finally:
                conn.close()

    def test_ingest_json_list_children(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            source = tmp / "genes.json.gz"
            source.write_bytes(
                gzip.compress(
                    json.dumps(
                        [
                            {
                                "primaryId": "FBgn1",
                                "symbol": "gene1",
                                "symbolSynonyms": ["g1", "gene-one"],
                                "gene": {"geneId": "FBgnParent1", "symbol": "parent1"},
                                "genomeLocations": [{"assembly": "R6", "chromosome": "2L"}],
                            }
                        ]
                    ).encode("utf-8")
                )
            )
            conn = sqlite3.connect(":memory:")
            try:
                tables = ingest_json(conn, source, "fb_json")
                self.assertEqual(
                    tables,
                    [
                        ("fb_json", 1),
                        ("fb_json_symbolsynonyms", 2),
                        ("fb_json_genomelocations", 1),
                    ],
                )
                synonyms = conn.execute(
                    "select parent_record_id, ordinal, value from fb_json_symbolsynonyms order by ordinal"
                ).fetchall()
                self.assertEqual(synonyms, [("FBgn1", "1", "g1"), ("FBgn1", "2", "gene-one")])
                locations = conn.execute(
                    "select parent_record_id, assembly, chromosome from fb_json_genomelocations"
                ).fetchall()
                self.assertEqual(locations, [("FBgn1", "R6", "2L")])
            finally:
                conn.close()

    def test_flatten_json_record(self) -> None:
        flattened = flatten_json_record(
            {
                "primaryId": "FBgn1",
                "gene": {"geneId": "FBgn2", "symbol": "gene2"},
                "publications": ["PMID:1"],
            }
        )
        self.assertEqual(flattened["primaryId"], "FBgn1")
        self.assertEqual(flattened["gene_geneId"], "FBgn2")
        self.assertNotIn("publications", flattened)

    def test_ingest_no_header(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            source = tmp / "headerless.tsv"
            source.write_text("a\tb\nc\td\n", encoding="utf-8")
            conn = sqlite3.connect(":memory:")
            try:
                row_count = ingest_delimited(conn, source, "fb_headerless", no_header=True)
                self.assertEqual(row_count, 2)
                rows = conn.execute("select col_1, col_2 from fb_headerless order by col_1").fetchall()
                self.assertEqual(rows, [("a", "b"), ("c", "d")])
            finally:
                conn.close()

    def test_sync_presets_shape(self) -> None:
        self.assertIn("gene-core", SYNC_PRESETS)
        self.assertTrue(SYNC_PRESETS["gene-core"].includes)

    def test_build_manifest_from_url_rejects_outside_root(self) -> None:
        self.assertEqual(
            path_from_root_url(
                "https://s3ftp.flybase.org/releases/FB2026_01/precomputed_files/genes/",
                "https://example.com/other/file.tsv.gz",
            ),
            "",
        )

    def test_search_index(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "flybase.sqlite"
            conn = open_db(db_path)
            try:
                conn.execute(
                    """
                    CREATE TABLE fb_best_gene_summary_fb_2026_01 (
                        fbgn_id TEXT,
                        gene_symbol TEXT,
                        summary TEXT
                    )
                    """
                )
                conn.execute(
                    """
                    CREATE TABLE fb_ingest_registry (
                        source_path TEXT NOT NULL,
                        table_name TEXT NOT NULL,
                        row_count INTEGER NOT NULL,
                        PRIMARY KEY (source_path, table_name)
                    )
                    """
                )
                conn.execute(
                    """
                    INSERT INTO fb_best_gene_summary_fb_2026_01 VALUES
                    ('FBgn1', 'Nep3', 'memory formation protein'),
                    ('FBgn2', 'Or19b', 'odorant receptor')
                    """
                )
                conn.execute(
                    """
                    INSERT INTO fb_ingest_registry VALUES
                    ('/tmp/a.tsv.gz', 'fb_best_gene_summary_fb_2026_01', 2)
                    """
                )
                conn.commit()
            finally:
                conn.close()

            indexed = rebuild_search_index(db_path)
            self.assertEqual(indexed[0]["row_count"], 2)
            results = search_index(db_path, "memory")
            self.assertEqual(results[0]["record_id"], "FBgn1")

    def test_sync_manifest_writes_manifest_and_ingests(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            source = tmp / "mini.tsv"
            source.write_text("#id\tvalue\na\tb\n", encoding="utf-8")
            manifest = [{"path": "mini.tsv", "url": source.as_uri()}]
            summary = sync_manifest(
                manifest,
                root=tmp / "root",
                db_path=tmp / "db.sqlite",
                manifest_path=tmp / "manifest.json",
            )
            self.assertEqual(summary["file_count"], 1)
            self.assertTrue((tmp / "manifest.json").exists())
            self.assertEqual(summary["ingested_tables"][0]["row_count"], 1)

    def test_registry_migrates_single_table_key(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "flybase.sqlite"
            conn = open_db(db_path)
            try:
                conn.execute(
                    """
                    CREATE TABLE fb_ingest_registry (
                        source_path TEXT PRIMARY KEY,
                        table_name TEXT NOT NULL,
                        row_count INTEGER NOT NULL
                    )
                    """
                )
                conn.execute(
                    """
                    INSERT INTO fb_ingest_registry VALUES
                    ('/tmp/source.json.gz', 'fb_json', 1)
                    """
                )
                conn.commit()
            finally:
                conn.close()

            summary = list_tables(db_path)
            self.assertEqual(summary[0]["table_name"], "fb_json")

            conn = open_db(db_path)
            try:
                pk_map = {
                    row[1]: row[5]
                    for row in conn.execute("PRAGMA table_info(fb_ingest_registry)").fetchall()
                }
                self.assertEqual(pk_map["source_path"], 1)
                self.assertEqual(pk_map["table_name"], 2)
            finally:
                conn.close()


if __name__ == "__main__":
    unittest.main()
