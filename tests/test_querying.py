from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from flybase_cli.core import ensure_registry, open_db
from flybase_cli.querying import execute_sql, run_query_template
from flybase_cli.schema import build_query_plan


def register_table(conn, source_path: str, table_name: str, row_count: int) -> None:
    conn.execute(
        """
        INSERT INTO fb_ingest_registry (source_path, table_name, row_count)
        VALUES (?, ?, ?)
        """,
        (source_path, table_name, row_count),
    )


class FlybaseQueryingTests(unittest.TestCase):
    def test_execute_sql_shapes_records(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "flybase.sqlite"
            conn = open_db(db_path)
            try:
                conn.execute('CREATE TABLE "fb_example" ("record_id" TEXT, "symbol" TEXT)')
                conn.execute('INSERT INTO "fb_example" VALUES ("FBgn1", "gene1"), ("FBgn2", "gene2")')
                conn.commit()
            finally:
                conn.close()

            payload = execute_sql(
                db_path,
                'SELECT * FROM "fb_example" ORDER BY "record_id"',
                limit=1,
            )
            self.assertEqual(payload["columns"], ["record_id", "symbol"])
            self.assertEqual(payload["records"][0]["record_id"], "FBgn1")
            self.assertTrue(payload["summary"]["truncated"])
            self.assertIn("record_id", payload["summary"]["identifier_columns"])

    def test_query_plan_emits_named_biological_templates(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "flybase.sqlite"
            conn = open_db(db_path)
            try:
                ensure_registry(conn)
                conn.execute(
                    """
                    CREATE TABLE fb_best_gene_summary (
                        fbgn_id TEXT,
                        gene_symbol TEXT,
                        summary TEXT
                    )
                    """
                )
                conn.execute(
                    """
                    INSERT INTO fb_best_gene_summary VALUES
                    ('FBgn1', 'amx', 'important gene')
                    """
                )
                register_table(conn, "/tmp/best_gene_summary.tsv.gz", "fb_best_gene_summary", 1)
                conn.commit()
            finally:
                conn.close()

            plan = build_query_plan(db_path, sample_values=1, limit=5)
            named = [query for query in plan["queries"] if query["kind"] == "named"]
            names = {query["name"] for query in named}
            self.assertIn("gene-summary-by-fbgn", names)
            self.assertIn("gene-summary-by-symbol", names)

    def test_run_query_template_executes_named_template(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "flybase.sqlite"
            conn = open_db(db_path)
            try:
                ensure_registry(conn)
                conn.execute(
                    """
                    CREATE TABLE fb_best_gene_summary (
                        fbgn_id TEXT,
                        gene_symbol TEXT,
                        summary TEXT
                    )
                    """
                )
                conn.execute(
                    """
                    INSERT INTO fb_best_gene_summary VALUES
                    ('FBgn1', 'amx', 'important gene')
                    """
                )
                register_table(conn, "/tmp/best_gene_summary.tsv.gz", "fb_best_gene_summary", 1)
                conn.commit()
            finally:
                conn.close()

            payload = run_query_template(
                db_path,
                template_name="gene-summary-by-fbgn",
                params={"fbgn_id": "FBgn1"},
                sample_values=1,
                plan_limit=5,
                result_limit=2,
            )
            self.assertEqual(payload["selected_query"]["name"], "gene-summary-by-fbgn")
            self.assertEqual(payload["result"]["records"][0]["summary"], "important gene")


if __name__ == "__main__":
    unittest.main()
