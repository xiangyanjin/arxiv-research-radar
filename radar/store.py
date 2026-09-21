"""SQLite persistence; each operation uses its own connection."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path


class Store:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS papers (
                    id TEXT PRIMARY KEY, version INTEGER NOT NULL, payload TEXT NOT NULL,
                    first_seen TEXT NOT NULL, last_seen TEXT NOT NULL,
                    feedback TEXT NOT NULL DEFAULT '', assessment TEXT);
                CREATE TABLE IF NOT EXISTS runs (id TEXT PRIMARY KEY, payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS events (
                    run_id TEXT NOT NULL, paper_id TEXT NOT NULL, kind TEXT NOT NULL,
                    PRIMARY KEY(run_id, paper_id));
                CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            """)

    def connect(self):
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA journal_mode=WAL")
        return db

    def get_setting(self, key, default=None):
        with self.connect() as db:
            row = db.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def set_setting(self, key, value):
        with self.connect() as db:
            db.execute("INSERT OR REPLACE INTO settings VALUES (?,?)", (key, json.dumps(value, ensure_ascii=False)))

    def save_run(self, run):
        with self.connect() as db:
            db.execute("INSERT OR REPLACE INTO runs VALUES (?,?)", (run["id"], json.dumps(run, ensure_ascii=False)))

    def runs(self):
        with self.connect() as db:
            rows = db.execute("SELECT payload FROM runs ORDER BY id DESC LIMIT 100").fetchall()
        return [json.loads(r[0]) for r in rows]

    def upsert(self, paper, run_id, now):
        """Never downgrade a version or discard feedback. Revisions invalidate reviews."""
        with self.connect() as db:
            old = db.execute("SELECT * FROM papers WHERE id=?", (paper["id"],)).fetchone()
            if old is None:
                db.execute("INSERT INTO papers (id,version,payload,first_seen,last_seen) VALUES (?,?,?,?,?)",
                           (paper["id"], paper["version"], json.dumps(paper, ensure_ascii=False), now, now))
                event = "new"
            elif paper["version"] < old["version"]:
                return "unchanged"
            else:
                event = "updated" if old["version"] > 0 and paper["version"] > old["version"] else "unchanged"
                previous = json.loads(old["payload"])
                changed_version = paper["version"] != old["version"]
                if changed_version:
                    merged = dict(paper)
                    # The first submission date is stable across revisions, but
                    # a prior version's update date must never label a new one.
                    if not merged.get("published") and previous.get("published"):
                        merged["published"] = previous["published"]
                elif previous.get("source") == "arxiv-api" and paper.get("source") == "arxiv-rss":
                    merged = dict(previous)
                    if paper.get("announced"):
                        merged["announced"] = paper["announced"]
                else:
                    merged = dict(previous)
                    merged.update({k: v for k, v in paper.items() if v not in (None, "", [])})
                changed_text = any(merged.get(k) != previous.get(k) for k in ("title", "abstract"))
                db.execute("UPDATE papers SET version=?, payload=?, last_seen=?, assessment=? WHERE id=?",
                           (paper["version"], json.dumps(merged, ensure_ascii=False), now,
                            None if changed_version or changed_text else old["assessment"], paper["id"]))
            if event != "unchanged":
                # One event per run even when a feed repeats cross-listed papers.
                db.execute("INSERT INTO events VALUES (?,?,?) ON CONFLICT(run_id,paper_id) DO UPDATE SET kind=CASE WHEN events.kind='new' THEN 'new' ELSE excluded.kind END",
                           (run_id, paper["id"], event))
        return event

    def papers(self, run_id=None):
        with self.connect() as db:
            rows = db.execute("SELECT * FROM papers").fetchall()
            events = {r[0]: r[1] for r in db.execute("SELECT paper_id,kind FROM events WHERE run_id=?", (run_id,))} if run_id else {}
        result = []
        for row in rows:
            item = json.loads(row["payload"])
            item.update(first_seen=row["first_seen"], last_seen=row["last_seen"], feedback=row["feedback"],
                        assessment=json.loads(row["assessment"]) if row["assessment"] else None,
                        last_event=events.get(row["id"], "unchanged"))
            result.append(item)
        return result

    def feedback(self, paper_id, value):
        if value not in ("", "saved", "irrelevant", "read"):
            raise ValueError("未知阅读状态")
        with self.connect() as db:
            if db.execute("UPDATE papers SET feedback=? WHERE id=?", (value, paper_id)).rowcount != 1:
                raise ValueError("论文不存在")

    def review(self, paper_id, version, assessment):
        with self.connect() as db:
            if db.execute("UPDATE papers SET assessment=? WHERE id=? AND version=?",
                          (json.dumps(assessment, ensure_ascii=False), paper_id, version)).rowcount != 1:
                raise ValueError("论文不存在或版本已更新")
