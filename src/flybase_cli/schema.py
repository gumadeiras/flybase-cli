from __future__ import annotations

import itertools
import re
import sqlite3
from pathlib import Path

from .config import SEARCH_ID_CANDIDATES
from .core import ensure_registry, list_registry_table_names, open_db, write_json
from .semantics import RELATIONSHIP_GROUPS, describe_column_name, infer_table_tags


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
    column_names = [column_name for _, column_name, *_ in columns_meta]
    columns = [
        {
            "name": column_name,
            **(
                {"description": description}
                if (description := describe_column_name(column_name))
                else {}
            ),
            "sample_values": sample_column_values(
                conn,
                table_name,
                column_name,
                sample_values,
            ),
        }
        for _, column_name, *_ in columns_meta
    ]
    return {
        "table_name": table_name,
        "source_path": source_path,
        "row_count": row_count,
        "column_count": len(column_names),
        "semantic_tags": infer_table_tags(table_name, source_path, column_names),
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
        return [
            description
            for table_name in selected
            for description in [describe_table(conn, table_name, sample_values=sample_values)]
            if description is not None
        ]
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


def infer_id_alias_relationships(tables: list[dict[str, object]]) -> list[dict[str, object]]:
    relationships: list[dict[str, object]] = []
    seen: set[tuple[str, str, str, str, str]] = set()

    for group, config in RELATIONSHIP_GROUPS.items():
        aliases = tuple(str(alias) for alias in config["aliases"])
        matches: list[tuple[str, str]] = []
        for table in tables:
            table_name = str(table["table_name"])
            columns = set(table_column_names(table))
            alias = next((candidate for candidate in aliases if candidate in columns), None)
            if alias is not None:
                matches.append((table_name, alias))
        for (left_table, left_column), (right_table, right_column) in itertools.combinations(matches, 2):
            key = tuple(sorted((left_table, right_table))) + (group, left_column, right_column)
            if key in seen:
                continue
            seen.add(key)
            kind = str(config["kind"])
            confidence = "high" if left_column == right_column else "medium"
            if kind == "id-alias":
                description = f"Shared {config['label']} identifiers inferred from column names."
            else:
                description = f"Shared {config['label']} identifiers inferred from column names."
            relationships.append(
                {
                    "kind": kind,
                    "entity": group,
                    "from_table": left_table,
                    "to_table": right_table,
                    "column_pairs": [{"from": left_column, "to": right_column}],
                    "confidence": confidence,
                    "description": description,
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


def select_alias_lines(alias: str, columns: list[str]) -> list[str]:
    return [
        f'  {alias}.{quote_identifier(column)} AS {quote_identifier(alias + "_" + safe_label(column))}'
        for column in columns
    ]


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
        "id": f"table-sample:{table_name}",
        "name": f"{table_name}-sample",
        "kind": "table-sample",
        "tables": [table_name],
        "description": f"Sample rows from {table_name}.",
        "sql": f'SELECT *\nFROM {quote_identifier(table_name)}\nLIMIT {limit}',
        "parameters": [],
        "semantic_tags": list(table.get("semantic_tags", [])),
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
        *select_alias_lines("src", from_projection),
        *select_alias_lines("dst", to_projection),
    ]
    on_clause = " AND\n".join(
        f'  src.{quote_identifier(str(pair["from"]))} = dst.{quote_identifier(str(pair["to"]))}'
        for pair in relationship["column_pairs"]
    )
    return {
        "id": f"join:{relationship['kind']}:{from_table_name}:{to_table_name}",
        "name": f"{from_table_name}-to-{to_table_name}",
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
        "parameters": [],
        "semantic_tags": sorted(
            set(from_table.get("semantic_tags", [])) | set(to_table.get("semantic_tags", []))
        ),
    }


def pick_first_column(table: dict[str, object], candidates: tuple[str, ...]) -> str | None:
    columns = set(table_column_names(table))
    return next((candidate for candidate in candidates if candidate in columns), None)


def select_projection(table: dict[str, object], preferred: list[str]) -> list[str]:
    columns = table_column_names(table)
    selected = [column for column in preferred if column in columns]
    if not selected:
        selected = pick_projection_columns(table, limit=4)
    return selected


def quoted_projection(columns: list[str]) -> str:
    return ", ".join(quote_identifier(column) for column in columns)


def build_named_template(
    *,
    template_id: str,
    name: str,
    table: dict[str, object],
    description: str,
    sql: str,
    parameters: list[dict[str, str]],
    semantic_tags: list[str],
) -> dict[str, object]:
    return {
        "id": template_id,
        "name": name,
        "kind": "named",
        "tables": [str(table["table_name"])],
        "description": description,
        "sql": sql,
        "parameters": parameters,
        "semantic_tags": semantic_tags,
    }


def build_gene_summary_templates(table: dict[str, object], limit: int) -> list[dict[str, object]]:
    table_name = str(table["table_name"])
    gene_column = pick_first_column(table, tuple(str(alias) for alias in RELATIONSHIP_GROUPS["fbgn"]["aliases"]))
    summary_column = next(
        (column for column in table_column_names(table) if "summary" in column.lower()),
        None,
    )
    symbol_column = pick_first_column(table, ("gene_symbol", "symbol"))
    if gene_column is None or summary_column is None:
        return []
    projection = select_projection(table, [gene_column, symbol_column or "", summary_column])
    templates = [
        build_named_template(
            template_id=f"named:gene-summary-by-fbgn:{table_name}",
            name="gene-summary-by-fbgn",
            table=table,
            description=f"Look up gene summaries in {table_name} by FlyBase gene identifier.",
            sql="\n".join(
                [
                    f"SELECT {quoted_projection(projection)}",
                    f"FROM {quote_identifier(table_name)}",
                    f"WHERE {quote_identifier(gene_column)} = :fbgn_id",
                    f"LIMIT {limit}",
                ]
            ),
            parameters=[
                {
                    "name": "fbgn_id",
                    "example": "FBgn0002121",
                    "description": "FlyBase gene identifier.",
                }
            ],
            semantic_tags=sorted(set(table.get("semantic_tags", [])) | {"gene", "summary"}),
        )
    ]
    if symbol_column is not None:
        templates.append(
            build_named_template(
                template_id=f"named:gene-summary-by-symbol:{table_name}",
                name="gene-summary-by-symbol",
                table=table,
                description=f"Look up gene summaries in {table_name} by gene symbol.",
                sql="\n".join(
                    [
                        f"SELECT {quoted_projection(projection)}",
                        f"FROM {quote_identifier(table_name)}",
                        f"WHERE {quote_identifier(symbol_column)} = :gene_symbol",
                        f"LIMIT {limit}",
                    ]
                ),
                parameters=[
                    {
                        "name": "gene_symbol",
                        "example": "amx",
                        "description": "Gene symbol.",
                    }
                ],
                semantic_tags=sorted(set(table.get("semantic_tags", [])) | {"gene", "summary"}),
            )
        )
    return templates


def build_link_templates(table: dict[str, object], limit: int) -> list[dict[str, object]]:
    table_name = str(table["table_name"])
    gene_column = pick_first_column(table, tuple(str(alias) for alias in RELATIONSHIP_GROUPS["fbgn"]["aliases"]))
    transcript_column = pick_first_column(table, tuple(str(alias) for alias in RELATIONSHIP_GROUPS["fbtr"]["aliases"]))
    protein_column = pick_first_column(table, tuple(str(alias) for alias in RELATIONSHIP_GROUPS["fbpp"]["aliases"]))
    if transcript_column is None or protein_column is None:
        return []
    projection = select_projection(
        table,
        [gene_column or "", transcript_column, protein_column],
    )
    filters: list[tuple[str, str, str, str]] = []
    if gene_column is not None:
        filters.append(("transcript-protein-links", gene_column, "fbgn_id", "FBgn0002121"))
    filters.append(("transcript-protein-links-by-transcript", transcript_column, "fbtr_id", "FBtr0080001"))
    templates: list[dict[str, object]] = []
    for name, column, parameter, example in filters:
        templates.append(
            build_named_template(
                template_id=f"named:{name}:{table_name}",
                name=name,
                table=table,
                description=f"Resolve linked transcript/protein rows in {table_name}.",
                sql="\n".join(
                    [
                        f"SELECT {quoted_projection(projection)}",
                        f"FROM {quote_identifier(table_name)}",
                        f"WHERE {quote_identifier(column)} = :{parameter}",
                        f"LIMIT {limit}",
                    ]
                ),
                parameters=[
                    {
                        "name": parameter,
                        "example": example,
                        "description": f"Filter value for {column}.",
                    }
                ],
                semantic_tags=sorted(set(table.get("semantic_tags", [])) | {"transcript", "protein"}),
            )
        )
    return templates


def build_publication_templates(table: dict[str, object], limit: int) -> list[dict[str, object]]:
    table_name = str(table["table_name"])
    gene_column = pick_first_column(table, tuple(str(alias) for alias in RELATIONSHIP_GROUPS["fbgn"]["aliases"]))
    publication_column = pick_first_column(
        table,
        tuple(str(alias) for alias in RELATIONSHIP_GROUPS["publication"]["aliases"]),
    )
    if gene_column is None or publication_column is None:
        return []
    projection = select_projection(table, [gene_column, publication_column, "record_id"])
    return [
        build_named_template(
            template_id=f"named:publications-for-gene:{table_name}",
            name="publications-for-gene",
            table=table,
            description=f"Find publication-linked rows in {table_name} for a gene.",
            sql="\n".join(
                [
                    f"SELECT {quoted_projection(projection)}",
                    f"FROM {quote_identifier(table_name)}",
                    f"WHERE {quote_identifier(gene_column)} = :fbgn_id",
                    f"LIMIT {limit}",
                ]
            ),
            parameters=[
                {
                    "name": "fbgn_id",
                    "example": "FBgn0002121",
                    "description": "FlyBase gene identifier.",
                }
            ],
            semantic_tags=sorted(set(table.get("semantic_tags", [])) | {"gene", "publication"}),
        )
    ]


def build_coordinate_templates(table: dict[str, object], limit: int) -> list[dict[str, object]]:
    table_name = str(table["table_name"])
    transcript_column = pick_first_column(table, ("transcript_id", "fbtr_id", "primary_fbtr", "flybase_fbtr"))
    feature_column = pick_first_column(table, ("feature_id", "parent_id", "record_id"))
    coordinate_columns = [
        column
        for column in ("seqid", "start", "end", "strand", "startPosition", "endPosition")
        if column in table_column_names(table)
    ]
    if not coordinate_columns:
        return []
    if transcript_column is not None:
        filter_column = transcript_column
        parameter = ("transcript_id", "FBtr0080001")
        name = "coordinates-for-transcript"
    elif feature_column is not None:
        filter_column = feature_column
        parameter = ("feature_id", "FBgn0002121")
        name = "coordinates-for-feature"
    else:
        return []
    projection = select_projection(table, [filter_column, *coordinate_columns])
    return [
        build_named_template(
            template_id=f"named:{name}:{table_name}",
            name=name,
            table=table,
            description=f"Fetch coordinate rows from {table_name}.",
            sql="\n".join(
                [
                    f"SELECT {quoted_projection(projection)}",
                    f"FROM {quote_identifier(table_name)}",
                    f"WHERE {quote_identifier(filter_column)} = :{parameter[0]}",
                    f"LIMIT {limit}",
                ]
            ),
            parameters=[
                {
                    "name": parameter[0],
                    "example": parameter[1],
                    "description": f"Filter value for {filter_column}.",
                }
            ],
            semantic_tags=sorted(set(table.get("semantic_tags", [])) | {"coordinates"}),
        )
    ]


def build_biological_query_templates(
    tables: list[dict[str, object]],
    limit: int,
) -> list[dict[str, object]]:
    templates: list[dict[str, object]] = []
    for table in tables:
        templates.extend(build_gene_summary_templates(table, limit))
        templates.extend(build_link_templates(table, limit))
        templates.extend(build_publication_templates(table, limit))
        templates.extend(build_coordinate_templates(table, limit))
    return templates


def dedupe_templates(templates: list[dict[str, object]]) -> list[dict[str, object]]:
    deduped: dict[str, dict[str, object]] = {}
    for template in templates:
        deduped[str(template["id"])] = template
    return list(deduped.values())


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
    templates.extend(build_biological_query_templates(tables, limit))
    return dedupe_templates(templates)


def collect_schema_details(
    db_path: Path,
    table_names: list[str] | None = None,
    sample_values: int = 3,
    query_limit: int = 5,
) -> tuple[list[dict[str, object]], list[dict[str, object]], list[dict[str, object]]]:
    tables = describe_tables(
        db_path,
        table_names=table_names,
        sample_values=sample_values,
    )
    relationships = infer_schema_relationships(tables)
    query_templates = build_query_templates(tables, relationships, limit=query_limit)
    return tables, relationships, query_templates


def semantic_summary(tables: list[dict[str, object]]) -> dict[str, object]:
    tag_counts: dict[str, int] = {}
    for table in tables:
        for tag in table.get("semantic_tags", []):
            key = str(tag)
            tag_counts[key] = tag_counts.get(key, 0) + 1
    return {
        "tags": sorted(tag_counts),
        "tag_counts": dict(sorted(tag_counts.items())),
    }


def build_schema_summary(
    db_path: Path,
    table_names: list[str] | None = None,
    sample_values: int = 3,
    query_limit: int = 5,
) -> dict[str, object]:
    tables, relationships, query_templates = collect_schema_details(
        db_path,
        table_names=table_names,
        sample_values=sample_values,
        query_limit=query_limit,
    )
    return {
        "db_path": str(db_path),
        "table_count": len(tables),
        "tables": tables,
        "semantic_summary": semantic_summary(tables),
        "relationships": relationships,
        "query_templates": query_templates,
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
    tables, relationships, query_templates = collect_schema_details(
        db_path,
        table_names=table_names,
        sample_values=sample_values,
        query_limit=limit,
    )
    return {
        "db_path": str(db_path),
        "table_count": len(tables),
        "relationship_count": len(relationships),
        "semantic_summary": semantic_summary(tables),
        "queries": query_templates,
    }
