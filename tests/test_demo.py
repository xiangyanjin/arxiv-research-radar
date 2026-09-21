"""Fresh-checkout smoke tests; only loopback HTTP, never a live arXiv call."""
import json
import os
from pathlib import Path
import selectors
import shutil
import subprocess
import sys
import tempfile
import unittest
import urllib.error
import urllib.request

from radar.service import ROOT


class DemoSmokeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.clone = Path(self.temp.name) / "clone"
        self.clone.mkdir()
        # Copy only the source intended for a fresh checkout. In particular,
        # never inherit this developer's data or private profile override.
        for name in ("radar", "static", "examples", "config"):
            shutil.copytree(ROOT / name, self.clone / name,
                            ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "profile.local.json"))
        self.env = {key: value for key, value in os.environ.items()
                    if not key.startswith("ARXIV_RADAR_") and key not in ("PYTHONPATH", "PYTHONHOME")}

    def run_cli(self, *args, env=None):
        result = subprocess.run([sys.executable, *args], cwd=self.clone,
                                env=env or self.env, capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout

    def load_demo(self, env=None):
        self.assertIn("No network request", self.run_cli("examples/load_demo.py", env=env))

    def test_demo_overrides_environment_without_touching_private_collection(self):
        private = Path(self.temp.name) / "private-data"
        private.mkdir()
        sentinel = private / "keep.txt"
        sentinel.write_text("unchanged", encoding="utf-8")
        # Invalid custom profiles must be ignored by the isolated demo loader.
        self.load_demo({**self.env, "ARXIV_RADAR_DATA_DIR": str(private),
                        "ARXIV_RADAR_PROFILE": str(self.clone / "missing-private-profile.json")})
        self.assertEqual(list(private.iterdir()), [sentinel])
        self.assertEqual(sentinel.read_text(), "unchanged")
        self.assertFalse((self.clone / "data/radar.sqlite3").exists())
        demo_env = {**self.env, "ARXIV_RADAR_DATA_DIR": "data/demo"}
        state = json.loads(self.run_cli("-m", "radar", "status", env=demo_env))
        self.assertEqual(state["stats"]["papers"], 4)
        self.assertEqual(state["latest_run"]["status"], "partial")
        self.assertFalse(state["latest_run"]["coverage"]["complete_window"])
        self.assertIn("OFFLINE DEMO", state["latest_run"]["errors"][0])
        self.load_demo()
        second = json.loads(self.run_cli("-m", "radar", "status", env=demo_env))
        self.assertEqual(second["stats"]["papers"], 4)
        # The default collection starts empty even after trying the snapshot.
        normal = json.loads(self.run_cli("-m", "radar", "status"))
        self.assertEqual(normal["stats"]["papers"], 0)

    def test_fresh_clone_serves_dashboard_and_rejects_cross_origin_access(self):
        self.load_demo()
        process = subprocess.Popen([sys.executable, "-m", "radar", "serve", "--port", "0"],
                                   cwd=self.clone, env={**self.env, "ARXIV_RADAR_DATA_DIR": "data/demo"},
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
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
            # Hosted runners may start slowly; readiness is the emitted URL,
            # not a startup performance requirement. Keep failure diagnostics.
            ready = selector.select(timeout=30)
        if not ready:
            process.terminate()
            try:
                stdout, stderr = process.communicate(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                stdout, stderr = process.communicate(timeout=3)
            self.fail(f"Dashboard did not start within 30s (exit {process.returncode}). "
                      f"stdout={stdout!r}; stderr={stderr!r}")
        line = process.stdout.readline()
        self.assertIn("http://127.0.0.1:", line)
        base = "http://" + line.split("http://", 1)[1].strip()
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(base, timeout=3) as response:
            self.assertEqual(response.status, 200)
            self.assertIn("text/html", response.headers["Content-Type"])
            self.assertIn("frame-ancestors 'none'", response.headers["Content-Security-Policy"])
            self.assertIn("<!doctype html>", response.read().decode().lower())
        with opener.open(base + "/api/papers", timeout=3) as response:
            papers = json.load(response)
        self.assertEqual(papers["total"], 4)
        body = json.dumps({"id": papers["papers"][0]["id"], "feedback": "saved"}).encode()
        request = urllib.request.Request(base + "/api/feedback", data=body,
                                         headers={"Origin": base, "Content-Type": "application/json"})
        with opener.open(request, timeout=3) as response:
            self.assertEqual(json.load(response), {"ok": True})
        for method, headers in (("GET", {"Host": "attacker.invalid"}),
                                ("GET", {"Origin": "https://attacker.invalid"}),
                                ("POST", {"Origin": "https://attacker.invalid"})):
            request = urllib.request.Request(base + "/api/state", method=method, headers=headers)
            with self.subTest(method=method, headers=headers), self.assertRaises(urllib.error.HTTPError) as raised:
                opener.open(request, timeout=3)
            self.assertEqual(raised.exception.code, 403)
            raised.exception.close()
        with self.assertRaises(urllib.error.HTTPError) as raised:
            opener.open(base + "/../config/profile.json", timeout=3)
        self.assertEqual(raised.exception.code, 404)
        raised.exception.close()

    def test_a_later_scan_can_replace_demo_as_latest_run(self):
        self.load_demo()
        # Simulate a later completed scan without contacting any data source.
        code = """
from radar.service import Radar
r = Radar()
run = r.latest()
run.update(id='20990101T120000000000-test', started_at='2099-01-01T12:00:00Z',
           finished_at='2099-01-01T12:00:01Z', status='success',
           initial_backfill=False, errors=[], new_count=0)
run['coverage']['complete_window'] = True
r.store.save_run(run)
assert r.latest()['id'] == run['id'], 'Demo must not shadow a later run'
assert r.digest()['run_id'] == run['id'], 'Digest should follow the later run'
"""
        self.run_cli("-c", code, env={**self.env, "ARXIV_RADAR_DATA_DIR": "data/demo"})


if __name__ == "__main__":
    unittest.main()
