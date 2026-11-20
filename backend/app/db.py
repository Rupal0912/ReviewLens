"""SQLite storage. Analysis cache identity includes text, model, and prompt version."""
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone

SCHEMA = """
CREATE TABLE IF NOT EXISTS analyses (
    text_hash TEXT NOT NULL,
    model TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    sentiment TEXT NOT NULL,
    topics TEXT NOT NULL,
    summary TEXT NOT NULL,
    needs_reply INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (text_hash, model, prompt_version)
);
CREATE TABLE IF NOT EXISTS uploads (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    filename TEXT,
    created_at TEXT NOT NULL,
    run_stats TEXT
);
CREATE TABLE IF NOT EXISTS reviews (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    upload_id INTEGER NOT NULL REFERENCES uploads(id),
    review_id TEXT,
    product TEXT,
    rating_raw TEXT,
    rating INTEGER,
    text TEXT,
    text_hash TEXT,
    status TEXT NOT NULL,          -- analyzed | skipped_empty | analysis_failed
    duplicate_of TEXT,
    issues TEXT,
    suggested_reply TEXT,
    analysis_model TEXT,
    analysis_prompt_version TEXT
);
CREATE INDEX IF NOT EXISTS idx_reviews_upload ON reviews(upload_id);
"""

LEGACY_PROMPT_VERSION = "legacy-unknown"

_CREATE_ANALYSES = """CREATE TABLE analyses (
    text_hash TEXT NOT NULL,
    model TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    sentiment TEXT NOT NULL,
    topics TEXT NOT NULL,
    summary TEXT NOT NULL,
    needs_reply INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (text_hash, model, prompt_version)
)"""

_JOIN = """SELECT r.*, a.sentiment, a.topics, a.summary, a.needs_reply
           FROM reviews r LEFT JOIN analyses a
             ON a.text_hash = r.text_hash
            AND a.model = r.analysis_model
            AND a.prompt_version = r.analysis_prompt_version"""


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _review_row(row) -> dict:
    d = dict(row)
    d.pop("analysis_model", None)
    d.pop("analysis_prompt_version", None)
    d["issues"] = json.loads(d["issues"] or "[]")
    d["topics"] = json.loads(d["topics"]) if d.get("topics") else []
    d["needs_reply"] = bool(d["needs_reply"]) if d.get("needs_reply") is not None else False
    return d


