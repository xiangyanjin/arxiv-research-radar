"""Explainable abstract-level relevance. Scores are not research-quality scores."""
from __future__ import annotations

import re
import unicodedata


def _text(value: str) -> str:
    value = unicodedata.normalize("NFKD", value).casefold()
    value = "".join(c for c in value if not unicodedata.combining(c))
    # Common TeX rendering of Poincare and comparable accented words.
    value = re.sub(r"\\['`^\"~]\{?([a-z])\}?", r"\1", value)
    return " ".join(re.sub(r"[^\w]+", " ", value).split())


def _match(term: str, text: str) -> bool:
    return bool(re.search(r"(?<!\w)" + re.escape(_text(term)) + r"(?!\w)", text))


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
    combined = title + " " + abstract
    categories = set(paper.get("categories", []))
    own_ids = {re.sub(r"v\d+$", "", str(i).split("/abs/")[-1]) for i in profile.get("own_arxiv_ids", [])}
    paper_id = re.sub(r"v\d+$", "", str(paper.get("id", "")).split("/abs/")[-1])
    self_names = {_text(n) for n in profile.get("self_author_names", [])}
    is_own = paper_id in own_ids or any(_text(a) in self_names for a in paper.get("authors", []))
    topics, reasons, matched = [], [], []
    for topic in profile.get("topics", []):
        topic_id = topic["id"]
        hits = [term for term in topic.get("keywords", []) if _match(term, combined)]
        if not hits:
            continue
        anchors = [term for term in topic.get("anchors", ANCHORS.get(topic_id, topic.get("keywords", []))) if _match(term, combined)]
        # Spectral-gap-only mathematics still has contextual relevance, while
        # semiconductor / photonic / quantum-device gaps do not satisfy this.
        contextual_gap = topic_id == "markov" and bool(categories & MATH_CATEGORIES) and any(_match(t, combined) for t in ("spectral gap", "mixing time"))
        contextual_cube = topic_id == "concentration" and bool(categories & MATH_CATEGORIES) and _match("Boolean cube", combined)
        if not (anchors or contextual_gap or contextual_cube):
            continue
        # Tensor decompositions used only as engineering compression are not a
        # statistical-inference match without a statistical category or context.
        if topic_id == "tensor" and not categories.intersection(topic.get("categories", [])):
            if not any(_match(t, combined) for t in ("spiked", "statistical", "inference", "estimation", "PCA")):
                continue
        title_hits = [t for t in hits if _match(t, title)]
        bonus = 6 if categories.intersection(topic.get("categories", [])) else 0
        score = min(95, round((15 + (24 if title_hits else 12) + min(30, 6 * (len(hits) - 1)) + bonus) * float(topic.get("weight", 1))))
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
    if is_own:
        score = 0
        reasons.insert(0, "命中本人 arXiv 编号或完整作者名，保留记录并排除每日推荐。")
    label = "本人论文（不推荐）" if is_own else "高度相关" if score >= 60 else "相关候选" if score >= int(profile.get("minimum_score", 20)) else "低相关"
    return {"score": score, "topics": topics, "reasons": reasons, "matched_terms": list(dict.fromkeys(matched)), "is_own": is_own, "relevance_label": label, "evidence_level": "abstract"}
