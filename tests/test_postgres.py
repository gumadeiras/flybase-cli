from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from flybase_cli.postgres import (
    build_pg_load_plan,
    default_db_name,
    dump_url_for_release,
    render_pg_load_script,
    write_pg_load_script,
)


class FlybasePostgresTests(unittest.TestCase):
    def test_dump_url_for_release(self) -> None:
        self.assertEqual(
            dump_url_for_release("FB2026_01"),
            "https://s3ftp.flybase.org/releases/FB2026_01/psql/FB2026_01.sql.gz",
        )

    def test_default_db_name(self) -> None:
        self.assertEqual(default_db_name("FB2026_01"), "flybase_fb2026_01")

    def test_render_script(self) -> None:
        script = render_pg_load_script(
            dump_path=Path("/tmp/FB2026_01.sql.gz"),
            db_name="flybase_fb2026_01",
            drop_existing=True,
        )
        self.assertIn("dropdb --if-exists flybase_fb2026_01", script)
        self.assertIn("gzip -dc /tmp/FB2026_01.sql.gz | psql flybase_fb2026_01", script)

    def test_write_script(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = write_pg_load_script(
                release="FB2026_01",
                dump_path=Path("/tmp/FB2026_01.sql.gz"),
                db_name="flybase_fb2026_01",
                script_path=Path(tmpdir) / "load.sh",
                drop_existing=False,
            )
            self.assertTrue(path.exists())
            self.assertIn("createdb flybase_fb2026_01", path.read_text())

    def test_build_plan(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            plan = build_pg_load_plan(release="FB2026_01", root=Path(tmpdir))
            self.assertEqual(plan["db_name"], "flybase_fb2026_01")
            self.assertTrue(str(plan["dump_path"]).endswith("FB2026_01.sql.gz"))


if __name__ == "__main__":
    unittest.main()
