"""Offline relevance evaluation against explicit, user-supplied labels."""
from __future__ import annotations

import hashlib
import json

from .config import validate_profile
from .ranking import rank_paper


def fingerprint(value):
    encoded = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def validate_dataset(dataset):
    if not isinstance(dataset, dict) or dataset.get("kind") not in ("synthetic", "human-labeled"):
        raise ValueError("Dataset kind must be synthetic or human-labeled")
    if not isinstance(dataset.get("name"), str) or not dataset["name"].strip():
        raise ValueError("Dataset needs a non-empty name")
    if not isinstance(dataset.get("description"), str) or not dataset["description"].strip():
        raise ValueError("Dataset needs a description of its provenance and labeling")
    cases = dataset.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ValueError("Dataset cases must be a non-empty list")
    seen = set()
    for index, case in enumerate(cases):
        prefix = f"cases[{index}]"
        if not isinstance(case, dict) or type(case.get("relevant")) is not bool:
            raise ValueError(f"{prefix}.relevant must be a JSON boolean")
        paper = case.get("paper")
        if not isinstance(paper, dict):
            raise ValueError(f"{prefix}.paper must be an object")
        for field in ("id", "title", "abstract"):
            if not isinstance(paper.get(field), str) or not paper[field].strip():
                raise ValueError(f"{prefix}.paper.{field} must be a non-empty string")
        if paper["id"] in seen:
            raise ValueError(f"Duplicate paper id: {paper['id']}")
        seen.add(paper["id"])
        for field in ("authors", "categories"):
            value = paper.get(field)
            if not isinstance(value, list) or not all(isinstance(item, str) and item.strip() for item in value):
                raise ValueError(f"{prefix}.paper.{field} must be a string array")
    return dataset


def evaluate(dataset, profile, k=5):
    """Evaluate recommendation decisions; never infer labels from model output."""
    validate_dataset(dataset)
    profile = validate_profile(profile)
    if type(k) is not int or not 1 <= k <= 1000:
        raise ValueError("k must be an integer between 1 and 1000")
    rows = []
    for case in dataset["cases"]:
        paper = case["paper"]
        ranking = rank_paper(paper, profile)
        predicted = not ranking["is_own"] and ranking["score"] >= profile["minimum_score"]
        rows.append({"id": paper["id"], "title": paper["title"],
                     "relevant": case["relevant"], "recommended": predicted,
                     "score": ranking["score"], "matched_terms": ranking["matched_terms"],
                     "topics": [topic["id"] for topic in ranking["topics"]],
                     "is_own": ranking["is_own"]})
    rows.sort(key=lambda row: (-row["score"], row["id"]))
    tp = sum(row["relevant"] and row["recommended"] for row in rows)
    fp = sum(not row["relevant"] and row["recommended"] for row in rows)
    fn = sum(row["relevant"] and not row["recommended"] for row in rows)
    tn = len(rows) - tp - fp - fn

    def ratio(a, b):
        return a / b if b else None

    top = [row for row in rows if row["recommended"]][:k]
    top_relevant = sum(row["relevant"] for row in top)
    return {
        "dataset": {"name": dataset["name"], "kind": dataset["kind"],
                    "description": dataset["description"], "sha256": fingerprint(dataset)},
        "profile_sha256": fingerprint(profile), "minimum_score": profile["minimum_score"],
        "scope": "Metadata relevance only; does not measure retrieval coverage, paper quality, or review correctness.",
        "warning": ("Synthetic regression fixtures, not real-world recommendation accuracy."
                    if dataset["kind"] == "synthetic" else
                    "Valid only for these supplied labels; document sampling and annotation before generalizing."),
        "metrics": {"cases": len(rows), "positives": tp + fn, "recommended": tp + fp,
                    "true_positive": tp, "false_positive": fp, "true_negative": tn, "false_negative": fn,
                    "precision": ratio(tp, tp + fp), "recall": ratio(tp, tp + fn),
                    "f1": ratio(2 * tp, 2 * tp + fp + fn),
                    "k": k, "returned_at_k": len(top),
                    "precision_at_k": ratio(top_relevant, len(top)),
                    "recall_at_k": ratio(top_relevant, tp + fn)},
        "metric_notes": "Precision@k uses the actual number returned above threshold, at most k; empty denominators are null. Ties use ascending paper ID.",
        "top_ids": [row["id"] for row in top],
        "errors": [row for row in rows if row["relevant"] != row["recommended"]],
        "ranked": rows,
    }
