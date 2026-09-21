"""Lexical relevance boundaries, transparent decisions, and exclusion semantics."""
import json
from pathlib import Path
import tempfile
import unittest

from radar.config import ConfigError, validate_profile
from radar.evaluation import evaluate
from radar.profiles import load_preset
from radar.ranking import is_recommended, rank_paper
from radar.service import Radar, ROOT


def topic(identifier="custom", keywords=None, **extra):
    return {"id": identifier, "label": identifier, "keywords": keywords or ["protein folding"],
            "categories": ["q-bio.BM"], "weight": 1.0, **extra}


def profile(topics=None, **extra):
    return {"name": "Precision fixture", "categories": ["q-bio.BM"],
            "topics": topics or [topic()], "minimum_score": 20, **extra}


def paper(title="Protein folding", abstract="A study of protein folding.", categories=None):
    return {"id": "2609.54321", "version": 1, "title": title, "abstract": abstract,
            "authors": ["Example Author"], "categories": categories or ["q-bio.BM"],
            "published": "2026-09-01T00:00:00Z", "updated": "2026-09-01T00:00:00Z",
            "url": "https://arxiv.org/abs/2609.54321v1", "pdf_url": "https://arxiv.org/pdf/2609.54321v1",
            "source": "synthetic-fixture"}


class NormalizationTests(unittest.TestCase):
    def test_equivalent_keyword_spellings_count_once_without_rewriting_profile(self):
        single = profile([topic(keywords=["high-dimensional inference"])])
        duplicate = profile([topic(keywords=["high-dimensional inference", "HIGH DIMENSIONAL INFERENCE",
                                            "high_dimensional_inference", "high—dimensional inference"])])
        candidate = paper("High dimensional inference", "We analyze high-dimensional inference.")
        base = rank_paper(candidate, single)
        result = rank_paper(candidate, duplicate)
        self.assertEqual(result["score"], base["score"])
        self.assertEqual(result["matched_terms"], ["high-dimensional inference"])
        decision = result["topic_decisions"][0]
        self.assertEqual(decision["title_terms"], ["high-dimensional inference"])
        self.assertEqual(decision["abstract_terms"], ["high-dimensional inference"])
        validated = validate_profile(duplicate)
        self.assertEqual(validated["topics"][0]["keywords"], duplicate["topics"][0]["keywords"])

    def test_a_phrase_cannot_be_assembled_across_title_and_abstract(self):
        config = profile([topic(keywords=["protein folding"])])
        result = rank_paper(paper("A study of protein", "Folding mechanisms are examined."), config)
        self.assertEqual(result["score"], 0)
        self.assertEqual(result["topic_decisions"][0]["status"], "no_keywords")
        anchored = profile([topic(keywords=["spectral gap"], anchors=["Markov chain"])])
        result = rank_paper(paper("Spectral gap of Markov", "Chain approximations."), anchored)
        self.assertEqual(result["topic_decisions"][0]["status"], "missing_anchor")

    def test_exclusion_phrases_also_respect_field_boundaries_and_deduplicate(self):
        config = profile(exclude_keywords=["review-article", "REVIEW ARTICLE"])
        boundary = rank_paper(paper("Protein folding review", "Article with new experiments."), config)
        self.assertFalse(boundary["excluded"])
        actual = rank_paper(paper("Protein folding review article"), config)
        self.assertTrue(actual["excluded"])
        self.assertEqual(actual["excluded_terms"], ["review-article"])

    def test_normalization_empty_terms_are_rejected_in_every_config_location(self):
        for term in ("...", "---", "___", "🧪", "\u0301"):
            for location in ("keywords", "anchors", "topic_exclude", "global_exclude"):
                config = profile()
                if location == "global_exclude":
                    config["exclude_keywords"] = [term]
                else:
                    config["topics"][0]["exclude_keywords" if location == "topic_exclude" else location] = [term]
                with self.subTest(term=term, location=location), self.assertRaises(ConfigError):
                    validate_profile(config)
        valid = profile([topic(keywords=["蛋白质折叠"], anchors=["蛋白质"], exclude_keywords=[])], exclude_keywords=[])
        self.assertEqual(validate_profile(valid)["topics"][0]["keywords"], ["蛋白质折叠"])

    def test_exclusion_arrays_enforce_types_but_accept_empty_lists(self):
        for invalid in ("survey", [1], None, [" "]):
            for at_root in (True, False):
                config = profile()
                target = config if at_root else config["topics"][0]
                target["exclude_keywords"] = invalid
                with self.subTest(invalid=invalid, root=at_root), self.assertRaises(ConfigError):
                    validate_profile(config)
        validate_profile(profile([topic(exclude_keywords=[])], exclude_keywords=[]))


