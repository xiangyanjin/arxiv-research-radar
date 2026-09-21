"""Official arXiv metadata fetcher with explicit coverage and archived responses.

API dates describe submission versions; RSS dates describe announcements. They
are deliberately never substituted for each other. No third-party APIs or keys.
"""
from __future__ import annotations

from datetime import datetime, timezone
from html import unescape
import json
from pathlib import Path
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

ATOM = "http://www.w3.org/2005/Atom"
OPEN = "http://a9.com/-/spec/opensearch/1.1/"
DC = "http://purl.org/dc/elements/1.1/"
NS = {"a": ATOM, "o": OPEN, "dc": DC}
API_URL = "https://export.arxiv.org/api/query"
RSS_URL = "https://rss.arxiv.org/atom/"
USER_AGENT = "ArxivResearchRadar/0.1 (https://github.com/xiangyanjin/arxiv-research-radar)"
MAX_RESPONSE_BYTES = 12 * 1024 * 1024
_REQUEST_LOCK = threading.Lock()
_LAST_REQUEST = 0.0


class ArxivError(ValueError):
    """A transport/feed error, never a zero-result search."""


def _utc(value: str) -> datetime:
    try:
        result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (ValueError, TypeError) as exc:
        raise ArxivError(f"Invalid timestamp: {value!r}") from exc
    if result.tzinfo is None:
        raise ArxivError(f"Timestamp must have timezone: {value!r}")
    return result.astimezone(timezone.utc)


def _iso(value: str) -> str:
    return _utc(value).isoformat(timespec="seconds").replace("+00:00", "Z")


def normalize_id(value: str) -> tuple[str, int]:
    """Accept official URLs, OAI IDs, or bare IDs; version 0 means unknown."""
    value = str(value).strip()
    if "://" in value:
        url = urllib.parse.urlsplit(value)
        if url.scheme not in {"http", "https"} or url.hostname not in {"arxiv.org", "export.arxiv.org", "www.arxiv.org"}:
            raise ArxivError("Paper ID is not an official arXiv URL")
        match = re.fullmatch(r"/(?:abs|pdf)/(.+?)(?:\.pdf)?", url.path)
        if not match:
            raise ArxivError(f"Invalid arXiv paper URL: {value}")
        value = match.group(1)
    value = re.sub(r"^(?:oai:arXiv\.org:|arXiv:)", "", value, flags=re.I)
    match = re.fullmatch(r"((?:\d{4}\.\d{4,5})|(?:[a-z][a-z.\-]+/\d{7}))(?:v([1-9]\d*))?", value, re.I)
    if not match:
        raise ArxivError(f"Invalid arXiv identifier: {value!r}")
    return match.group(1), int(match.group(2) or 0)


def _clean(value: str | None) -> str:
    return " ".join((value or "").split())


def _xml(data: bytes) -> ET.Element:
    if b"<!DOCTYPE" in data.upper() or b"<!ENTITY" in data.upper():
        raise ArxivError("Unexpected DTD/entity declaration in feed")
    try:
        root = ET.fromstring(data)
    except ET.ParseError as exc:
        raise ArxivError(f"Invalid XML feed: {exc}") from exc
    if root.tag != f"{{{ATOM}}}feed":
        raise ArxivError("Expected an Atom feed, received another document")
    return root


def _identity(entry: ET.Element) -> tuple[str, int]:
    raw_id = _clean(entry.findtext("a:id", namespaces=NS))
    title = _clean(entry.findtext("a:title", namespaces=NS))
    if "/api/errors" in raw_id or title.casefold() == "error":
        raise ArxivError("arXiv API error: " + _clean(entry.findtext("a:summary", namespaces=NS)))
    paper_id, version = normalize_id(raw_id)
    if not version:
        for link in entry.findall("a:link", NS):
            try:
                link_id, link_version = normalize_id(link.get("href", ""))
            except ArxivError:
                continue
            if link_id == paper_id and link_version:
                version = link_version
                break
    return paper_id, version


