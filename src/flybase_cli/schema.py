from __future__ import annotations

import itertools
import re
import sqlite3
from pathlib import Path

from .config import SEARCH_ID_CANDIDATES
from .core import ensure_registry, list_registry_table_names, open_db, write_json


def sample_column_values(
    conn: sqlite3.Connection,
    table_name: str,
    column_name: str,
    limit: int,
) -> list[str]:
    if limit <= 0:
        return []
    rows = conn.execute(
        f'''
        SELECT "{column_name}"
        FROM "{table_name}"
        WHERE "{column_name}" IS NOT NULL AND TRIM(CAST("{column_name}" AS TEXT)) != ''
        LIMIT ?
        ''',
        (limit,),
    ).fetchall()
    return [str(row[0]) for row in rows]


def describe_table(
    conn: sqlite3.Connection,
    table_name: str,
    sample_values: int = 3,
) -> dict[str, object] | None:
    row = conn.execute(
        """
        SELECT source_path, row_count
        FROM fb_ingest_registry
        WHERE table_name = ?
        """,
        (table_name,),
    ).fetchone()
    if row is None:
        return None
    source_path, row_count = row
    columns_meta = conn.execute(f'PRAGMA table_info("{table_name}")').fetchall()
    columns = []
    for meta in columns_meta:
        column_name = meta[1]
        columns.append(
            {
                "name": column_name,
                "sample_values": sample_column_values(
                    conn,
                    table_name,
                    column_name,
                    sample_values,
                ),
            }
        )
    return {
        "table_name": table_name,
        "source_path": source_path,
        "row_count": row_count,
        "columns": columns,
    }


def describe_tables(
    db_path: Path,
    table_names: list[str] | None = None,
    sample_values: int = 3,
) -> list[dict[str, object]]:
    conn = open_db(db_path)
    ensure_registry(conn)
    try:
        selected = table_names or list_registry_table_names(conn)
        descriptions: list[dict[str, object]] = []
        for table_name in selected:
            description = describe_table(conn, table_name, sample_values=sample_values)
            if description is not None:
                descriptions.append(description)
        return descriptions
    finally:
        conn.close()


def table_column_names(table: dict[str, object]) -> list[str]:
    return [str(column["name"]) for column in table["columns"]]


def lineage_reference_columns(columns: list[str]) -> list[str]:
    ordered: list[tuple[int, str]] = []
    for column in columns:
        match = re.fullmatch(r"ancestor_ordinal_(\d+)", column)
        if match:
            ordered.append((int(match.group(1)), column))
    lineage = [column for _, column in sorted(ordered)]
    if "parent_ordinal" in columns:
        lineage.append("parent_ordinal")
    return lineage


def lineage_key_columns(columns: list[str]) -> list[str]:
    lineage = lineage_reference_columns(columns)
    if "ordinal" in columns:
        lineage.append("ordinal")
    return lineage


def infer_lineage_relationship(
    child: dict[str, object],
    tables_by_name: dict[str, dict[str, object]],
) -> dict[str, object] | None:
    child_name = str(child["table_name"])
    child_columns = table_column_names(child)
    if "parent_record_id" not in child_columns:
        return None

    candidates = [
        table_name
        for table_name in tables_by_name
        if table_name != child_name and child_name.startswith(f"{table_name}_")
    ]
    if not candidates:
        return None
    parent_name = max(candidates, key=len)
    parent = tables_by_name[parent_name]
    parent_columns = table_column_names(parent)
    child_refs = lineage_reference_columns(child_columns)

    if "record_id" in parent_columns and not child_refs:
        return {
            "kind": "lineage",
            "from_table": child_name,
            "to_table": parent_name,
            "column_pairs": [{"from": "parent_record_id", "to": "record_id"}],
            "confidence": "high",
            "description": "Nested child table joins to its parent record_id.",
        }

    if "parent_record_id" not in parent_columns:
        return None
    parent_keys = lineage_key_columns(parent_columns)
    if len(child_refs) != len(parent_keys):
        return None
    return {
        "kind": "lineage",
        "from_table": child_name,
        "to_table": parent_name,
        "column_pairs": [
            {"from": "parent_record_id", "to": "parent_record_id"},
            *[
                {"from": from_column, "to": to_column}
                for from_column, to_column in zip(child_refs, parent_keys, strict=True)
            ],
        ],
        "confidence": "high",
        "description": "Nested child table joins to its direct parent via lineage columns.",
    }


ID_ALIAS_GROUPS: dict[str, tuple[str, ...]] = {
    "fbgn": ("fbgn_id", "primary_fbgn", "flybase_fbgn"),
    "fbtr": ("fbtr_id", "primary_fbtr", "flybase_fbtr"),
    "fbpp": ("fbpp_id", "primary_fbpp", "flybase_fbpp"),
}


def infer_id_alias_relationships(tables: list[dict[str, object]]) -> list[dict[str, object]]:
    relationships: list[dict[str, object]] = []
    seen: set[tuple[str, str, str]] = set()

    for group, aliases in ID_ALIAS_GROUPS.items():
        matches: list[tuple[str, str]] = []
        for table in tables:
            table_name = str(table["table_name"])
            columns = set(table_column_names(table))
            alias = next((candidate for candidate in aliases if candidate in columns), None)
            if alias is not None:
                matches.append((table_name, alias))
        for (left_table, left_column), (right_table, right_column) in itertools.combinations(matches, 2):
            key = (group, left_table, right_table)
            if key in seen:
                continue
            seen.add(key)
            relationships.append(
                {
                    "kind": "id-alias",
                    "entity": group,
                    "from_table": left_table,
                    "to_table": right_table,
                    "column_pairs": [{"from": left_column, "to": right_column}],
                    "confidence": "medium",
                    "description": f"Shared FlyBase {group} identifiers inferred from column names.",
                }
            )
    return relationships


