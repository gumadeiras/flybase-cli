from __future__ import annotations

import json
import sqlite3
import subprocess
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from pathlib import Path

from .config import (
    BASE_RELEASES,
    BATCH_SIZE,
    GENOME_ASSET_PATTERNS,
    GENOME_SECTIONS,
    SEARCH_ID_CANDIDATES,
    SyncPreset,
)
from .loaders import ingest_source, is_ingestable


def site_root_url() -> str:
    parts = urllib.parse.urlsplit(BASE_RELEASES)
    return f"{parts.scheme}://{parts.netloc}/"


class DirectoryIndexParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.entries: list[dict[str, str]] = []
        self.current_href: str | None = None
        self.current_text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "a":
            return
        href = dict(attrs).get("href")
        if href:
            self.current_href = href
            self.current_text = []

    def handle_data(self, data: str) -> None:
        if self.current_href is not None:
            self.current_text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag != "a" or self.current_href is None:
            return
        self.entries.append(
            {
                "href": self.current_href,
                "text": "".join(self.current_text).strip(),
            }
        )
        self.current_href = None
        self.current_text = []


def fetch_via_curl(url: str) -> bytes:
    result = subprocess.run(
        ["curl", "-fsSL", url],
        check=True,
        capture_output=True,
    )
    return result.stdout


def request_bytes(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "curl/8.7.1"})
    with urllib.request.urlopen(request) as response:
        payload = response.read()
        if getattr(response, "status", 200) == 202 or not payload:
            raise RuntimeError(f"empty or challenged response for {url}")
        return payload


def fetch_text(url: str) -> str:
    return fetch_bytes(url).decode("utf-8", errors="replace")


def fetch_bytes(url: str) -> bytes:
    try:
        return request_bytes(url)
    except Exception:
        return fetch_via_curl(url)


def release_base_url(release: str) -> str:
    normalized = release.strip("/")
    return urllib.parse.urljoin(BASE_RELEASES, f"{normalized}/")


def normalize_crawl_url(url: str) -> str:
    clean = url.split("?", 1)[0]
    if clean.endswith("index.html"):
        clean = clean[: -len("index.html")]
    if not clean.endswith("/"):
        clean = f"{clean}/"
    return clean


def normalize_path(path: str) -> str:
    return path.lstrip("/")


def normalize_bucket_href(href: str, release: str) -> str:
    clean = href.split("?", 1)[0]
    release_prefix = f"/releases/{release.strip('/')}/"
    if clean.startswith(release_prefix):
        clean = clean[len(release_prefix) :]
    return normalize_path(clean)


def scrape_links(url: str) -> list[dict[str, str]]:
    parser = DirectoryIndexParser()
    parser.feed(fetch_text(url))
    return parser.entries


def scrape_index(url: str) -> list[str]:
    results: list[str] = []
    for entry in scrape_links(url):
        href = entry["href"]
        if href.startswith(("?", "#")):
            continue
        clean = href.split("?", 1)[0]
        if clean in ("", "../", "./", "index.html"):
            continue
        results.append(clean)
    return results


def build_manifest(prefix: str, release: str = "current") -> list[dict[str, str]]:
    normalized_prefix = normalize_path(prefix)
    if normalized_prefix and not normalized_prefix.endswith("/"):
        normalized_prefix = f"{normalized_prefix}/"

    base_url = release_base_url(release)
    todo = [normalized_prefix]
    seen: set[str] = set()
    files: list[dict[str, str]] = []

    while todo:
        current = todo.pop()
        if current in seen:
            continue
        seen.add(current)
        page_url = urllib.parse.urljoin(base_url, current)
        for entry in scrape_index(page_url):
            normalized_entry = normalize_bucket_href(entry, release)
            if normalized_entry.endswith("index.html"):
                normalized_entry = normalized_entry[: -len("index.html")]
            if current and not normalized_entry.startswith(current):
                continue
            if current and normalized_entry == current.rstrip("/"):
                continue
            if normalized_entry.endswith("/"):
                todo.append(normalized_entry)
                continue
            files.append(
                {
                    "path": normalized_entry,
                    "url": urllib.parse.urljoin(base_url, normalized_entry),
                }
            )
    return sorted(files, key=lambda item: item["path"])


def path_from_root_url(root_url: str, url: str) -> str:
    root = urllib.parse.urlsplit(normalize_crawl_url(root_url))
    target = urllib.parse.urlsplit(url.split("?", 1)[0])
    if (root.scheme, root.netloc) != (target.scheme, target.netloc):
        return ""
    if not target.path.startswith(root.path):
        return ""
    relative = target.path[len(root.path) :].lstrip("/")
    if url.endswith("/") and relative and not relative.endswith("/"):
        relative = f"{relative}/"
    return relative


