# Changelog

## Unreleased

### Changes

- Updated release automation to the current GitHub Actions checkout, Python setup, and release actions.
- Added a local release wrapper for version sync, package validation, tagging, and release workflow verification.

## 0.1.2 - 2026-05-05

### Fixes

- Fixed the CLI shim source path for release CI.

## 0.1.1 - 2026-05-05

Initial PyPI release.

### Features

- Added packaged FlyBase CLI surfaces for release-pinned bulk sync and local query workflows.
- Added ingestion for FlyBase bulk files, flexible crawling, multi-format loaders, and nested JSON child tables.
- Added local full-text search, table descriptions, schema exports, relationship hints, semantic query planning, and query templates.
- Added genome discovery, genome asset sync, URL sync, declarative genome presets, and full release sync commands.
- Added multi-source preset diff, incremental sync, and query execution commands.
- Added `--version` support for packaging.

### Fixes

- Added regression coverage for ingestion, genome asset workflows, JSON projection, Postgres planning, and child-table extraction.

### Changes

- Documented genome sync, schema export, relationship hints, nested JSON extraction, and query planning workflows.
