"""Inspect a proposed profile on a fixed metadata pool without changing state."""
from __future__ import annotations

import html
import re

from .config import validate_profile
from .evaluation import fingerprint
from .ranking import is_recommended, rank_paper


def validate_candidates(document):
    """Accept a review queue/export or a metadata list, never infer truth labels."""
    papers = document.get("papers") if isinstance(document, dict) else document
    if not isinstance(papers, list):
        raise ValueError("Candidates must be a paper list or an object with a papers array")
    result, seen = [], set()
    for index, paper in enumerate(papers):
        prefix = f"papers[{index}]"
        if not isinstance(paper, dict):
            raise ValueError(f"{prefix} must be an object")
        for field in ("id", "title"):
            if not isinstance(paper.get(field), str) or not paper[field].strip():
                raise ValueError(f"{prefix}.{field} must be a non-empty string")
        if paper["id"] in seen:
            raise ValueError(f"Duplicate paper id: {paper['id']}")
        seen.add(paper["id"])
        if not isinstance(paper.get("abstract"), str):
            raise ValueError(f"{prefix}.abstract must be a string; use an empty string when unavailable")
        for field in ("authors", "categories"):
            value = paper.get(field)
            if not isinstance(value, list) or any(not isinstance(x, str) or not x.strip() for x in value):
                raise ValueError(f"{prefix}.{field} must be a string array")
        # Exclude notes, prior reviews/scores, and arbitrary instruction fields.
        result.append({key: paper[key] for key in ("id", "title", "abstract", "authors", "categories")})
    return result


def preview_profile(document, profile, *, baseline=None, limit=10):
    papers = validate_candidates(document)
    profile = validate_profile(profile)
    baseline = validate_profile(baseline) if baseline is not None else None
    if type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError("limit must be an integer between 1 and 100")

    def rank(pool, config):
        rows = []
        for paper in pool:
            result = rank_paper(paper, config)
            rows.append({"id": paper["id"], "title": paper["title"],
                         "recommended": is_recommended(result, config), **result})
        return sorted(rows, key=lambda item: (-item["score"], item["id"]))

    rows = rank(papers, profile)
    selected = [row for row in rows if row["recommended"]]
    report = {
        "kind": "profile-preview", "profile_name": profile["name"],
        "profile_sha256": fingerprint(profile), "candidate_sha256": fingerprint(papers),
        "minimum_score": profile["minimum_score"], "limit": limit,
        "scope": "Same supplied metadata pool only; does not estimate retrieval coverage or recommendation accuracy.",
        "warnings": ["No research profile or library was modified. No network or model request was made.",
                     "A review queue is already filtered; export-candidates includes stored unrecommended papers but still cannot reveal papers never retrieved.",
                     "Excluded words are literal phrase rules, including negated mentions; they are not semantic judgments."],
        "summary": {"candidates": len(rows), "recommended": len(selected),
                    "excluded": sum(row["excluded"] for row in rows),
                    "own_papers": sum(row["is_own"] for row in rows),
                    "unrecommended": len(rows) - len(selected)},
        "top_ids": [row["id"] for row in selected[:limit]], "ranked": rows,
    }
    if baseline is not None:
        before = rank(papers, baseline)
        old = {row["id"]: row for row in before}
        old_selected = {row["id"] for row in before if row["recommended"]}
        new_selected = {row["id"] for row in selected}
        report["comparison"] = {
            "baseline_name": baseline["name"], "baseline_sha256": fingerprint(baseline),
            "recommended_before": len(old_selected), "recommended_after": len(new_selected),
            "added_ids": sorted(new_selected - old_selected),
            "removed_ids": sorted(old_selected - new_selected),
            "retained_ids": sorted(old_selected & new_selected),
            "changes": [{"id": row["id"], "title": row["title"],
                         "score_before": old[row["id"]]["score"], "score_after": row["score"],
                         "recommended_before": old[row["id"]]["recommended"],
                         "recommended_after": row["recommended"]}
                        for row in rows if (row["score"], row["recommended"]) !=
                        (old[row["id"]]["score"], old[row["id"]]["recommended"])],
        }
    return report


