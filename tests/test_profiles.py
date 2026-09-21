"""Generic profile onboarding and explicit per-command path isolation."""
import contextlib
import io
import json
import os
from pathlib import Path
import selectors
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch
import urllib.request

from radar.__main__ import main
from radar.config import ConfigError, load_profile, validate_profile
from radar.profiles import PRESET_IDS, init_profile, list_presets, load_preset
from radar.ranking import ANCHORS, rank_paper
from radar.service import ROOT


CUSTOM = {"name": "Protein Research", "categories": ["q-bio.BM"], "topics": [
    {"id": "protein-structure", "label": "Protein structure", "keywords": ["protein folding", "protein design"],
     "anchors": ["protein", "proteins"], "categories": ["q-bio.BM"]}]}


class ProfileTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="radar profile tests ")
        self.addCleanup(self.temp.cleanup)
        self.cwd = Path(self.temp.name)
        self.profile = self.cwd / "custom research.json"
        self.profile.write_text(json.dumps(CUSTOM), encoding="utf-8")
        self.data = self.cwd / "selected collection"
        self.unwanted = self.cwd / "unwanted environment data"
        self.env = {**os.environ, "PYTHONPATH": str(ROOT),
                    "ARXIV_RADAR_PROFILE": str(self.cwd / "missing-environment-profile.json"),
                    "ARXIV_RADAR_DATA_DIR": str(self.unwanted)}
        self.env.pop("PYTHONHOME", None)

    def cli(self, *args, status=0):
        result = subprocess.run([sys.executable, "-m", "radar", *map(str, args)],
                                cwd=self.cwd, env=self.env, capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, status, result.stdout + result.stderr)
        self.assertNotIn("Traceback", result.stderr)
        return result

    def test_presets_have_explicit_anchors_and_cover_all_topic_categories(self):
        self.assertEqual({p["id"] for p in list_presets()}, set(PRESET_IDS))
        for name in PRESET_IDS:
            with self.subTest(preset=name):
                profile = load_preset(name)
                self.assertEqual(validate_profile(profile), profile)
                self.assertEqual(profile["own_arxiv_ids"], [])
                self.assertEqual(profile["self_author_names"], [])
                for topic in profile["topics"]:
                    self.assertNotIn(topic["id"], ANCHORS)
                    self.assertTrue(topic["anchors"])
                    self.assertTrue(set(topic["categories"]) <= set(profile["categories"]))
                    candidate = {"title": topic["keywords"][0], "abstract": topic["anchors"][0],
                                 "categories": topic["categories"], "authors": ["Example Author"]}
                    self.assertGreaterEqual(rank_paper(candidate, profile)["score"], profile["minimum_score"])

    def test_profile_listing_ignores_active_profile_and_has_no_database_side_effect(self):
        result = json.loads(self.cli("profiles").stdout)
        self.assertEqual([p["id"] for p in result["presets"]], list(PRESET_IDS))
        self.assertTrue(result["custom_profiles_supported"])
        self.assertFalse(self.unwanted.exists())
        self.assertFalse((self.cwd / "data").exists())

    def test_custom_output_name_and_timezone_are_validated_before_creation(self):
        output = self.cwd / "settings" / "agents.json"
        result = json.loads(self.cli("init-profile", "--preset", "ai-agents", "--output", output,
                                     "--name", "My Agents", "--timezone", "Asia/Shanghai").stdout)
        self.assertTrue(result["created"])
        loaded = load_profile(output)
        self.assertEqual(loaded["name"], "My Agents")
        self.assertEqual(loaded["display"], {"name": "My Agents", "timezone": "Asia/Shanghai"})
        self.assertFalse(self.unwanted.exists())
        self.assertFalse((self.cwd / "data").exists())

    def test_default_profile_output_is_local_to_invocation_directory(self):
        self.cli("init-profile", "--preset", "astrophysics")
        output = self.cwd / "config/profile.local.json"
        self.assertTrue(output.is_file())
        self.assertIn("astro-ph.CO", load_profile(output)["categories"])

    def test_existing_files_and_dangling_symlinks_are_never_overwritten(self):
        original = self.profile.read_bytes()
        failure = self.cli("init-profile", "--preset", "ai-agents", "--output", self.profile, status=1)
        self.assertIn("already exists", failure.stderr)
        self.assertEqual(self.profile.read_bytes(), original)
        dangling = self.cwd / "dangling.json"
        target = self.cwd / "must-not-create.json"
        dangling.symlink_to(target)
        with self.assertRaises(ConfigError):
            init_profile("ai-agents", dangling)
        self.assertTrue(dangling.is_symlink())
        self.assertFalse(target.exists())

    def test_bad_overrides_and_unknown_presets_do_not_create_output(self):
        output = self.cwd / "not-created" / "profile.json"
        self.cli("init-profile", "--preset", "ai-agents", "--output", output, "--timezone", "invalid/timezone", status=1)
        self.assertFalse(output.parent.exists())
        self.cli("init-profile", "--preset", "ai-agents", "--output", output, "--name", "  ", status=1)
        self.assertFalse(output.exists())
        with self.assertRaises(ConfigError):
            load_preset("../profile")

    def test_arbitrary_non_math_json_validates_and_matches_without_a_preset(self):
        result = json.loads(self.cli("validate-profile", self.profile).stdout)
        self.assertTrue(result["valid"])
        self.assertEqual(result["profile"]["topics"][0]["id"], "protein-structure")
        candidate = {"title": "Protein folding with limited data", "abstract": "Protein structure prediction.", "categories": ["q-bio.BM"]}
        self.assertGreaterEqual(rank_paper(candidate, result["profile"])["score"], 20)
        self.assertFalse(self.unwanted.exists())
        invalid = self.cwd / "invalid.json"
        invalid.write_text('{"topics": []}', encoding="utf-8")
        self.cli("validate-profile", invalid, status=1)
        self.assertFalse(self.unwanted.exists())

    def test_every_stateful_command_passes_explicit_profile_and_data_paths(self):
        review_file = self.cwd / "reviews.json"
        review_file.write_text("[]", encoding="utf-8")
        plan_file = self.cwd / "plan.json"
        plan_file.write_text("{}", encoding="utf-8")
        commands = [("scan", []), ("serve", []), ("review-queue", []),
                    ("import-reviews", [str(review_file)]), ("delivery-plan", []),
                    ("acknowledge", [str(plan_file)]), ("digest", []), ("status", [])]
        for command, positional in commands:
            radar = MagicMock()
            radar.scan.return_value = {"status": "success"}
            radar.review_queue.return_value = {"papers": []}
            radar.import_reviews.return_value = 0
            radar.delivery_plan.return_value = {"should_notify": False}
            radar.digest.return_value = {"markdown": ""}
            radar.state.return_value = {}
            argv = ["radar", command, *positional, "--profile", str(self.profile), "--data-dir", str(self.data)]
            with self.subTest(command=command), patch("sys.argv", argv), \
                 patch("radar.__main__.Radar", return_value=radar) as constructor, \
                 patch("radar.server.serve", return_value=0) as serve, contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main(), 0)
                constructor.assert_called_once_with(profile=self.profile, data_dir=self.data)
                if command == "serve":
                    serve.assert_called_once_with(8765, radar=radar)

    def test_absolute_profile_and_data_paths_work_from_an_unrelated_cwd(self):
        result = json.loads(self.cli("status", "--profile", self.profile, "--data-dir", self.data).stdout)
        self.assertEqual(result["profile"]["name"], CUSTOM["name"])
        self.assertEqual(result["stats"]["papers"], 0)
        self.assertTrue((self.data / "radar.sqlite3").exists())
        self.assertFalse(self.unwanted.exists())

    def test_evaluate_uses_the_explicit_profile_without_creating_a_database(self):
        dataset = {"kind": "synthetic", "name": "Custom profile fixture", "description": "One offline positive example.",
                   "cases": [{"relevant": True, "paper": {"id": "synthetic-protein", "title": "Protein folding", "abstract": "Protein folding methods.",
                                                            "authors": ["Example Author"], "categories": ["q-bio.BM"]}}]}
        path = self.cwd / "labels.json"
        path.write_text(json.dumps(dataset), encoding="utf-8")
        result = json.loads(self.cli("evaluate", path, "--profile", self.profile).stdout)
        self.assertEqual(result["metrics"]["true_positive"], 1)
        self.assertFalse(self.unwanted.exists())
        self.assertFalse(self.data.exists())

    def test_server_exposes_the_selected_profile_and_uses_the_selected_database(self):
        process = subprocess.Popen([sys.executable, "-m", "radar", "serve", "--port", "0", "--profile", str(self.profile), "--data-dir", str(self.data)],
                                   cwd=self.cwd, env=self.env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        def stop():
            process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=3)
            process.stdout.close()
            process.stderr.close()
        self.addCleanup(stop)
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ)
            self.assertTrue(selector.select(timeout=30), "Profile-specific server did not start")
        line = process.stdout.readline()
        self.assertIn("http://127.0.0.1:", line)
        base = "http://" + line.split("http://", 1)[1].strip()
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(base + "/api/state", timeout=3) as response:
            state = json.load(response)
        self.assertEqual(state["profile"]["name"], CUSTOM["name"])
        self.assertEqual(state["topics"][0]["id"], "protein-structure")
        self.assertTrue((self.data / "radar.sqlite3").exists())
        self.assertFalse(self.unwanted.exists())


if __name__ == "__main__":
    unittest.main()
