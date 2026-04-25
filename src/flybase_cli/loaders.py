from __future__ import annotations

import csv
import gzip
import json
import re
import sqlite3
import tarfile
from contextlib import contextmanager
from io import TextIOWrapper
from pathlib import Path
from typing import Iterator

from .config import (
    BATCH_SIZE,
    DELIMITED_SUFFIXES,
    FASTA_SUFFIXES,
    GFF_SUFFIXES,
    GTF_SUFFIXES,
    JSON_ID_CANDIDATES,
    JSON_MAX_INFERRED_COLUMNS,
    JSON_SUFFIXES,
)


@contextmanager
def open_maybe_gzip(path: Path):
    if path.suffix != ".gz":
        with path.open("r", encoding="utf-8", newline="") as handle:
            yield handle
        return

    try:
        archive = tarfile.open(path, mode="r:gz")
    except tarfile.ReadError:
        with gzip.open(path, "rt", encoding="utf-8", newline="") as handle:
            yield handle
        return

    try:
        member = next((item for item in archive if item.isfile()), None)
        if member is None:
            raise ValueError(f"no regular file found in archive: {path}")
        extracted = archive.extractfile(member)
        if extracted is None:
            raise ValueError(f"unable to extract archive member: {path}")
        wrapper = TextIOWrapper(extracted, encoding="utf-8", newline="")
        try:
            yield wrapper
        finally:
            wrapper.close()
    finally:
        archive.close()


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
    batch: list[list[str]] | list[tuple[str, ...]],
    row_count: int,
) -> int:
    if batch:
        conn.executemany(insert_sql, batch)
        row_count += len(batch)
    return row_count


def sample_delimiter(path: Path) -> str:
    return "," if ".csv" in path.name.lower() else "\t"


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


def split_fasta_header(header: str) -> tuple[str, str]:
    text = header[1:].strip()
    if not text:
        return "", ""
    parts = text.split(None, 1)
    record_id = parts[0]
    description = parts[1] if len(parts) > 1 else ""
    return record_id, description


def ingest_fasta(conn: sqlite3.Connection, source: Path, table_name: str) -> int:
    columns = ["record_id", "header", "description", "sequence", "sequence_length"]
    insert_sql = create_table(conn, table_name, columns)
    batch: list[tuple[str, ...]] = []
    row_count = 0
    current_header = ""
    current_id = ""
    current_description = ""
    sequence_parts: list[str] = []

    def flush_current() -> None:
        nonlocal row_count, batch, sequence_parts
        if not current_header:
            return
        sequence = "".join(sequence_parts)
        batch.append(
            (
                current_id,
                current_header[1:].strip(),
                current_description,
                sequence,
                str(len(sequence)),
            )
        )
        sequence_parts = []

    with open_maybe_gzip(source) as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line:
                continue
            if line.startswith(">"):
                flush_current()
                current_header = line
                current_id, current_description = split_fasta_header(line)
                if len(batch) >= BATCH_SIZE:
                    row_count = flush_batch(conn, insert_sql, batch, row_count)
                    batch.clear()
                continue
            sequence_parts.append(line)

    flush_current()
    return flush_batch(conn, insert_sql, batch, row_count)


def parse_feature_attributes(raw_attributes: str) -> dict[str, str]:
    attributes: dict[str, str] = {}
    for part in raw_attributes.split(";"):
        chunk = part.strip()
        if not chunk:
            continue
        if "=" in chunk:
            key, value = chunk.split("=", 1)
        elif " " in chunk:
            key, value = chunk.split(" ", 1)
            value = value.strip().strip('"')
        else:
            key, value = chunk, ""
        attributes[key.strip()] = value.strip().strip('"')
    return attributes


def pick_attribute(attributes: dict[str, str], *keys: str) -> str:
    for key in keys:
        value = attributes.get(key)
        if value:
            return value
    return ""


def ingest_feature_file(
    conn: sqlite3.Connection,
    source: Path,
    table_name: str,
) -> int:
    columns = [
        "seqid",
        "source",
        "feature_type",
        "start",
        "end",
        "score",
        "strand",
        "phase",
        "feature_id",
        "parent_id",
        "feature_name",
        "gene_id",
        "transcript_id",
        "attributes_json",
        "attributes_raw",
    ]
    insert_sql = create_table(conn, table_name, columns)
    batch: list[tuple[str, ...]] = []
    row_count = 0

    with open_maybe_gzip(source) as handle:
        for raw_line in handle:
            line = raw_line.rstrip("\n")
            if not line or line.startswith("#"):
                continue
            fields = line.split("\t")
            if len(fields) != 9:
                continue
            attributes = parse_feature_attributes(fields[8])
            batch.append(
                (
                    fields[0],
                    fields[1],
                    fields[2],
                    fields[3],
                    fields[4],
                    fields[5],
                    fields[6],
                    fields[7],
                    pick_attribute(attributes, "ID", "id"),
                    pick_attribute(attributes, "Parent", "parent"),
                    pick_attribute(attributes, "Name", "gene_name", "transcript_name", "name"),
                    pick_attribute(attributes, "gene_id", "geneID", "gene"),
                    pick_attribute(attributes, "transcript_id", "transcriptID", "transcript"),
                    json.dumps(attributes, sort_keys=True),
                    fields[8],
                )
            )
            if len(batch) >= BATCH_SIZE:
                row_count = flush_batch(conn, insert_sql, batch, row_count)
                batch.clear()

    return flush_batch(conn, insert_sql, batch, row_count)


