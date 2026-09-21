import json
from pathlib import Path
import tempfile
import unittest

from radar.service import Radar, BusyError, ROOT


def paper(version=1):
    return {"id": "2609.12345", "version": version, "title": "Random matrices and strong convergence",
            "abstract": "We establish strong convergence for random matrices with independent entries.",
            "authors": ["Test Author"], "categories": ["math.PR"],
            "published": "2026-09-10T12:00:00Z", "updated": "2026-09-19T12:00:00Z",
            "url": f"https://arxiv.org/abs/2609.12345v{version}", "pdf_url": "https://arxiv.org/pdf/2609.12345", "source": "fixture"}


class HarnessTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "config").mkdir()
        (self.root / "config/profile.json").write_bytes((ROOT / "config/profile.json").read_bytes())
        self.radar = Radar(self.root)

    def tearDown(self):
        self.tmp.cleanup()

    def fetch(self, papers, status="success"):
        return lambda *a, **kw: {"papers": papers, "status": status, "errors": [], "coverage": {"complete_window": status == "success"}}

    def test_duplicates_revisions_feedback_and_no_downgrade(self):
        r = self.radar.scan(fetcher=self.fetch([paper(), paper()]))
        self.assertEqual((r["candidate_count"], r["new_count"]), (1, 1))
        self.radar.store.feedback("2609.12345", "saved")
        r = self.radar.scan(fetcher=self.fetch([paper()]))
        self.assertEqual((r["new_count"], r["updated_count"]), (0, 0))
        r = self.radar.scan(fetcher=self.fetch([paper(2)]))
        self.assertEqual(r["updated_count"], 1)
        self.radar.scan(fetcher=self.fetch([paper()]))
        p = self.radar.papers()[0]
        self.assertEqual((p["version"], p["feedback"]), (2, "saved"))

    def test_partial_and_fail_do_not_advance_watermark(self):
        self.radar.scan(fetcher=self.fetch([paper()], "partial"))
        self.assertIsNone(self.radar.store.get_setting("watermark"))
        self.radar.scan(fetcher=self.fetch([], "failed"))
        self.assertIsNone(self.radar.store.get_setting("watermark"))
        self.assertIn("不能据此判断", self.radar.digest()["markdown"])
        self.radar.scan(fetcher=self.fetch([]))
        self.assertIsNotNone(self.radar.store.get_setting("watermark"))

    def test_process_lock_and_exception_release(self):
        handle = self.radar.acquire()
        with self.assertRaises(BusyError):
            self.radar.scan(fetcher=self.fetch([]))
        handle.close()
        def bad(*a, **kw):
            raise RuntimeError("network unavailable")
        self.assertEqual(self.radar.scan(fetcher=bad)["status"], "failed")
        self.assertFalse(self.radar.scanning())

    def review(self):
        return {"id": "2609.12345", "version": 1, "summary_zh": "研究随机矩阵强收敛。", "relevance_zh": "与强收敛方向有关。", "caveat_zh": "仅依据摘要，未核对证明。", "model": "test", "evidence_level": "abstract", "priority": "read", "evidence_quotes": ["strong convergence for random matrices"]}

    def test_review_evidence_and_revision_invalidation(self):
        self.radar.scan(fetcher=self.fetch([paper()]))
        self.radar.import_reviews([self.review()])
        self.assertIsNotNone(self.radar.papers()[0]["assessment"])
        bad = self.review()
        bad["evidence_quotes"] = ["A theorem never stated in the abstract"]
        with self.assertRaises(ValueError):
            self.radar.import_reviews([bad])
        self.radar.scan(fetcher=self.fetch([paper(2)]))
        self.assertIsNone(self.radar.papers()[0]["assessment"])
        with self.assertRaises(ValueError):
            self.radar.import_reviews([self.review()])

    def test_manual_short_window_cannot_close_historical_gap(self):
        self.radar.store.set_setting("watermark", "2020-01-01T00:00:00Z")
        self.radar.scan(days=1, fetcher=self.fetch([]))
        self.assertEqual(self.radar.store.get_setting("watermark"), "2020-01-01T00:00:00Z")

    def test_unknown_version_refinement_is_not_revision(self):
        p = paper(0)
        self.radar.scan(fetcher=self.fetch([p], "partial"))
        r = self.radar.scan(fetcher=self.fetch([paper()]))
        self.assertEqual(r["updated_count"], 0)
        self.assertEqual(self.radar.papers()[0]["version"], 1)

    def test_notifications_are_durable_and_revisions_notify_again(self):
        self.radar.scan(fetcher=self.fetch([paper()]))
        plan = self.radar.delivery_plan()
        self.assertTrue(plan["should_notify"])
        self.radar.acknowledge(plan)
        self.assertFalse(Radar(self.root).delivery_plan()["should_notify"])
        self.radar.scan(fetcher=self.fetch([paper(2)]))
        self.assertTrue(self.radar.delivery_plan()["should_notify"])
        with self.assertRaises(ValueError):
            self.radar.acknowledge(plan)

    def test_same_failure_is_quiet_and_recovery_is_notified(self):
        self.radar.scan(fetcher=self.fetch([], "failed"))
        self.assertTrue(self.radar.delivery_plan()["should_notify"])
        self.radar.acknowledge(self.radar.delivery_plan())
        self.radar.scan(fetcher=self.fetch([], "failed"))
        self.assertFalse(self.radar.delivery_plan()["should_notify"])
        self.radar.scan(fetcher=self.fetch([]))
        self.assertTrue(self.radar.delivery_plan()["should_notify"])


if __name__ == "__main__":
    unittest.main()
