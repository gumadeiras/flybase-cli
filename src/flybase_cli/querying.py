from __future__ import annotations

import re
from pathlib import Path

from .config import SEARCH_ID_CANDIDATES
from .core import open_db
from .schema import build_query_plan


PARAM_PATTERN = re.compile(r":([A-Za-z_][A-Za-z0-9_]*)")


def parse_cli_params(items: list[str] | None) -> dict[str, str]:
    params: dict[str, str] = {}
    for item in items or []:
        if "=" not in item:
            raise ValueError(f"invalid parameter assignment: {item}")
        key, value = item.split("=", 1)
        clean_key = key.strip()
        if not clean_key:
            raise ValueError(f"invalid parameter assignment: {item}")
        params[clean_key] = value
    return params


def required_parameters(sql: str) -> list[str]:
    seen: list[str] = []
    for match in PARAM_PATTERN.findall(sql):
        if match not in seen:
            seen.append(match)
    return seen


def row_to_record(columns: list[str], row: tuple[object, ...]) -> dict[str, object]:
    return dict(zip(columns, row, strict=True))


def summarize_records(columns: list[str], records: list[dict[str, object]], truncated: bool) -> dict[str, object]:
    populated_columns = [
        column
        for column in columns
        if any(record.get(column) not in {None, ""} for record in records)
    ]
    return {
        "column_count": len(columns),
        "row_count_shown": len(records),
        "truncated": truncated,
        "identifier_columns": [
            column
            for column in columns
            if column in SEARCH_ID_CANDIDATES or column.endswith("_id") or column.endswith("Id")
        ],
        "populated_columns": populated_columns,
    }


def execute_sql(
    db_path: Path,
    query: str,
    *,
    params: dict[str, object] | None = None,
    limit: int = 20,
    output_format: str = "records",
) -> dict[str, object]:
    conn = open_db(db_path)
    try:
        cursor = conn.execute(query, params or {})
        if cursor.description is None:
            conn.commit()
            return {
                "query": query,
                "parameters": params or {},
                "status": "ok",
            }

        columns = [description[0] for description in cursor.description]
        fetched = cursor.fetchmany(limit + 1)
        truncated = len(fetched) > limit
        rows = fetched[:limit]
        records = [row_to_record(columns, row) for row in rows]
        payload: dict[str, object] = {
            "query": query,
            "parameters": params or {},
            "columns": columns,
            "summary": summarize_records(columns, records, truncated),
        }
        if output_format == "rows":
            payload["rows"] = rows
        else:
            payload["records"] = records
        return payload
    finally:
        conn.close()


def select_query_template(
    queries: list[dict[str, object]],
    *,
    template_id: str | None = None,
    template_name: str | None = None,
    kind: str | None = None,
    table_name: str | None = None,
) -> dict[str, object]:
    matches = queries
    if template_id:
        matches = [query for query in matches if query.get("id") == template_id]
    if template_name:
        matches = [query for query in matches if query.get("name") == template_name]
    if kind:
        matches = [query for query in matches if query.get("kind") == kind]
    if table_name:
        matches = [
            query
            for query in matches
            if table_name in [str(name) for name in query.get("tables", [])]
        ]
    if not matches:
        raise ValueError("no query template matched the requested selector")
    return matches[0]


def run_query_template(
    db_path: Path,
    *,
    template_id: str | None = None,
    template_name: str | None = None,
    kind: str | None = None,
    table_name: str | None = None,
    params: dict[str, str] | None = None,
    sample_values: int = 1,
    plan_limit: int = 5,
    result_limit: int = 20,
    output_format: str = "records",
) -> dict[str, object]:
    plan = build_query_plan(
        db_path,
        sample_values=sample_values,
        limit=plan_limit,
    )
    selected = select_query_template(
        plan["queries"],
        template_id=template_id,
        template_name=template_name,
        kind=kind,
        table_name=table_name,
    )
    provided_params = params or {}
    missing = [name for name in required_parameters(str(selected["sql"])) if name not in provided_params]
    if missing:
        raise ValueError(f"missing template parameters: {', '.join(missing)}")
    result = execute_sql(
        db_path,
        str(selected["sql"]),
        params=provided_params,
        limit=result_limit,
        output_format=output_format,
    )
    return {
        "selected_query": selected,
        "result": result,
    }
