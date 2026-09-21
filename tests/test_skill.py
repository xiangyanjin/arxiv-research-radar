"""Exercise a relocated, self-contained skill without network or host setup."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from radar.service import ROOT


class InstalledSkillTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.base = Path(temp.name)
        self.skill = self.base / "installed skills" / "arxiv-research-radar"
        self.skill.mkdir(parents=True)
        for folder in ("scripts", "radar", "config", "static"):
            shutil.copytree(ROOT / folder, self.skill / folder,
                            ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "profile.local.json"))
        self.project = self.base / "another project"
        self.project.mkdir()
        # A caller's similarly named module must not replace the skill runtime.
        (self.project / "radar.py").write_text("raise RuntimeError('wrong package')\n", encoding="utf-8")
        self.env = {key: value for key, value in os.environ.items()
                    if not key.startswith("ARXIV_RADAR_") and key not in ("PYTHONPATH", "PYTHONHOME")}

    def cli(self, *args, success=True):
        result = subprocess.run([sys.executable, str(self.skill / "scripts/radar.py"), *map(str, args)],
                                cwd=self.project, env=self.env, text=True,
                                capture_output=True, timeout=15)
        if success:
            self.assertEqual(result.returncode, 0, result.stderr)
        else:
            self.assertNotEqual(result.returncode, 0)
        return result

    def test_relocated_skill_initializes_and_reuses_an_arbitrary_direction(self):
        workspace = self.project / "radar-workspace"
        workspace.mkdir()
        profile = workspace / "profile.json"
        profile.write_text(json.dumps({
            "name": "Neural signal research", "categories": ["q-bio.NC"],
            "topics": [{"id": "neural-signals", "label": "神经信号解码",
                        "keywords": ["neural decoding", "brain computer interface"],
                        "anchors": ["neural decoding", "brain computer interface"],
                        "categories": ["q-bio.NC"]}]
        }), encoding="utf-8")
        original = profile.read_bytes()
        self.cli("validate-profile", profile)
        self.assertFalse((workspace / "data").exists())
        state = json.loads(self.cli("status", "--profile", profile,
                                    "--data-dir", workspace / "data").stdout)
        self.assertEqual(state["profile"]["name"], "Neural signal research")
        self.assertEqual([x["id"] for x in state["topics"]], ["neural-signals"])
        self.assertTrue((workspace / "data/radar.sqlite3").is_file())
        self.assertEqual(profile.read_bytes(), original)
        self.assertFalse((self.skill / "data").exists())
        self.assertFalse((self.project / "data").exists())

    def test_preset_setup_does_not_create_a_database_or_replace_a_profile(self):
        self.cli("profiles")
        profile = self.project / "radar-workspace/profile.json"
        self.cli("init-profile", "--preset", "astrophysics", "--output", profile,
                 "--name", "My exoplanet feed", "--timezone", "Asia/Shanghai")
        self.cli("validate-profile", profile)
        original = profile.read_bytes()
        self.cli("init-profile", "--preset", "ai-agents", "--output", profile, success=False)
        self.assertEqual(profile.read_bytes(), original)
        self.assertFalse(any(self.base.rglob("*.sqlite3")))
        self.assertFalse((self.skill / "config/profile.local.json").exists())


if __name__ == "__main__":
    unittest.main()
