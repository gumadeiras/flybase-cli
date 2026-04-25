# FlyBase local sync/query

Use FlyBase bulk files for agent workloads. Live API: helper only.

## Why

- `https://api.flybase.org/api/v1.0/` exists.
- some endpoints return useful JSON now, eg `domain/FBgn0001250`, `sequence/id/FBgn0001250`.
- some plausible endpoints return empty body today.
- bulk bucket + release files: better for repeatable agent queries.

## Current surfaces checked

- release bucket: `https://s3ftp.flybase.org/releases/current/`
- precomputed files: `https://s3ftp.flybase.org/releases/current/precomputed_files/`
- Postgres dump: `https://s3ftp.flybase.org/releases/current/psql/FB2026_01.sql.gz`
- API root: `https://api.flybase.org/api/v1.0/`
- batch download: `https://flybase.org/batchdownload`

## Layout

- `src/flybase_cli/`: package code
- `tests/`: stdlib `unittest`
- `flybase_cli.py`: thin repo-root shim
- `pyproject.toml`: package metadata / console entrypoint

## CLI

```bash
python3 flybase_cli.py presets

python3 flybase_cli.py sync gene-core

python3 flybase_cli.py sync gene-core --release FB2026_01

PYTHONPATH=src python3 -m flybase_cli sync gene-expression

python3 flybase_cli.py manifest \
  --url https://s3ftp.flybase.org/genomes/Drosophila_melanogaster/dmel_r6.67_FB2026_01/fasta/ \
  --include 'miRNA'

python3 flybase_cli.py ingest \
  data/flybase/precomputed_files/genes/best_gene_summary_fb_2026_01.tsv.gz \
  data/flybase/precomputed_files/genes/fbgn_fbtr_fbpp_fb_2026_01.tsv.gz \
  data/flybase/precomputed_files/genes/fbgn_annotation_ID_fb_2026_01.tsv.gz

python3 flybase_cli.py tables --columns

python3 flybase_cli.py fts-build

python3 flybase_cli.py search 'memory formation'

python3 flybase_cli.py sql \
  "select * from fb_best_gene_summary_fb_2026_01 limit 5"

python3 flybase_cli.py sql \
  "select s.fbgn_id, s.gene_symbol, a.annotation_id, p.flybase_fbtr, p.flybase_fbpp \
   from fb_best_gene_summary_fb_2026_01 s \
   join fb_fbgn_annotation_id_fb_2026_01 a on a.primary_fbgn = s.fbgn_id \
   left join fb_fbgn_fbtr_fbpp_fb_2026_01 p on p.flybase_fbgn = s.fbgn_id \
   limit 5"

python3 flybase_cli.py api domain/FBgn0001250
```

## Sync presets

- `gene-core`: summaries + FBgn/FBtr/FBpp + annotation IDs + SO annotations
- `gene-expression`: curated/high-throughput/scRNA expression slices
- `references`: publication/link tables

## Ingest formats

- delimited: `tsv`, `csv`, gzipped variants
- sequence: `fasta`, `fa`, `fna`, `faa`, gzipped variants
- annotation: `gff`, `gff3`, `gtf`, gzipped variants
- JSON: `json`, `json.gz`

## Search

- `fts-build` creates a local SQLite FTS5 index from ingested tables
- `search` queries that index without calling the live FlyBase API
- record ids prefer stable FlyBase-like columns such as `fbgn_id`, `primary_fbgn`, `flybase_fbtr`

## Notes

- ingest path assumes delimited `tsv/csv` files only.
- many FlyBase files start with `##` metadata lines; loader skips those.
- `sync` writes a preset manifest under `data/flybase/manifests/<release>/`.
- `sync --release FB2026_01` defaults to `data/flybase/FB2026_01.sqlite` to avoid cross-release mixing.
- `manifest --url` lets you crawl non-`releases/` FlyBase directories such as genome FASTA/GFF trees.
- some FlyBase `.gff.gz` assets are tar-wrapped gzip archives; loader handles that transparently.
- SQLite keeps setup minimal; switch to DuckDB/Postgres if you want bigger joins/faster scans.
- if you only need a few IDs, FlyBase Batch Download may be simpler than syncing files.
- use `--no-header` for files whose first non-comment row is data, not column names.

## Tests

```bash
python3 -m unittest discover -s tests
```
