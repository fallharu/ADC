from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch


REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
from adc_vaults import load_vaults
from new_analysis_run import create_run, _append_index
from retrieve_memory import find_notes


class AnalysisVaultTests(unittest.TestCase):
    def test_index_update_preserves_user_text_and_advances_revision(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            index = Path(directory) / "index.md"
            index.write_text("---\nrevision: 3\nupdated: old\ntags: [mine]\n---\n\nUser text.\n", encoding="utf-8")
            _append_index(index, "| new row |\n", "2026-09-24")
            result = index.read_text(encoding="utf-8")
            self.assertIn("revision: 4\nupdated: 2026-09-24\ntags: [mine]", result)
            self.assertIn("User text.\n| new row |", result)

    def make_repo(self, root: Path) -> Path:
        (root / "docs").mkdir()
        (root / "docs/vault-registry.json").write_text(
            (REPO / "docs/vault-registry.json").read_text(encoding="utf-8"), encoding="utf-8"
        )
        for vault in load_vaults(root).values():
            vault.mkdir()
        analysis = root / "docs/analysis-vault"
        (analysis / "90-Templates").mkdir()
        (analysis / "90-Templates/slide-card.md").write_text("# Slide\n- run_id:\n", encoding="utf-8")
        (analysis / "00-Index.md").write_text("# User index\n\nKeep my notes.\n", encoding="utf-8")
        return analysis

    def test_run_retains_reproduction_and_slide_slots_without_inventing_results(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            analysis = self.make_repo(root)
            result = create_run("speed-test", "速度比較 | 試験", repo_root=root)
            assets = root / result["artifacts"]
            manifest = json.loads((assets / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["status"], "planned")
            self.assertEqual(manifest["validation_status"], "unverified")
            self.assertEqual(manifest["artifacts"], [])
            self.assertIsNone(manifest["code_revision"])
            for folder in ("code", "config", "tables", "figures", "logs", "slides"):
                self.assertTrue((assets / folder).is_dir())
            self.assertIn(result["run_id"], (assets / "slides/slide-card.md").read_text(encoding="utf-8"))
            note = root / result["note"]
            self.assertTrue((note.parent / "../80-Artifacts" / result["run_id"] / "manifest.json").is_file())
            index = (analysis / "00-Index.md").read_text(encoding="utf-8")
            self.assertIn("Keep my notes.", index)
            self.assertIn("速度比較 ／ 試験", index)
            self.assertEqual(len(find_notes(analysis, "速度比較")), 1)

    def test_rerun_links_parent_and_never_modifies_existing_experiment(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            self.make_repo(root)
            first = create_run("test", "First", repo_root=root)
            original = (root / first["note"]).read_bytes()
            second = create_run("test", "Second", first["run_id"], repo_root=root)
            manifest = json.loads((root / second["artifacts"] / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["parent_run_id"], first["run_id"])
            self.assertNotEqual(first["run_id"], second["run_id"])
            self.assertEqual((root / first["note"]).read_bytes(), original)

    def test_bad_input_does_not_create_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            analysis = self.make_repo(root)
            for slug, title, parent in (("../escape", "Test", None), ("test", "Bad\nTitle", None), ("test", "Test", "../../escape")):
                with self.assertRaises(ValueError):
                    create_run(slug, title, parent, repo_root=root)
            self.assertFalse((analysis / "80-Artifacts").exists())

    def test_collision_refuses_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            self.make_repo(root)
            with patch("new_analysis_run.uuid.uuid4") as identifier, patch("new_analysis_run.datetime") as clock:
                from datetime import datetime, timezone
                identifier.return_value.hex = "12345678" * 4
                clock.now.return_value = datetime(2026, 9, 24, tzinfo=timezone.utc)
                first = create_run("test", "First", repo_root=root)
                original = (root / first["note"]).read_bytes()
                with self.assertRaises(FileExistsError):
                    create_run("test", "Second", repo_root=root)
                self.assertEqual((root / first["note"]).read_bytes(), original)

    def test_registry_rejects_escape_and_nested_vaults(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            self.make_repo(root)
            path = root / "docs/vault-registry.json"
            baseline = json.loads(path.read_text(encoding="utf-8"))
            for destination in ("../outside", "docs/program-vault/nested", "docs/program-vault"):
                baseline["vaults"]["analysis"] = destination
                path.write_text(json.dumps(baseline), encoding="utf-8")
                with self.assertRaises(ValueError):
                    load_vaults(root)


if __name__ == "__main__":
    unittest.main()