class DecisionTests(unittest.TestCase):
    def test_topic_exclusion_removes_only_its_contribution(self):
        first = topic("folding", exclude_keywords=["survey"])
        second = topic("design", keywords=["protein design"])
        candidate = paper("Protein folding survey and protein design")
        result = rank_paper(candidate, profile([first, second]))
        remaining = rank_paper(candidate, profile([second]))
        self.assertFalse(result["excluded"])
        self.assertEqual(result["score"], remaining["score"])
        self.assertEqual([t["id"] for t in result["topics"]], ["design"])
        self.assertEqual(result["excluded_terms"], [])
        self.assertEqual(result["topic_decisions"][0]["status"], "excluded")
        self.assertEqual(result["topic_decisions"][0]["excluded_terms"], ["survey"])
        self.assertEqual(result["topic_decisions"][0]["score"], 0)

    def test_only_excluding_otherwise_eligible_topics_excludes_the_whole_paper(self):
        config = profile([topic("folding", exclude_keywords=["survey"]),
                          topic("unrelated", keywords=["dark energy"], exclude_keywords=["survey"])])
        result = rank_paper(paper("Protein folding survey"), config)
        self.assertTrue(result["excluded"])
        self.assertEqual(result["score"], 0)
        self.assertEqual([d["status"] for d in result["topic_decisions"]], ["excluded", "no_keywords"])
        for inactive in (topic(keywords=["dark energy"], exclude_keywords=["survey"]),
                         topic(anchors=["missing anchor"], exclude_keywords=["survey"]),
                         topic("tensor", keywords=["tensor decomposition"], categories=["stat.ML"], exclude_keywords=["survey"])):
            result = rank_paper(paper("Protein folding and tensor decomposition survey", categories=["physics.optics"]), profile([inactive]))
            self.assertFalse(result["excluded"])
            self.assertNotEqual(result["topic_decisions"][0]["status"], "excluded")

    def test_all_decision_statuses_have_source_terms_and_integer_contributions(self):
        config = profile([topic("matched", keywords=["random matrix"]),
                          topic("absent", keywords=["dark energy"]),
                          topic("unanchored", keywords=["random matrix"], anchors=["free probability"]),
                          topic("filtered", keywords=["random matrix"], exclude_keywords=["photonic"]),
                          topic("tensor", keywords=["tensor decomposition"], categories=["stat.ML"])])
        candidate = paper("Random matrix and tensor decomposition for photonic devices", "A random matrix construction.", ["physics.optics"])
        decisions = rank_paper(candidate, config)["topic_decisions"]
        self.assertEqual([d["status"] for d in decisions], ["matched", "no_keywords", "missing_anchor", "excluded", "context_rejected"])
        for decision in decisions:
            self.assertEqual(set(decision), {"id", "label", "status", "title_terms", "abstract_terms", "anchor_terms", "excluded_terms", "score"})
            self.assertIs(type(decision["score"]), int)
        self.assertEqual(decisions[0]["title_terms"], ["random matrix"])
        self.assertEqual(decisions[0]["abstract_terms"], ["random matrix"])

    def test_global_exclusions_override_other_positive_topics_even_at_zero_threshold(self):
        config = profile(exclude_keywords=["survey"], minimum_score=0)
        result = rank_paper(paper("Protein folding survey"), config)
        self.assertTrue(result["excluded"])
        self.assertEqual(result["excluded_terms"], ["survey"])
        self.assertEqual(result["topic_decisions"][0]["status"], "matched")
        self.assertFalse(is_recommended(result, config))
        result = rank_paper(paper("Unrelated survey", "No positive keyword."), config)
        self.assertTrue(result["excluded"])
        self.assertFalse(is_recommended(result, config))

    def test_explicit_anchors_cannot_be_bypassed_by_legacy_mathematical_context(self):
        for identifier, keyword, anchor in (("markov", "spectral gap", "Markov chain"),
                                             ("concentration", "Boolean cube", "stochastic localization")):
            with self.subTest(identifier=identifier):
                config = profile([topic(identifier, keywords=[keyword], anchors=[anchor], categories=["math.PR"])])
                candidate = paper(keyword, "A mathematical study.", ["math.PR"])
                result = rank_paper(candidate, config)
                self.assertEqual(result["topic_decisions"][0]["status"], "missing_anchor")
                self.assertEqual(result["score"], 0)
                del config["topics"][0]["anchors"]
                self.assertGreater(rank_paper(candidate, config)["score"], 0)

    def test_default_and_mathematics_preset_have_equivalent_relevance_behavior(self):
        default = json.loads((ROOT / "config/profile.json").read_text(encoding="utf-8"))
        preset = load_preset("math-statistics")
        candidates = [paper("Spectral gap", "A mathematical study.", ["math.PR"]),
                      paper("Boolean cube", "A mathematical study.", ["math.PR"]),
                      paper("Strong convergence of random matrices", "Universality under fourth moment conditions.", ["math.PR"]),
                      paper("Warm starts for spiked tensor PCA", "Finite iteration dynamics.", ["math.ST"]),
                      paper("Tensor decomposition for engineering compression", "Device compression.", ["physics.optics"]),
                      paper("Spectral gap of photonic devices", "Semiconductor design.", ["physics.optics"])]
        for candidate in candidates:
            with self.subTest(title=candidate["title"]):
                a, b = rank_paper(candidate, default), rank_paper(candidate, preset)
                self.assertEqual(a["score"], b["score"])
                self.assertEqual(a["matched_terms"], b["matched_terms"])
                self.assertEqual([(d["id"], d["status"]) for d in a["topic_decisions"]], [(d["id"], d["status"]) for d in b["topic_decisions"]])
        for candidate in candidates[:2]:
            self.assertGreater(rank_paper(candidate, preset)["score"], 0)

    def test_own_exclusion_and_unmatched_zero_threshold_keep_their_existing_semantics(self):
        config = profile(minimum_score=0, own_arxiv_ids=["2609.54321"])
        result = rank_paper(paper(), config)
        self.assertTrue(result["is_own"])
        self.assertFalse(is_recommended(result, config))
        config["own_arxiv_ids"] = []
        result = rank_paper(paper("Unrelated topic", "No matching phrases."), config)
        self.assertFalse(result["excluded"])
        self.assertTrue(is_recommended(result, config), "A zero threshold retains its previous permissive behavior")

    def test_lexical_matching_does_not_claim_negation_or_synonym_understanding(self):
        config = profile()
        negated = rank_paper(paper("We do not study protein folding", "No study is reported."), config)
        synonym = rank_paper(paper("Macromolecular conformational search", "A study of molecular structure."), config)
        self.assertTrue(is_recommended(negated, config), "This remains a known limitation of literal term matching")
        self.assertFalse(is_recommended(synonym, config), "Unconfigured synonyms are not inferred")


