from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import flybase_cli.syncing as syncing
from flybase_cli.config import ManifestSelection, SyncPreset
from flybase_cli.syncing import (
    build_preset_release_diff,
    diff_manifests,
    full_manifest,
    incremental_manifest,
    stable_manifest_key,
    sync_full_release,
    sync_incremental_preset,
)


class FlybaseSyncingTests(unittest.TestCase):
    def test_stable_manifest_key_normalizes_release_tokens(self) -> None:
        self.assertEqual(
            stable_manifest_key("precomputed_files/genes/best_gene_summary_fb_2026_01.tsv.gz"),
            "precomputed_files/genes/best_gene_summary_fb_release.tsv.gz",
        )

    def test_diff_manifests_detects_release_renames_as_updates(self) -> None:
        previous = [
            {
                "path": "precomputed_files/genes/best_gene_summary_fb_2025_06.tsv.gz",
                "url": "https://example.test/best_gene_summary_fb_2025_06.tsv.gz",
            }
        ]
        current = [
            {
                "path": "precomputed_files/genes/best_gene_summary_fb_2026_01.tsv.gz",
                "url": "https://example.test/best_gene_summary_fb_2026_01.tsv.gz",
            }
        ]
        diff = diff_manifests(previous, current)
        self.assertEqual(diff["updated_count"], 1)
        self.assertEqual(diff["added_count"], 0)
        self.assertEqual(diff["removed_count"], 0)
        self.assertEqual(incremental_manifest(diff), current)

    def test_build_preset_release_diff_uses_all_selections(self) -> None:
        preset = SyncPreset(
            name="gene-knowledge",
            description="multi-prefix",
            selections=(
                ManifestSelection(prefix="precomputed_files/genes/", includes=(r"best_gene_summary",)),
                ManifestSelection(prefix="precomputed_files/references/", includes=(r"entity_publication",)),
            ),
        )
        original = syncing.preset_manifest
        try:
            syncing.preset_manifest = lambda chosen, release: (
                [{"path": f"precomputed_files/genes/best_gene_summary_{release}.tsv.gz", "url": f"https://example.test/{release}/gene.tsv.gz"}]
                if release == "FB2025_06"
                else [
                    {"path": f"precomputed_files/genes/best_gene_summary_{release}.tsv.gz", "url": f"https://example.test/{release}/gene.tsv.gz"},
                    {"path": f"precomputed_files/references/entity_publication_{release}.tsv.gz", "url": f"https://example.test/{release}/refs.tsv.gz"},
                ]
            )
            diff = build_preset_release_diff(
                preset=preset,
                from_release="FB2025_06",
                to_release="FB2026_01",
            )
            self.assertEqual(diff["added_count"], 1)
            self.assertEqual(diff["updated_count"], 1)
            self.assertEqual(diff["prefixes"], list(preset.prefixes))
        finally:
            syncing.preset_manifest = original

    def test_full_manifest_defaults_to_ingestable_entries(self) -> None:
        original = syncing.build_manifest
        try:
            syncing.build_manifest = lambda prefix, release: [
                {"path": "precomputed_files/genes/a.tsv.gz", "url": "https://example.test/a.tsv.gz"},
                {"path": "precomputed_files/genes/b.json.gz", "url": "https://example.test/b.json.gz"},
                {"path": "precomputed_files/genes/c.zip", "url": "https://example.test/c.zip"},
            ]
            manifest = full_manifest(release="FB2026_01")
            self.assertEqual(
                [item["path"] for item in manifest],
                [
                    "precomputed_files/genes/a.tsv.gz",
                    "precomputed_files/genes/b.json.gz",
                ],
            )
            full = full_manifest(release="FB2026_01", ingestable_only=False)
            self.assertEqual(len(full), 3)
        finally:
            syncing.build_manifest = original

    def test_sync_incremental_preset_downloads_only_selected_files(self) -> None:
        preset = SyncPreset(
            name="mini",
            description="fixture",
            selections=(ManifestSelection(prefix="precomputed_files/genes/", includes=(r"mini",)),),
        )
        original = syncing.preset_manifest
        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                tmp = Path(tmpdir)
                source = tmp / "mini_fb_2026_01.tsv"
                source.write_text("#id\tvalue\na\tb\n", encoding="utf-8")
                previous_manifest = [
                    {
                        "path": "precomputed_files/genes/mini_fb_2025_06.tsv",
                        "url": source.as_uri(),
                    }
                ]
                current_manifest = [
                    {
                        "path": "precomputed_files/genes/mini_fb_2026_01.tsv",
                        "url": source.as_uri(),
                    }
                ]
                syncing.preset_manifest = lambda chosen, release: (
                    previous_manifest if release == "FB2025_06" else current_manifest
                )
                summary = sync_incremental_preset(
                    preset=preset,
                    root=tmp / "root",
                    db_path=tmp / "flybase.sqlite",
                    manifest_path=tmp / "manifest.json",
                    diff_path=tmp / "diff.json",
                    from_release="FB2025_06",
                    to_release="FB2026_01",
                )
                self.assertEqual(summary["incremental_file_count"], 1)
                self.assertEqual(summary["updated_count"], 1)
                self.assertEqual(summary["ingested_tables"][0]["row_count"], 1)
                self.assertTrue((tmp / "diff.json").exists())
        finally:
            syncing.preset_manifest = original

    def test_sync_full_release_ingests_filtered_manifest(self) -> None:
        original = syncing.build_manifest
        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                tmp = Path(tmpdir)
                source = tmp / "mini.tsv"
                source.write_text("#id\tvalue\na\tb\n", encoding="utf-8")
                syncing.build_manifest = lambda prefix, release: [
                    {"path": "precomputed_files/genes/mini.tsv", "url": source.as_uri()},
                    {"path": "precomputed_files/genes/skip.zip", "url": "https://example.test/skip.zip"},
                ]
                summary = sync_full_release(
                    root=tmp / "root",
                    db_path=tmp / "flybase.sqlite",
                    manifest_path=tmp / "manifest.json",
                    release="FB2026_01",
                )
                self.assertEqual(summary["mode"], "full-sync")
                self.assertEqual(summary["file_count"], 1)
                self.assertEqual(summary["ingested_tables"][0]["row_count"], 1)
        finally:
            syncing.build_manifest = original


if __name__ == "__main__":
    unittest.main()
