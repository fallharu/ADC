"""Bounded local retrieval: summaries first, evidence on demand."""
from __future__ import annotations

import argparse
import hashlib
import os
import re
import sys
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from adc_vaults import load_vaults

DEFAULT_ROOT = Path(__file__).resolve().parents[1] / "docs" / "program-vault"
EXCLUDED_DIRS = {
    "80-artifacts", "90-templates", "key", "credentials", "secrets",
    "exports", "raw", "db", "databases", "uploads", "media",
}
HISTORICAL_STATES = {"stale", "superseded", "archived", "deleted", "unverified"}
WORD_RE = re.compile(r"[A-Za-z0-9_./-]+|[\u3040-\u30ff\u3400-\u9fff]+")
JP_PART_RE = re.compile(r"[\u3400-\u9fff]+|[\u30a0-\u30ff]+")
FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n?", re.DOTALL)
SECRET_PATTERNS = (
    re.compile(r"(?i)\b(?:api[_-]?key|token|secret|authorization)\s*[:=]\s*\S+"),
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]+"),
    re.compile(r"\b[A-Za-z]:\\(?:[^\s<>:\"/\\|?*]+\\)+[^\s<>:\"|?*]*"),
)


@dataclass(frozen=True)
class Note:
    path: Path
    relative_path: str
    note_id: str
    revision: str
    summary: str
    title: str
    body: str
    digest: str
    score: int
    status: str = "current"
    note_type: str = "note"


def _frontmatter(text: str) -> tuple[dict[str, str], str]:
    """Read the Vault's single-line fields plus inline/block aliases and tags."""
    match = FRONTMATTER_RE.match(text)
    if not match:
        return {}, text
    fields: dict[str, str] = {}
    list_key = None
    for line in match.group(1).splitlines():
        if list_key and re.match(r"^\s*-\s+", line):
            fields[list_key] += " " + re.sub(r"^\s*-\s+", "", line)
            continue
        if ":" not in line or line[:1].isspace():
            continue
        key, value = line.split(":", 1)
        fields[key.strip()] = value.strip().strip("\"'")
        list_key = key.strip() if key.strip() in {"aliases", "tags"} else None
    return fields, text[match.end():]


def _normalize(value: str) -> str:
    return unicodedata.normalize("NFKC", value).casefold()


def _terms(query: str) -> list[str]:
    # Preserve phrases and split script runs. Kanji bigrams let 実験結果 match
    # 実験 / 結果 without a model or dictionary. This is not semantic search.
    terms = []
    for term in WORD_RE.findall(_normalize(query)):
        if len(term) > 1:
            terms.append(term)
        for part in JP_PART_RE.findall(term):
            if len(part) > 1:
                terms.append(part)
            if len(part) > 2 and re.fullmatch(r"[\u3400-\u9fff]+", part):
                terms.extend(part[index:index + 2] for index in range(len(part) - 1))
    return list(dict.fromkeys(terms))


def _redact(text: str) -> str:
    for pattern in SECRET_PATTERNS:
        text = pattern.sub("[REDACTED]", text)
    return text


def _score(fields: dict[str, str], body: str, terms: list[str]) -> int:
    title = _normalize(fields.get("title", ""))
    summary = _normalize(fields.get("summary", ""))
    note_id = _normalize(fields.get("note_id", ""))
    aliases = _normalize(fields.get("aliases", "") + " " + fields.get("tags", ""))
    folded = _normalize(body)
    headings = "\n".join(line for line in folded.splitlines() if line.startswith("#"))
    # Cap repetitions so a long index cannot win just by repeating a keyword.
    return (1000 if note_id in terms else 0) + sum(
        8 * min(2, title.count(term))
        + 6 * min(2, summary.count(term))
        + 5 * min(2, note_id.count(term))
        + 6 * min(2, aliases.count(term))
        + 4 * min(2, headings.count(term))
        + min(2, folded.count(term))
        for term in terms
    )


