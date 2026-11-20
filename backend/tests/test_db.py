import sqlite3

from app.db import Database, LEGACY_PROMPT_VERSION


def test_legacy_cache_migration_preserves_upload_review_and_analysis(tmp_path):
    path = tmp_path / "legacy.db"
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE analyses (
            text_hash TEXT PRIMARY KEY, sentiment TEXT NOT NULL, topics TEXT NOT NULL,
            summary TEXT NOT NULL, needs_reply INTEGER NOT NULL, model TEXT, created_at TEXT NOT NULL
        );
        CREATE TABLE uploads (
            id INTEGER PRIMARY KEY AUTOINCREMENT, filename TEXT, created_at TEXT NOT NULL, run_stats TEXT
        );
        CREATE TABLE reviews (
            id INTEGER PRIMARY KEY AUTOINCREMENT, upload_id INTEGER NOT NULL, review_id TEXT,
            product TEXT, rating_raw TEXT, rating INTEGER, text TEXT, text_hash TEXT,
            status TEXT NOT NULL, duplicate_of TEXT, issues TEXT, suggested_reply TEXT
        );
        INSERT INTO analyses VALUES (
            'legacy-hash', 'negative', '["quality"]', 'Legacy cached result.', 1,
            'model-a', '2026-01-01T00:00:00+00:00'
        );
        INSERT INTO uploads VALUES (1, 'old.csv', '2026-01-01T00:00:00+00:00', '{}');
        INSERT INTO reviews VALUES (
            1, 1, 'OLD-1', 'Product', '1', 1, 'legacy review', 'legacy-hash',
            'analyzed', NULL, '[]', NULL
        );
        """
    )
    conn.commit()
    conn.close()

    db = Database(str(path))

    assert db.get_upload(1)["filename"] == "old.csv"
    review = db.get_reviews(1)[0]
    assert review["review_id"] == "OLD-1"
    assert review["summary"] == "Legacy cached result."
    assert review["needs_reply"] is True
    assert "analysis_model" not in review
    assert "analysis_prompt_version" not in review
    assert db.get_analyses(["legacy-hash"], "model-a", "1") == {}
    assert db.get_analyses(["legacy-hash"], "model-a", LEGACY_PROMPT_VERSION) == {
        "legacy-hash": {
            "sentiment": "negative",
            "topics": ["quality"],
            "summary": "Legacy cached result.",
            "needs_reply": True,
        }
    }
