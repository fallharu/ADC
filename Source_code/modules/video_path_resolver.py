"""Utilities to resolve original video file paths across different modules."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Iterable, List, Optional, Set


def _sanitize_fragment(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    return text.replace("\\", os.sep)


def _ensure_unique(items: Iterable[str]) -> List[str]:
    seen: Set[str] = set()
    unique: List[str] = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            unique.append(item)
    return unique


def collect_video_candidates(
    *,
    upload_folder: Optional[str],
    filename: str,
    source_path: Optional[str] = None,
    output_folder: Optional[str] = None,
    folder_alias: Optional[str] = None,
    repo_root: Optional[Path] = None,
    extra_search_dirs: Optional[Iterable[str]] = None,
    extra_candidates: Optional[Iterable[str]] = None,
) -> List[str]:
    """Return candidate paths for locating the original uploaded video.

    The resolver considers the stored absolute path, the configured upload
    directory, output folders, and optional folder aliases.  The returned list
    prioritises the most likely locations and includes fallbacks such as
    recursive searches when direct combinations do not exist.
    """

    repo_root_path = repo_root or Path(__file__).resolve().parents[2]
    repo_root_str = str(repo_root_path)
    cwd_str = str(Path.cwd())

    upload_fragment = _sanitize_fragment(upload_folder) or (upload_folder or "")
    upload_abs = os.path.abspath(upload_fragment) if upload_fragment else cwd_str

    base_candidates = [upload_abs]
    if output_folder:
        base_candidates.append(os.path.abspath(str(output_folder)))
        base_dir = os.path.dirname(str(output_folder))
        if base_dir:
            base_candidates.append(os.path.abspath(base_dir))
    base_candidates.extend([repo_root_str, cwd_str])
    if extra_search_dirs:
        base_candidates.extend(os.path.abspath(p) for p in extra_search_dirs if p)
    unique_bases = _ensure_unique(os.path.normpath(b) for b in base_candidates if b)

    candidates: List[str] = []
    seen: Set[str] = set()

    def add_candidate(path: str, *, front: bool = False) -> None:
        if path in seen:
            return
        seen.add(path)
        if front:
            candidates.insert(0, path)
        else:
            candidates.append(path)

    def register(path: Optional[str], *, front: bool = False) -> None:
        if not path:
            return
        normalized = os.path.normpath(path)
        add_candidate(normalized, front=front)
        absolute = os.path.abspath(normalized)
        add_candidate(absolute, front=front)
        if not os.path.isabs(normalized):
            for base in (repo_root_str, cwd_str):
                add_candidate(os.path.normpath(os.path.join(base, normalized)), front=front)

    def expand_relative(base: str, fragment: str, *, front: bool = False) -> None:
        if not fragment:
            return
        trimmed = fragment.lstrip("/\\")
        if not trimmed:
            return
        register(os.path.join(base, trimmed), front=front)

    def expand_across_bases(fragment: str, *, front: bool = False) -> None:
        for base in unique_bases:
            expand_relative(base, fragment, front=front)

    if extra_candidates:
        for explicit in extra_candidates:
            register(explicit, front=True)

    source_fragment = _sanitize_fragment(source_path)
    if source_fragment:
        if os.path.isabs(source_fragment):
            register(source_fragment, front=True)
        else:
            expand_across_bases(source_fragment, front=True)
            base_name = os.path.basename(source_fragment)
            if base_name:
                expand_across_bases(base_name, front=True)
            register(source_fragment, front=True)

    filename_fragment = _sanitize_fragment(filename) or filename
    if filename_fragment:
        if os.path.isabs(filename_fragment):
            register(filename_fragment)
        else:
            expand_across_bases(filename_fragment)
            base_name = os.path.basename(filename_fragment)
            if base_name:
                expand_across_bases(base_name)
            if upload_fragment:
                register(os.path.join(upload_fragment, filename_fragment))
            register(filename_fragment)

    alias_fragment = _sanitize_fragment(folder_alias)
    if alias_fragment:
        base_name = os.path.basename(filename_fragment) if filename_fragment else ""
        if base_name:
            alias_combo = os.path.join(alias_fragment, base_name)
            register(alias_combo, front=True)
            if upload_fragment:
                register(os.path.join(upload_fragment, alias_combo), front=True)
            expand_across_bases(alias_combo, front=True)
        if filename_fragment and alias_fragment not in filename_fragment:
            alias_filename = os.path.join(alias_fragment, filename_fragment)
            register(alias_filename, front=True)
            if upload_fragment:
                register(os.path.join(upload_fragment, alias_filename), front=True)
            expand_across_bases(alias_filename, front=True)

    if not candidates and filename_fragment:
        default_path = os.path.join(upload_abs, filename_fragment)
        register(default_path)

    if filename_fragment and not any(os.path.exists(path) for path in candidates):
        search_name = os.path.basename(filename_fragment)
        search_bases = [upload_abs]
        if output_folder:
            search_bases.append(os.path.abspath(str(output_folder)))
        for base in _ensure_unique(os.path.normpath(b) for b in search_bases if b):
            try:
                base_path = Path(base)
            except Exception:
                continue
            if not base_path.exists():
                continue
            try:
                for found in base_path.rglob(search_name):
                    register(str(found))
            except Exception:
                continue

    if not candidates and filename_fragment:
        register(os.path.join(upload_abs, filename_fragment))

    return candidates


__all__ = ["collect_video_candidates"]

