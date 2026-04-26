from __future__ import annotations

import re
from pathlib import Path

from .config import SyncPreset
from .core import build_manifest, filter_manifest, sync_manifest, write_json


RELEASE_TOKEN_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"FB\d{4}_\d{2}", flags=re.IGNORECASE), "FBRELEASE"),
    (re.compile(r"fb_\d{4}_\d{2}", flags=re.IGNORECASE), "fb_release"),
)


def stable_manifest_key(path: str) -> str:
    stable = path
    for pattern, replacement in RELEASE_TOKEN_PATTERNS:
        stable = pattern.sub(replacement, stable)
    return stable.lower()


def prefer_manifest_entry(entries: list[dict[str, str]]) -> dict[str, str]:
    return sorted(entries, key=lambda item: item["path"])[0]


def group_manifest_by_stable_key(
    manifest: list[dict[str, str]],
) -> dict[str, list[dict[str, str]]]:
    grouped: dict[str, list[dict[str, str]]] = {}
    for item in manifest:
        grouped.setdefault(stable_manifest_key(item["path"]), []).append(item)
    return grouped


def merge_manifests(manifests: list[list[dict[str, str]]]) -> list[dict[str, str]]:
    merged: dict[str, dict[str, str]] = {}
    for manifest in manifests:
        for item in manifest:
            merged[item["path"]] = item
    return sorted(merged.values(), key=lambda item: item["path"])


def preset_manifest(preset: SyncPreset, release: str) -> list[dict[str, str]]:
    manifests: list[list[dict[str, str]]] = []
    for selection in preset.selections:
        manifests.append(
            filter_manifest(
                build_manifest(selection.prefix, release=release),
                selection.includes,
                selection.excludes,
            )
        )
    return merge_manifests(manifests)


def diff_manifests(
    previous_manifest: list[dict[str, str]],
    current_manifest: list[dict[str, str]],
) -> dict[str, object]:
    previous_by_key = group_manifest_by_stable_key(previous_manifest)
    current_by_key = group_manifest_by_stable_key(current_manifest)
    keys = sorted(set(previous_by_key) | set(current_by_key))

    added: list[dict[str, object]] = []
    removed: list[dict[str, object]] = []
    updated: list[dict[str, object]] = []
    unchanged: list[dict[str, object]] = []

    for key in keys:
        previous_entries = previous_by_key.get(key, [])
        current_entries = current_by_key.get(key, [])
        if not previous_entries:
            added.extend({"stable_key": key, "to": item} for item in current_entries)
            continue
        if not current_entries:
            removed.extend({"stable_key": key, "from": item} for item in previous_entries)
            continue

        previous_entry = prefer_manifest_entry(previous_entries)
        current_entry = prefer_manifest_entry(current_entries)
        if previous_entry["path"] == current_entry["path"] and previous_entry["url"] == current_entry["url"]:
            unchanged.append({"stable_key": key, "item": current_entry})
            continue
        updated.append(
            {
                "stable_key": key,
                "from": previous_entry,
                "to": current_entry,
            }
        )

    return {
        "added": added,
        "removed": removed,
        "updated": updated,
        "unchanged": unchanged,
        "added_count": len(added),
        "removed_count": len(removed),
        "updated_count": len(updated),
        "unchanged_count": len(unchanged),
    }


def build_release_diff(
    *,
    prefix: str,
    from_release: str,
    to_release: str,
    include: list[str] | tuple[str, ...] = (),
    exclude: list[str] | tuple[str, ...] = (),
) -> dict[str, object]:
    previous_manifest = filter_manifest(
        build_manifest(prefix, release=from_release),
        include,
        exclude,
    )
    current_manifest = filter_manifest(
        build_manifest(prefix, release=to_release),
        include,
        exclude,
    )
    return {
        "prefix": prefix,
        "from_release": from_release,
        "to_release": to_release,
        "previous_manifest_count": len(previous_manifest),
        "current_manifest_count": len(current_manifest),
        **diff_manifests(previous_manifest, current_manifest),
    }


def build_preset_release_diff(
    *,
    preset: SyncPreset,
    from_release: str,
    to_release: str,
) -> dict[str, object]:
    previous_manifest = preset_manifest(preset, release=from_release)
    current_manifest = preset_manifest(preset, release=to_release)
    return {
        "preset": preset.name,
        "description": preset.description,
        "prefixes": list(preset.prefixes),
        "from_release": from_release,
        "to_release": to_release,
        "previous_manifest_count": len(previous_manifest),
        "current_manifest_count": len(current_manifest),
        **diff_manifests(previous_manifest, current_manifest),
    }


def incremental_manifest(diff: dict[str, object]) -> list[dict[str, str]]:
    selected = [item["to"] for item in diff["added"]]
    selected.extend(item["to"] for item in diff["updated"])
    return sorted(selected, key=lambda item: item["path"])


def sync_incremental_preset(
    *,
    preset: SyncPreset,
    root: Path,
    db_path: Path,
    manifest_path: Path,
    diff_path: Path | None,
    from_release: str,
    to_release: str,
    force: bool = False,
    no_header: bool = False,
) -> dict[str, object]:
    previous_manifest = preset_manifest(preset, release=from_release)
    current_manifest = preset_manifest(preset, release=to_release)
    diff = diff_manifests(previous_manifest, current_manifest)
    selected_manifest = incremental_manifest(diff)
    if diff_path is not None:
        write_json(diff_path, diff)
    summary = sync_manifest(
        selected_manifest,
        root=root,
        db_path=db_path,
        manifest_path=manifest_path,
        force=force,
        no_header=no_header,
    )
    return {
        "preset": preset.name,
        "description": preset.description,
        "from_release": from_release,
        "to_release": to_release,
        "incremental_file_count": len(selected_manifest),
        "diff_path": str(diff_path) if diff_path is not None else None,
        **diff,
        **summary,
    }
