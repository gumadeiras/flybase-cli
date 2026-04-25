from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.parse
from pathlib import Path

from .config import (
    BASE_API,
    DEFAULT_DB,
    DEFAULT_MANIFEST,
    DEFAULT_POSTGRES_DIR,
    DEFAULT_RELEASE,
    DEFAULT_ROOT,
    GENOME_SYNC_PRESETS,
    GENOME_ASSET_PATTERNS,
    GENOME_SECTIONS,
    SYNC_PRESETS,
)
from .core import (
    build_manifest,
    build_manifest_from_url,
    fetch_bytes,
    filter_manifest,
    ingest_files,
    find_genome,
    genome_asset_pattern,
    genome_section_url,
    list_genomes,
    list_tables,
    load_manifest,
    rebuild_search_index,
    release_base_url,
    run_query,
    search_index,
    sync_manifest,
    sync_preset,
    write_json,
)
from .postgres import (
    build_pg_load_plan,
    ensure_dump_file,
    execute_pg_load_script,
    write_pg_load_script,
)


def print_json(payload: object) -> None:
    print(json.dumps(payload, indent=2))


def default_manifest_for_release(root: Path, preset: str, release: str) -> Path:
    return root / "manifests" / release / f"{preset}.json"


def default_db_for_release(root: Path, release: str) -> Path:
    if release == DEFAULT_RELEASE:
        return root / DEFAULT_DB.name
    return root / f"{release}.sqlite"


def cmd_manifest(args: argparse.Namespace) -> int:
    if args.url:
        manifest = build_manifest_from_url(args.url)
    else:
        manifest = build_manifest(args.prefix, release=args.release)
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


def cmd_genome_presets(_: argparse.Namespace) -> int:
    payload = [
        {
            "name": preset.name,
            "description": preset.description,
            "section": preset.section,
            "asset": preset.asset,
            "includes": list(preset.includes),
            "excludes": list(preset.excludes),
        }
        for preset in GENOME_SYNC_PRESETS.values()
    ]
    print_json(payload)
    return 0


def cmd_sync(args: argparse.Namespace) -> int:
    preset = SYNC_PRESETS[args.preset]
    root = Path(args.root)
    manifest_path = Path(args.manifest or default_manifest_for_release(root, preset.name, args.release))
    db_path = Path(args.db) if args.db else default_db_for_release(root, args.release)
    summary = sync_preset(
        preset=preset,
        root=root,
        db_path=db_path,
        manifest_path=manifest_path,
        release=args.release,
        force=args.force,
    )
    summary["db_path"] = str(db_path)
    print_json(summary)
    return 0


def cmd_sync_url(args: argparse.Namespace) -> int:
    root = Path(args.root)
    db_path = Path(args.db) if args.db else default_db_for_release(root, args.release)
    manifest = filter_manifest(
        build_manifest_from_url(args.url),
        args.include,
        args.exclude,
    )
    manifest_path = Path(args.manifest) if args.manifest else root / "manifests" / args.release / "url-sync.json"
    summary = sync_manifest(
        manifest,
        root=root,
        db_path=db_path,
        manifest_path=manifest_path,
        force=args.force,
        no_header=args.no_header,
    )
    summary["url"] = args.url
    summary["db_path"] = str(db_path)
    print_json(summary)
    return 0


