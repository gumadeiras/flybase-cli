# AGENTS.md

## Goal

Use `flybase-cli` to fetch FlyBase data into local files + SQLite, then query locally first.

## Defaults

- Prefer bulk files over the live API.
- Prefer local SQLite over repeated re-fetches.
- Prefer `schema-export` before ad hoc SQL.
- Pin releases for reproducibility: `--release FB2026_01`.

## Fast path

1. Sync data.
2. Export schema metadata.
3. Query locally with `sql` or `search`.
4. Use `api` only for narrow live lookups not present locally.

## Fetch

Core gene tables:

```bash
python3 flybase_cli.py sync gene-core --release FB2026_01
```

Genome assets:

```bash
python3 flybase_cli.py genomes --release FB2026_01
python3 flybase_cli.py sync-genome --release FB2026_01 --genome dmel_r6.67 --preset mirna-fasta
```

Arbitrary FlyBase directories:

```bash
python3 flybase_cli.py sync-url --url <flybase-directory-url> --include '<regex>'
```

## Consume

Inspect available tables:

```bash
python3 flybase_cli.py tables --db data/flybase/FB2026_01.sqlite --columns
python3 flybase_cli.py describe --db data/flybase/FB2026_01.sqlite --sample-values 1
python3 flybase_cli.py schema-export --db data/flybase/FB2026_01.sqlite --sample-values 1
python3 flybase_cli.py query-plan --db data/flybase/FB2026_01.sqlite --sample-values 1 --limit 5
```

Query locally:

```bash
python3 flybase_cli.py sql --db data/flybase/FB2026_01.sqlite "select * from fb_best_gene_summary_fb_2026_01 limit 5"
python3 flybase_cli.py fts-build --db data/flybase/FB2026_01.sqlite
python3 flybase_cli.py search --db data/flybase/FB2026_01.sqlite 'memory formation'
```

## Schema hints

- `schema-export` writes `<db>.schema.json`.
- Use `tables` + `columns` for available surfaces.
- Use `relationships` from `schema-export` for joins.
- Use `query_templates` from `schema-export` or `query-plan` for ready SQL.
- Nested JSON child tables use lineage columns like `parent_record_id`, `parent_ordinal`, `ordinal`.

## Online fallback

Use live API only when:

- the data is not synced locally
- you need a narrow point lookup
- you need current live behavior rather than a pinned release snapshot

Example:

```bash
python3 flybase_cli.py api domain/FBgn0001250
```

## Notes

- Some FlyBase API endpoints are uneven; local bulk data is the reliable path.
- JSON ingest can emit child/descendant tables.
- For large analytical workloads, keep one DB per release.
