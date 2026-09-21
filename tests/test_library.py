"""Reading-library migration, independent state, and exact-view export contracts."""
from copy import deepcopy
import json
import os
from pathlib import Path
import selectors
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
import urllib.error
import urllib.parse
import urllib.request

from radar.service import Radar, ROOT
from radar.store import Store


PROFILE = json.loads((ROOT / "config/profile.json").read_text(encoding="utf-8"))
NOW = "2026-09-21T06:00:00Z"


def paper(number=1, version=1, title="Random matrices", updated=NOW):
    identity = f"2609.{number:05d}"
    return {"id": identity, "version": version, "title": title, "authors": ["Example Author"],
            "abstract": "We study random matrices and their strong convergence.", "categories": ["math.PR"],
            "published": "2026-09-01T00:00:00Z", "updated": updated,
            "url": f"https://arxiv.org/abs/{identity}v{version}",
            "pdf_url": f"https://arxiv.org/pdf/{identity}v{version}", "source": "test-fixture"}


def create_legacy(path):
    with sqlite3.connect(path) as db:
        db.execute("""CREATE TABLE papers (id TEXT PRIMARY KEY, version INTEGER NOT NULL,
                    payload TEXT NOT NULL, first_seen TEXT NOT NULL, last_seen TEXT NOT NULL,
                    feedback TEXT NOT NULL DEFAULT '', assessment TEXT)""")
        for number, feedback in enumerate(("saved", "read", "irrelevant", ""), start=1):
            record = paper(number)
            db.execute("INSERT INTO papers VALUES (?,?,?,?,?,?,?)", (record["id"], 1, json.dumps(record), NOW, NOW,
                                                                       feedback, json.dumps({"version": 1})))


class MigrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "legacy.sqlite3"
        create_legacy(self.path)

    def test_legacy_feedback_migrates_without_changing_records(self):
        store = Store(self.path)
        records = {p["id"]: p for p in store.papers()}
        self.assertEqual(len(records), 4)
        for number, state in ((1, "saved"), (2, "read"), (3, "hidden")):
            record = records[paper(number)["id"]]
            self.assertTrue(record[state])
            self.assertEqual(sum(record[key] for key in ("saved", "read", "hidden")), 1)
            self.assertEqual(record["assessment"], {"version": 1})
            self.assertEqual(record["first_seen"], NOW)
            self.assertEqual((record["notes"], record["notes_updated_at"], record["notes_version"]), ("", "", None))
        store.update_library({"id": paper()["id"], "read": True, "notes": "Keep this note"})
        reopened = Store(self.path).papers()[0]
        self.assertTrue(reopened["saved"] and reopened["read"])
        self.assertEqual(reopened["notes"], "Keep this note")

    def test_concurrent_processes_migrate_the_same_legacy_database(self):
        directory = Path(self.temp.name)
        gate = directory / "go"
        code = """from pathlib import Path
import sys, time
from radar.store import Store
Path(sys.argv[3]).touch()
deadline = time.monotonic() + 20
while not Path(sys.argv[2]).exists():
    if time.monotonic() > deadline: raise RuntimeError('Migration gate timed out')
    time.sleep(.01)
s = Store(Path(sys.argv[1]))
assert len(s.papers()) == 4
assert s.papers()[0]['saved']
"""
        processes = []
        try:
            for index in range(3):
                processes.append(subprocess.Popen([sys.executable, "-c", code, str(self.path), str(gate), str(directory / f"ready-{index}")],
                                                  cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True))
            deadline = time.monotonic() + 15
            while len(list(directory.glob("ready-*"))) < 3 and time.monotonic() < deadline:
                time.sleep(.01)
            self.assertEqual(len(list(directory.glob("ready-*"))), 3)
            gate.touch()
            for process in processes:
                stdout, stderr = process.communicate(timeout=20)
                self.assertEqual(process.returncode, 0, stdout + stderr)
        finally:
            for process in processes:
                if process.poll() is None:
                    process.kill()
                process.communicate(timeout=3)
        self.assertEqual(len(Store(self.path).papers()), 4)


class LibraryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "config").mkdir()
        profile = deepcopy(PROFILE)
        profile["digest_limit"] = 1
        (self.root / "config/profile.json").write_text(json.dumps(profile), encoding="utf-8")
        clean = {key: value for key, value in os.environ.items() if not key.startswith("ARXIV_RADAR_")}
        self.environment = patch.dict(os.environ, clean, clear=True)
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.radar = Radar(self.root)
        self.radar.store.upsert(paper(), "test", NOW)

    def record(self, number=1):
        return next(p for p in self.radar.store.papers() if p["id"] == paper(number)["id"])

    def test_independent_states_partial_updates_and_legacy_compatibility(self):
        self.radar.store.update_library({"id": paper()["id"], "saved": True})
        self.radar.store.update_library({"id": paper()["id"], "read": True})
        self.assertTrue(self.record()["saved"] and self.record()["read"])
        self.radar.store.update_library({"id": paper()["id"], "notes": "Do not clear states"})
        self.radar.store.update_library({"id": paper()["id"], "hidden": True})
        self.assertTrue(self.record()["saved"] and self.record()["read"] and self.record()["hidden"])
        self.radar.store.update_library({"id": paper()["id"], "hidden": False, "read": False})
        self.assertTrue(self.record()["saved"])
        self.assertFalse(self.record()["read"])
        self.assertEqual(self.record()["notes"], "Do not clear states")
        self.radar.store.feedback(paper()["id"], "read")
        self.assertTrue(self.record()["read"])
        self.assertFalse(self.record()["saved"])
        self.assertEqual(self.record()["feedback"], "read")
        self.assertEqual(self.record()["notes"], "Do not clear states")

    def test_notes_survive_revisions_and_capture_the_version_when_saved(self):
        self.radar.store.update_library({"id": paper()["id"], "notes": "Version one notes"})
        first = self.record()
        self.assertEqual(first["notes_version"], 1)
        self.assertTrue(first["notes_updated_at"])
        self.radar.store.upsert(paper(version=2), "new-version", NOW)
        self.assertEqual(self.record()["notes"], "Version one notes")
        self.assertEqual(self.record()["notes_version"], 1)
        self.assertIn("different paper version", self.radar.markdown(filter="notes"))
        self.radar.store.update_library({"id": paper()["id"], "notes": "Version two notes"})
        self.assertEqual(self.record()["notes_version"], 2)
        reopened = Radar(self.root)
        self.assertEqual(reopened.papers(filter="notes")[0]["notes"], "Version two notes")
        self.radar.store.update_library({"id": paper()["id"], "notes": "  \n"})
        self.assertEqual(self.record()["notes"], "  \n")
        self.assertIsNone(self.record()["notes_version"])
        self.assertEqual(self.radar.papers(filter="notes"), [])

    def test_managed_papers_remain_reachable_after_profile_change(self):
        self.radar.store.update_library({"id": paper()["id"], "saved": True, "read": True, "notes": "Keep"})
        changed = deepcopy(PROFILE)
        changed["minimum_score"] = 100
        changed["topics"] = [{"id": "other", "label": "Other", "keywords": ["unrelated topic"], "categories": ["cs.AI"]}]
        (self.root / "config/profile.json").write_text(json.dumps(changed), encoding="utf-8")
        self.assertEqual(self.radar.papers(), [])
        for view in ("saved", "read", "notes"):
            self.assertEqual([p["id"] for p in self.radar.papers(filter=view)], [paper()["id"]])
        self.assertIn(paper()["id"], self.radar.bibtex())
        self.radar.store.update_library({"id": paper()["id"], "hidden": True})
        for view in ("saved", "read", "notes", "all"):
            self.assertEqual(self.radar.papers(filter=view), [])
        self.assertEqual(len(self.radar.papers(filter="hidden")), 1)

    def test_filters_notes_search_sort_and_stats_use_independent_fields(self):
        self.radar.store.upsert(paper(2, title="Alpha random matrices", updated="2026-09-19T00:00:00Z"), "test", NOW)
        self.radar.store.upsert(paper(3, title="Zeta random matrices", updated="2026-09-22T00:00:00Z"), "test", NOW)
        self.radar.store.update_library({"id": paper()["id"], "saved": True, "read": True, "notes": "Unique research question"})
        self.assertEqual([p["id"] for p in self.radar.papers(q="RESEARCH QUESTION")], [paper()["id"]])
        self.assertEqual(len(self.radar.papers(filter="unread")), 2)
        self.assertEqual(len(self.radar.papers(filter="read")), 1)
        self.assertEqual([p["id"] for p in self.radar.papers(sort="title")], [paper(2)["id"], paper()["id"], paper(3)["id"]])
        self.assertEqual([p["id"] for p in self.radar.papers(sort="newest")], [paper(3)["id"], paper()["id"], paper(2)["id"]])
        self.assertEqual([p["id"] for p in self.radar.papers(sort="relevance")], [paper(3)["id"], paper()["id"], paper(2)["id"]])
        stats = self.radar.state()["stats"]
        self.assertEqual((stats["saved"], stats["read"], stats["notes"]), (1, 1, 1))
        self.assertNotIn(paper()["id"], [p["id"] for p in self.radar.review_queue()["papers"]])

    def test_current_view_exports_are_exact_untruncated_and_preserve_notes_as_text(self):
        for number in range(2, 5):
            self.radar.store.upsert(paper(number, title=f"Random matrices {number}"), "test", NOW)
            self.radar.store.update_library({"id": paper(number)["id"], "saved": True, "notes": "Same export selector"})
        self.radar.store.update_library({"id": paper(4)["id"], "hidden": True})
        selected = self.radar.papers(filter="saved", q="export selector", topic="matrix", sort="title")
        self.assertEqual(len(selected), 2)
        params = {"scope": "view", "filter": "saved", "q": "export selector", "topic": "matrix", "sort": "title"}
        bib = self.radar.bibtex(**params)
        markdown = self.radar.markdown(**params)
        self.assertEqual(bib.count("@misc{"), len(selected))
        self.assertEqual(markdown.count("### Original abstract"), len(selected))
        self.assertLess(bib.index(paper(2)["id"]), bib.index(paper(3)["id"]))
        self.assertNotIn(paper(4)["id"], bib + markdown)
        self.assertEqual(self.radar.bibtex(scope="view", q="no matches").strip(), "")
        hostile = '```\n<script>alert(1)</script>\n[link](javascript:alert(1))\n````'
        self.radar.store.update_library({"id": paper()["id"], "notes": hostile})
        exported = self.radar.markdown(filter="notes", q="alert(1)")
        self.assertIn("`````text\n" + hostile + "\n`````", exported)
        self.assertIn("### User notes", exported)

    def test_invalid_library_patches_and_view_parameters_are_rejected_without_changes(self):
        before = self.record()
        invalid = [[], None, {}, {"id": paper()["id"]}, {"id": []}, {"id": "unknown", "saved": True},
                   {"id": paper()["id"], "saved": 1}, {"id": paper()["id"], "read": "true"},
                   {"id": paper()["id"], "hidden": None}, {"id": paper()["id"], "notes": []},
                   {"id": paper()["id"], "notes": "x" * 5001}, {"id": paper()["id"], "notes_version": 2},
                   {"id": paper()["id"], "saved": True, "unexpected": "no"}]
        for document in invalid:
            with self.subTest(document=str(document)[:100]), self.assertRaises(ValueError):
                self.radar.store.update_library(document)
        self.assertEqual(self.record(), before)
        for params in ({"filter": "invalid"}, {"sort": "invalid"}):
            with self.assertRaises(ValueError):
                self.radar.papers(**params)


