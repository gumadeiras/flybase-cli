from __future__ import annotations

import csv
import gzip
import json
import re
import sqlite3
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from pathlib import Path
from typing import Iterator

from .config import BASE_BUCKET, BATCH_SIZE, INGEST_SUFFIXES, SyncPreset


class DirectoryIndexParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.entries: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "a":
            return
        href = dict(attrs).get("href")
        if href:
            self.entries.append(href)


def fetch_text(url: str) -> str:
    with urllib.request.urlopen(url) as response:
        return response.read().decode("utf-8", errors="replace")


def fetch_bytes(url: str) -> bytes:
    with urllib.request.urlopen(url) as response:
        return response.read()


def normalize_path(path: str) -> str:
    return path.lstrip("/")


def normalize_bucket_href(href: str) -> str:
    clean = href.split("?", 1)[0]
    if clean.startswith("/releases/current/"):
        clean = clean[len("/releases/current/") :]
    return normalize_path(clean)


def scrape_index(url: str) -> list[str]:
    parser = DirectoryIndexParser()
    parser.feed(fetch_text(url))
    results: list[str] = []
    for href in parser.entries:
        if href.startswith(("?", "#", "http://", "https://")):
            continue
        clean = normalize_bucket_href(href)
        if clean in ("", "../", "./", "index.html"):
            continue
        results.append(clean)
    return results


def build_manifest(prefix: str) -> list[dict[str, str]]:
    normalized_prefix = normalize_path(prefix)
    if normalized_prefix and not normalized_prefix.endswith("/"):
        normalized_prefix = f"{normalized_prefix}/"

    todo = [normalized_prefix]
    seen: set[str] = set()
    files: list[dict[str, str]] = []

    while todo:
        current = todo.pop()
        if current in seen:
            continue
        seen.add(current)
        page_url = urllib.parse.urljoin(BASE_BUCKET, current)
        for entry in scrape_index(page_url):
            normalized_entry = entry[:-10] if entry.endswith("/index.html") else entry
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
                    "url": urllib.parse.urljoin(BASE_BUCKET, normalized_entry),
                }
            )
    return sorted(files, key=lambda item: item["path"])


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def load_manifest(path: Path) -> list[dict[str, str]]:
    return json.loads(path.read_text(encoding="utf-8"))


def compile_patterns(patterns: list[str] | tuple[str, ...]) -> list[re.Pattern[str]]:
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
    with urllib.request.urlopen(url) as response, dest.open("wb") as handle:
        while chunk := response.read(1024 * 1024):
            handle.write(chunk)


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


def table_name_from_path(path: str) -> str:
    name = Path(path).name
    for suffix in INGEST_SUFFIXES:
        if name.endswith(suffix):
            name = name[: -len(suffix)]
            break
    safe = re.sub(r"[^A-Za-z0-9_]+", "_", name).strip("_").lower()
    return f"fb_{safe or 'table'}"


def sample_delimiter(path: Path) -> str:
    return "," if ".csv" in path.name.lower() else "\t"


def open_maybe_gzip(path: Path):
    if path.suffix == ".gz":
        return gzip.open(path, "rt", encoding="utf-8", newline="")
    return path.open("r", encoding="utf-8", newline="")


