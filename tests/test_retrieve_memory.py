from __future__ import annotations

import importlib.util
import contextlib
import hashlib
import io
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "retrieve_memory.py"
sys.path.insert(0, str(SCRIPT.parent))
SPEC = importlib.util.spec_from_file_location("retrieve_memory", SCRIPT)
assert SPEC and SPEC.loader
retrieve_memory = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = retrieve_memory
SPEC.loader.exec_module(retrieve_memory)


class RetrieveMemoryTests(unittest.TestCase):
    def _write(self, root: Path, relative: str, title: str, summary: str, body: str) -> None:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "---\n"
            f"note_id: {path.stem}\n"
            f"title: {title}\n"
            f"summary: {summary}\n"
            "revision: 1\n"
            "---\n\n"
            f"# {title}\n\n{body}\n",
            encoding="utf-8",
        )

    def test_ranks_matching_note_and_skips_archive(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._write(root, "active.md", "Database schema", "SQLite columns", "migration rules")
            self._write(root, "other.md", "UI colors", "template palette", "button styles")
            self._write(root, "99-Archive/old.md", "Database history", "old SQLite", "obsolete")

            notes = retrieve_memory.find_notes(root, "database SQLite")

            self.assertEqual([note.relative_path for note in notes], ["active.md"])

    def test_packet_obeys_budget_and_redacts_secrets(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._write(
                root,
                "ai.md",
                "AI provider",
                "Provider configuration",
                "API_KEY=do-not-emit " + ("provider context " * 100),
            )
            notes = retrieve_memory.find_notes(root, "provider")

            packet = retrieve_memory.render_packet("provider", notes, top_k=1, max_chars=500, summaries_only=False)

            self.assertLessEqual(len(packet), 500)
            self.assertNotIn("do-not-emit", packet)
            self.assertIn("[REDACTED]", packet)

    def test_artifact_private_and_template_directories_are_never_read(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._write(root, "active.md", "Analysis", "Analysis summary", "evidence")
            for folder in ("80-Artifacts/run", "90-Templates", "key", "uploads", ".obsidian"):
                path = root / folder / "invalid.md"
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"\xff\xfe invalid utf8 must not be read")
            for historical in (False, True):
                notes = retrieve_memory.find_notes(root, "analysis", historical)
                self.assertEqual([note.relative_path for note in notes], ["active.md"])

    def test_stale_notes_are_opt_in_and_status_is_visible(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._write(root, "stale.md", "Speed", "Speed comparison", "Old evidence")
            path = root / "stale.md"
            path.write_text(path.read_text(encoding="utf-8").replace(
                "revision: 1", "revision: 1\nstatus: stale"
            ), encoding="utf-8")
            self.assertEqual(retrieve_memory.find_notes(root, "speed"), [])
            notes = retrieve_memory.find_notes(root, "speed", include_archive=True)
            packet = retrieve_memory.render_packet("speed", notes, 3, 8000)
            self.assertIn("status=stale", packet)

    def test_summary_packet_does_not_emit_body_or_header_secrets(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._write(root, "note.md", "Speed API_KEY=header-secret", "Speed summary", "body-only-evidence")
            notes = retrieve_memory.find_notes(root, "speed")
            packet = retrieve_memory.render_packet("speed", notes, 3, 1200, summaries_only=True)
            self.assertIn("Speed summary", packet)
            self.assertNotIn("body-only-evidence", packet)
            self.assertNotIn("header-secret", packet)
            self.assertLessEqual(len(packet), 1200)

    def test_vault_selection_preserves_default_and_custom_root(self) -> None:
        self.assertEqual(retrieve_memory.parse_args(["speed"]).root, retrieve_memory.DEFAULT_ROOT)
        selected = retrieve_memory.parse_args(["speed", "--vault", "analysis", "--summaries"])
        self.assertEqual(selected.root.name, "analysis-vault")
        self.assertTrue(selected.summaries)
        with tempfile.TemporaryDirectory() as directory:
            args = retrieve_memory.parse_args(["speed", "--root", directory])
            self.assertEqual(args.root, Path(directory))

    def test_default_is_compact_and_body_and_digest_are_opt_in(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._write(root, "speed.md", "Speed", "Speed summary", "unique-evidence")
            notes = retrieve_memory.find_notes(root, "speed")
            packet = retrieve_memory.render_packet("speed", notes, 3, 1200)
            self.assertIn("Speed summary", packet)
            self.assertNotIn("unique-evidence", packet)
            self.assertNotIn("sha256:", packet)
            packet = retrieve_memory.render_packet("speed", notes, 3, 8000, False, provenance=True)
            self.assertIn("unique-evidence", packet)
            self.assertIn("sha256:" + notes[0].digest, packet)
        args = retrieve_memory.parse_args(["speed"])
        self.assertTrue(args.summaries)
        self.assertEqual(args.max_chars, 1200)
        args = retrieve_memory.parse_args(["speed", "--excerpts"])
        self.assertFalse(args.summaries)
        self.assertEqual(args.max_chars, 8000)

    def test_japanese_sentence_ranks_relevant_note_above_unrelated_note(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._write(root, "save.md", "実験の保存", "結果と条件を保持", "記録の手順")
            self._write(root, "unrelated.md", "画面配色", "色の設定", "背景の色")
            notes = retrieve_memory.find_notes(root, "実験結果を保存する")
            self.assertEqual([note.note_id for note in notes], ["save"])

    def test_alias_lists_and_fullwidth_queries(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name, metadata in (
                ("inline", "aliases: [速度平滑化, smoothing]\ntags: [analysis]"),
                ("block", "aliases:\n  - 速度平滑化\n  - smoothing\ntags:\n  - analysis"),
            ):
                self._write(root, name + ".md", "Method", "Compare filters", "Evidence")
                path = root / (name + ".md")
                path.write_text(path.read_text(encoding="utf-8").replace("revision: 1", metadata + "\nrevision: 1"), encoding="utf-8")
            for query in ("速度平滑化", "ｓｍｏｏｔｈｉｎｇ", "analysis"):
                self.assertEqual(len(retrieve_memory.find_notes(root, query)), 2)

    def test_id_and_type_filters_are_exact_and_composable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name, kind in (("run", "experiment"), ("run-old", "router")):
                self._write(root, name + ".md", "Experiment", "Experiment summary", "Evidence")
                path = root / (name + ".md")
                path.write_text(path.read_text(encoding="utf-8").replace("revision: 1", f"revision: 1\nnote_type: {kind}"), encoding="utf-8")
            self.assertEqual([n.note_id for n in retrieve_memory.find_notes(root, note_id="run")], ["run"])
            self.assertEqual([n.note_id for n in retrieve_memory.find_notes(root, note_types=["experiment"])], ["run"])
            self.assertEqual(retrieve_memory.find_notes(root, note_id="run", note_types=["router"]), [])
            self.assertEqual(retrieve_memory.find_notes(root, note_id="../run"), [])
            self.assertEqual(retrieve_memory.find_notes(root, note_id="missing"), [])
            self.assertEqual(len(retrieve_memory.find_notes(root, note_types=["experiment", "router"])), 2)

    def test_duplicate_id_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._write(root, "one/same.md", "One", "Summary", "Evidence")
            self._write(root, "two/same.md", "Two", "Summary", "Evidence")
            with self.assertRaisesRegex(ValueError, "duplicate note_id"):
                retrieve_memory.find_notes(root, note_id="same")

    def test_section_keeps_children_excludes_siblings_and_ignores_code_headings(self) -> None:
        body = "# Main\nintro\n```md\n## Results\nfake\n```\n## Results\nactual\n### Detail\nchild\n## Other\nsibling"
        selected = retrieve_memory.select_section(body, "results")
        self.assertEqual(selected, "## Results\nactual\n### Detail\nchild")
        self.assertIsNone(retrieve_memory.select_section(body, "missing"))
        with self.assertRaisesRegex(ValueError, "ambiguous"):
            retrieve_memory.select_section("## Same\na\n## Same\nb", "Same")

    def test_section_cli_outputs_only_named_evidence_and_full_note_hash(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._write(root, "run.md", "Run", "Summary", "## Results\nactual\n## Other\nsibling")
            args = ["--root", directory, "--id", "run", "--section", "Results", "--provenance"]
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                self.assertEqual(retrieve_memory.main(args), 0)
            packet = output.getvalue()
            self.assertIn("actual", packet)
            self.assertNotIn("sibling", packet)
            digest = hashlib.sha256((root / "run.md").read_text(encoding="utf-8").encode("utf-8")).hexdigest()
            self.assertIn(digest, packet)

    def test_invalid_argument_combinations_are_rejected(self) -> None:
        for args in ([], ["speed", "--section", ""], ["speed", "--section", "Results", "--summaries"],
                     ["speed", "--excerpts", "--summaries"], ["speed", "--max-chars", "499"]):
            with self.subTest(args=args), contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                retrieve_memory.parse_args(args)

    def test_long_first_line_does_not_starve_other_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name, body in (("a", "match " * 3000), ("b", "second-evidence"), ("c", "third-evidence")):
                self._write(root, name + ".md", "Match", "Matching summary", body)
            notes = retrieve_memory.find_notes(root, "match")
            for budget in (500, 1200, 8000):
                packet = retrieve_memory.render_packet("match", notes, 3, budget, summaries_only=False)
                self.assertLessEqual(len(packet), budget)
                self.assertIn("second-evidence", packet)
                self.assertIn("third-evidence", packet)
                self.assertIn("…", packet)

    def test_excerpt_always_obeys_its_own_budget(self) -> None:
        for budget in (0, 1, 4, 5, 80, 500):
            for body in ("prefix " * 2000 + "needle", "needle " * 2000, "short"):
                self.assertLessEqual(len(retrieve_memory._excerpt(body, ["needle"], budget)), budget)

    def test_omitted_entries_are_counted_without_partial_id(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for i in range(3):
                self._write(root, f"{i}.md", "Match", "summary " * 200, "evidence")
            notes = retrieve_memory.find_notes(root, "match")
            packet = retrieve_memory.render_packet("match", notes, 1, 500)
            self.assertIn("omitted=2", packet)
            self.assertLessEqual(len(packet), 500)

    def test_repeated_body_keywords_do_not_outrank_relevant_summary(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._write(root, "target.md", "Speed", "Speed validation", "Actual evidence")
            self._write(root, "index.md", "Index", "Navigation", "speed " * 1000)
            self.assertEqual(retrieve_memory.find_notes(root, "speed")[0].note_id, "target")


if __name__ == "__main__":
    unittest.main()