def build_manifest_from_url(root_url: str) -> list[dict[str, str]]:
    base_url = normalize_crawl_url(root_url)
    todo = [base_url]
    seen: set[str] = set()
    files: list[dict[str, str]] = []

    while todo:
        current_url = todo.pop()
        if current_url in seen:
            continue
        seen.add(current_url)
        for href in scrape_index(current_url):
            absolute = urllib.parse.urljoin(current_url, href)
            if absolute.endswith(("index.html", "/")):
                normalized = normalize_crawl_url(absolute)
            else:
                normalized = absolute.split("?", 1)[0]
            relative = path_from_root_url(base_url, normalized)
            if not relative:
                continue
            if normalized == base_url or relative in {"", "."}:
                continue
            if normalized.endswith("/"):
                todo.append(normalized)
                continue
            files.append({"path": relative, "url": normalized})

    return sorted(files, key=lambda item: item["path"])


def extract_genomes(links: list[dict[str, str]]) -> list[dict[str, str]]:
    genomes: list[dict[str, str]] = []
    for link in links:
        href = link["href"].split("?", 1)[0]
        if not href.startswith("/genomes/"):
            continue
        parts = [part for part in href.split("/") if part]
        if len(parts) < 3:
            continue
        species = parts[1]
        genome_build = parts[2]
        label = link["text"] or genome_build
        genomes.append(
            {
                "label": label,
                "species": species,
                "genome_build": genome_build,
                "url": urllib.parse.urljoin(site_root_url(), href.lstrip("/")),
            }
        )
    return genomes


def list_genomes(release: str = "current") -> list[dict[str, str]]:
    links = scrape_links(release_base_url(release))
    genomes = extract_genomes(links)
    return sorted(genomes, key=lambda item: (item["species"], item["genome_build"]))


def find_genome(
    *,
    release: str,
    genome: str | None = None,
    species: str | None = None,
) -> dict[str, str]:
    genomes = list_genomes(release)
    normalized_genome = genome.lower() if genome else None
    normalized_species = species.lower() if species else None

    matches: list[dict[str, str]] = []
    for item in genomes:
        label = item["label"].lower()
        build = item["genome_build"].lower()
        species_name = item["species"].lower()
        genome_ok = normalized_genome is None or normalized_genome in {label, build}
        species_ok = normalized_species is None or normalized_species in {species_name, label}
        if genome_ok and species_ok:
            matches.append(item)

    if not matches:
        raise ValueError("no genome matched the requested release/species/build")
    if len(matches) > 1:
        joined = ", ".join(match["label"] for match in matches[:10])
        raise ValueError(f"multiple genomes matched: {joined}")
    return matches[0]


def genome_section_url(genome_url: str, section: str) -> str:
    if section not in GENOME_SECTIONS:
        raise ValueError(f"unsupported genome section: {section}")
    return urllib.parse.urljoin(normalize_crawl_url(genome_url), f"{section}/")


def genome_asset_pattern(asset: str | None) -> list[str]:
    if not asset:
        return []
    pattern = GENOME_ASSET_PATTERNS.get(asset.lower())
    if pattern is None:
        raise ValueError(f"unknown genome asset preset: {asset}")
    return [pattern]


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def load_manifest(path: Path) -> list[dict[str, str]]:
    return json.loads(path.read_text(encoding="utf-8"))


def compile_patterns(patterns: list[str] | tuple[str, ...]) -> list:
    import re

    return [re.compile(pattern) for pattern in patterns]


def filter_manifest(
    manifest: list[dict[str, str]],
    include: list[str] | tuple[str, ...],
    exclude: list[str] | tuple[str, ...],
) -> list[dict[str, str]]:
    include_patterns = compile_patterns(include)
    exclude_patterns = compile_patterns(exclude)
    filtered: list[dict[str, str]] = []

    for item in manifest:
        path = item["path"]
        if include_patterns and not any(pattern.search(path) for pattern in include_patterns):
            continue
        if any(pattern.search(path) for pattern in exclude_patterns):
            continue
        filtered.append(item)

    return filtered