class Database:
    def __init__(self, path: str):
        self.path = path
        with self._conn() as c:
            c.executescript(SCHEMA)
            self._migrate(c)

    @staticmethod
    def _migrate(c):
        """Upgrade hash-only caches while retaining uploads and their old analyses."""
        analysis_columns = {row["name"] for row in c.execute("PRAGMA table_info(analyses)")}
        reviews_columns = {row["name"] for row in c.execute("PRAGMA table_info(reviews)")}
        legacy_cache = "prompt_version" not in analysis_columns

        c.execute("BEGIN")
        if legacy_cache:
            c.execute("ALTER TABLE analyses RENAME TO analyses_legacy")
            c.execute(_CREATE_ANALYSES)
            c.execute(
                "INSERT INTO analyses (text_hash, model, prompt_version, sentiment, topics, summary,"
                " needs_reply, created_at) SELECT text_hash, COALESCE(model, 'unknown'), ?, sentiment,"
                " topics, summary, needs_reply, created_at FROM analyses_legacy",
                (LEGACY_PROMPT_VERSION,),
            )
            c.execute("DROP TABLE analyses_legacy")

        if "analysis_model" not in reviews_columns:
            c.execute("ALTER TABLE reviews ADD COLUMN analysis_model TEXT")
        if "analysis_prompt_version" not in reviews_columns:
            c.execute("ALTER TABLE reviews ADD COLUMN analysis_prompt_version TEXT")

        if legacy_cache:
            c.execute(
                "UPDATE reviews SET analysis_model = COALESCE((SELECT model FROM analyses a"
                " WHERE a.text_hash = reviews.text_hash AND a.prompt_version = ? LIMIT 1), 'unknown'),"
                " analysis_prompt_version = ? WHERE text_hash IS NOT NULL AND EXISTS"
                " (SELECT 1 FROM analyses a WHERE a.text_hash = reviews.text_hash"
                " AND a.prompt_version = ?)",
                (LEGACY_PROMPT_VERSION, LEGACY_PROMPT_VERSION, LEGACY_PROMPT_VERSION),
            )

    @contextmanager
    def _conn(self):
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    # --- cache -----------------------------------------------------------
    def get_analyses(self, hashes: list[str], model: str, prompt_version: str) -> dict[str, dict]:
        if not hashes:
            return {}
        marks = ",".join("?" * len(hashes))
        with self._conn() as c:
            rows = c.execute(
                f"SELECT * FROM analyses WHERE text_hash IN ({marks}) AND model=? AND prompt_version=?",
                (*hashes, model, prompt_version),
            ).fetchall()
        return {r["text_hash"]: {"sentiment": r["sentiment"], "topics": json.loads(r["topics"]),
                                 "summary": r["summary"], "needs_reply": bool(r["needs_reply"])}
                for r in rows}

    def save_analysis(self, text_hash: str, result: dict, model: str, prompt_version: str):
        with self._conn() as c:
            c.execute(
                "INSERT OR REPLACE INTO analyses (text_hash, model, prompt_version, sentiment, topics,"
                " summary, needs_reply, created_at) VALUES (?,?,?,?,?,?,?,?)",
                (text_hash, model, prompt_version, result["sentiment"], json.dumps(result["topics"]),
                 result["summary"], int(result["needs_reply"]), _now()),
            )

    # --- uploads / reviews ----------------------------------------------
    def create_upload(self, filename: str) -> int:
        with self._conn() as c:
            return c.execute("INSERT INTO uploads (filename, created_at) VALUES (?,?)",
                             (filename, _now())).lastrowid

    def add_review(self, upload_id: int, cr, status: str,
                   analysis_model: str | None = None,
                   analysis_prompt_version: str | None = None) -> int:
        with self._conn() as c:
            return c.execute(
                "INSERT INTO reviews (upload_id, review_id, product, rating_raw, rating, text,"
                " text_hash, status, duplicate_of, issues, analysis_model, analysis_prompt_version)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (upload_id, cr.review_id, cr.product, cr.rating_raw, cr.rating, cr.text,
                 cr.text_hash, status, cr.duplicate_of, json.dumps(cr.issues), analysis_model,
                 analysis_prompt_version)).lastrowid

    def set_run_stats(self, upload_id: int, stats: dict):
        with self._conn() as c:
            c.execute("UPDATE uploads SET run_stats=? WHERE id=?", (json.dumps(stats), upload_id))

    def latest_upload_id(self) -> int | None:
        with self._conn() as c:
            row = c.execute("SELECT MAX(id) AS m FROM uploads").fetchone()
        return row["m"]

    def get_upload(self, upload_id: int) -> dict | None:
        with self._conn() as c:
            row = c.execute("SELECT * FROM uploads WHERE id=?", (upload_id,)).fetchone()
        if not row:
            return None
        d = dict(row)
        d["run_stats"] = json.loads(d["run_stats"] or "{}")
        return d

    def get_reviews(self, upload_id: int) -> list[dict]:
        with self._conn() as c:
            rows = c.execute(_JOIN + " WHERE r.upload_id=? ORDER BY r.id", (upload_id,)).fetchall()
        return [_review_row(r) for r in rows]

    def get_review(self, row_id: int) -> dict | None:
        with self._conn() as c:
            row = c.execute(_JOIN + " WHERE r.id=?", (row_id,)).fetchone()
        return _review_row(row) if row else None

    def save_reply(self, row_id: int, reply: str):
        with self._conn() as c:
            c.execute("UPDATE reviews SET suggested_reply=? WHERE id=?", (reply, row_id))
