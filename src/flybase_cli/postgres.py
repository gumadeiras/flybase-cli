from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from .config import DEFAULT_POSTGRES_DIR
from .core import download_file, release_base_url


def dump_url_for_release(release: str) -> str:
    return f"{release_base_url(release)}psql/{release}.sql.gz"


def default_dump_path(root: Path, release: str) -> Path:
    return root / f"{release}.sql.gz"


def default_script_path(root: Path, release: str) -> Path:
    return root / f"load-{release}.sh"


def default_db_name(release: str) -> str:
    return f"flybase_{release.lower()}"


def available_postgres_tools() -> dict[str, str | None]:
    return {
        "createdb": shutil.which("createdb"),
        "dropdb": shutil.which("dropdb"),
        "psql": shutil.which("psql"),
    }


def render_pg_load_script(
    *,
    dump_path: Path,
    db_name: str,
    drop_existing: bool,
) -> str:
    lines = ["#!/usr/bin/env bash", "set -euo pipefail", ""]
    if drop_existing:
        lines.append(f"dropdb --if-exists {db_name}")
    lines.append(f"createdb {db_name}")
    lines.append(f"gzip -dc {dump_path} | psql {db_name}")
    lines.append("")
    return "\n".join(lines)


def write_pg_load_script(
    *,
    release: str,
    dump_path: Path,
    db_name: str,
    script_path: Path,
    drop_existing: bool,
) -> Path:
    script_path.parent.mkdir(parents=True, exist_ok=True)
    script = render_pg_load_script(
        dump_path=dump_path,
        db_name=db_name,
        drop_existing=drop_existing,
    )
    script_path.write_text(script, encoding="utf-8")
    script_path.chmod(0o755)
    return script_path


def ensure_dump_file(
    *,
    release: str,
    dump_path: Path,
    force: bool = False,
) -> Path:
    if dump_path.exists() and not force:
        return dump_path
    dump_path.parent.mkdir(parents=True, exist_ok=True)
    download_file(dump_url_for_release(release), dump_path)
    return dump_path


def execute_pg_load_script(script_path: Path) -> None:
    subprocess.run([str(script_path)], check=True)


def build_pg_load_plan(
    *,
    release: str,
    root: Path = DEFAULT_POSTGRES_DIR,
    db_name: str | None = None,
    dump_path: Path | None = None,
    script_path: Path | None = None,
    drop_existing: bool = False,
) -> dict[str, object]:
    db = db_name or default_db_name(release)
    dump = dump_path or default_dump_path(root, release)
    script = script_path or default_script_path(root, release)
    return {
        "release": release,
        "db_name": db,
        "dump_url": dump_url_for_release(release),
        "dump_path": str(dump),
        "script_path": str(script),
        "drop_existing": drop_existing,
        "tools": available_postgres_tools(),
    }
