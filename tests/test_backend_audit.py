"""Independent regressions for observed persistence/state-transition defects."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from radar.service import BusyError, Radar
from radar.store import Store


PROFILE = json.loads((Path(__file__).resolve().parents[1] / "config/profile.json").read_text(encoding="utf-8"))
NOW = "2026-09-21T05:00:00Z"


def paper(version=1, source="arxiv-api", abstract="We establish universality for random matrices under fourth moment assumptions."):
    p = {"id": "2609.12345", "version": version, "version_known": bool(version),
         "title": "Universality for random matrices", "abstract": abstract,
         "authors": ["Ada Example"], "categories": ["math.PR"], "source": source,
         "url": f"https://arxiv.org/abs/2609.12345v{version}",
         "pdf_url": f"https://arxiv.org/pdf/2609.12345v{version}",
         "published": "2026-09-10T00:00:00Z", "updated": "2026-09-10T00:00:00Z",
         "date_basis": "submission"}
    if source == "arxiv-rss":
        p.update(published="", updated="", announced="2026-09-20T00:00:00Z", date_basis="announcement", announce_type="replace")
    return p


class StoreAuditTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = Store(Path(self.temp.name) / "state.sqlite3")

    def test_unknown_version_becoming_known_is_metadata_enrichment(self):
        self.store.upsert(paper(version=0, source="arxiv-rss"), "a", NOW)
        event = self.store.upsert(paper(version=1), "b", NOW)
        self.assertEqual(event, "unchanged", "Unknown -> known version alone is not evidence of an actual revision")
        self.assertEqual(self.store.papers()[0]["version"], 1)

    def test_rss_new_version_does_not_retain_previous_version_updated_date(self):
        self.store.upsert(paper(), "a", NOW)
        self.store.upsert(paper(version=2, source="arxiv-rss"), "b", NOW)
        stored = self.store.papers()[0]
        self.assertEqual(stored["updated"], "", "RSS does not tell us when this new revision was submitted")
        self.assertEqual(stored["announced"], "2026-09-20T00:00:00Z")

    def test_api_metadata_restores_submission_date_basis_after_rss_revision(self):
        self.store.upsert(paper(), "a", NOW)
        self.store.upsert(paper(version=2, source="arxiv-rss"), "b", NOW)
        enriched = paper(version=2)
        enriched["updated"] = "2026-09-19T17:00:00Z"
        self.store.upsert(enriched, "c", NOW)
        self.assertEqual(self.store.papers()[0]["date_basis"], "submission")

    def test_same_version_rss_does_not_replace_richer_api_source(self):
        self.store.upsert(paper(version=2), "a", NOW)
        self.store.upsert(paper(version=2, source="arxiv-rss"), "b", NOW)
        self.assertEqual(self.store.papers()[0]["source"], "arxiv-api")

    def test_changed_abstract_invalidates_review_even_with_same_version(self):
        self.store.upsert(paper(), "a", NOW)
        self.store.review("2609.12345", 1, {"version": 1, "evidence_quotes": ["under fourth moment assumptions"]})
        self.store.upsert(paper(abstract="We give a counterexample requiring stronger tail assumptions."), "b", NOW)
        self.assertIsNone(self.store.papers()[0]["assessment"], "Review quotes no longer match the stored abstract")

    def test_feedback_survives_revision_and_review_is_invalidated(self):
        self.store.upsert(paper(), "a", NOW)
        self.store.feedback("2609.12345", "saved")
        self.store.review("2609.12345", 1, {"version": 1})
        self.store.upsert(paper(version=2), "b", NOW)
        self.assertEqual(self.store.papers()[0]["feedback"], "saved")
        self.assertIsNone(self.store.papers()[0]["assessment"])


class HarnessAuditTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        (root / "config").mkdir()
        (root / "config/profile.json").write_text(json.dumps(PROFILE), encoding="utf-8")
        self.radar = Radar(root)

    @staticmethod
    def fetch_result(papers, status="success"):
        return {"papers": papers, "status": status, "errors": [], "requests": 1,
                "coverage": {"complete_window": status == "success", "sources": ["arxiv-api"]}}

    def test_terminal_status_is_not_published_before_storage_finishes(self):
        observed = []
        original = self.radar.store.upsert
        def upsert(*args, **kwargs):
            observed.append(self.radar.latest()["status"])
            return original(*args, **kwargs)
        with patch.object(self.radar.store, "upsert", side_effect=upsert):
            result = self.radar.scan(fetcher=lambda *a, **kw: self.fetch_result([paper()]))
        self.assertEqual(result["status"], "success")
        self.assertEqual(observed, ["running"], "Only finalized runs should be exposed as terminal")

    def test_partial_scan_does_not_advance_api_watermark(self):
        watermark = "2026-09-18T05:00:00Z"
        self.radar.store.set_setting("watermark", watermark)
        result = self.radar.scan(fetcher=lambda *a, **kw: self.fetch_result([paper()], "partial"))
        self.assertEqual(result["status"], "partial")
        self.assertEqual(self.radar.store.get_setting("watermark"), watermark)

    def test_scan_lock_excludes_another_process_or_instance(self):
        other = Radar(self.radar.root)
        lock = self.radar.acquire()
        try:
            self.assertTrue(other.scanning())
            with self.assertRaises(BusyError):
                other.acquire()
        finally:
            lock.close()
        self.assertFalse(other.scanning())

    def test_cross_listing_counts_once_and_preserves_category_union(self):
        cross = paper()
        cross["categories"] = ["math.ST"]
        result = self.radar.scan(fetcher=lambda *a, **kw: self.fetch_result([paper(), cross]))
        self.assertEqual(result["new_count"], 1)
        self.assertEqual(result["candidate_count"], 1)
        self.assertEqual(set(self.radar.store.papers()[0]["categories"]), {"math.PR", "math.ST"})

    def test_failed_run_does_not_clear_previous_success_new_filter(self):
        good = {"id": "20260921T010000-a", "status": "success", "finished_at": NOW}
        failed = {"id": "20260921T020000-b", "status": "failed", "finished_at": NOW}
        self.radar.store.save_run(good)
        self.radar.store.upsert(paper(), good["id"], NOW)
        self.radar.store.save_run(failed)
        self.assertEqual(len(self.radar.papers(filter="new")), 1,
                         "New/update filters refer to latest successful or partial run, not latest failed run")


if __name__ == "__main__":
    unittest.main()
