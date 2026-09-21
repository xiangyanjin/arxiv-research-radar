"""Explainable abstract-level relevance. Scores are not research-quality scores."""
from __future__ import annotations

import re
import unicodedata


def _text(value: str) -> str:
    value = unicodedata.normalize("NFKD", value).casefold()
    value = "".join(c for c in value if not unicodedata.combining(c))
    # Common TeX rendering of Poincare and comparable accented words.
    value = re.sub(r"\\['`^\"~]\{?([a-z])\}?", r"\1", value)
    return " ".join(re.sub(r"[_\W]+", " ", value).split())


def _match(term: str, text: str) -> bool:
    normalized = _text(term)
    return bool(normalized and re.search(r"(?<!\w)" + re.escape(normalized) + r"(?!\w)", text))


def _unique_terms(terms):
    """Keep the first spelling for explanations, count each normalized term once."""
    seen, result = set(), []
    for term in terms:
        normalized = _text(term)
        if normalized and normalized not in seen:
            seen.add(normalized)
            result.append(term)
    return result


def is_recommended(ranking: dict, profile: dict) -> bool:
    return (not ranking.get("is_own", False) and not ranking.get("excluded", False)
            and ranking["score"] >= profile.get("minimum_score", 20))


# A category alone never scores; ambiguous phrases require an anchor. This
# prevents photonic band gaps / generic ML from being promoted as probability.
ANCHORS = {
    "matrix": ["random matrix", "random matrices", "free probability", "Wigner matrix", "Wigner matrices", "sample covariance", "Fuss Catalan", "non Hermitian random"],
    "tensor": ["spiked tensor", "tensor PCA", "tensor principal component", "tensor estimation", "tensor decomposition", "alternating power", "high dimensional statistics", "high dimensional inference", "spiked model", "statistical computational", "statistical to computational"],
    "markov": ["Markov chain", "Markov chains", "Glauber dynamics", "heat bath", "occupation count", "occupation counts", "occupation measure", "conditional resampling", "conditionally resampled", "Poincare inequality", "Poincare inequalities"],
    "concentration": ["concentration inequality", "concentration inequalities", "concentration of measure", "KLS conjecture", "Kannan Lovasz Simonovits", "Talagrand", "log concave", "log concavity", "stochastic localization", "reverse heat", "high dimensional probability", "transport inequality", "transport inequalities", "log Sobolev"],
}
MATH_CATEGORIES = {"math.PR", "math.ST", "math.FA", "stat.TH"}


def rank_paper(paper: dict, profile: dict) -> dict:
    title = _text(paper.get("title", ""))
    abstract = _text(paper.get("abstract", ""))
    # A phrase must occur inside a source field, never across their boundary.
    def in_fields(term):
        return _match(term, title) or _match(term, abstract)

    def hits_in_fields(terms):
        return [term for term in _unique_terms(terms) if in_fields(term)]

    categories = set(paper.get("categories", []))
    own_ids = {re.sub(r"v\d+$", "", str(i).split("/abs/")[-1]) for i in profile.get("own_arxiv_ids", [])}
    paper_id = re.sub(r"v\d+$", "", str(paper.get("id", "")).split("/abs/")[-1])
    self_names = {_text(n) for n in profile.get("self_author_names", [])}
    is_own = paper_id in own_ids or any(_text(a) in self_names for a in paper.get("authors", []))
    global_exclusions = hits_in_fields(profile.get("exclude_keywords", []))
    topics, reasons, matched, decisions = [], [], [], []
    eligible_topics, excluded_topics = 0, 0
    for topic in profile.get("topics", []):
        topic_id = topic["id"]
        keywords = _unique_terms(topic.get("keywords", []))
        title_hits = [term for term in keywords if _match(term, title)]
        abstract_hits = [term for term in keywords if _match(term, abstract)]
        hits = [term for term in keywords if term in title_hits or term in abstract_hits]
        anchors = hits_in_fields(topic.get("anchors", ANCHORS.get(topic_id, keywords)))
        exclusions = hits_in_fields(topic.get("exclude_keywords", []))
        decision = {"id": topic_id, "label": topic["label"], "status": "no_keywords",
                    "title_terms": title_hits, "abstract_terms": abstract_hits, "anchor_terms": anchors,
                    "excluded_terms": exclusions, "score": 0}
        decisions.append(decision)
        if not hits:
            continue
        # Spectral-gap-only mathematics still has contextual relevance, while
        # semiconductor / photonic / quantum-device gaps do not satisfy this.
        contextual_gap = topic_id == "markov" and bool(categories & MATH_CATEGORIES) and any(in_fields(t) for t in ("spectral gap", "mixing time"))
        contextual_cube = topic_id == "concentration" and bool(categories & MATH_CATEGORIES) and in_fields("Boolean cube")
        legacy_context = "anchors" not in topic and (contextual_gap or contextual_cube)
        if not (anchors or legacy_context):
            decision["status"] = "missing_anchor"
            continue
        # Tensor decompositions used only as engineering compression are not a
        # statistical-inference match without a statistical category or context.
        if topic_id == "tensor" and not categories.intersection(topic.get("categories", [])):
            if not any(in_fields(t) for t in ("spiked", "statistical", "inference", "estimation", "PCA")):
                decision["status"] = "context_rejected"
                continue
        eligible_topics += 1
        if exclusions:
            excluded_topics += 1
            decision["status"] = "excluded"
            reasons.append(f"{topic['label']}：命中方向排除词「{'、'.join(exclusions)}」，不计入相关性。")
            continue
        bonus = 6 if categories.intersection(topic.get("categories", [])) else 0
        score = min(95, round((15 + (24 if title_hits else 12) + min(30, 6 * (len(hits) - 1)) + bonus) * float(topic.get("weight", 1))))
        decision.update(status="matched", score=score)
        topics.append({"id": topic_id, "label": topic["label"], "score": score})
        matched.extend(hits)
        where = "标题" if title_hits else "摘要"
        terms = title_hits if title_hits else hits
        reason = f"{topic['label']}：{where}命中「{'、'.join(terms[:3])}」"
        if bonus:
            reason += f"；分类 {', '.join(sorted(categories.intersection(topic.get('categories', []))))} 提供方向依据"
        reasons.append(reason)
    topics.sort(key=lambda t: (-t["score"], t["id"]))
    score = min(100, (topics[0]["score"] + min(10, (len(topics) - 1) * 5))) if topics else 0
    excluded = bool(global_exclusions) or bool(eligible_topics and excluded_topics == eligible_topics)
    if excluded:
        score = 0
        if global_exclusions:
            reasons.insert(0, f"命中全局排除词「{'、'.join(global_exclusions)}」，不进入推荐。")
        else:
            reasons.insert(0, "所有原本匹配的研究方向均被方向排除词过滤，不进入推荐。")
    if is_own:
        score = 0
        reasons.insert(0, "命中本人 arXiv 编号或完整作者名，保留记录并排除每日推荐。")
    label = "本人论文（不推荐）" if is_own else "已按配置排除" if excluded else "高度相关" if score >= 60 else "相关候选" if score >= int(profile.get("minimum_score", 20)) else "低相关"
    return {"score": score, "topics": topics, "reasons": reasons, "matched_terms": _unique_terms(matched),
            "is_own": is_own, "excluded": excluded, "excluded_terms": global_exclusions,
            "topic_decisions": decisions, "relevance_label": label, "evidence_level": "abstract"}
