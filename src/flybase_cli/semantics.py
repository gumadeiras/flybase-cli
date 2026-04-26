from __future__ import annotations


COLUMN_DESCRIPTION_HINTS: dict[str, str] = {
    "record_id": "Primary row identifier for this table.",
    "parent_record_id": "Parent record identifier from a nested JSON source row.",
    "parent_ordinal": "Ordinal position of the direct parent row within a repeated list.",
    "ordinal": "Ordinal position within a repeated list.",
    "value": "Scalar value from a repeated JSON list.",
    "payload_json": "Full raw JSON payload for the source record.",
    "fbgn_id": "FlyBase gene identifier.",
    "primary_fbgn": "FlyBase gene identifier alias.",
    "flybase_fbgn": "FlyBase gene identifier alias.",
    "fbtr_id": "FlyBase transcript identifier.",
    "primary_fbtr": "FlyBase transcript identifier alias.",
    "flybase_fbtr": "FlyBase transcript identifier alias.",
    "fbpp_id": "FlyBase protein identifier.",
    "primary_fbpp": "FlyBase protein identifier alias.",
    "flybase_fbpp": "FlyBase protein identifier alias.",
    "annotation_id": "Genome annotation identifier.",
    "feature_id": "Feature identifier from GFF or GTF annotations.",
    "feature_name": "Feature symbol or display name.",
    "gene_symbol": "Gene symbol.",
    "symbol": "Feature symbol.",
    "seqid": "Sequence or chromosome identifier.",
    "start": "Genomic start coordinate.",
    "end": "Genomic end coordinate.",
    "strand": "Genomic strand.",
    "summary": "Free-text summary field.",
}

RELATIONSHIP_GROUPS: dict[str, dict[str, object]] = {
    "fbgn": {
        "aliases": ("fbgn_id", "primary_fbgn", "flybase_fbgn"),
        "kind": "id-alias",
        "label": "FlyBase fbgn",
    },
    "fbtr": {
        "aliases": ("fbtr_id", "primary_fbtr", "flybase_fbtr", "transcript_id"),
        "kind": "id-alias",
        "label": "FlyBase fbtr/transcript",
    },
    "fbpp": {
        "aliases": ("fbpp_id", "primary_fbpp", "flybase_fbpp"),
        "kind": "id-alias",
        "label": "FlyBase fbpp",
    },
    "publication": {
        "aliases": ("fbrf", "fbrf_id", "reference_id", "publication_id", "pmid"),
        "kind": "shared-id",
        "label": "publication",
    },
    "annotation": {
        "aliases": ("annotation_id", "feature_id"),
        "kind": "shared-id",
        "label": "annotation",
    },
}


def describe_column_name(column_name: str) -> str:
    hinted = COLUMN_DESCRIPTION_HINTS.get(column_name)
    if hinted is not None:
        return hinted
    lowered = column_name.lower()
    if lowered.endswith("_json"):
        return "Raw JSON payload for this nested structure."
    if lowered.endswith("_id") or lowered.endswith("id"):
        return "Identifier column."
    if "summary" in lowered or "description" in lowered:
        return "Free-text description or summary field."
    if lowered.endswith("symbol") or lowered == "symbol":
        return "Symbol or short label."
    if lowered in {"startposition", "endposition"}:
        return "Genomic coordinate from a nested JSON location record."
    return ""


def infer_table_tags(table_name: str, source_path: str, columns: list[str]) -> list[str]:
    name_blob = " ".join([table_name, source_path]).lower()
    lowered_columns = {column.lower() for column in columns}
    tags: set[str] = set()

    if any(alias in lowered_columns for alias in RELATIONSHIP_GROUPS["fbgn"]["aliases"]) or {
        "gene_symbol",
        "symbol",
    } & lowered_columns:
        tags.add("gene")
    if any(alias in lowered_columns for alias in RELATIONSHIP_GROUPS["fbtr"]["aliases"]):
        tags.add("transcript")
    if any(alias in lowered_columns for alias in RELATIONSHIP_GROUPS["fbpp"]["aliases"]):
        tags.add("protein")
    if any(alias in lowered_columns for alias in RELATIONSHIP_GROUPS["publication"]["aliases"]):
        tags.add("publication")
    if any(alias in lowered_columns for alias in RELATIONSHIP_GROUPS["annotation"]["aliases"]):
        tags.add("annotation")
    if {"seqid", "start", "end", "startposition", "endposition"} & lowered_columns:
        tags.add("coordinates")
    if "summary" in name_blob or "summary" in lowered_columns:
        tags.add("summary")
    if "expression" in name_blob or "rpkm" in name_blob or "scrna" in name_blob:
        tags.add("expression")
    if "ortholog" in name_blob or "paralog" in name_blob:
        tags.add("orthology")
    if "interaction" in name_blob:
        tags.add("interaction")
    if "publication" in name_blob or "reference" in name_blob:
        tags.add("reference")
    if "payload_json" in lowered_columns:
        tags.add("json")
    if "parent_record_id" in lowered_columns:
        tags.add("nested")

    return sorted(tags)