class LibraryHTTPTests(LibraryTests):
    # HTTP contract coverage uses the same isolated library fixture but does not
    # inherit its test methods a second time (see test loader below).
    def test_http_patch_validation_and_exact_view_exports(self):
        self.radar.store.upsert(paper(2), "test", NOW)
        env = {**os.environ, "ARXIV_RADAR_DATA_DIR": str(self.radar.data),
               "ARXIV_RADAR_PROFILE": str(self.root / "config/profile.json")}
        process = subprocess.Popen([sys.executable, "-m", "radar", "serve", "--port", "0"], cwd=ROOT,
                                   env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
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
            self.assertTrue(selector.select(timeout=30), "Library server did not start")
        base = "http://" + process.stdout.readline().split("http://", 1)[1].strip()
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        def post(document, origin=base):
            request = urllib.request.Request(base + "/api/library", data=json.dumps(document).encode(),
                                             headers={"Origin": origin, "Content-Type": "application/json"})
            with opener.open(request, timeout=3) as response:
                return json.load(response)
        note = "😀" * 5000
        response = post({"id": paper()["id"], "saved": True, "read": True, "notes": note})
        self.assertTrue(response["ok"] and response["paper"]["saved"] and response["paper"]["read"])
        self.assertEqual(response["paper"]["notes"], note)
        for document in ([1], {"id": "unknown", "saved": True}, {"id": paper()["id"], "saved": "yes"},
                         {"id": paper()["id"], "notes_version": 2}):
            with self.assertRaises(urllib.error.HTTPError) as raised:
                post(document)
            self.assertEqual(raised.exception.code, 400)
            raised.exception.close()
        with self.assertRaises(urllib.error.HTTPError) as raised:
            post({"id": paper()["id"], "saved": False}, origin="https://attacker.invalid")
        self.assertEqual(raised.exception.code, 403)
        raised.exception.close()
        query = urllib.parse.urlencode({"scope": "view", "filter": "saved", "q": "😀", "sort": "title"})
        with opener.open(base + "/api/papers?" + query, timeout=3) as response:
            selected = json.load(response)
        self.assertEqual(selected["total"], 1)
        for endpoint, mime in (("bib", "application/x-bibtex"), ("markdown", "text/markdown")):
            with opener.open(base + "/api/exports/" + endpoint + "?" + query, timeout=3) as response:
                text = response.read().decode()
                self.assertIn(mime, response.headers["Content-Type"])
                self.assertIn("attachment", response.headers["Content-Disposition"])
            self.assertIn(paper()["id"], text)
            self.assertNotIn(paper(2)["id"], text)
        with self.assertRaises(urllib.error.HTTPError) as raised:
            opener.open(base + "/api/papers?sort=invalid", timeout=3)
        self.assertEqual(raised.exception.code, 400)
        raised.exception.close()


def load_tests(loader, tests, pattern):
    suite = unittest.TestSuite()
    suite.addTests(loader.loadTestsFromTestCase(MigrationTests))
    suite.addTests(loader.loadTestsFromTestCase(LibraryTests))
    suite.addTest(LibraryHTTPTests("test_http_patch_validation_and_exact_view_exports"))
    return suite


if __name__ == "__main__":
    unittest.main()
