"""Offline fixtures test source semantics, coverage, and meaningful relevance."""
from copy import deepcopy
from datetime import datetime, timezone
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import urllib.error

from radar.arxiv import ArxivError, _Fetcher, fetch_recent, normalize_id, parse_atom, parse_rss_atom
from radar.ranking import rank_paper


PROFILE = json.loads((Path(__file__).resolve().parents[1] / "config/profile.json").read_text(encoding="utf-8"))


def entry(paper_id="2609.12345v2", published="2026-01-02T10:00:00Z", updated="2026-09-20T12:00:00Z", title="Strong convergence of random matrices", summary="Universality under a finite fourth moment."):
    return f"""<entry><id>http://arxiv.org/abs/{paper_id}</id>
      <published>{published}</published><updated>{updated}</updated><title>{title}</title>
      <summary>{summary}</summary><author><name>Ada Example</name></author>
      <category term="math.PR"/><link rel="alternate" href="http://arxiv.org/abs/{paper_id}"/>
      </entry>"""


def feed(*entries, total=None):
    count = len(entries) if total is None else total
    return f"""<feed xmlns="http://www.w3.org/2005/Atom" xmlns:opensearch="http://a9.com/-/spec/opensearch/1.1/">
        <opensearch:totalResults>{count}</opensearch:totalResults>{''.join(entries)}</feed>""".encode()


RSS_FIXTURE = b'''<feed xmlns="http://www.w3.org/2005/Atom" xmlns:dc="http://purl.org/dc/elements/1.1/">
  <id>http://rss.arxiv.org/atom/math.PR</id><updated>2026-09-21T05:00:00Z</updated>
  <entry><id>oai:arXiv.org:2401.01234v3</id><title>Markov chain mixing</title>
  <published>2026-09-20T00:00:00-04:00</published><updated>2026-09-21T05:00:00Z</updated>
  <summary>arXiv:2401.01234v3 Announce Type: replace-cross
  Abstract: We establish a spectral gap for a Markov chain.</summary>
  <dc:creator>Ada Example, Bo Example</dc:creator><category term="math.PR"/></entry></feed>'''


class AtomParsingTests(unittest.TestCase):
    def test_normalizes_version_modern_legacy_and_official_url(self):
        self.assertEqual(normalize_id("https://arxiv.org/abs/2609.12345v12"), ("2609.12345", 12))
        self.assertEqual(normalize_id("oai:arXiv.org:math/0601234v2"), ("math/0601234", 2))
        self.assertEqual(normalize_id("https://arxiv.org/pdf/2609.12345v2.pdf"), ("2609.12345", 2))
        self.assertEqual(normalize_id("2609.12345"), ("2609.12345", 0))
        with self.assertRaises(ArxivError):
            normalize_id("https://evil.example/abs/2609.12345v1")

    def test_atom_error_is_not_empty_success(self):
        error = '<entry><id>http://arxiv.org/api/errors#bad_query</id><title>Error</title><summary>Bad query syntax</summary></entry>'
        with self.assertRaisesRegex(ArxivError, "Bad query syntax"):
            parse_atom(feed(error))

    def test_invalid_feed_and_missing_count_rejected(self):
        for invalid in (b"<html>Maintenance</html>", b'<feed xmlns="http://www.w3.org/2005/Atom"/>', b"not xml"):
            with self.subTest(invalid=invalid), self.assertRaises(ArxivError):
                parse_atom(invalid)
        self.assertEqual(parse_atom(feed()), ([], 0))

    def test_old_paper_revision_retains_first_submission_date(self):
        papers, total = parse_atom(feed(entry("2401.12345v3", "2024-01-02T05:00:00-05:00")))
        self.assertEqual(total, 1)
        self.assertEqual(papers[0]["id"], "2401.12345")
        self.assertEqual(papers[0]["version"], 3)
        self.assertEqual(papers[0]["published"], "2024-01-02T10:00:00Z")
        self.assertEqual(papers[0]["updated"], "2026-09-20T12:00:00Z")
        self.assertEqual(papers[0]["url"], "https://arxiv.org/abs/2401.12345v3")

    def test_rss_announcement_is_not_falsely_first_submission(self):
        papers, coverage = parse_rss_atom(RSS_FIXTURE)
        paper = papers[0]
        self.assertEqual(paper["published"], "")
        self.assertEqual(paper["updated"], "")
        self.assertEqual(paper["announced"], "2026-09-20T04:00:00Z")
        self.assertEqual(paper["announce_type"], "replace-cross")
        self.assertEqual(paper["version"], 3)
        self.assertEqual(paper["authors"], ["Ada Example", "Bo Example"])
        self.assertEqual(paper["abstract"], "We establish a spectral gap for a Markov chain.")
        self.assertEqual(coverage["feed_items"], 1)


class FetchCoverageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.profile = deepcopy(PROFILE)
        self.profile["scan"].update(page_size=2, max_pages=3, retries=0)

    def run_fetch(self):
        return fetch_recent(self.profile, "2026-09-19T00:00:00Z", "2026-09-21T00:00:00Z", Path(self.temp.name))

    def test_window_includes_old_revision_and_both_date_edges(self):
        first = feed(entry("2609.12345v1", updated="2026-09-21T00:00:00Z"), entry("2401.12345v3", "2024-01-01T00:00:00Z", "2026-09-20T12:00:00Z"), total=100)
        second = feed(entry("2609.12346v1", updated="2026-09-19T00:00:00Z"), entry("2609.12347v1", updated="2026-09-18T23:59:59Z"), total=100)
        with patch("radar.arxiv._Fetcher.get", side_effect=[first, second]) as get:
            result = self.run_fetch()
        self.assertEqual(result["status"], "success")
        self.assertTrue(result["coverage"]["complete_window"])
        self.assertEqual({p["id"] for p in result["papers"]}, {"2609.12345", "2401.12345", "2609.12346"})
        urls = [c.args[0] for c in get.call_args_list]
        self.assertTrue(all("sortBy=lastUpdatedDate" in u and "submittedDate" not in u for u in urls))
        self.assertIn("start=2", urls[1])

    def test_page_cap_is_partial(self):
        self.profile["scan"]["max_pages"] = 1
        with patch("radar.arxiv._Fetcher.get", return_value=feed(entry(), total=99)):
            result = self.run_fetch()
        self.assertEqual(result["status"], "partial")
        self.assertTrue(result["coverage"]["truncated"])
        self.assertFalse(result["coverage"]["complete_window"])

    def test_empty_nonfinal_page_is_partial_not_success(self):
        with patch("radar.arxiv._Fetcher.get", side_effect=[feed(total=100), RSS_FIXTURE]):
            result = self.run_fetch()
        self.assertEqual(result["status"], "partial")
        self.assertFalse(result["coverage"]["complete_window"])
        self.assertTrue(any("空分页" in error for error in result["errors"]))

    def test_network_errors_not_zero_result_success(self):
        with patch("radar.arxiv._Fetcher.get", side_effect=ArxivError("timeout")):
            result = self.run_fetch()
        self.assertEqual(result["status"], "failed")
        self.assertTrue(result["errors"])
        self.assertFalse(result["coverage"]["complete_window"])

    def test_rss_fallback_never_claims_api_window_complete(self):
        with patch("radar.arxiv._Fetcher.get", side_effect=[ArxivError("timeout"), RSS_FIXTURE]):
            result = self.run_fetch()
        self.assertEqual(result["status"], "partial")
        self.assertFalse(result["coverage"]["complete_window"])
        self.assertEqual(result["coverage"]["sources"], ["arxiv-rss"])
        self.assertEqual(result["papers"][0]["source"], "arxiv-rss")

    def test_rss_newer_revision_supersedes_stale_api_entry(self):
        first = feed(entry("2401.01234v2", published="2024-01-01T00:00:00Z"), total=100)
        with patch("radar.arxiv._Fetcher.get", side_effect=[first, ArxivError("timeout"), RSS_FIXTURE]):
            result = self.run_fetch()
        self.assertEqual(result["status"], "partial")
        self.assertEqual(len(result["papers"]), 1)
        self.assertEqual(result["papers"][0]["version"], 3)
        self.assertEqual(result["papers"][0]["date_basis"], "announcement")

    def test_valid_empty_api_feed_is_success(self):
        with patch("radar.arxiv._Fetcher.get", return_value=feed()):
            result = self.run_fetch()
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["papers"], [])

    def test_non_mathematics_categories_are_supported(self):
        self.profile["categories"] = ["physics.optics", "cond-mat.stat-mech"]
        with patch("radar.arxiv._Fetcher.get", return_value=feed()) as get:
            result = self.run_fetch()
        self.assertEqual(result["status"], "success")
        self.assertIn("physics.optics", get.call_args.args[0])

    def test_rate_limit_and_http_error_response_are_archived(self):
        exc = urllib.error.HTTPError("https://export.arxiv.org/api/query", 503, "Unavailable", {}, io.BytesIO(b"maintenance"))
        fetcher = _Fetcher(Path(self.temp.name), 1)
        with patch("radar.arxiv._LAST_REQUEST", 100.0), patch("radar.arxiv.time.monotonic", return_value=101.0), patch("radar.arxiv.time.sleep") as sleep, patch("radar.arxiv.urllib.request.urlopen", side_effect=exc):
            with self.assertRaisesRegex(ArxivError, "503"):
                fetcher.get("https://export.arxiv.org/api/query", "fixture")
        self.assertAlmostEqual(sleep.call_args.args[0], 2.05)
        self.assertEqual((Path(self.temp.name) / "001-fixture.xml").read_bytes(), b"maintenance")
        meta = json.loads((Path(self.temp.name) / "001-fixture.json").read_text())
        self.assertEqual(meta["status"], 503)
        self.assertIn("ArxivResearchRadar", meta["user_agent"])