def cmd_sync_genome(args: argparse.Namespace) -> int:
    root = Path(args.root)
    db_path = Path(args.db) if args.db else default_db_for_release(root, args.release)
    preset = GENOME_SYNC_PRESETS.get(args.preset) if args.preset else None
    genome = find_genome(
        release=args.release,
        genome=args.genome,
        species=args.species,
    )
    section = preset.section if preset else args.section
    asset = preset.asset if preset else args.asset
    include = [*genome_asset_pattern(asset), *(preset.includes if preset else ()), *args.include]
    exclude = [*(preset.excludes if preset else ()), *args.exclude]
    url = genome_section_url(genome["url"], section)
    manifest = filter_manifest(
        build_manifest_from_url(url),
        include,
        exclude,
    )
    default_name = f"{genome['label']}-{section}"
    if preset:
        default_name = f"{default_name}-{preset.name}"
    elif asset:
        default_name = f"{default_name}-{asset}"
    manifest_path = Path(args.manifest) if args.manifest else root / "manifests" / args.release / f"{default_name}.json"
    summary = sync_manifest(
        manifest,
        root=root,
        db_path=db_path,
        manifest_path=manifest_path,
        force=args.force,
        no_header=args.no_header,
    )
    summary["release"] = args.release
    summary["genome"] = genome
    summary["section"] = section
    summary["asset"] = asset
    summary["preset"] = args.preset
    summary["url"] = url
    summary["db_path"] = str(db_path)
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


def cmd_release_url(args: argparse.Namespace) -> int:
    print_json({"release": args.release, "base_url": release_base_url(args.release)})
    return 0


def cmd_genomes(args: argparse.Namespace) -> int:
    print_json(list_genomes(args.release))
    return 0


def cmd_fts_build(args: argparse.Namespace) -> int:
    indexed = rebuild_search_index(Path(args.db), table_names=args.tables or None)
    print_json(indexed)
    return 0


def cmd_search(args: argparse.Namespace) -> int:
    results = search_index(
        Path(args.db),
        query=args.query,
        limit=args.limit,
        table_name=args.table,
    )
    print_json(results)
    return 0


