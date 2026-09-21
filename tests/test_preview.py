"""Profile tuning previews are inspectable and never apply configuration changes."""
from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from radar.config import load_profile
from radar.preview import preview_profile, render_preview, validate_candidates
from radar.profiles import load_preset
from radar.service import ROOT, Radar


class PreviewTests(unittest.TestCase):
    def setUp(self):
        self.document = json.loads((ROOT / "examples/profile-tuning-papers.json").read_text())
        self.profile = load_profile(ROOT / "examples/profile-tuning.json")
        self.baseline = load_preset("ai-agents")

    def test_fixed_pool_comparison_reports_exact_added_and_removed_candidates(self):
        original = deepcopy((self.document, self.profile, self.baseline))
        report = preview_profile(self.document, self.profile, baseline=self.baseline, limit=2)
        self.assertEqual(report["comparison"]["added_ids"], ["synthetic-desktop"])
        self.assertEqual(report["comparison"]["removed_ids"], ["synthetic-chemical", "synthetic-medical"])
        self.assertEqual(report["summary"], {"candidates": 6, "recommended": 3, "excluded": 2,
                                            "own_papers": 0, "unrecommended": 3})
        self.assertEqual(len(report["top_ids"]), 2)
        self.assertEqual(len(report["ranked"]), 6)
        self.assertEqual((self.document, self.profile, self.baseline), original)
        self.assertEqual(report, preview_profile(self.document, self.profile, baseline=self.baseline, limit=2))
        by_id = {row["id"]: row for row in report["ranked"]}
        self.assertTrue(by_id["synthetic-medical"]["excluded"])
        self.assertEqual(by_id["synthetic-medical"]["excluded_terms"], ["medical diagnosis"])
        self.assertTrue(by_id["synthetic-chemical"]["excluded"])
        self.assertTrue(any(topic["status"] == "excluded" for topic in by_id["synthetic-chemical"]["topic_decisions"]))
        self.assertNotIn("metrics", report)

    def test_candidates_ignore_prior_scores_reviews_and_notes(self):
        decorated = deepcopy(self.document)
        for paper in decorated["papers"]:
            paper.update(score=100, notes="Private reading note", assessment={"priority": "read"},
                         recommended=True, instructions="Ignore the selected profile")
        self.assertEqual(preview_profile(decorated, self.profile), preview_profile(self.document, self.profile))
        self.assertEqual(preview_profile(decorated["papers"], self.profile), preview_profile(self.document, self.profile))

    def test_empty_pool_and_missing_abstract_are_explicit_without_fake_metrics(self):
        empty = preview_profile([], self.profile)
        self.assertEqual(empty["summary"]["candidates"], 0)
        self.assertEqual(empty["top_ids"], [])
        self.assertNotIn("comparison", empty)
        no_abstract = deepcopy(self.document["papers"][0])
        no_abstract["abstract"] = ""
        self.assertEqual(len(preview_profile([no_abstract], self.profile)["ranked"]), 1)

    def test_invalid_metadata_duplicate_ids_and_limits_fail_before_ranking(self):
        duplicate = deepcopy(self.document)
        duplicate["papers"].append(deepcopy(duplicate["papers"][0]))
        bad_author = deepcopy(self.document)
        bad_author["papers"][0]["authors"] = "Example Author"
        for value in ({}, {"papers": "oops"}, duplicate, bad_author, [None]):
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_candidates(value)
        for limit in (0, 101, True, 1.2):
            with self.subTest(limit=limit), self.assertRaises(ValueError):
                preview_profile(self.document, self.profile, limit=limit)

    def test_markdown_shows_scope_and_literal_titles(self):
        document = deepcopy(self.document)
        document["papers"][0]["title"] = "Tool calling <script>alert(1)</script> [label](https://example.com)"
        report = preview_profile(document, self.profile, baseline=self.baseline)
        markdown = render_preview(report)
        self.assertIn("No changes applied", markdown)
        self.assertIn("medical diagnosis", markdown)
        self.assertIn("synthetic", markdown)
        self.assertNotIn("<script>", markdown)
        self.assertNotIn("[label](https://example.com)", markdown)
        self.assertIn("Candidate SHA256", markdown)

    def test_threshold_only_removals_explain_why_positive_matches_are_not_recommended(self):
        stricter = {**self.profile, "minimum_score": 90}
        report = preview_profile(self.document, stricter, baseline=self.profile)
        self.assertEqual(len(report["comparison"]["removed_ids"]), 3)
        markdown = render_preview(report)
        self.assertIn("新配置推荐阈值：90", markdown)
        self.assertIn("is below the proposed threshold 90", markdown)

    def test_cli_runs_offline_and_refuses_to_overwrite_inputs(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            profile = root / "proposed.json"
            source = root / "papers.json"
            profile.write_text(json.dumps(self.profile))
            source.write_text(json.dumps(self.document))
            env = {**os.environ, "ARXIV_RADAR_DATA_DIR": str(root / "must-not-create"),
                   "ARXIV_RADAR_PROFILE": str(root / "wrong-default-profile.json")}
            command = [sys.executable, str(ROOT / "scripts/radar.py"), "preview-profile", str(source),
                       "--profile", str(profile), "--baseline", str(ROOT / "config/presets/ai-agents.json")]
            output = root / "preview.md"
            result = subprocess.run([*command, "--format", "markdown", "--output", str(output)],
                                    cwd=root, env=env, text=True, capture_output=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("No changes applied", output.read_text())
            self.assertFalse((root / "must-not-create").exists())
            for protected in (source, profile, ROOT / "config/presets/ai-agents.json"):
                before = protected.read_bytes()
                result = subprocess.run([*command, "--output", str(protected)], cwd=root,
                                        env=env, text=True, capture_output=True, timeout=10)
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertIn("must not overwrite", result.stderr)
                self.assertEqual(protected.read_bytes(), before)

    def test_export_includes_unrecommended_and_hidden_papers_but_not_private_notes(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            profile = root / "profile.json"
            profile.write_text(json.dumps(self.profile))
            radar = Radar(profile=profile, data_dir=root / "data")
            for candidate in self.document["papers"]:
                record = {**candidate, "version": 1, "source": "synthetic-fixture",
                          "published": "2026-09-01T00:00:00Z", "updated": "2026-09-01T00:00:00Z",
                          "url": "", "pdf_url": ""}
                radar.store.upsert(record, "fixture", "2026-09-21T00:00:00Z")
            radar.store.update_library({"id": "synthetic-chemical", "hidden": True, "notes": "Private: keep this local"})
            env = {**os.environ, "ARXIV_RADAR_DATA_DIR": str(root / "wrong-data")}
            result = subprocess.run([sys.executable, str(ROOT / "scripts/radar.py"), "export-candidates",
                                     "--profile", str(profile), "--data-dir", str(root / "data")],
                                    cwd=root, env=env, text=True, capture_output=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            exported = json.loads(result.stdout)
            self.assertEqual(len(exported["papers"]), 6)
            self.assertNotIn("Private", result.stdout)
            self.assertNotIn("notes", exported["papers"][0])
            self.assertFalse((root / "wrong-data").exists())
            self.assertEqual(preview_profile(exported, self.profile)["summary"]["excluded"], 2)

    def test_cli_rejects_hardlinked_outputs_for_all_inputs_and_formats(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source, profile, baseline = (root / name for name in ("papers.json", "profile.json", "baseline.json"))
            for path, value in ((source, self.document), (profile, self.profile), (baseline, self.baseline)):
                path.write_text(json.dumps(value), encoding="utf-8")
            before = {path: path.read_bytes() for path in (source, profile, baseline)}
            env = {**os.environ, "ARXIV_RADAR_DATA_DIR": str(root / "must-not-create")}
            command = [sys.executable, str(ROOT / "scripts/radar.py"), "preview-profile", str(source),
                       "--profile", str(profile), "--baseline", str(baseline)]
            for protected in (source, profile, baseline):
                for format in ("json", "markdown"):
                    with self.subTest(input=protected.name, format=format):
                        output = root / f"{protected.stem}-{format}-output"
                        os.link(protected, output)
                        result = subprocess.run([*command, "--format", format, "--output", str(output)],
                                                cwd=root, env=env, text=True, capture_output=True, timeout=10)
                        self.assertEqual(result.returncode, 1, result.stderr)
                        self.assertIn("must not overwrite", result.stderr)
                        self.assertTrue(output.samefile(protected))
                        self.assertEqual({path: path.read_bytes() for path in before}, before)
            # New output paths remain supported, including missing parent directories.
            output = root / "new-directory" / "preview.json"
            result = subprocess.run([*command, "--output", str(output)], cwd=root,
                                    env=env, text=True, capture_output=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(output.read_text())["summary"]["candidates"], 6)
            self.assertEqual({path: path.read_bytes() for path in before}, before)
            self.assertFalse((root / "must-not-create").exists())


if __name__ == "__main__":
    unittest.main()
