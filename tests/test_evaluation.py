"""Check metric denominators, label integrity and reproducible CLI behavior."""
from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from radar.evaluation import evaluate, validate_dataset

ROOT = Path(__file__).resolve().parents[1]
PROFILE = {"categories": ["math.PR"], "minimum_score": 20,
           "topics": [{"id": "sample", "label": "Sample", "keywords": ["needle"]}]}


def dataset():
    cases = []
    for key, relevant, title in (("a", True, "needle"), ("b", False, "needle"),
                                 ("c", True, "paraphrase"), ("d", False, "background")):
        cases.append({"relevant": relevant, "paper": {"id": key, "title": title,
                      "abstract": "An example for testing.", "authors": [], "categories": ["math.PR"]}})
    return {"name": "Hand-calculated example", "kind": "synthetic",
            "description": "Fictional cases with known confusion counts.", "cases": cases}


class EvaluationTests(unittest.TestCase):
    def test_hand_calculated_metrics_and_deterministic_ties(self):
        report = evaluate(dataset(), PROFILE, k=1)
        m = report["metrics"]
        for key in ("true_positive", "false_positive", "true_negative", "false_negative"):
            self.assertEqual(m[key], 1)
        for key in ("precision", "recall", "f1", "recall_at_k"):
            self.assertEqual(m[key], 0.5)
        self.assertEqual(m["precision_at_k"], 1)
        self.assertEqual(m["returned_at_k"], 1)
        self.assertEqual(report["top_ids"], ["a"])
        self.assertEqual({row["id"] for row in report["errors"]}, {"b", "c"})
        self.assertEqual(evaluate(dataset(), PROFILE, k=1), report)

    def test_fewer_than_k_and_empty_denominators_are_explicit(self):
        self.assertEqual(evaluate(dataset(), PROFILE, k=5)["metrics"]["precision_at_k"], 0.5)
        profile = {**PROFILE, "minimum_score": 100}
        metrics = evaluate(dataset(), profile)["metrics"]
        self.assertIsNone(metrics["precision"])
        self.assertIsNone(metrics["precision_at_k"])
        self.assertEqual(metrics["returned_at_k"], 0)
        self.assertEqual(metrics["recall"], 0)
        empty_positive = dataset()
        for case in empty_positive["cases"]:
            case["relevant"] = False
        metrics = evaluate(empty_positive, profile)["metrics"]
        self.assertIsNone(metrics["recall"])
        self.assertIsNone(metrics["f1"])

    def test_own_paper_exclusion_is_part_of_decision(self):
        report = evaluate(dataset(), {**PROFILE, "own_arxiv_ids": ["a"]})
        row = next(r for r in report["ranked"] if r["id"] == "a")
        self.assertFalse(row["recommended"])
        self.assertTrue(row["is_own"])

    def test_invalid_labels_duplicates_and_metadata_fail_closed(self):
        bad = []
        value = dataset(); value["cases"][0]["relevant"] = "false"; bad.append(value)
        value = dataset(); value["cases"].append(deepcopy(value["cases"][0])); bad.append(value)
        value = dataset(); value["cases"][0]["paper"]["authors"] = "Author"; bad.append(value)
        value = dataset(); value["cases"] = []; bad.append(value)
        value = dataset(); value["kind"] = "verified"; bad.append(value)
        for value in bad:
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_dataset(value)
        for k in (0, -1, 1001, True, 1.5):
            with self.subTest(k=k), self.assertRaises(ValueError):
                evaluate(dataset(), PROFILE, k)

    def test_fingerprints_track_labels_and_profile_without_mutating_inputs(self):
        data = dataset(); profile = deepcopy(PROFILE)
        before = deepcopy((data, profile))
        original = evaluate(data, profile)
        self.assertEqual((data, profile), before)
        data["cases"][0]["relevant"] = False
        changed = evaluate(data, {**profile, "minimum_score": 30})
        self.assertNotEqual(original["dataset"]["sha256"], changed["dataset"]["sha256"])
        self.assertNotEqual(original["profile_sha256"], changed["profile_sha256"])

    def test_cli_is_offline_and_does_not_initialize_research_database(self):
        with tempfile.TemporaryDirectory() as temp:
            data_path = Path(temp) / "private-data"
            result_path = Path(temp) / "evaluation.json"
            env = {**os.environ, "ARXIV_RADAR_DATA_DIR": str(data_path)}
            result = subprocess.run([sys.executable, "-m", "radar", "evaluate",
                                     "examples/ranking-eval.json", "--profile", "config/profile.json",
                                     "--output", str(result_path)], cwd=ROOT, env=env,
                                    capture_output=True, text=True, timeout=15)
            self.assertEqual(result.returncode, 0, result.stderr)
            report = json.loads(result_path.read_text())
            self.assertEqual(report["dataset"]["kind"], "synthetic")
            self.assertIn("not real-world", report["warning"])
            self.assertFalse(data_path.exists())


if __name__ == "__main__":
    unittest.main()