def render_preview(report):
    """Render an inspectable report, keeping supplied titles as literal text."""
    def literal(value):
        value = html.escape(" ".join(str(value).split()), quote=False)
        return re.sub(r"([\\`*_{}\[\]()#+.!|>~-])", r"\\\1", value)

    summary = report["summary"]
    lines = ["# Research profile preview / 研究方向预览", "",
             f"Profile / 配置：{literal(report['profile_name'])}", "",
             f"Candidates / 候选：{summary['candidates']} · Recommended / 推荐：{summary['recommended']} · Excluded / 排除：{summary['excluded']}", "",
             f"Proposed minimum score / 新配置推荐阈值：{report['minimum_score']}", "",
             "> 仅比较输入候选集，不代表检索覆盖或推荐准确率；没有修改配置或论文库。",
             "> Same input pool only, not coverage or accuracy. No changes applied.", ""]
    comparison = report.get("comparison")
    if comparison is not None:
        lines += [f"Baseline / 原配置：{literal(comparison['baseline_name'])}", "",
                  f"Recommended / 推荐数：{comparison['recommended_before']} → {comparison['recommended_after']}",
                  f"Added / 新增：{len(comparison['added_ids'])} · Removed / 移出：{len(comparison['removed_ids'])}", "",
                  "## Decision changes / 推荐变化", ""]
        by_id = {row["id"]: row for row in report["ranked"]}
        for label, key in (("Added / 新增", "added_ids"), ("Removed / 移出", "removed_ids")):
            for paper_id in comparison[key]:
                row = by_id[paper_id]
                explanation = "; ".join(row["reasons"]) or "No topic satisfies the configured keyword and context rules / 未满足配置的关键词与语境规则"
                if not row["recommended"] and not row["excluded"] and not row["is_own"] and row["score"] < report["minimum_score"]:
                    explanation = f"Score {row['score']} is below the proposed threshold {report['minimum_score']} / 得分低于新配置阈值. " + explanation
                lines.append(f"- {label} — {literal(row['title'])} ({literal(paper_id)}) — {literal(explanation)}")
        if not comparison["added_ids"] and not comparison["removed_ids"]:
            lines.append("推荐名单未变 / Recommendation membership is unchanged.")
        lines.append("")
    lines += ["## Recommended papers / 推荐候选", ""]
    top_ids = set(report["top_ids"])
    for row in report["ranked"]:
        if row["id"] not in top_ids:
            continue
        lines += [f"### {literal(row['title'])}", "",
                  f"ID: {literal(row['id'])} · Score / 匹配分：{row['score']}", ""]
        lines += [f"- {literal(reason)}" for reason in row["reasons"]]
        lines.append("")
    if not top_ids:
        lines += ["没有达到推荐条件的候选 / No candidates meet the recommendation rules.", ""]
    lines += ["## Excluded candidates / 排除候选", ""]
    excluded = [row for row in report["ranked"] if row["excluded"]]
    for row in excluded[:report["limit"]]:
        terms = list(row["excluded_terms"])
        for topic in row.get("topic_decisions", []):
            if topic["status"] == "excluded":
                terms.extend(topic["excluded_terms"])
        lines.append(f"- {literal(row['title'])} — {literal(', '.join(dict.fromkeys(terms)))}")
    if not excluded:
        lines.append("没有命中排除规则的候选 / No candidates were excluded by a rule.")
    lines += ["", "## Scope / 范围", ""]
    lines += [f"- {literal(warning)}" for warning in report["warnings"]]
    lines += ["", f"Profile SHA256: `{report['profile_sha256']}`",
              f"Candidate SHA256: `{report['candidate_sha256']}`", ""]
    return "\n".join(lines)