def _base_paper(entry: ET.Element, source: str) -> dict:
    paper_id, version = _identity(entry)
    title = _clean(entry.findtext("a:title", namespaces=NS))
    if not title:
        raise ArxivError(f"Missing paper title: {paper_id}")
    authors = [_clean(e.findtext("a:name", namespaces=NS)) for e in entry.findall("a:author", NS)]
    authors = [a for a in authors if a]
    if not authors:
        creators = _clean(entry.findtext("dc:creator", namespaces=NS))
        authors = [a.strip() for a in creators.split(",") if a.strip()]
    categories = [c.get("term", "") for c in entry.findall("a:category", NS)]
    categories = list(dict.fromkeys(c for c in categories if re.fullmatch(r"[a-z][a-z\-]*(?:\.[A-Z]{2})?", c)))
    versioned = paper_id + (f"v{version}" if version else "")
    return {"id": paper_id, "version": version, "version_known": bool(version), "title": title,
            "authors": authors, "abstract": _clean(entry.findtext("a:summary", namespaces=NS)),
            "categories": categories, "url": "https://arxiv.org/abs/" + versioned,
            "pdf_url": "https://arxiv.org/pdf/" + versioned, "source": source}


def parse_atom(data: bytes) -> tuple[list[dict], int]:
    """Parse API Atom, reject error entries and invalid/missing count metadata."""
    root = _xml(data)
    # Inspect entries before count parsing so error feeds retain helpful errors.
    entries = root.findall("a:entry", NS)
    papers = []
    for entry in entries:
        paper = _base_paper(entry, "arxiv-api")
        published = _iso(_clean(entry.findtext("a:published", namespaces=NS)))
        updated = _iso(_clean(entry.findtext("a:updated", namespaces=NS)))
        if _utc(updated) < _utc(published):
            raise ArxivError(f"Revision date precedes first submission: {paper['id']}")
        if not paper["authors"] or not paper["abstract"] or not paper["categories"]:
            raise ArxivError(f"Missing required paper metadata: {paper['id']}")
        paper.update(published=published, updated=updated, date_basis="submission", source_date={"published": published, "updated": updated})
        papers.append(paper)
    try:
        total = int(root.findtext("o:totalResults", namespaces=NS))
    except (ValueError, TypeError) as exc:
        raise ArxivError("Missing or invalid API totalResults") from exc
    if total < len(papers) or total < 0:
        raise ArxivError("Inconsistent API totalResults")
    return papers, total


def parse_rss_atom(data: bytes) -> tuple[list[dict], dict]:
    """Parse official RSS service's Atom form with honest announcement dates."""
    root = _xml(data)
    feed_id = _clean(root.findtext("a:id", namespaces=NS))
    if not feed_id.startswith(("https://rss.arxiv.org/", "http://rss.arxiv.org/")):
        raise ArxivError("Not an official arXiv RSS Atom feed")
    feed_updated = _iso(_clean(root.findtext("a:updated", namespaces=NS)))
    papers = []
    for entry in root.findall("a:entry", NS):
        paper = _base_paper(entry, "arxiv-rss")
        announced = _iso(_clean(entry.findtext("a:published", namespaces=NS)))
        generated = _iso(_clean(entry.findtext("a:updated", namespaces=NS)))
        abstract = unescape(re.sub(r"<[^>]+>", " ", paper["abstract"]))
        announce_match = re.search(r"Announce Type:\s*([\w-]+)", abstract, re.I)
        announce_type = announce_match.group(1).lower() if announce_match else "unknown"
        abstract = re.sub(r"^.*?Abstract:\s*", "", abstract, count=1, flags=re.I | re.S)
        if not paper["authors"] or not abstract or not paper["categories"]:
            raise ArxivError(f"Missing RSS paper metadata: {paper['id']}")
        paper.update(abstract=_clean(abstract), published="", updated="", announced=announced,
                     announce_type=announce_type, date_basis="announcement",
                     source_date={"published": announced, "updated": generated,
                                  "meaning": "RSS published=announcement; updated=feed generation"})
        papers.append(paper)
    return papers, {"feed_generated_at": feed_updated, "feed_items": len(papers)}


