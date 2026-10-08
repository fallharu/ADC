"""Small, local registry shared by ADC knowledge tools (no runtime data access)."""

from __future__ import annotations

import json
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def load_vaults(repo_root: Path = REPO_ROOT) -> dict[str, Path]:
    repo_root = repo_root.resolve()
    registry = json.loads((repo_root / "docs/vault-registry.json").read_text(encoding="utf-8"))
    if registry.get("schema_version") != 1:
        raise ValueError("unsupported ADC vault registry version")
    configured = registry.get("vaults", {})
    if set(configured) != {"software", "output", "analysis"}:
        raise ValueError("registry must declare software, output and analysis")
    roots = {}
    for name, value in configured.items():
        relative = Path(value)
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("vault paths must be repository-relative")
        root = (repo_root / relative).resolve()
        if not root.is_relative_to(repo_root) or root == repo_root:
            raise ValueError("vault root must stay inside the repository")
        roots[name] = root
    for name, root in roots.items():
        if any(root.is_relative_to(other) for key, other in roots.items() if key != name):
            raise ValueError("vault roots must be distinct and not nested")
    return roots
