"""Configuration precedence and isolation must be safe for a fresh clone."""
from copy import deepcopy
from datetime import datetime
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from radar.config import ConfigError, load_profile, validate_profile
from radar.service import Radar, ROOT


PROFILE = json.loads((ROOT / "config/profile.json").read_text(encoding="utf-8"))


class ConfigTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "config").mkdir()
        self.write("config/profile.json", PROFILE)
        self.env = patch.dict(os.environ, {}, clear=True)
        self.env.start()
        self.addCleanup(self.env.stop)

    def write(self, path, value):
        (self.root / path).write_text(json.dumps(value), encoding="utf-8")

    def test_local_profile_overrides_sample_and_env_overrides_local(self):
        local = {**PROFILE, "name": "Local profile"}
        remote = {**PROFILE, "name": "Explicit profile"}
        self.write("config/profile.local.json", local)
        self.write("custom.json", remote)
        self.assertEqual(Radar(self.root).profile["name"], "Local profile")
        with patch.dict(os.environ, {"ARXIV_RADAR_PROFILE": "custom.json"}):
            radar = Radar(self.root)
            self.assertEqual(radar.profile["name"], "Explicit profile")
            self.assertEqual(radar.profile_path, (self.root / "custom.json").resolve())

    def test_missing_explicit_profile_does_not_silently_fall_back(self):
        with patch.dict(os.environ, {"ARXIV_RADAR_PROFILE": "missing.json"}):
            with self.assertRaisesRegex(ConfigError, "missing.json"):
                Radar(self.root)
        self.assertFalse((self.root / "data").exists())

    def test_invalid_json_reports_location_before_creating_data(self):
        (self.root / "config/profile.json").write_text('{"name": }', encoding="utf-8")
        with self.assertRaisesRegex(ConfigError, "line 1, column"):
            Radar(self.root)
        self.assertFalse((self.root / "data").exists())

    def test_bad_profile_fields_are_explained(self):
        cases = [("topics", []), ("categories", ["math.PR OR all:test"]),
                 ("display", {"timezone": "invalid/timezone"}), ("minimum_score", True),
                 ("scan", {"lookback_days": 0}), ("digest_limit", "eight")]
        for field, value in cases:
            with self.subTest(field=field), self.assertRaisesRegex(ConfigError, field):
                validate_profile({**PROFILE, field: value})
        duplicate = deepcopy(PROFILE)
        duplicate["topics"].append(deepcopy(duplicate["topics"][0]))
        with self.assertRaisesRegex(ConfigError, "topics"):
            validate_profile(duplicate)

    def test_optional_settings_default_without_mutating_input(self):
        profile = {"name": "Example", "categories": ["cs.AI"], "topics": [
            {"id": "agents", "label": "Agents", "keywords": ["language model agent"]}]}
        validated = validate_profile(profile)
        self.assertEqual(validated["display"], {"name": "Example", "timezone": "UTC"})
        self.assertEqual(validated["scan"]["lookback_days"], 14)
        self.assertNotIn("scan", profile)

    def test_lowercase_physics_categories_are_accepted(self):
        profile = {**PROFILE, "categories": ["physics.optics", "cond-mat.stat-mech", "astro-ph.GA", "hep-th"]}
        self.assertEqual(validate_profile(profile)["categories"], profile["categories"])

    def test_data_directory_separates_state_locks_and_outputs(self):
        with patch.dict(os.environ, {"ARXIV_RADAR_DATA_DIR": "data-a"}):
            first = Radar(self.root)
        with patch.dict(os.environ, {"ARXIV_RADAR_DATA_DIR": "data-b"}):
            second = Radar(self.root)
        first.store.set_setting("watermark", "2026-09-01T00:00:00Z")
        self.assertIsNone(second.store.get_setting("watermark"))
        first_lock = first.acquire()
        try:
            self.assertFalse(second.scanning())
        finally:
            first_lock.close()
        first.scan(fetcher=lambda *a, **kw: {"papers": [], "status": "success", "coverage": {"complete_window": True}})
        self.assertTrue((first.data / "digests/latest.json").exists())
        self.assertFalse((second.data / "digests").exists())
        self.assertFalse((self.root / "data").exists())

    def test_category_change_backfills_instead_of_reusing_watermark(self):
        radar = Radar(self.root)
        watermark = "2026-09-20T00:00:00Z"
        radar.store.set_setting("watermark", watermark)
        radar.store.set_setting("scan_categories", ["cs.AI"])
        profile = deepcopy(PROFILE)
        profile["scan"].update(lookback_days=14, overlap_days=0)
        self.write("config/profile.json", profile)
        run = radar.scan(fetcher=lambda *a, **kw: {"papers": [], "status": "success", "coverage": {"complete_window": True}})
        self.assertTrue(run["scope_changed"])
        duration = datetime.fromisoformat(run["coverage"]["until"]) - datetime.fromisoformat(run["coverage"]["since"])
        self.assertEqual(duration.days, 14)
        self.assertEqual(radar.store.get_setting("scan_categories"), sorted(PROFILE["categories"]))

    def test_cli_reports_config_error_without_traceback(self):
        env = {**os.environ, "ARXIV_RADAR_PROFILE": str(self.root / "missing.json")}
        result = subprocess.run([sys.executable, "-m", "radar", "status"], cwd=ROOT, env=env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 1)
        self.assertIn("missing.json", result.stderr)
        self.assertNotIn("Traceback", result.stderr)


if __name__ == "__main__":
    unittest.main()
