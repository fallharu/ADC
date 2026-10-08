from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import Iterable, Optional

from .db_manager import MAIN_DB_PATH, resolve_project_path


IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp"}
VIDEO_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv", ".m4v", ".wmv"}


class PathValidationError(Exception):
    def __init__(self, message: str, status_code: int) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def _resolve_path(path_value: str) -> Path:
    raw_value = str(path_value or "").strip().strip('"').strip("'")
    if not raw_value:
        raise PathValidationError("path is required", 400)
    candidate = Path(os.path.expanduser(raw_value))
    if not candidate.is_absolute():
        candidate = Path(resolve_project_path(raw_value))
    return candidate.resolve(strict=False)


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _iter_pathlink_roots(upload_root: Path) -> Iterable[Path]:
    if not upload_root.exists():
        return []
    roots: list[Path] = []
    for link_file in upload_root.rglob(".pathlink"):
        if not link_file.is_file():
            continue
        try:
            linked = link_file.read_text(encoding="utf-8").strip()
        except OSError:
            continue
        if linked:
            roots.append(_resolve_path(linked))
    return roots


def _iter_database_roots() -> Iterable[Path]:
    if not os.path.exists(MAIN_DB_PATH):
        return []
    roots: list[Path] = []
    try:
        with sqlite3.connect(MAIN_DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            for row in conn.execute(
                "SELECT source_path FROM Video "
                "WHERE source_path IS NOT NULL AND source_path != ''"
            ):
                path = _resolve_path(row["source_path"])
                roots.append(path.parent if path.suffix else path)
            for row in conn.execute(
                "SELECT output_folder FROM ProcessLog "
                "WHERE output_folder IS NOT NULL AND output_folder != ''"
            ):
                roots.append(_resolve_path(row["output_folder"]))
    except sqlite3.Error:
        return roots
    return roots


def allowed_file_roots(upload_folder: Optional[str] = None) -> list[Path]:
    upload_root = _resolve_path(
        upload_folder or os.getenv("Upload_folder") or os.getenv("UPLOAD_FOLDER") or "uploads"
    )
    candidates = [
        upload_root,
        _resolve_path(os.getenv("Opt_files") or "output"),
        _resolve_path("output"),
        _resolve_path("OutPut"),
    ]
    candidates.extend(_iter_pathlink_roots(upload_root))
    candidates.extend(_iter_database_roots())

    unique: list[Path] = []
    seen: set[str] = set()
    for root in candidates:
        key = os.path.normcase(str(root))
        if key not in seen:
            seen.add(key)
            unique.append(root)
    return unique


def resolve_allowed_file(
    path_value: str,
    *,
    allowed_extensions: Optional[set[str]] = None,
    upload_folder: Optional[str] = None,
) -> Path:
    candidate = _resolve_path(path_value)
    if not any(_is_relative_to(candidate, root) for root in allowed_file_roots(upload_folder)):
        raise PathValidationError("path is outside allowed directories", 403)
    if not candidate.exists() or not candidate.is_file():
        raise PathValidationError("file not found", 404)
    if allowed_extensions and candidate.suffix.lower() not in allowed_extensions:
        raise PathValidationError("file extension is not allowed", 400)
    return candidate