class _Fetcher:
    def __init__(self, raw_dir: Path, timeout: float, on_event=None):
        self.raw_dir = raw_dir
        self.timeout = timeout
        self.requests = 0
        self.on_event = on_event
        raw_dir.mkdir(parents=True, exist_ok=True)

    def event(self, message: str):
        if self.on_event:
            self.on_event({"stage": "fetch", "message": message})

    def get(self, url: str, name: str) -> bytes:
        global _LAST_REQUEST
        with _REQUEST_LOCK:
            delay = 3.05 - (time.monotonic() - _LAST_REQUEST)
            if delay > 0:
                time.sleep(delay)
            self.requests += 1
            self.event(f"读取 arXiv 元数据（请求 {self.requests}）")
            started_at = datetime.now(timezone.utc).isoformat()
            request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/atom+xml, application/xml"})
            data = b""
            metadata = {"url": url, "requested_at": started_at, "user_agent": USER_AGENT}
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    final_host = urllib.parse.urlsplit(response.geturl()).hostname
                    if final_host not in {"arxiv.org", "export.arxiv.org", "rss.arxiv.org"}:
                        raise ArxivError("Unexpected redirect outside official arXiv hosts")
                    metadata.update(status=response.status, content_type=response.headers.get("Content-Type", ""), final_url=response.geturl())
                    data = response.read(MAX_RESPONSE_BYTES + 1)
                    if len(data) > MAX_RESPONSE_BYTES:
                        raise ArxivError("arXiv response exceeds size limit")
            except urllib.error.HTTPError as exc:
                data = exc.read(MAX_RESPONSE_BYTES)
                metadata.update(status=exc.code, error=str(exc))
                raise ArxivError(f"arXiv HTTP {exc.code}") from exc
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                metadata["error"] = str(exc)
                raise ArxivError(f"arXiv request failed: {exc}") from exc
            finally:
                _LAST_REQUEST = time.monotonic()
                stem = f"{self.requests:03d}-{name}"
                if data:
                    (self.raw_dir / (stem + ".xml")).write_bytes(data)
                metadata["response_bytes"] = len(data)
                (self.raw_dir / (stem + ".json")).write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
            return data


