# FlyBase local sync/query

> This package has been renamed. Install `flybase` now:
> `pipx install flybase`

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

## Install

PyPI with `pipx`:

```bash
pipx install flybase-cli
```

PyPI with plain `pip`:

```bash
python3 -m pip install flybase-cli
```

Homebrew:

```bash
brew tap gumadeiras/tap
brew install flybase-cli
```

From source:

```bash
python3 -m pip install -e .
```

## Release

Current release: `v0.1.2`.

Tag pushes like `vX.Y.Z` run the release workflow: build artifacts, create a
GitHub release, publish to PyPI, and update `gumadeiras/homebrew-tap`.

Release prerequisites:

- PyPI trusted publishing configured for this repo.
- `HOMEBREW_TAP_TOKEN` repository secret can write to
  `gumadeiras/homebrew-tap`.

## CLI

```bash
python3 flybase_cli.py presets

python3 flybase_cli.py sync gene-core

python3 flybase_cli.py sync gene-core --release FB2026_01

python3 flybase_cli.py sync gene-knowledge --release FB2026_01

python3 flybase_cli.py full-sync --release FB2026_01

python3 flybase_cli.py full-sync \
  --release FB2026_01 \
  --include 'best_gene_summary|entity_publication'

python3 flybase_cli.py sync-incremental \
  gene-knowledge \
  --from-release FB2025_06 \
  --release FB2026_01

python3 flybase_cli.py release-diff \
  --preset gene-knowledge \
  --from-release FB2025_06 \
  --to-release FB2026_01

python3 flybase_cli.py genomes --release FB2026_01

python3 flybase_cli.py sync-genome \
  --release FB2026_01 \
  --genome dmel_r6.67 \
  --section fasta \
  --asset mirna

python3 flybase_cli.py genome-presets

python3 flybase_cli.py sync-genome \
  --release FB2026_01 \
  --genome dmel_r6.67 \
  --preset mirna-fasta

PYTHONPATH=src python3 -m flybase_cli sync gene-expression

python3 flybase_cli.py manifest \
  --url https://s3ftp.flybase.org/genomes/Drosophila_melanogaster/dmel_r6.67_FB2026_01/fasta/ \
  --include 'miRNA'

python3 flybase_cli.py sync-url \
  --url https://s3ftp.flybase.org/genomes/Drosophila_melanogaster/dmel_r6.67_FB2026_01/fasta/ \
  --include 'miRNA'

python3 flybase_cli.py ingest \
  data/flybase/precomputed_files/genes/best_gene_summary_fb_2026_01.tsv.gz \
  data/flybase/precomputed_files/genes/fbgn_fbtr_fbpp_fb_2026_01.tsv.gz \
  data/flybase/precomputed_files/genes/fbgn_annotation_ID_fb_2026_01.tsv.gz

python3 flybase_cli.py tables --columns

python3 flybase_cli.py describe --sample-values 2
python3 flybase_cli.py schema-export --sample-values 1
python3 flybase_cli.py query-plan --sample-values 1 --limit 5
python3 flybase_cli.py query-run --template-name gene-summary-by-fbgn --param fbgn_id=FBgn0002121

python3 flybase_cli.py fts-build

python3 flybase_cli.py search 'memory formation'

python3 flybase_cli.py pg-load --release FB2026_01

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
- `gene-knowledge`: core gene facts + representative publications + orthology tables
- `orthology`: ortholog, paralog, and disease-association tables
- `interactions`: gene- and allele-level interaction tables

## Full sync

- `full-sync` crawls an entire release prefix, default `precomputed_files/`
- default behavior: download only files the current loaders can ingest into SQLite
- use `--all-files` if you want non-ingestable release artifacts too
- use `--include` / `--exclude` to stage a narrower smoke or partial warehouse
- default manifest path: `data/flybase/manifests/<release>/full-sync.json`

## Discovery

- `genomes --release FB2026_01` lists genome builds linked from that FlyBase release
- `sync-url` turns a crawlable FlyBase directory URL into a one-step local sync
- `sync-genome` resolves a release/build pair into the right genome-section URL automatically
- `genome-presets` lists reusable genome asset sync recipes

## Genome sync

- sections: `fasta`, `gff`, `gtf`, `dna`, `chado-xml`
- asset shortcuts include `mirna`, `transcript`, `translation`, `gene`, `chromosome`, `cds`, `ncrna`, `gff`, `gtf`
- presets include `mirna-fasta`, `transcript-fasta`, `translation-fasta`, `gene-fasta`, `chromosome-fasta`, `ncrna-fasta`, `gff-all`, `gtf-all`
- use `--include`/`--exclude` for narrower file selection on top of the asset preset

## Ingest formats

- delimited: `tsv`, `csv`, gzipped variants
- sequence: `fasta`, `fa`, `fna`, `faa`, gzipped variants
- annotation: `gff`, `gff3`, `gtf`, gzipped variants
- JSON: `json`, `json.gz`

## JSON ingest

- top-level scalar JSON fields become queryable SQLite columns
- one nested dict level is flattened, eg `gene.symbol` -> `gene_symbol`
- repeated top-level lists become child tables, eg `symbolSynonyms` -> `<table>_symbolsynonyms`
- repeated lists nested inside child dict rows become descendant tables, eg `genomeLocations[].exons[]` -> `<table>_genomelocations_exons`
- full source record remains in `payload_json`

Example:

```bash
python3 flybase_cli.py sql \
  "select record_id, symbol, gene_geneId from fb_ncrna_genes_fb_2026_01 limit 5"