class RankingTests(unittest.TestCase):
    def rank(self, title, abstract="", categories=None, paper_id="2609.12345", authors=None):
        return rank_paper({"id": paper_id, "title": title, "abstract": abstract, "categories": categories or ["math.PR"], "authors": authors or ["Ada Example"]}, PROFILE)

    def test_random_matrix_positive_has_explanation(self):
        result = self.rank("Strong convergence for random matrices", "We establish universality under a finite fourth moment.")
        self.assertGreaterEqual(result["score"], 60)
        self.assertEqual(result["topics"][0]["id"], "matrix")
        self.assertIn("random matrices", result["matched_terms"])
        self.assertTrue(result["reasons"])
        self.assertEqual(result["evidence_level"], "abstract")

    def test_markov_vs_photonic_spectral_gap(self):
        positive = self.rank("Spectral gaps of Markov chains", "Poincaré inequalities for Glauber dynamics.")
        negative = self.rank("Tunable spectral gap in photonic devices", "Spectral gap optimization in a semiconductor laser.", ["physics.optics"])
        self.assertGreaterEqual(positive["score"], 20)
        self.assertEqual(negative["score"], 0)

    def test_bare_ml_and_generic_universality_are_not_matches(self):
        self.assertEqual(self.rank("Machine learning for image classification", "We improve inference speed and benchmark accuracy.", ["cs.LG"])["score"], 0)
        self.assertEqual(self.rank("Universality in stellar physics", "Strong convergence of our solver.", ["astro-ph.CO"])["score"], 0)

    def test_spiked_tensor_and_concentration_positive(self):
        for title, expected in [("Warm starts for spiked tensor PCA", "tensor"), ("Concentration of measure for log-concave distributions", "concentration")]:
            with self.subTest(title=title):
                result = self.rank(title)
                self.assertGreaterEqual(result["score"], 20)
                self.assertIn(expected, [t["id"] for t in result["topics"]])

    def test_own_ids_and_exact_author_are_excluded(self):
        profile = deepcopy(PROFILE)
        profile["own_arxiv_ids"] = ["2609.11111", "math/0601234"]
        profile["self_author_names"] = ["Ada Example"]
        for own_id in profile["own_arxiv_ids"]:
            result = rank_paper({"id": own_id + "v2", "title": "Strong convergence of random matrices", "authors": ["Bo Example"]}, profile)
            self.assertTrue(result["is_own"])
            self.assertEqual(result["score"], 0)
        self.assertTrue(rank_paper({"authors": ["Ada Example"]}, profile)["is_own"])
        self.assertFalse(rank_paper({"authors": ["Ada Examples"]}, profile)["is_own"])

    def test_custom_topic_and_anchor_override_are_not_bound_to_math(self):
        profile = {"topics": [{"id": "agents", "label": "Agent evaluation", "keywords": ["agent", "benchmark"],
                                "anchors": ["language model"], "categories": ["cs.AI"], "weight": 1.0}]}
        self.assertGreater(rank_paper({"title": "A benchmark for language model agents", "abstract": "An agent benchmark.", "categories": ["cs.AI"]}, profile)["score"], 20)
        self.assertEqual(rank_paper({"title": "A benchmark for chemical agents", "categories": ["chem-ph"]}, profile)["score"], 0)


if __name__ == "__main__":
    unittest.main()
