from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.parse
from pathlib import Path

from .config import BASE_API, DEFAULT_DB, DEFAULT_MANIFEST, DEFAULT_ROOT, SYNC_PRESETS
from .core import (
    build_manifest,
    fetch_bytes,
    filter_manifest,
    ingest_files,
    list_tables,
    load_manifest,
    run_query,
    sync_preset,
    write_json,
)


def print_json(payload: object) -> None:
    print(json.dumps(payload, indent=2))


def cmd_manifest(args: argparse.Namespace) -> int:
    manifest = build_manifest(args.prefix)
    filtered = filter_manifest(manifest, args.include, args.exclude)
    write_json(Path(args.output), filtered)
    print(f"{len(filtered)} files -> {args.output}")
    return 0


def cmd_download(args: argparse.Namespace) -> int:
    from .core import download_manifest_entries

    manifest = load_manifest(Path(args.manifest))
    selected = filter_manifest(manifest, args.include, args.exclude)
    local_paths = download_manifest_entries(selected, Path(args.root), force=args.force)
    for item, (local_path, downloaded) in zip(selected, local_paths, strict=True):
        status = "get " if downloaded else "skip"
        print(f"{status} {item['path']}")
    return 0


def cmd_ingest(args: argparse.Namespace) -> int:
    sources = [Path(item) for item in args.sources]
    results = ingest_files(Path(args.db), sources, no_header=args.no_header)
    for item in results:
        print(f"ingest {item['source_path']} -> {item['table_name']} ({item['row_count']} rows)")
    return 0


def cmd_sql(args: argparse.Namespace) -> int:
    result = run_query(Path(args.db), args.query)
    if result is None:
        print("ok")
        return 0
    columns, rows = result
    print_json({"columns": columns, "rows": rows[: args.limit]})
    return 0


def cmd_tables(args: argparse.Namespace) -> int:
    print_json(list_tables(Path(args.db), include_columns=args.columns))
    return 0


def cmd_presets(_: argparse.Namespace) -> int:
    payload = [
        {
            "name": preset.name,
            "description": preset.description,
            "prefix": preset.prefix,
            "includes": list(preset.includes),
        }
        for preset in SYNC_PRESETS.values()
    ]
    print_json(payload)
    return 0


def cmd_sync(args: argparse.Namespace) -> int:
    preset = SYNC_PRESETS[args.preset]
    root = Path(args.root)
    manifest_path = Path(args.manifest or root / "manifests" / f"{preset.name}.json")
    summary = sync_preset(
        preset=preset,
        root=root,
        db_path=Path(args.db),
        manifest_path=manifest_path,
        force=args.force,
    )
    print_json(summary)
    return 0


def cmd_api(args: argparse.Namespace) -> int:
    endpoint = args.endpoint.lstrip("/")
    url = urllib.parse.urljoin(BASE_API, endpoint)
    try:
        payload = fetch_bytes(url)
    except urllib.error.HTTPError as error:
        print(f"HTTP {error.code}: {error.reason}", file=sys.stderr)
        return 1
    if not payload:
        print_json({"url": url, "status": "empty-body"})
        return 0
    try:
        print_json(json.loads(payload.decode("utf-8")))
    except json.JSONDecodeError:
        print(payload.decode("utf-8", errors="replace"))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="FlyBase sync/query helper for agents.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    manifest_parser = subparsers.add_parser("manifest", help="scrape a file manifest")
    manifest_parser.add_argument("--prefix", default="precomputed_files/genes/")
    manifest_parser.add_argument("--include", action="append", default=[])
    manifest_parser.add_argument("--exclude", action="append", default=[])
    manifest_parser.add_argument("--output", default=str(DEFAULT_MANIFEST))
    manifest_parser.set_defaults(func=cmd_manifest)

    download_parser = subparsers.add_parser("download", help="download files from a manifest")
    download_parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST))
    download_parser.add_argument("--root", default=str(DEFAULT_ROOT))
    download_parser.add_argument("--include", action="append", default=[])
    download_parser.add_argument("--exclude", action="append", default=[])
    download_parser.add_argument("--force", action="store_true")
    download_parser.set_defaults(func=cmd_download)

    ingest_parser = subparsers.add_parser("ingest", help="ingest TSV/CSV(.gz) into sqlite")
    ingest_parser.add_argument("sources", nargs="+")
    ingest_parser.add_argument("--db", default=str(DEFAULT_DB))
    ingest_parser.add_argument("--no-header", action="store_true")
    ingest_parser.set_defaults(func=cmd_ingest)

    sql_parser = subparsers.add_parser("sql", help="run SQL against the local sqlite db")
    sql_parser.add_argument("query")
    sql_parser.add_argument("--db", default=str(DEFAULT_DB))
    sql_parser.add_argument("--limit", type=int, default=20)
    sql_parser.set_defaults(func=cmd_sql)

    tables_parser = subparsers.add_parser("tables", help="list ingested tables")
    tables_parser.add_argument("--db", default=str(DEFAULT_DB))
    tables_parser.add_argument("--columns", action="store_true")
    tables_parser.set_defaults(func=cmd_tables)

    presets_parser = subparsers.add_parser("presets", help="list sync presets")
    presets_parser.set_defaults(func=cmd_presets)

    sync_parser = subparsers.add_parser("sync", help="manifest + download + ingest a preset")
    sync_parser.add_argument("preset", choices=sorted(SYNC_PRESETS))
    sync_parser.add_argument("--root", default=str(DEFAULT_ROOT))
    sync_parser.add_argument("--db", default=str(DEFAULT_DB))
    sync_parser.add_argument("--manifest")
    sync_parser.add_argument("--force", action="store_true")
    sync_parser.set_defaults(func=cmd_sync)

    api_parser = subparsers.add_parser("api", help="call the FlyBase HTTP API")
    api_parser.add_argument("endpoint")
    api_parser.set_defaults(func=cmd_api)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)