def download_file(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        payload = request_bytes(url)
        dest.write_bytes(payload)
    except Exception:
        subprocess.run(["curl", "-fsSL", "-o", str(dest), url], check=True)


def download_manifest_entries(
    manifest: list[dict[str, str]],
    root: Path,
    force: bool = False,
) -> list[tuple[Path, bool]]:
    local_paths: list[tuple[Path, bool]] = []
    for item in manifest:
        dest = root / item["path"]
        should_download = force or not dest.exists()
        local_paths.append((dest, should_download))
        if dest.exists() and not force:
            continue
        download_file(item["url"], dest)
    return local_paths


def sync_manifest(
    manifest: list[dict[str, str]],
    *,
    root: Path,
    db_path: Path,
    manifest_path: Path | None = None,
    force: bool = False,
    no_header: bool = False,
) -> dict[str, object]:
    if manifest_path is not None:
        write_json(manifest_path, manifest)
    local_paths = download_manifest_entries(manifest, root, force=force)
    ingested = ingest_files(
        db_path,
        [path for path, _ in local_paths if is_ingestable(path)],
        no_header=no_header,
    )
    return {
        "manifest_path": str(manifest_path) if manifest_path is not None else None,
        "file_count": len(manifest),
        "ingested_tables": ingested,
    }


def table_name_from_path(path: str) -> str:
    import re

    name = Path(path).name
    suffixes = (
        ".tsv.gz",
        ".csv.gz",
        ".fasta.gz",
        ".fa.gz",
        ".fna.gz",
        ".faa.gz",
        ".gff.gz",
        ".gff3.gz",
        ".gtf.gz",
        ".json.gz",
        ".tsv",
        ".csv",
        ".fasta",
        ".fa",
        ".fna",
        ".faa",
        ".gff",
        ".gff3",
        ".gtf",
        ".json",
    )
    for suffix in suffixes:
        if name.endswith(suffix):
            name = name[: -len(suffix)]
            break
    safe = re.sub(r"[^A-Za-z0-9_]+", "_", name).strip("_").lower()
    return f"fb_{safe or 'table'}"


def open_db(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def ensure_registry(conn: sqlite3.Connection) -> None:
    existing = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='fb_ingest_registry'"
    ).fetchone()
    if not existing:
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
        return

    columns = conn.execute("PRAGMA table_info(fb_ingest_registry)").fetchall()
    source_path_column = next((column for column in columns if column[1] == "source_path"), None)
    table_name_column = next((column for column in columns if column[1] == "table_name"), None)
    if source_path_column and source_path_column[5] == 1 and table_name_column and table_name_column[5] == 0:
        conn.execute("ALTER TABLE fb_ingest_registry RENAME TO fb_ingest_registry_old")
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
            INSERT INTO fb_ingest_registry (source_path, table_name, row_count)
            SELECT source_path, table_name, row_count
            FROM fb_ingest_registry_old
            """
        )
        conn.execute("DROP TABLE fb_ingest_registry_old")


def upsert_registry(
    conn: sqlite3.Connection,
    source: Path,
    table_name: str,
    row_count: int,
) -> None:
    conn.execute(
        """
        INSERT INTO fb_ingest_registry (source_path, table_name, row_count)
        VALUES (?, ?, ?)
        ON CONFLICT(source_path, table_name)
        DO UPDATE SET row_count = excluded.row_count
        """,
        (str(source), table_name, row_count),
    )


def ingest_files(
    db_path: Path,
    sources: list[Path],
    no_header: bool = False,
) -> list[dict[str, str | int]]:
    conn = open_db(db_path)
    ensure_registry(conn)
    ingested: list[dict[str, str | int]] = []
    try:
        for source in sources:
            table_name = table_name_from_path(source.name)
            for emitted_table_name, row_count in ingest_source(conn, source, table_name, no_header=no_header):
                upsert_registry(conn, source, emitted_table_name, row_count)
                ingested.append(
                    {
                        "source_path": str(source),
                        "table_name": emitted_table_name,
                        "row_count": row_count,
                    }
                )
        conn.commit()
    finally:
        conn.close()
    return ingested


def list_tables(db_path: Path, include_columns: bool = False) -> list[dict[str, object]]:
    conn = open_db(db_path)
    ensure_registry(conn)
    try:
        rows = conn.execute(
            """
            SELECT table_name, row_count, source_path
            FROM fb_ingest_registry
            ORDER BY table_name
            """
        ).fetchall()
        payload: list[dict[str, object]] = []
        for table_name, row_count, source_path in rows:
            item: dict[str, object] = {
                "table_name": table_name,
                "row_count": row_count,
                "source_path": source_path,
            }
            if include_columns:
                item["columns"] = [
                    row[1]
                    for row in conn.execute(f'PRAGMA table_info("{table_name}")').fetchall()
                ]
            payload.append(item)
        return payload
    finally:
        conn.close()


def run_query(db_path: Path, query: str) -> tuple[list[str], list[tuple[object, ...]]] | None:
    conn = open_db(db_path)
    try:
        cursor = conn.execute(query)
        if cursor.description is None:
            conn.commit()
            return None
        columns = [description[0] for description in cursor.description]
        return columns, cursor.fetchall()
    finally:
        conn.close()


def pick_record_id(columns: list[str], row: tuple[object, ...], rowid: int) -> str:
    row_map = dict(zip(columns, row, strict=True))
    for candidate in SEARCH_ID_CANDIDATES:
        value = row_map.get(candidate)
        if value:
            return str(value)
    return str(rowid)


def ensure_search_table(conn: sqlite3.Connection) -> None:
    conn.execute("DROP TABLE IF EXISTS fb_search_fts")
    conn.execute(
        """
        CREATE VIRTUAL TABLE fb_search_fts
        USING fts5(table_name, record_id, text)
        """
    )


def list_registry_table_names(conn: sqlite3.Connection) -> list[str]:
    ensure_registry(conn)
    return [
        row[0]
        for row in conn.execute(
            "SELECT table_name FROM fb_ingest_registry ORDER BY table_name"
        ).fetchall()
    ]


def rebuild_search_index(
    db_path: Path,
    table_names: list[str] | None = None,
) -> list[dict[str, object]]:
    conn = open_db(db_path)
    try:
        ensure_search_table(conn)
        selected_tables = table_names or list_registry_table_names(conn)
        indexed: list[dict[str, object]] = []

        for table_name in selected_tables:
            columns = [
                row[1]
                for row in conn.execute(f'PRAGMA table_info("{table_name}")').fetchall()
            ]
            if not columns:
                continue

            batch: list[tuple[str, str, str]] = []
            row_count = 0
            quoted = ", ".join(f'"{column}"' for column in columns)
            sql = f'SELECT rowid, {quoted} FROM "{table_name}"'
            for result in conn.execute(sql):
                rowid = int(result[0])
                row = tuple("" if value is None else str(value) for value in result[1:])
                text_parts = [
                    f"{column}: {value}"
                    for column, value in zip(columns, row, strict=True)
                    if value
                ]
                if not text_parts:
                    continue
                batch.append(
                    (
                        table_name,
                        pick_record_id(columns, row, rowid),
                        "\n".join(text_parts),
                    )
                )
                if len(batch) >= BATCH_SIZE:
                    conn.executemany(
                        "INSERT INTO fb_search_fts (table_name, record_id, text) VALUES (?, ?, ?)",
                        batch,
                    )
                    row_count += len(batch)
                    batch.clear()

            if batch:
                conn.executemany(
                    "INSERT INTO fb_search_fts (table_name, record_id, text) VALUES (?, ?, ?)",
                    batch,
                )
                row_count += len(batch)

            indexed.append({"table_name": table_name, "row_count": row_count})

        conn.commit()
        return indexed
    finally:
        conn.close()


def search_index(
    db_path: Path,
    query: str,
    limit: int = 20,
    table_name: str | None = None,
) -> list[dict[str, object]]:
    conn = open_db(db_path)
    try:
        sql = """
            SELECT
                table_name,
                record_id,
                bm25(fb_search_fts) AS score,
                snippet(fb_search_fts, 2, '[', ']', '...', 12) AS snippet
            FROM fb_search_fts
            WHERE fb_search_fts MATCH ?
        """
        params: list[object] = [query]
        if table_name:
            sql += " AND table_name = ?"
            params.append(table_name)
        sql += " LIMIT ?"
        params.append(limit)
        return [
            {
                "table_name": row[0],
                "record_id": row[1],
                "score": row[2],
                "snippet": row[3],
            }
            for row in conn.execute(sql, params).fetchall()
        ]
    finally:
        conn.close()


def sync_preset(
    preset: SyncPreset,
    root: Path,
    db_path: Path,
    manifest_path: Path,
    release: str = "current",
    force: bool = False,
) -> dict[str, object]:
    manifest_map: dict[str, dict[str, str]] = {}
    for selection in preset.selections:
        filtered = filter_manifest(
            build_manifest(selection.prefix, release=release),
            selection.includes,
            selection.excludes,
        )
        for item in filtered:
            manifest_map[item["path"]] = item
    manifest = sorted(manifest_map.values(), key=lambda item: item["path"])
    summary = sync_manifest(
        manifest,
        root=root,
        db_path=db_path,
        manifest_path=manifest_path,
        force=force,
    )
    return {
        "preset": preset.name,
        "description": preset.description,
        "release": release,
        **summary,
    }