python3 flybase_cli.py sql \
  "select parent_record_id, ordinal, value \
   from fb_ncrna_genes_fb_2026_01_symbolsynonyms \
   limit 5"

python3 flybase_cli.py sql \
  "select parent_record_id, parent_ordinal, ordinal, startPosition, endPosition \
   from fb_ncrna_genes_fb_2026_01_genomelocations_exons \
   limit 5"
```

## Search

- `fts-build` creates a local SQLite FTS5 index from ingested tables
- `search` queries that index without calling the live FlyBase API
- record ids prefer stable FlyBase-like columns such as `fbgn_id`, `primary_fbgn`, `flybase_fbtr`

## Metadata

- `describe` summarizes ingested tables with row counts, source paths, semantic tags, columns, and representative non-empty values
- `schema-export` writes the same metadata to a deterministic JSON artifact beside the SQLite DB, eg `FB2026_01.schema.json`
- `schema-export` also includes inferred `relationships` for nested child tables and common FlyBase ID joins
- `schema-export` also emits `semantic_summary` for table/entity tag coverage
- `schema-export` also emits ready-to-run `query_templates`
- `query-plan` prints starter SQL without the larger schema payload
- `query-plan` now includes named biological templates such as `gene-summary-by-fbgn`, `transcript-protein-links`, `publications-for-gene`, and coordinate lookups when matching tables exist
- `query-run` selects one template and executes it with parameter values
- useful first step before writing ad hoc SQL or building agent query plans

Example:

```bash
python3 flybase_cli.py schema-export \
  --db data/flybase/FB2026_01.sqlite \
  --sample-values 1

python3 flybase_cli.py query-plan \
  --db data/flybase/FB2026_01.sqlite \
  --sample-values 1 \
  --limit 5

python3 flybase_cli.py query-run \
  --db data/flybase/FB2026_01.sqlite \
  --template-name gene-summary-by-fbgn \
  --param fbgn_id=FBgn0002121
```

## Notes

- nested JSON child tables keep lineage columns like `parent_record_id`, `parent_ordinal`, `ordinal`.
- many FlyBase files start with `##` metadata lines; loader skips those.
- `sync` writes a preset manifest under `data/flybase/manifests/<release>/`.
- `full-sync` is the broadest offline path for release bulk data without going through the full Postgres dump.
- `sync --release FB2026_01` defaults to `data/flybase/FB2026_01.sqlite` to avoid cross-release mixing.
- `sync-incremental` uses stable manifest keys so release-renamed files still land in `updated` instead of noisy add/remove pairs.
- `release-diff` compares releases either by raw prefix or by curated multi-prefix preset.
- `manifest --url` lets you crawl non-`releases/` FlyBase directories such as genome FASTA/GFF trees.
- `sync-url` is the shortest path for genome assets once you know the directory URL.
- `sync-genome` is the shortest path when you know the FlyBase release + genome build label.
- `sync-genome --preset ...` is the preferred path for common genome asset pulls.
- some FlyBase `.gff.gz` assets are tar-wrapped gzip archives; loader handles that transparently.
- `sql` and `query-run` shape results as record-oriented JSON with summary metadata for agent chaining.
- `pg-load` stages the full Postgres import script for `releases/<release>/psql/<release>.sql.gz`.
- `pg-load --execute` runs the staged script when `createdb` and `psql` are installed locally.
- SQLite keeps setup minimal; switch to DuckDB/Postgres if you want bigger joins/faster scans.
- if you only need a few IDs, FlyBase Batch Download may be simpler than syncing files.
- use `--no-header` for files whose first non-comment row is data, not column names.

## Tests

```bash
python3 -m unittest discover -s tests
```
