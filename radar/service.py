"""Stateful harness: retrieve -> rank -> review -> deliver, with explicit failures."""
from __future__ import annotations

import fcntl
import json
import re
import time
import uuid
from functools import lru_cache
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote, urlsplit

from .store import Store
from .ranking import rank_paper
from .config import data_path, profile_path, load_profile

ROOT = Path(__file__).resolve().parent.parent


@lru_cache(maxsize=12000)
def cached_rank(paper_json, profile_json):
    return rank_paper(json.loads(paper_json), json.loads(profile_json))


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def parse_time(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


class BusyError(RuntimeError):
    pass


class Radar:
    def __init__(self, root=ROOT, *, profile=None, data_dir=None):
        self.root = Path(root).expanduser().resolve()
        self.profile_path = profile_path(self.root, profile)
        self._profile = None
        self._profile_stamp = None
        # Reject a broken profile before creating a database or acquiring a lock.
        self.profile
        self.data = data_path(self.root, data_dir)
        self.data.mkdir(parents=True, exist_ok=True)
        self.store = Store(self.data / "radar.sqlite3")

    @property
    def profile(self):
        try:
            stat = self.profile_path.stat()
        except OSError:
            return load_profile(self.profile_path)  # Produce a readable path-specific error.
        stamp = (stat.st_mtime_ns, stat.st_size)
        if self._profile is None or self._profile_stamp != stamp:
            self._profile = load_profile(self.profile_path)
            self._profile_stamp = stamp
        return self._profile

    def acquire(self):
        handle = (self.data / "scan.lock").open("a+")
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            handle.close()
            raise BusyError("已有扫描正在运行") from None
        return handle

    def scanning(self):
        try:
            handle = self.acquire()
        except BusyError:
            return True
        handle.close()
        return False

    def latest(self, finished=False):
        runs = self.store.runs()
        return next((r for r in runs if r["status"] != "running"), None) if finished else (runs[0] if runs else None)

    def scan(self, days=None, fetcher=None, handle=None):
        if days is not None and (isinstance(days, bool) or not isinstance(days, int) or not 1 <= days <= 90):
            if handle:
                handle.close()
            raise ValueError("--days 须在 1 至 90 之间")
        handle = handle or self.acquire()
        run = None
        try:
            # Holding the OS lock proves any older 'running' record was interrupted.
            for old in self.store.runs():
                if old["status"] == "running":
                    old.update(status="failed", finished_at=now_iso())
                    old["errors"].append("上次扫描中断；此次将重试未完成的日期范围。")
                    self.store.save_run(old)
            profile = self.profile
            previous_run = self.latest(finished=True)
            if fetcher is None and previous_run and previous_run.get("finished_at"):
                elapsed = (datetime.now(timezone.utc) - parse_time(previous_run["finished_at"])).total_seconds()
                if 0 <= elapsed < 3.05:
                    time.sleep(3.05 - elapsed)
            until = datetime.now(timezone.utc)
            watermark = self.store.get_setting("watermark")
            scope = sorted(set(profile["categories"]))
            old_scope = self.store.get_setting("scan_categories")
            scope_changed = old_scope is not None and scope != old_scope
            if scope_changed:
                watermark = None
            since = (parse_time(watermark) - timedelta(days=profile["scan"]["overlap_days"])) if watermark and days is None else until - timedelta(days=days or profile["scan"]["lookback_days"])
            run = {"id": until.strftime("%Y%m%dT%H%M%S%f") + "-" + uuid.uuid4().hex[:6],
                   "started_at": until.isoformat(timespec="seconds"), "finished_at": None,
                   "status": "running", "new_count": 0, "updated_count": 0,
                   "candidate_count": 0, "relevant_count": 0, "errors": [], "stages": [],
                   "initial_backfill": not bool(self.store.papers()),
                   "scope_changed": scope_changed,
                   "coverage": {"since": since.isoformat(timespec="seconds"), "until": until.isoformat(timespec="seconds")}}
            self.store.save_run(run)
            raw = self.data / "raw" / run["id"]
            def on_event(event):
                record = dict(event) if isinstance(event, dict) else {"message": str(event)}
                record.setdefault("at", now_iso())
                run["stages"].append(record)
                self.store.save_run(run)
            on_event({"stage": "retrieve", "message": "正在请求 arXiv 官方数据", "at": now_iso()})
            if fetcher is None:
                from .arxiv import fetch_recent
                fetcher = fetch_recent
            result = fetcher(profile, run["coverage"]["since"], run["coverage"]["until"], raw, on_event=on_event)
            run["coverage"].update(result.get("coverage", {}))
            run["errors"] = list(result.get("errors", []))
            run["requests"] = result.get("requests", 0)
            final_status = result["status"]
            if final_status not in ("success", "partial", "failed"):
                raise ValueError("数据源返回了无效扫描状态")
            # Collapse cross-listings before counting; keep the highest version.
            unique = {}
            for p in result.get("papers", []):
                if p["id"] not in unique or p["version"] > unique[p["id"]]["version"]:
                    unique[p["id"]] = dict(p)
                elif p["version"] == unique[p["id"]]["version"]:
                    unique[p["id"]]["categories"] = sorted(set(unique[p["id"]]["categories"]) | set(p["categories"]))
            on_event({"stage": "rank", "message": f"对 {len(unique)} 篇去重论文进行方向匹配", "at": now_iso()})
            for paper in unique.values():
                self.store.upsert(paper, run["id"], now_iso())
            papers = self.papers(run_id=run["id"], include_hidden=True, include_low=True)
            relevant = [p for p in papers if self.is_relevant(p)]
            run["candidate_count"] = len(unique)
            run["new_count"] = sum(p["last_event"] == "new" for p in relevant)
            run["updated_count"] = sum(p["last_event"] == "updated" for p in relevant)
            run["relevant_count"] = sum(p["id"] in unique for p in relevant)
            run["status"] = final_status
            run["finished_at"] = now_iso()
            self.store.save_run(run)
            # Only a complete API scan closes the interval; RSS fallback cannot.
            continuous = not watermark and (days is None or days >= profile["scan"]["lookback_days"]) or watermark and since <= parse_time(watermark)
            if run["status"] == "success" and run["coverage"].get("complete_window") and continuous:
                previous = None if scope_changed else self.store.get_setting("watermark")
                if not previous or parse_time(run["coverage"]["until"]) > parse_time(previous):
                    self.store.set_setting("watermark", run["coverage"]["until"])
                    self.store.set_setting("scan_categories", scope)
            write_json(raw / "run.json", run)
            self.digest()
            return run
        except Exception as error:
            if run:
                run.update(status="failed", finished_at=now_iso())
                run["errors"].append(f"{type(error).__name__}: {error}")
                self.store.save_run(run)
                self.digest()
                return run
            raise
        finally:
            handle.close()

    def is_relevant(self, paper):
        return paper["score"] >= self.profile.get("minimum_score", 20) and not paper["is_own"]

    def papers(self, topic="", filter="all", q="", run_id=None, include_hidden=False, include_low=False, sort="relevance"):
        filter = filter or "all"
        sort = sort or "relevance"
        if filter not in ("all", "new", "updates", "saved", "read", "unread", "notes", "hidden"):
            raise ValueError("未知论文筛选条件")
        if sort not in ("relevance", "newest", "title"):
            raise ValueError("未知论文排序方式")
        if run_id is None:
            latest = next((r for r in self.store.runs() if r["status"] in ("success", "partial")), None)
            run_id = latest["id"] if latest else None
        profile = self.profile
        profile_json = json.dumps(profile, sort_keys=True, ensure_ascii=False)
        papers = self.store.papers(run_id)
        for p in papers:
            ranking_input = {k: p.get(k) for k in ("id", "title", "abstract", "categories", "authors")}
            p.update(cached_rank(json.dumps(ranking_input, sort_keys=True, ensure_ascii=False), profile_json))
        # Managed library items remain reachable when a profile changes or its
        # relevance threshold rises. Discovery views still follow that profile.
        if not include_low and filter not in ("saved", "read", "notes", "hidden"):
            papers = [p for p in papers if self.is_relevant(p)]
        if filter == "hidden":
            papers = [p for p in papers if p["hidden"]]
        elif not include_hidden:
            papers = [p for p in papers if not p["hidden"]]
        if filter in ("new", "updates"):
            papers = [p for p in papers if p["last_event"] == ("updated" if filter == "updates" else "new")]
        elif filter in ("saved", "read"):
            papers = [p for p in papers if p[filter]]
        elif filter == "unread":
            papers = [p for p in papers if not p["read"]]
        elif filter == "notes":
            papers = [p for p in papers if p["notes"].strip()]
        if topic:
            papers = [p for p in papers if topic in [t["id"] for t in p["topics"]]]
        if q:
            papers = [p for p in papers if q.casefold() in (p["title"] + " " + p["abstract"] + " " + " ".join(p["authors"]) + " " + p["notes"]).casefold()]
        def date_key(paper):
            value = paper.get("updated") or paper.get("announced") or paper.get("published")
            return parse_time(value).timestamp() if value else float("-inf")
        if sort == "title":
            papers.sort(key=lambda p: (p["title"].casefold(), p["id"]))
        elif sort == "newest":
            papers.sort(key=lambda p: (date_key(p), p["score"], p["id"]), reverse=True)
        else:
            papers.sort(key=lambda p: (p["score"], date_key(p), p["id"]), reverse=True)
        return papers

    def state(self):
        all_papers = self.papers(include_hidden=True, include_low=True)
        visible = [p for p in all_papers if not p["hidden"]]
        relevant = [p for p in visible if self.is_relevant(p)]
        return {"profile": self.profile, "latest_run": self.latest(), "scanning": self.scanning(),
                "stats": {"papers": len(all_papers), "relevant": len(relevant),
                          "new": sum(p["last_event"] == "new" for p in relevant),
                          "updates": sum(p["last_event"] == "updated" for p in relevant),
                          "saved": sum(p["saved"] for p in visible),
                          "read": sum(p["read"] for p in visible),
                          "notes": sum(bool(p["notes"].strip()) for p in visible)},
                "topics": self.profile["topics"],
                "notice": "基于标题与摘要进行方向匹配；相关性分数不代表论文质量或证明正确性。定时扫描需自行配置，启动服务不会自动启用定时任务。"}

    def review_queue(self):
        papers = [p for p in self.papers() if not p["assessment"] and not p["read"]]
        return {"evidence_level": "abstract", "instruction": "仅依据提供的摘要解读；不得声称阅读全文或验证证明。证据引文必须逐字来自 abstract。", "papers": papers[:self.profile.get("digest_limit", 8)]}

    def delivery_plan(self):
        """A durable notification ledger, separate from scan/update detection."""
        run = self.latest(finished=True)
        if not run:
            return {"should_notify": False, "papers": [], "acknowledge": {}, "status_key": None}
        notified = self.store.get_setting("notified_versions", {})
        pending = [p for p in self.papers() if notified.get(p["id"], -1) < p["version"]]
        status_key = json.dumps({"status": run["status"], "errors": run["errors"]}, sort_keys=True, ensure_ascii=False)
        old_status = self.store.get_setting("notified_status")
        changed_status = status_key != old_status and (run["status"] != "success" or old_status is not None)
        return {"should_notify": bool(pending) or changed_status,
                "run_id": run["id"], "status": run["status"], "errors": run["errors"], "coverage": run["coverage"],
                "pending_count": len(pending), "papers": pending[:self.profile.get("digest_limit", 8)],
                "acknowledge": {p["id"]: p["version"] for p in pending}, "status_key": status_key}

    def acknowledge(self, plan):
        known = {p["id"]: p["version"] for p in self.store.papers()}
        additions = plan.get("acknowledge", {})
        if not isinstance(additions, dict) or any(known.get(k) != v for k, v in additions.items()):
            raise ValueError("通知清单包含不存在或已过时的版本")
        old = self.store.get_setting("notified_versions", {})
        old.update(additions)
        self.store.set_setting("notified_versions", old)
        self.store.set_setting("notified_status", plan.get("status_key"))
        write_json(self.data / "notifications" / (now_iso().replace(":", "") + ".json"), plan)

    def import_reviews(self, document):
        reviews = document.get("reviews", []) if isinstance(document, dict) else document
        if not isinstance(reviews, list):
            raise ValueError("reviews 必须是数组")
        by_id = {p["id"]: p for p in self.papers(include_hidden=True, include_low=True)}
        validated = []
        for r in reviews:
            if not isinstance(r, dict):
                raise ValueError("每条解读必须是 JSON 对象")
            paper = by_id.get(r.get("id"))
            if not paper or r.get("version") != paper["version"]:
                raise ValueError(f"论文版本不一致：{r.get('id')}")
            if r.get("evidence_level") != "abstract" or r.get("priority") not in ("read", "skim", "skip"):
                raise ValueError("解读须标注 abstract 证据层级和有效优先级")
            for field in ("summary_zh", "relevance_zh", "caveat_zh", "model"):
                if not isinstance(r.get(field), str) or not r[field].strip() or len(r[field]) > 3000:
                    raise ValueError(f"解读字段不合法：{field}")
            quotes = r.get("evidence_quotes")
            if not isinstance(quotes, list) or not 1 <= len(quotes) <= 3 or any(not isinstance(x, str) or len(x) < 12 or x not in paper["abstract"] for x in quotes):
                raise ValueError("缺少可在原摘要中逐字核对的证据")
            if sum(len(x.split()) for x in quotes) > 25:
                raise ValueError("每篇摘要的证据引文合计最多 25 词")
            validated.append({k: r[k] for k in ("id", "version", "summary_zh", "relevance_zh", "caveat_zh", "model", "evidence_level", "priority", "evidence_quotes")})
        for review in validated:
            review["assessed_at"] = now_iso()
            self.store.review(review["id"], review["version"], review)
        self.digest()
        return len(validated)

    def digest(self):
        run = self.latest(finished=True)
        if not run:
            return {"markdown": "# arXiv 研究雷达\n\n尚未执行扫描。", "run_id": None}
        candidates = [p for p in self.papers(run_id=run["id"]) if p["last_event"] in ("new", "updated")]
        title = "方向配置更新简报" if run.get("scope_changed") else "首次回溯简报" if run.get("initial_backfill") else "每日研究简报"
        lines = [f"# {title}", "", f"扫描时间（UTC）：{run['started_at']}",
                 f"扫描状态：{ {'success': '完整', 'partial': '部分覆盖', 'failed': '失败'}[run['status']]}",
                 f"日期范围：{run['coverage'].get('since', '')} 至 {run['coverage'].get('until', '')}", "",
                 "按标题与摘要筛选；未验证论文证明。首次发现不等于当日新发表。", ""]
        if run["status"] != "success":
            lines += ["> 本次未完整覆盖目标范围，不能据此判断是否没有其他相关论文。", ""]
        for error in run["errors"]:
            lines += [f"- 数据源说明：{error}"]
        if run["errors"]:
            lines.append("")
        if not candidates:
            lines.append("本次完整扫描未发现新的相关记录或版本变化。" if run["status"] == "success" else "本次已获取的数据中没有新的相关推荐；其余范围仍待补扫。")
        for p in candidates[:self.profile.get("digest_limit", 8)]:
            label = "版本更新" if p["last_event"] == "updated" else "首次发现"
            versioned_id = p['id'] + (f"v{p['version']}" if p['version'] else "（版本未提供）")
            lines += [f"## [{p['title']}]({p['url']})", "", f"{versioned_id} · {label} · 相关性 {p['score']}", "",
                      "推荐依据：" + "；".join(p["reasons"]), ""]
            if p["assessment"]:
                a = p["assessment"]
                lines += [a["summary_zh"], "", "与你的研究联系：" + a["relevance_zh"], "", "阅读边界：" + a["caveat_zh"], ""]
            else:
                lines += ["中文摘要解读待生成；当前为规则初筛。", ""]
        result = {"markdown": "\n".join(lines).strip() + "\n", "run_id": run["id"]}
        path = self.data / "digests"
        path.mkdir(exist_ok=True)
        (path / (run["id"] + ".md")).write_text(result["markdown"], encoding="utf-8")
        write_json(path / "latest.json", result)
        return result

    def bibtex(self, scope="", **view):
        def esc(value):
            return re.sub(r"([{}%&#_])", r"\\\1", value.replace("\\", " "))
        if scope not in ("", "view"):
            raise ValueError("未知导出范围")
        selected = self.papers(**view) if scope == "view" else self.papers(filter="saved") or self.papers()[:self.profile.get("digest_limit", 8)]
        blocks = []
        for p in selected:
            year = (p.get("published") or p.get("announced") or p["first_seen"])[:4]
            blocks.append("@misc{arxiv" + p["id"].replace(".", "").replace("/", "") + ",\n" +
                          f"  title = {{{esc(p['title'])}}},\n  author = {{{' and '.join(esc(a) for a in p['authors'])}}},\n  year = {{{year}}},\n  eprint = {{{p['id']}}},\n  archivePrefix = {{arXiv}},\n  url = {{{p['url']}}}\n}}")
        return "\n\n".join(blocks) + "\n"

    def markdown(self, scope="view", **view):
        """Export precisely one library view; user text remains literal text."""
        if scope not in ("", "view"):
            raise ValueError("未知导出范围")
        selected = self.papers(**view)

        def inline(value):
            return re.sub(r"([\\`*_{}\[\]<>()#+.!|~-])", r"\\\1", str(value)).replace("\n", " ")

        def literal(value):
            # A note may contain HTML or Markdown fences. Use a longer fence
            # than any supplied backtick run, preserving its text verbatim.
            width = max([2] + [len(match) for match in re.findall(r"`+", value)]) + 1
            fence = "`" * width
            return [fence + "text", value, fence]

        def link(label, value):
            # Source adapters normally produce canonical arXiv URLs. Retain a
            # safe text fallback for older or manually imported metadata too.
            try:
                parsed = urlsplit(value)
                valid = parsed.scheme == "https" and parsed.hostname == "arxiv.org" and not parsed.username
            except (TypeError, ValueError):
                valid = False
            return f"[{label}]({quote(value, safe=':/?=&%#')})" if valid else inline(label + ": " + str(value))

        lines = ["# Research library export / 阅读库导出", "", f"Papers / 论文数: {len(selected)}", "",
                 "Paper metadata and abstracts are source material. User notes are separate personal annotations; neither verifies a paper's claims.", "",
                 "## Selection / 筛选条件", ""]
        lines += literal(json.dumps({key: view.get(key, default) for key, default in
                                    (("topic", ""), ("filter", "all"), ("q", ""), ("sort", "relevance"))}, ensure_ascii=False))
        for paper in selected:
            version = f"v{paper['version']}" if paper["version"] else " (version unavailable)"
            lines += ["", f"## {inline(paper['title'])}", "",
                      f"- arXiv: {inline(paper['id'])}{version}",
                      f"- Authors / 作者: {inline('; '.join(paper['authors']))}",
                      f"- Categories / 分类: {inline(', '.join(paper['categories']))}",
                      f"- Source / 来源: {inline(paper.get('source', ''))}",
                      f"- First submitted / 首稿日期: {inline(paper.get('published') or 'not provided')}",
                      f"- Revision submitted / 修订日期: {inline(paper.get('updated') or 'not provided')}"]
            if paper.get("announced"):
                lines.append(f"- Announcement / 公告日期: {inline(paper['announced'])} (not a submission date)")
            lines += [f"- Reading state / 阅读状态: saved={paper['saved']}, read={paper['read']}, hidden={paper['hidden']}",
                      "", link("arXiv", paper["url"]) + " · " + link("PDF", paper["pdf_url"]), "",
                      "### Original abstract / 原始摘要", ""]
            lines += literal(paper["abstract"])
            lines += ["", "### User notes / 用户笔记", ""]
            if paper["notes"].strip():
                lines += [f"Notes saved for version / 笔记对应版本: {paper['notes_version']}",
                          f"Updated (UTC) / 笔记更新时间: {paper['notes_updated_at']}", ""]
                if paper["notes_version"] != paper["version"]:
                    lines += ["These notes were saved for a different paper version. / 笔记对应旧版本，请结合当前版本复核。", ""]
                lines += literal(paper["notes"])
            else:
                lines += ["No notes / 暂无笔记"]
        return "\n".join(lines).rstrip() + "\n"