def _excerpt(body: str, terms: list[str], limit: int) -> str:
    body = _redact(body.strip())
    if limit <= 0:
        return ""
    if len(body) <= limit:
        return body
    if limit <= 4:
        return "…"
    folded = body.casefold()
    positions = [folded.find(term) for term in terms if folded.find(term) >= 0]
    center = min(positions) if positions else 0
    start = max(0, center - limit // 3)
    # Reserve both markers. Never extend to the end of a long line.
    end = min(len(body), start + limit - 4)
    return ("…\n" if start else "") + body[start:end].strip() + ("\n…" if end < len(body) else "")


def select_section(body: str, heading: str) -> str | None:
    """Select an exact ATX heading and children, ignoring fenced code."""
    headings = []
    fence = None
    offset = 0
    for line in body.splitlines(keepends=True):
        marker = re.match(r"^ {0,3}(\x60{3,}|~{3,})(.*)$", line.rstrip("\r\n"))
        if marker:
            run, tail = marker.groups()
            if fence is None:
                fence = (run[0], len(run))
            elif run[0] == fence[0] and len(run) >= fence[1] and not tail.strip():
                fence = None
        elif fence is None:
            match = re.match(r"^ {0,3}(#{1,6})[ \t]+(.+?)\s*$", line)
            if match:
                title = re.sub(r"\s+#+\s*$", "", match.group(2))
                headings.append((offset, len(match.group(1)), title))
        offset += len(line)
    matches = [i for i, (_, _, title) in enumerate(headings)
               if _normalize(title).strip() == _normalize(heading).strip()]
    if len(matches) > 1:
        raise ValueError("heading is ambiguous; use a unique heading name")
    if not matches:
        return None
    index = matches[0]
    start, level, _ = headings[index]
    end = next((position for position, depth, _ in headings[index + 1:] if depth <= level), len(body))
    return body[start:end].strip()


def find_notes(
    root: Path, query: str = "", include_archive: bool = False, *,
    note_id: str | None = None, note_types: list[str] | None = None,
    section: str | None = None,
) -> list[Note]:
    terms = _terms(query)
    if not terms and not note_id and not note_types:
        raise ValueError("provide searchable terms, --id or --type")
    notes: list[Note] = []
    matched_ids = 0
    root = root.resolve()
    candidates = []
    for directory, folders, filenames in os.walk(root, followlinks=False):
        folders[:] = sorted(
            name for name in folders
            if not name.startswith(".")
            and name.casefold() not in EXCLUDED_DIRS
            and (include_archive or name.casefold() != "99-archive")
            and not (Path(directory) / name).is_symlink()
            and not getattr(Path(directory) / name, "is_junction", lambda: False)()
        )
        candidates.extend(
            Path(directory) / name for name in filenames
            if name.endswith(".md") and not name.startswith(".")
        )
    for path in sorted(candidates):
        if path.is_symlink() or not path.resolve().is_relative_to(root):
            continue
        relative = path.relative_to(root)
        text = path.read_text(encoding="utf-8")
        fields, body = _frontmatter(text)
        if not fields.get("note_id") or not fields.get("summary"):
            continue
        if note_id is not None:
            if fields["note_id"] != note_id:
                continue
            matched_ids += 1
            if matched_ids > 1:
                raise ValueError("duplicate note_id in Vault; resolve the conflict before retrieval")
        if note_types and fields.get("note_type", "note") not in note_types:
            continue
        status = fields.get("status", "current").casefold()
        if not include_archive and status in HISTORICAL_STATES:
            continue
        score = _score(fields, body, terms) if terms else 1
        if score <= 0:
            continue
        if section is not None:
            selected = select_section(body, section)
            if selected is None:
                continue
            body = selected
        notes.append(Note(
            path=path, relative_path=relative.as_posix(), note_id=fields["note_id"],
            revision=fields.get("revision", "unknown"), summary=fields["summary"],
            title=fields.get("title", path.stem), body=body,
            digest=hashlib.sha256(text.encode("utf-8")).hexdigest(), score=score,
            status=status, note_type=fields.get("note_type", "note"),
        ))
    return sorted(notes, key=lambda note: (-note.score, note.relative_path))


def render_packet(
    query: str, notes: list[Note], top_k: int, max_chars: int, summaries_only: bool = True,
    *, provenance: bool = False,
) -> str:
    if top_k < 1 or max_chars < 1:
        raise ValueError("top_k and max_chars must be positive")
    if not notes:
        return "No matching notes; check keywords, ID, type, heading or archive status."[:max_chars]
    entries = []
    for note in notes[:top_k]:
        label = _redact(
            f"{note.note_id} | {note.relative_path} | r{note.revision} "
            f"{note.note_type} status={note.status}"
        )
        if provenance:
            label += f" | sha256:{note.digest}"
        content = _redact((note.summary if summaries_only else note.body).strip())
        entries.append((label, content))

    def footer(count: int) -> str:
        omitted = len(notes) - count
        return f"\n\nomitted={omitted} (top-k/budget)" if omitted else ""

    # Reserve content for each displayed source. If even identities + minimal
    # content cannot fit, drop entries explicitly rather than cutting the packet.
    while entries:
        minimum = sum(len(label) + 1 + min(80, len(content)) for label, content in entries)
        minimum += 2 * (len(entries) - 1) + len(footer(len(entries)))
        if minimum <= max_chars:
            break
        entries.pop()
    if not entries:
        return "No entries fit budget; increase --max-chars."[:max_chars]
    remaining = max_chars - sum(len(label) + 1 for label, _ in entries)
    remaining -= 2 * (len(entries) - 1) + len(footer(len(entries)))
    allowances = [0] * len(entries)
    pending = list(range(len(entries)))
    while pending and remaining:
        share = max(1, remaining // len(pending))
        for index in pending:
            amount = min(share, len(entries[index][1]) - allowances[index], remaining)
            allowances[index] += amount
            remaining -= amount
        pending = [i for i in pending if allowances[i] < len(entries[i][1])]
    terms = [] if summaries_only else _terms(query)
    return "\n\n".join(
        f"{label}\n{_excerpt(content, terms, allowance)}"
        for (label, content), allowance in zip(entries, allowances)
    ) + footer(len(entries))


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("query", nargs="?", default="", help="keywords or Japanese search phrase")
    location = parser.add_mutually_exclusive_group()
    location.add_argument("--root", type=Path)
    location.add_argument("--vault", choices=("software", "output", "analysis"))
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--summaries", dest="summaries", action="store_true",
                      help="compact summaries (default)")
    mode.add_argument("--excerpts", dest="summaries", action="store_false", help="retrieve evidence text")
    parser.set_defaults(summaries=None)
    parser.add_argument("--id", dest="note_id", help="exact note_id, not a path")
    parser.add_argument("--type", dest="note_types", action="append", help="note_type; repeat for multiple types")
    parser.add_argument("--section", help="exact Markdown # heading; implies --excerpts")
    parser.add_argument("--provenance", action="store_true", help="include full source SHA-256")
    parser.add_argument("--top-k", type=int, default=3)
    parser.add_argument("--max-chars", type=int, help="default: 1200 summaries / 8000 excerpts")
    parser.add_argument("--include-archive", action="store_true")
    args = parser.parse_args(argv)
    if not _terms(args.query) and not args.note_id and not args.note_types:
        parser.error("provide searchable terms, --id or --type")
    if args.section is not None:
        if not args.section.strip():
            parser.error("--section must not be empty")
        if args.summaries is True:
            parser.error("--section cannot be combined with --summaries")
        args.summaries = False
    elif args.summaries is None:
        args.summaries = True
    if args.max_chars is None:
        args.max_chars = 1200 if args.summaries else 8000
    if args.root is None:
        try:
            args.root = load_vaults()[args.vault or "software"]
        except (OSError, ValueError) as exc:
            parser.error(str(exc))
    if args.top_k < 1:
        parser.error("--top-k must be at least 1")
    if args.max_chars < 500:
        parser.error("--max-chars must be at least 500")
    if not args.root.is_dir():
        parser.error(f"vault root does not exist: {args.root}")
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        notes = find_notes(args.root, args.query, args.include_archive,
                           note_id=args.note_id, note_types=args.note_types, section=args.section)
        packet = render_packet(args.query, notes, args.top_k, args.max_chars, args.summaries,
                               provenance=args.provenance)
    except (OSError, UnicodeError, ValueError) as exc:
        print(f"retrieval error: {exc}", file=sys.stderr)
        return 2
    print(packet)
    return 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
