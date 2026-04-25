from __future__ import annotations

import gzip
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from flybase_cli.config import SYNC_PRESETS
from flybase_cli.core import (
    ingest_delimited,
    normalize_bucket_href,
    open_db,
    rebuild_search_index,
    release_base_url,
    sanitize_columns,
    search_index,
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
                        source_path TEXT PRIMARY KEY,
                        table_name TEXT NOT NULL,
                        row_count INTEGER NOT NULL
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


if __name__ == "__main__":
    unittest.main()