def cmd_pg_load(args: argparse.Namespace) -> int:
    root = Path(args.root)
    plan = build_pg_load_plan(
        release=args.release,
        root=root,
        db_name=args.db_name,
        dump_path=Path(args.dump_path) if args.dump_path else None,
        script_path=Path(args.script_path) if args.script_path else None,
        drop_existing=args.drop_existing,
    )
    dump_path = Path(plan["dump_path"])
    script_path = Path(plan["script_path"])
    if args.download:
        ensure_dump_file(
            release=args.release,
            dump_path=dump_path,
            force=args.force_download,
        )
        plan["downloaded"] = True
    write_pg_load_script(
        release=args.release,
        dump_path=dump_path,
        db_name=str(plan["db_name"]),
        script_path=script_path,
        drop_existing=args.drop_existing,
    )
    plan["script_written"] = True
    if args.execute:
        missing = [name for name, path in plan["tools"].items() if name in {"createdb", "psql"} and not path]
        if missing:
            print_json({"error": "missing-postgres-tools", "missing": missing, **plan})
            return 1
        execute_pg_load_script(script_path)
        plan["executed"] = True
    print_json(plan)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="FlyBase sync/query helper for agents.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    manifest_parser = subparsers.add_parser("manifest", help="scrape a release prefix or FlyBase directory URL")
    manifest_parser.add_argument("--prefix", default="precomputed_files/genes/")
    manifest_parser.add_argument("--url")
    manifest_parser.add_argument("--release", default=DEFAULT_RELEASE)
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

    ingest_parser = subparsers.add_parser("ingest", help="ingest supported FlyBase files into sqlite")
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

    genome_presets_parser = subparsers.add_parser("genome-presets", help="list genome sync presets")
    genome_presets_parser.set_defaults(func=cmd_genome_presets)

    sync_parser = subparsers.add_parser("sync", help="manifest + download + ingest a preset")
    sync_parser.add_argument("preset", choices=sorted(SYNC_PRESETS))
    sync_parser.add_argument("--root", default=str(DEFAULT_ROOT))
    sync_parser.add_argument("--db")
    sync_parser.add_argument("--release", default=DEFAULT_RELEASE)
    sync_parser.add_argument("--manifest")
    sync_parser.add_argument("--force", action="store_true")
    sync_parser.set_defaults(func=cmd_sync)

    sync_url_parser = subparsers.add_parser("sync-url", help="crawl + download + ingest an arbitrary FlyBase directory URL")
    sync_url_parser.add_argument("--url", required=True)
    sync_url_parser.add_argument("--root", default=str(DEFAULT_ROOT))
    sync_url_parser.add_argument("--db")
    sync_url_parser.add_argument("--release", default=DEFAULT_RELEASE)
    sync_url_parser.add_argument("--manifest")
    sync_url_parser.add_argument("--include", action="append", default=[])
    sync_url_parser.add_argument("--exclude", action="append", default=[])
    sync_url_parser.add_argument("--force", action="store_true")
    sync_url_parser.add_argument("--no-header", action="store_true")
    sync_url_parser.set_defaults(func=cmd_sync_url)

    sync_genome_parser = subparsers.add_parser("sync-genome", help="discover a genome build and sync one genome asset section")
    sync_genome_parser.add_argument("--release", default=DEFAULT_RELEASE)
    sync_genome_parser.add_argument("--genome")
    sync_genome_parser.add_argument("--species")
    sync_genome_parser.add_argument("--preset", choices=sorted(GENOME_SYNC_PRESETS))
    sync_genome_parser.add_argument("--section", choices=GENOME_SECTIONS, default="fasta")
    sync_genome_parser.add_argument("--asset", choices=sorted(GENOME_ASSET_PATTERNS))
    sync_genome_parser.add_argument("--root", default=str(DEFAULT_ROOT))
    sync_genome_parser.add_argument("--db")
    sync_genome_parser.add_argument("--manifest")
    sync_genome_parser.add_argument("--include", action="append", default=[])
    sync_genome_parser.add_argument("--exclude", action="append", default=[])
    sync_genome_parser.add_argument("--force", action="store_true")
    sync_genome_parser.add_argument("--no-header", action="store_true")
    sync_genome_parser.set_defaults(func=cmd_sync_genome)

    release_parser = subparsers.add_parser("release-url", help="show the bulk-data base URL for a release")
    release_parser.add_argument("--release", default=DEFAULT_RELEASE)
    release_parser.set_defaults(func=cmd_release_url)

    genomes_parser = subparsers.add_parser("genomes", help="list genome builds linked from a FlyBase release")
    genomes_parser.add_argument("--release", default=DEFAULT_RELEASE)
    genomes_parser.set_defaults(func=cmd_genomes)

    fts_build_parser = subparsers.add_parser("fts-build", help="build a local full-text index")
    fts_build_parser.add_argument("--db", default=str(DEFAULT_DB))
    fts_build_parser.add_argument("--tables", nargs="*")
    fts_build_parser.set_defaults(func=cmd_fts_build)

    search_parser = subparsers.add_parser("search", help="search the local full-text index")
    search_parser.add_argument("query")
    search_parser.add_argument("--db", default=str(DEFAULT_DB))
    search_parser.add_argument("--table")
    search_parser.add_argument("--limit", type=int, default=20)
    search_parser.set_defaults(func=cmd_search)

    pg_parser = subparsers.add_parser("pg-load", help="stage or execute a FlyBase Postgres import")
    pg_parser.add_argument("--release", default=DEFAULT_RELEASE)
    pg_parser.add_argument("--root", default=str(DEFAULT_POSTGRES_DIR))
    pg_parser.add_argument("--db-name")
    pg_parser.add_argument("--dump-path")
    pg_parser.add_argument("--script-path")
    pg_parser.add_argument("--download", action="store_true")
    pg_parser.add_argument("--force-download", action="store_true")
    pg_parser.add_argument("--drop-existing", action="store_true")
    pg_parser.add_argument("--execute", action="store_true")
    pg_parser.set_defaults(func=cmd_pg_load)

    api_parser = subparsers.add_parser("api", help="call the FlyBase HTTP API")
    api_parser.add_argument("endpoint")
    api_parser.set_defaults(func=cmd_api)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)
