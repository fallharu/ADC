"""Create durable experiment scaffolding; never run analysis or copy source data."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import uuid

from adc_vaults import REPO_ROOT, load_vaults


SLUG_RE = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")
RUN_RE = re.compile(r"adc-run-\d{8}T\d{6}Z-[a-z0-9-]+-[a-f0-9]{8}\Z")


def _write_new(path: Path, content: str) -> None:
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(content)


def _append_index(index: Path, row: str, stamp: str) -> None:
    """Preserve prose, advance managed metadata, and replace the index atomically."""
    original = index.read_text(encoding="utf-8")
    updated = original
    match = re.match(r"\A---\n(.*?)\n---", original, re.DOTALL)
    if match:
        metadata = re.sub(
            r"(?m)^revision: (\d+)\s*$",
            lambda value: f"revision: {int(value.group(1)) + 1}",
            match.group(1),
        )
        metadata = re.sub(r"(?m)^updated: [^\n]+$", f"updated: {stamp}", metadata)
        updated = "---\n" + metadata + "\n---" + original[match.end():]
    updated = updated.rstrip("\n") + "\n" + row
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", newline="\n", dir=index.parent,
            prefix=".adc-index-", suffix=".tmp", delete=False,
        ) as stream:
            temporary = Path(stream.name)
            stream.write(updated)
        if index.read_text(encoding="utf-8") != original:
            raise ValueError("index changed concurrently; add the new run row after resolving the conflict")
        os.replace(temporary, index)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def create_run(
    slug: str, title: str, parent_run_id: str | None = None, *, repo_root: Path = REPO_ROOT
) -> dict[str, str]:
    if not SLUG_RE.fullmatch(slug) or len(slug) > 48:
        raise ValueError("slug must be 1-48 lowercase letters/digits with single hyphens")
    if not title.strip() or len(title) > 120 or any(ord(char) < 32 for char in title):
        raise ValueError("title must be one nonempty line of at most 120 characters")
    if parent_run_id is not None and not RUN_RE.fullmatch(parent_run_id):
        raise ValueError("invalid parent run ID")
    root = load_vaults(repo_root)["analysis"]
    if parent_run_id and not (root / "10-Experiments" / f"{parent_run_id}.md").is_file():
        raise ValueError("parent run note does not exist in the analysis Vault")
    index = root / "00-Index.md"
    template = root / "90-Templates/slide-card.md"
    if not index.is_file() or not template.is_file():
        raise ValueError("analysis Vault index and slide-card template must exist")
    now = datetime.now(timezone.utc)
    run_id = f"adc-run-{now:%Y%m%dT%H%M%SZ}-{slug}-{uuid.uuid4().hex[:8]}"
    artifacts = root / "80-Artifacts" / run_id
    note = root / "10-Experiments" / f"{run_id}.md"
    # Resolve destinations before writing: do not follow a redirected artifact/notes folder.
    for path in (artifacts, note, index, template):
        if not path.resolve().is_relative_to(root):
            raise ValueError("experiment paths must stay inside the analysis Vault")
    if artifacts.exists() or note.exists():
        raise FileExistsError("run ID already exists; nothing overwritten")
    slide_template = template.read_text(encoding="utf-8")
    artifacts.mkdir(parents=True, exist_ok=False)
    for folder in ("code", "config", "tables", "figures", "logs", "slides"):
        (artifacts / folder).mkdir()
    stamp = now.isoformat(timespec="seconds")
    manifest = {
        "schema_version": 1,
        "run_id": run_id,
        "title": title,
        "created_at": stamp,
        "status": "planned",
        "validation_status": "unverified",
        "parent_run_id": parent_run_id,
        "source_ids": [],
        "code_revision": None,
        "code_dirty": None,
        "code_patch_path": None,
        "command": None,
        "working_directory": None,
        "environment": {},
        "parameters": {},
        "artifacts": [],
        "validation": [],
        "retention": "keep-until-explicit-user-deletion",
    }
    _write_new(artifacts / "manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    _write_new(
        artifacts / "slides/slide-card.md",
        slide_template.replace("- run_id:", f"- run_id: {run_id}", 1),
    )
    note.parent.mkdir(parents=True, exist_ok=True)
    quoted_title = json.dumps(title, ensure_ascii=False)
    _write_new(note, f"""---
note_id: {run_id}
vault_kind: analysis
note_type: experiment
title: {quoted_title}
summary: {json.dumps(title + '。計画のみ・未実行。', ensure_ascii=False)}
run_id: {run_id}
parent_run_id: {parent_run_id or 'null'}
source_ids: []
artifact_ids: []
revision: 1
status: planned
validation_status: unverified
updated: {stamp}
---

# {title}

## 問い・仮説

- 解決したい問題:
- 原因の仮説:
- 対象コード:

## 比較条件と再現

- 基準実装・変更案:
- 指標・単位・成功基準:
- source_id・データ版・件数・除外条件:
- コード版・未コミット差分・環境・seed:
- 実行コマンド・作業ディレクトリ:

## 結果と検証

未実行。結果を記入したら状態・summary・manifest・索引も更新する。

- 観測事実と根拠artifact_id:
- 検証コマンド・結果:
- 失敗・効果なし・限界:
- 採用／保留／棄却と理由:
- 次の最小実験:

## 保存した資料

- [manifest](../80-Artifacts/{run_id}/manifest.json)
- [スライド候補・発表者メモ](../80-Artifacts/{run_id}/slides/slide-card.md)
- 試験コードは `../80-Artifacts/{run_id}/code/`、図表は同じ実験の `figures/` へ保存。
""")
    # One index writer at a time, as specified by the team handoff contract.
    safe_title = title.replace("|", "／").replace("[", "（").replace("]", "）")
    _append_index(index, f"| `{run_id}` | {safe_title}。未実行。 | planned | [[10-Experiments/{run_id}]] |\n", stamp)
    return {
        "run_id": run_id,
        "note": note.relative_to(repo_root.resolve()).as_posix(),
        "artifacts": artifacts.relative_to(repo_root.resolve()).as_posix(),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("slug")
    parser.add_argument("--title", required=True, help="short title without private data")
    parser.add_argument("--parent-run-id")
    args = parser.parse_args(argv)
    try:
        result = create_run(args.slug, args.title, args.parent_run_id)
    except (OSError, ValueError) as exc:
        print(f"run creation failed: {exc}; retain any partially created files for review", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
