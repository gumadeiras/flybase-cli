# AGENTS.md

## Git

- Commit with `scripts/committer "<subject>" -- <path>...`; it stages only listed paths. Use `--body` or `--body-file` for commit bodies.

## Release

- Use `./scripts/release check <version>` for local preflight.
- Use `./scripts/release run <version>` only after explicit release approval.
- Tag pushes run the release workflow, publish GitHub assets, publish PyPI, and update `gumadeiras/homebrew-tap`.

## Goal

Use `flybase` to fetch FlyBase data into local files + SQLite, then query locally first.

## Defaults

- Prefer bulk files over the live API.
- Prefer local SQLite over repeated re-fetches.
- Prefer `schema-export` before ad hoc SQL.
- Pin releases for reproducibility: `--release FB2026_01`.

## Fast path

1. Sync data.
2. Export schema metadata.
3. Inspect `query-plan` / `query-run` if a named template fits.
4. Query locally with `sql` or `search`.
5. Use `api` only for narrow live lookups not present locally.

## Fetch

Core gene tables:

```bash
python3 flybase_cli.py sync gene-core --release FB2026_01
python3 flybase_cli.py sync gene-knowledge --release FB2026_01
python3 flybase_cli.py full-sync --release FB2026_01
python3 flybase_cli.py sync-incremental gene-knowledge --from-release FB2025_06 --release FB2026_01
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
python3 flybase_cli.py query-run --db data/flybase/FB2026_01.sqlite --template-name gene-summary-by-fbgn --param fbgn_id=FBgn0002121
```

Query locally:

```bash
python3 flybase_cli.py sql --db data/flybase/FB2026_01.sqlite "select * from fb_best_gene_summary_fb_2026_01 limit 5"
python3 flybase_cli.py fts-build --db data/flybase/FB2026_01.sqlite
python3 flybase_cli.py search --db data/flybase/FB2026_01.sqlite 'memory formation'
```

## Gene lookup playbook

For a gene symbol like `Or59b`:

1. Resolve the stable gene id first.

```bash
python3 flybase_cli.py query-run \
  --db data/flybase/FB2026_01.sqlite \
  --template-name gene-summary-by-symbol \
  --param gene_symbol=Or59b
```

2. Use the returned `fbgn_id` as the join key across local tables.

3. If a named template exists, prefer it over ad hoc SQL.

4. If table or column names are unclear, inspect schema directly.

```bash
python3 flybase_cli.py query-plan --db data/flybase/FB2026_01.sqlite --limit 10
sqlite3 -json data/flybase/FB2026_01.sqlite "pragma table_info('fb_entity_publication_fb_2026_01');"
```

5. Typical follow-up tables for one gene:

- `fb_fbgn_annotation_id_fb_<release>`
- `fb_fbgn_fbtr_fbpp_fb_<release>`
- `fb_gene_map_table_fb_<release>`
- `fb_curated_expression_fb_<release>`
- `fb_high_throughput_gene_expression_fb_<release>`
- `fb_entity_publication_fb_<release>`
- `fb_representative_publications_fb_<release>`
- `fb_dmel_gene_sequence_ontology_annotations_fb_<release>`

6. Build FTS before using `search`.

```bash
python3 flybase_cli.py fts-build --db data/flybase/FB2026_01.sqlite
python3 flybase_cli.py search --db data/flybase/FB2026_01.sqlite 'Or59b'
```

## Schema hints

- `schema-export` writes `<db>.schema.json`.
- Use `tables` + `columns` for available surfaces.
- Use `semantic_tags` / `semantic_summary` to narrow tables before writing SQL.
- Use `relationships` from `schema-export` for joins.
- Use `query_templates` from `schema-export` or `query-plan` for ready SQL.
- Prefer named templates for common biological questions; execute with `query-run`.
- Nested JSON child tables use lineage columns like `parent_record_id`, `parent_ordinal`, `ordinal`.
- `full-sync` is the broad offline release path; default mode skips non-ingestable artifacts like zip bundles.

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

## Changelog

- Keep `CHANGELOG.md` updated for user-facing changes. If a commit adds a feature, fix, behavior change, CLI change, GUI change, output-format change, install/release change, or other user-visible change, add or update an entry under the top `Unreleased` section in the same commit.
- Never edit released changelog sections for current work. Corrections, renames, and behavior changes after a release must be recorded only under the top `Unreleased` section unless Gustavo explicitly asks for release-history repair.
- Use these sections when they apply: `Features`, `Fixes`, and `Changes`.
- Omit empty sections.
- Write user-facing entries instead of repository chore notes.
- Do not include pure tests, internal refactors, CI-only changes, or docs-only changes unless they affect user behavior, API, installation, or usage.