def open_db(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def sanitize_columns(columns: list[str]) -> list[str]:
    seen: dict[str, int] = {}
    output: list[str] = []
    for index, column in enumerate(columns, start=1):
        base = re.sub(r"[^A-Za-z0-9_]+", "_", column.strip()).strip("_").lower()
        if not base:
            base = f"col_{index}"
        seen[base] = seen.get(base, 0) + 1
        output.append(base if seen[base] == 1 else f"{base}_{seen[base]}")
    return output


def iter_delimited_rows(source: Path) -> Iterator[tuple[list[str], str]]:
    delimiter = sample_delimiter(source)
    with open_maybe_gzip(source) as handle:
        reader = csv.reader(handle, delimiter=delimiter)
        for row in reader:
            yield row, delimiter


def read_header_and_rows(
    source: Path,
    no_header: bool,
) -> tuple[list[str], list[str] | None, Iterator[tuple[list[str], str]], str]:
    row_iter = iter_delimited_rows(source)
    delimiter = "\t"

    for row, delimiter in row_iter:
        if not row:
            continue
        if row[0].startswith("##") and len(row) == 1:
            continue
        if no_header:
            header = [f"col_{index}" for index in range(1, len(row) + 1)]
            return header, row, row_iter, delimiter
        row[0] = row[0].lstrip("#")
        return row, None, row_iter, delimiter

    raise ValueError(f"empty file: {source}")


def normalize_row(row: list[str], width: int, delimiter: str) -> list[str]:
    if len(row) < width:
        return row + [""] * (width - len(row))
    if len(row) > width:
        return row[: width - 1] + [delimiter.join(row[width - 1 :])]
    return row


def create_table(conn: sqlite3.Connection, table_name: str, columns: list[str]) -> str:
    conn.execute(f'DROP TABLE IF EXISTS "{table_name}"')
    create_sql = ", ".join(f'"{column}" TEXT' for column in columns)
    conn.execute(f'CREATE TABLE "{table_name}" ({create_sql})')
    quoted_columns = ", ".join(f'"{column}"' for column in columns)
    placeholders = ", ".join("?" for _ in columns)
    return f'INSERT INTO "{table_name}" ({quoted_columns}) VALUES ({placeholders})'


def flush_batch(
    conn: sqlite3.Connection,
    insert_sql: str,
    batch: list[list[str]],
    row_count: int,
) -> int:
    if batch:
        conn.executemany(insert_sql, batch)
        row_count += len(batch)
    return row_count


def ingest_delimited(
    conn: sqlite3.Connection,
    source: Path,
    table_name: str,
    no_header: bool = False,
) -> int:
    raw_header, first_data_row, row_iter, delimiter = read_header_and_rows(source, no_header)
    columns = sanitize_columns(raw_header)
    insert_sql = create_table(conn, table_name, columns)
    batch: list[list[str]] = []
    row_count = 0

    if first_data_row is not None:
        batch.append(normalize_row(first_data_row, len(columns), delimiter))

    for row, _ in row_iter:
        if not row:
            continue
        batch.append(normalize_row(row, len(columns), delimiter))
        if len(batch) >= BATCH_SIZE:
            row_count = flush_batch(conn, insert_sql, batch, row_count)
            batch.clear()

    return flush_batch(conn, insert_sql, batch, row_count)


def ensure_registry(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS fb_ingest_registry (
            source_path TEXT PRIMARY KEY,
            table_name TEXT NOT NULL,
            row_count INTEGER NOT NULL
        )
        """
    )


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
        ON CONFLICT(source_path)
        DO UPDATE SET table_name = excluded.table_name, row_count = excluded.row_count
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
            row_count = ingest_delimited(conn, source, table_name, no_header=no_header)
            upsert_registry(conn, source, table_name, row_count)
            ingested.append(
                {
                    "source_path": str(source),
                    "table_name": table_name,
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


def is_ingestable(path: Path) -> bool:
    path_str = path.name
    return any(path_str.endswith(suffix) for suffix in INGEST_SUFFIXES)


def sync_preset(
    preset: SyncPreset,
    root: Path,
    db_path: Path,
    manifest_path: Path,
    force: bool = False,
) -> dict[str, object]:
    manifest = filter_manifest(build_manifest(preset.prefix), preset.includes, preset.excludes)
    write_json(manifest_path, manifest)
    local_paths = download_manifest_entries(manifest, root, force=force)
    ingested = ingest_files(db_path, [path for path, _ in local_paths if is_ingestable(path)])
    return {
        "preset": preset.name,
        "description": preset.description,
        "manifest_path": str(manifest_path),
        "file_count": len(manifest),
        "ingested_tables": ingested,
    }