def iter_json_rows(payload: object) -> Iterator[tuple[str, str]]:
    if isinstance(payload, list):
        for index, item in enumerate(payload, start=1):
            yield pick_json_record_id(item, index), json.dumps(item, sort_keys=True)
        return

    if isinstance(payload, dict):
        list_keys = [key for key, value in payload.items() if isinstance(value, list)]
        if len(list_keys) == 1:
            for index, item in enumerate(payload[list_keys[0]], start=1):
                yield pick_json_record_id(item, index), json.dumps(item, sort_keys=True)
            return
        yield "1", json.dumps(payload, sort_keys=True)
        return

    yield "1", json.dumps(payload)


def pick_json_record_id(item: object, fallback_index: int) -> str:
    if isinstance(item, dict):
        for candidate in JSON_ID_CANDIDATES:
            value = item.get(candidate)
            if value:
                return str(value)
    return str(fallback_index)


def json_scalar_to_text(value: object) -> str | None:
    if value is None:
        return ""
    if isinstance(value, (str, int, float, bool)):
        return str(value)
    return None


def flatten_json_record(record: dict[str, object], prefix: str = "") -> dict[str, str]:
    flattened: dict[str, str] = {}
    for key, value in record.items():
        safe_key = re.sub(r"[^A-Za-z0-9_]+", "_", key).strip("_")
        if not safe_key:
            continue
        full_key = f"{prefix}{safe_key}" if not prefix else f"{prefix}_{safe_key}"
        scalar = json_scalar_to_text(value)
        if scalar is not None:
            flattened[full_key] = scalar
            continue
        if isinstance(value, dict):
            for nested_key, nested_value in flatten_json_record(value, full_key).items():
                flattened[nested_key] = nested_value
    return flattened


def extract_json_records(payload: object) -> list[dict[str, object]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        list_keys = [key for key, value in payload.items() if isinstance(value, list)]
        if len(list_keys) == 1:
            return [item for item in payload[list_keys[0]] if isinstance(item, dict)]
        return [payload]
    return []


def infer_json_columns(records: list[dict[str, object]]) -> list[str]:
    frequencies: dict[str, int] = {}
    for record in records[:200]:
        for key in flatten_json_record(record):
            frequencies[key] = frequencies.get(key, 0) + 1
    ordered = sorted(frequencies.items(), key=lambda item: (-item[1], item[0]))
    return [key for key, _ in ordered[:JSON_MAX_INFERRED_COLUMNS]]


def ingest_json(conn: sqlite3.Connection, source: Path, table_name: str) -> int:
    with open_maybe_gzip(source) as handle:
        payload = json.load(handle)
    records = extract_json_records(payload)
    if not records:
        columns = ["record_id", "payload_json"]
        insert_sql = create_table(conn, table_name, columns)
        batch = list(iter_json_rows(payload))
        conn.executemany(insert_sql, batch)
        return len(batch)

    inferred_columns = infer_json_columns(records)
    columns = ["record_id", *inferred_columns, "payload_json"]
    insert_sql = create_table(conn, table_name, columns)
    batch: list[tuple[str, ...]] = []
    for index, record in enumerate(records, start=1):
        flattened = flatten_json_record(record)
        row = [pick_json_record_id(record, index)]
        row.extend(flattened.get(column, "") for column in inferred_columns)
        row.append(json.dumps(record, sort_keys=True))
        batch.append(tuple(row))
    conn.executemany(insert_sql, batch)
    return len(batch)


def detect_ingest_format(source: Path) -> str | None:
    name = source.name.lower()
    if any(name.endswith(suffix) for suffix in DELIMITED_SUFFIXES):
        return "delimited"
    if any(name.endswith(suffix) for suffix in FASTA_SUFFIXES):
        return "fasta"
    if any(name.endswith(suffix) for suffix in GFF_SUFFIXES):
        return "gff"
    if any(name.endswith(suffix) for suffix in GTF_SUFFIXES):
        return "gtf"
    if any(name.endswith(suffix) for suffix in JSON_SUFFIXES):
        return "json"
    return None


def ingest_source(
    conn: sqlite3.Connection,
    source: Path,
    table_name: str,
    no_header: bool = False,
) -> int:
    detected = detect_ingest_format(source)
    if detected == "delimited":
        return ingest_delimited(conn, source, table_name, no_header=no_header)
    if detected == "fasta":
        return ingest_fasta(conn, source, table_name)
    if detected in {"gff", "gtf"}:
        return ingest_feature_file(conn, source, table_name)
    if detected == "json":
        return ingest_json(conn, source, table_name)
    raise ValueError(f"unsupported ingest format: {source}")


def is_ingestable(path: Path) -> bool:
    return detect_ingest_format(path) is not None