class ExclusionIntegrationTests(unittest.TestCase):
    def test_live_recommendations_and_evaluation_agree_and_managed_items_remain_accessible(self):
        for excluded_by in ("global", "topic"):
            with self.subTest(excluded_by=excluded_by), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                config = profile(minimum_score=0)
                target = config if excluded_by == "global" else config["topics"][0]
                target["exclude_keywords"] = ["survey"]
                path = root / "profile.json"
                path.write_text(json.dumps(config), encoding="utf-8")
                radar = Radar(root, profile=path, data_dir=root / "collection")
                candidate = paper("Protein folding survey")
                radar.store.upsert(candidate, "fixture", "2026-09-21T00:00:00Z")
                self.assertEqual(radar.papers(), [])
                self.assertEqual(radar.review_queue()["papers"], [])
                radar.store.update_library({"id": candidate["id"], "saved": True, "read": True, "notes": "Retain despite exclusion"})
                for view in ("saved", "read", "notes"):
                    selected = radar.papers(filter=view)
                    self.assertEqual([p["id"] for p in selected], [candidate["id"]])
                    self.assertTrue(selected[0]["excluded"])
                dataset = {"kind": "synthetic", "name": "Exclusion boundary", "description": "One explicit exclusion fixture.",
                           "cases": [{"paper": candidate, "relevant": False}]}
                report = evaluate(dataset, config)
                self.assertEqual(report["metrics"]["recommended"], 0)
                self.assertEqual(report["metrics"]["true_negative"], 1)
                self.assertEqual(radar.state()["stats"]["relevant"], 0)


if __name__ == "__main__":
    unittest.main()
