"""SQLite persistence; each operation uses its own connection."""
from __future__ import annotations

import json
import sqlite3
import time
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path


class Store:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self.connect()) as db, db:
            self._enable_wal(db)
            # Serialize discovery and ALTER TABLE across CLI/server processes.
            # SQLite DDL is transactional; no process sees a half-migrated table.
            db.execute("BEGIN IMMEDIATE")
            db.execute("""CREATE TABLE IF NOT EXISTS papers (
                    id TEXT PRIMARY KEY, version INTEGER NOT NULL, payload TEXT NOT NULL,
                    first_seen TEXT NOT NULL, last_seen TEXT NOT NULL,
                    feedback TEXT NOT NULL DEFAULT '', assessment TEXT)""")
            db.execute("CREATE TABLE IF NOT EXISTS runs (id TEXT PRIMARY KEY, payload TEXT NOT NULL)")
            db.execute("""CREATE TABLE IF NOT EXISTS events (
                    run_id TEXT NOT NULL, paper_id TEXT NOT NULL, kind TEXT NOT NULL,
                    PRIMARY KEY(run_id, paper_id))""")
            db.execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
            existing = {row[1] for row in db.execute("PRAGMA table_info(papers)")}
            columns = {"saved": "INTEGER NOT NULL DEFAULT 0", "read": "INTEGER NOT NULL DEFAULT 0",
                       "hidden": "INTEGER NOT NULL DEFAULT 0", "notes": "TEXT NOT NULL DEFAULT ''",
                       "notes_updated_at": "TEXT NOT NULL DEFAULT ''", "notes_version": "INTEGER"}
            legacy = {"saved": "saved", "read": "read", "hidden": "irrelevant"}
            for name, definition in columns.items():
                if name not in existing:
                    db.execute(f'ALTER TABLE papers ADD COLUMN "{name}" {definition}')
                    if name in legacy:
                        db.execute(f'UPDATE papers SET "{name}"=(feedback=?)', (legacy[name],))

    def connect(self):
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        return db

    @staticmethod
    def _enable_wal(db):
        """Initialize persistent WAL mode, tolerating brief opening races only."""
        # The mode-switch PRAGMA can fail immediately despite SQLite's normal
        # busy handler. Keep each attempt short instead of multiplying the
        # ordinary 15-second transaction timeout by the retry count.
        db.execute("PRAGMA busy_timeout=250")
        delays = (0.05, 0.1, 0.2, 0.4, 0.8, 1.0, 1.0)
        for attempt in range(len(delays) + 1):
            try:
                db.execute("PRAGMA journal_mode=WAL")
                break
            except sqlite3.OperationalError as error:
                code = getattr(error, "sqlite_errorcode", None)
                if isinstance(code, int):
                    transient = (code & 0xFF) in (5, 6)  # SQLITE_BUSY / SQLITE_LOCKED, including extended codes.
                else:
                    # Python 3.10 does not expose sqlite_errorcode. Match only
                    # SQLite's known lock messages, never unrelated failures.
                    message = str(error).lower()
                    transient = message in ("database is locked", "database table is locked", "database schema is locked") or \
                        message.startswith(("database table is locked:", "database schema is locked:"))
                if not transient or attempt == len(delays):
                    raise
                time.sleep(delays[attempt])
        db.execute("PRAGMA busy_timeout=15000")

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
                        saved=bool(row["saved"]), read=bool(row["read"]), hidden=bool(row["hidden"]),
                        notes=row["notes"], notes_updated_at=row["notes_updated_at"], notes_version=row["notes_version"],
                        assessment=json.loads(row["assessment"]) if row["assessment"] else None,
                        last_event=events.get(row["id"], "unchanged"))
            result.append(item)
        return result

    def feedback(self, paper_id, value):
        """Compatibility endpoint: the original mutually exclusive state change."""
        if not isinstance(paper_id, str) or not paper_id:
            raise ValueError("需要有效论文编号")
        if value not in ("", "saved", "irrelevant", "read"):
            raise ValueError("未知阅读状态")
        with self.connect() as db:
            if db.execute('UPDATE papers SET feedback=?, saved=?, "read"=?, hidden=? WHERE id=?',
                          (value, value == "saved", value == "read", value == "irrelevant", paper_id)).rowcount != 1:
                raise ValueError("论文不存在")

    def update_library(self, document):
        """Atomically patch independent reading state; omitted fields survive."""
        allowed = {"id", "saved", "read", "hidden", "notes"}
        if not isinstance(document, dict) or set(document) - allowed:
            raise ValueError("阅读库更新只允许 id、saved、read、hidden、notes 字段")
        paper_id = document.get("id")
        if not isinstance(paper_id, str) or not paper_id.strip() or len(paper_id) > 256:
            raise ValueError("需要有效论文编号")
        changes = {key: value for key, value in document.items() if key != "id"}
        if not changes:
            raise ValueError("至少提供一个要更新的阅读库字段")
        for name in ("saved", "read", "hidden"):
            if name in changes and type(changes[name]) is not bool:
                raise ValueError(f"{name} 必须是布尔值")
        if "notes" in changes and (not isinstance(changes["notes"], str) or len(changes["notes"]) > 5000):
            raise ValueError("notes 必须是最多 5000 个字符的文本")
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            paper = db.execute("SELECT version FROM papers WHERE id=?", (paper_id,)).fetchone()
            if paper is None:
                raise ValueError("论文不存在")
            if "notes" in changes:
                changes["notes_updated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
                changes["notes_version"] = paper["version"] if changes["notes"].strip() and paper["version"] > 0 else None
            assignments = ", ".join(f'"{name}"=?' for name in changes)
            db.execute(f"UPDATE papers SET {assignments} WHERE id=?", (*changes.values(), paper_id))
            # Legacy clients can represent only one state. The independent
            # columns are authoritative; this projection does not discard them.
            db.execute('''UPDATE papers SET feedback=CASE
                       WHEN hidden THEN 'irrelevant' WHEN saved THEN 'saved'
                       WHEN "read" THEN 'read' ELSE '' END WHERE id=?''', (paper_id,))
            row = db.execute('SELECT id, saved, "read", hidden, notes, notes_updated_at, notes_version FROM papers WHERE id=?', (paper_id,)).fetchone()
        result = dict(row)
        for name in ("saved", "read", "hidden"):
            result[name] = bool(result[name])
        return result

    def review(self, paper_id, version, assessment):
        with self.connect() as db:
            if db.execute("UPDATE papers SET assessment=? WHERE id=? AND version=?",
                          (json.dumps(assessment, ensure_ascii=False), paper_id, version)).rowcount != 1:
                raise ValueError("论文不存在或版本已更新")