def infer_schema_relationships(tables: list[dict[str, object]]) -> list[dict[str, object]]:
    tables_by_name = {str(table["table_name"]): table for table in tables}
    relationships = []
    for table in tables:
        relationship = infer_lineage_relationship(table, tables_by_name)
        if relationship is not None:
            relationships.append(relationship)
    relationships.extend(infer_id_alias_relationships(tables))
    return relationships


def quote_identifier(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def safe_label(identifier: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_]+", "_", identifier).strip("_")
    return cleaned or "value"


def projection_priority(column_name: str) -> tuple[int, str]:
    if column_name == "payload_json":
        return (999, column_name)
    if column_name == "record_id":
        return (0, column_name)
    if column_name in {"parent_record_id", "parent_ordinal", "ordinal"}:
        return (1, column_name)
    if column_name in SEARCH_ID_CANDIDATES:
        return (2, column_name)
    if column_name in {"symbol", "gene_symbol", "annotation_id", "feature_id"}:
        return (3, column_name)
    if column_name.endswith("_id") or column_name.endswith("Id"):
        return (4, column_name)
    return (10, column_name)


def pick_projection_columns(table: dict[str, object], limit: int = 3) -> list[str]:
    columns = table_column_names(table)
    ranked = sorted(columns, key=projection_priority)
    selected = [column for column in ranked if column != "payload_json"][:limit]
    return selected or columns[:limit]


def build_table_sample_query(table: dict[str, object], limit: int) -> dict[str, object]:
    table_name = str(table["table_name"])
    return {
        "kind": "table-sample",
        "tables": [table_name],
        "description": f"Sample rows from {table_name}.",
        "sql": f'SELECT *\nFROM {quote_identifier(table_name)}\nLIMIT {limit}',
    }


def build_relationship_query(
    relationship: dict[str, object],
    tables_by_name: dict[str, dict[str, object]],
    limit: int,
) -> dict[str, object] | None:
    from_table_name = str(relationship["from_table"])
    to_table_name = str(relationship["to_table"])
    from_table = tables_by_name.get(from_table_name)
    to_table = tables_by_name.get(to_table_name)
    if from_table is None or to_table is None:
        return None

    from_projection = pick_projection_columns(from_table)
    to_projection = pick_projection_columns(to_table)
    select_lines = [
        f'  src.{quote_identifier(column)} AS {quote_identifier("src_" + safe_label(column))}'
        for column in from_projection
    ]
    select_lines.extend(
        f'  dst.{quote_identifier(column)} AS {quote_identifier("dst_" + safe_label(column))}'
        for column in to_projection
    )
    on_clause = " AND\n".join(
        f'  src.{quote_identifier(str(pair["from"]))} = dst.{quote_identifier(str(pair["to"]))}'
        for pair in relationship["column_pairs"]
    )
    return {
        "kind": "join",
        "relationship_kind": relationship["kind"],
        "tables": [from_table_name, to_table_name],
        "description": str(relationship["description"]),
        "sql": "\n".join(
            [
                "SELECT",
                ",\n".join(select_lines),
                f"FROM {quote_identifier(from_table_name)} AS src",
                f"JOIN {quote_identifier(to_table_name)} AS dst",
                "ON",
                on_clause,
                f"LIMIT {limit}",
            ]
        ),
    }


def build_query_templates(
    tables: list[dict[str, object]],
    relationships: list[dict[str, object]],
    limit: int = 5,
) -> list[dict[str, object]]:
    templates = [build_table_sample_query(table, limit) for table in tables]
    tables_by_name = {str(table["table_name"]): table for table in tables}
    for relationship in relationships:
        template = build_relationship_query(relationship, tables_by_name, limit)
        if template is not None:
            templates.append(template)
    return templates


def build_schema_summary(
    db_path: Path,
    table_names: list[str] | None = None,
    sample_values: int = 3,
    query_limit: int = 5,
) -> dict[str, object]:
    tables = describe_tables(
        db_path,
        table_names=table_names,
        sample_values=sample_values,
    )
    relationships = infer_schema_relationships(tables)
    return {
        "db_path": str(db_path),
        "table_count": len(tables),
        "tables": tables,
        "relationships": relationships,
        "query_templates": build_query_templates(tables, relationships, limit=query_limit),
    }


def export_schema_summary(
    db_path: Path,
    output_path: Path,
    table_names: list[str] | None = None,
    sample_values: int = 3,
    query_limit: int = 5,
) -> dict[str, object]:
    payload = build_schema_summary(
        db_path,
        table_names=table_names,
        sample_values=sample_values,
        query_limit=query_limit,
    )
    write_json(output_path, payload)
    return payload


def build_query_plan(
    db_path: Path,
    table_names: list[str] | None = None,
    sample_values: int = 3,
    limit: int = 5,
) -> dict[str, object]:
    summary = build_schema_summary(
        db_path,
        table_names=table_names,
        sample_values=sample_values,
        query_limit=limit,
    )
    return {
        "db_path": summary["db_path"],
        "table_count": summary["table_count"],
        "relationship_count": len(summary["relationships"]),
        "queries": summary["query_templates"],
    }