def fetch_recent(profile: dict, since: str, until: str, raw_dir: Path, on_event=None) -> dict:
    """Scan inclusive UTC update window, retaining revisions of older papers.

    No submittedDate filter: it would exclude old manuscripts revised today.
    A page cap or transport error never advances complete-window coverage.
    """
    lower, upper = _utc(since), _utc(until)
    if lower > upper:
        raise ValueError("since must not be later than until")
    categories = list(dict.fromkeys(profile.get("categories", [])))
    if not categories or any(not re.fullmatch(r"[a-z][a-z\-]*(?:\.[A-Za-z][A-Za-z\-]*)?", c) for c in categories):
        raise ValueError("A valid explicit category list is required")
    config = profile.get("scan", {})
    page_size = max(1, min(1000, int(config.get("page_size", 100))))
    max_pages = max(1, min(50, int(config.get("max_pages", 5))))
    retries = max(0, min(1, int(config.get("retries", 1))))
    fetcher = _Fetcher(Path(raw_dir), max(1, min(20, float(config.get("timeout_seconds", 20)))), on_event)
    query = " OR ".join("cat:" + c for c in categories)
    errors, all_papers, dates = [], {}, []
    coverage = {"since": _iso(since), "until": _iso(until), "categories": categories,
                "query": query, "time_field": "updated", "complete_window": False,
                "sources": [], "api_pages": 0, "api_total_results": None,
                "page_size": page_size, "max_pages": max_pages, "truncated": False,
                "notes": ["分类范围内按修订日期倒序；不限制首稿日期。"]}
    start = 0
    previous_last = None
    seen_pages = set()
    source_failed = False
    for page_index in range(max_pages):
        url = API_URL + "?" + urllib.parse.urlencode({"search_query": query, "start": start, "max_results": page_size, "sortBy": "lastUpdatedDate", "sortOrder": "descending"})
        page, total = None, None
        for attempt in range(retries + 1):
            try:
                data = fetcher.get(url, f"api-page-{page_index + 1:03d}-attempt-{attempt + 1}")
                page, total = parse_atom(data)
                break
            except ArxivError as exc:
                errors.append(f"API 第{page_index + 1}页，第{attempt + 1}次：{exc}")
                fetcher.event(errors[-1])
        if page is None:
            source_failed = True
            break
        coverage["api_pages"] += 1
        coverage["api_total_results"] = total
        if "arxiv-api" not in coverage["sources"]:
            coverage["sources"].append("arxiv-api")
        if not page:
            if total == 0 or start >= total:
                coverage["complete_window"] = True
            else:
                errors.append("API 返回空分页，但 totalResults 表明仍有记录；覆盖不完整。")
                source_failed = True
            break
        fingerprint = tuple((p["id"], p["version"]) for p in page)
        if fingerprint in seen_pages:
            errors.append("API 分页重复，已停止，避免把重复数据误当完整扫描。")
            source_failed = True
            break
        seen_pages.add(fingerprint)
        page_dates = [_utc(p["updated"]) for p in page]
        sorted_ok = page_dates == sorted(page_dates, reverse=True) and (previous_last is None or page_dates[0] <= previous_last)
        for paper, updated in zip(page, page_dates):
            dates.append(paper["updated"])
            if lower <= updated <= upper:
                old = all_papers.get(paper["id"])
                if old is None or paper["version"] >= old["version"]:
                    all_papers[paper["id"]] = paper
        start += len(page)
        previous_last = min(page_dates)
        if not sorted_ok:
            errors.append("API 结果不符合修订时间倒序，无法证明窗口覆盖完整。")
            source_failed = True
            break
        if min(page_dates) < lower or start >= total:
            coverage["complete_window"] = True
            break
    else:
        coverage["truncated"] = True
        coverage["notes"].append("已达分页上限，较早候选可能尚未覆盖；不能视为完整扫描。")
        errors.append(f"达到 {max_pages} 页上限，尚未覆盖完整时间窗口。")
    coverage["api_scanned_items"] = start
    coverage["earliest_updated"] = min(dates) if dates else None
    coverage["latest_updated"] = max(dates) if dates else None
    # RSS is a daily announcement slice, never an API history substitute. Do not
    # invoke it on normal cap truncation: that adds no historical coverage.
    rss_valid = False
    if source_failed:
        coverage["notes"].append("API 不完整，尝试官方 RSS 当日公告；RSS 不覆盖整个回溯窗口。")
        try:
            data = fetcher.get(RSS_URL + "+".join(categories), "rss-fallback")
            rss_papers, rss_info = parse_rss_atom(data)
            rss_valid = True
            coverage["sources"].append("arxiv-rss")
            coverage["rss"] = {**rss_info, "scope": "current announcement feed only", "date_basis": "announcement", "result_limit": 2000}
            if len(rss_papers) >= 2000:
                coverage["notes"].append("RSS 达到 2000 条上限，当前公告也可能被截断。")
            included = 0
            for paper in rss_papers:
                old = all_papers.get(paper["id"])
                # Announcement feeds can expose a newly announced revision
                # before the search index reflects it. Keep that newer version.
                if lower <= _utc(paper["announced"]) <= upper and (old is None or paper["version"] > old["version"]):
                    all_papers[paper["id"]] = paper
                    included += 1
            coverage["rss"]["included_in_window"] = included
        except ArxivError as exc:
            errors.append(f"RSS 降级失败：{exc}")
    if coverage["complete_window"]:
        status = "success"
    elif coverage["api_pages"] or rss_valid:
        status = "partial"
    else:
        status = "failed"
    papers = sorted(all_papers.values(), key=lambda p: (p.get("updated") or p.get("announced") or "", p["id"]), reverse=True)
    return {"papers": papers, "status": status, "errors": errors, "coverage": coverage, "requests": fetcher.requests}
