"""
SQLite persistence for user profiles + lightweight usage analytics.

Plain stdlib sqlite3, no ORM — the schema is two tables, an ORM would be
more machinery than the problem needs. One connection per call (SQLite
handles concurrent readers fine; writes are rare here — a handful of
profile edits and analytics events, not the document-processing hot path).
"""
import json
import sqlite3
from pathlib import Path
from contextlib import contextmanager
from datetime import datetime, timezone

DB_PATH = Path(__file__).parent.parent / "data" / "jetek.db"

VALID_TEMPLATE_IDS = {"sgk", "saglik_bakanligi", "sgk_denetmen", "duz_tablo", "duz_tablo_excel"}


def _init_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                email TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                title TEXT,
                template_id TEXT NOT NULL,
                il TEXT,
                kvkk_consent_at TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        # Migration for DBs created before kvkk_consent_at existed — ALTER TABLE
        # ADD COLUMN is a no-op-safe way to bring an older users table up to date
        # without a full migration framework for a single nullable column.
        existing_cols = {row[1] for row in conn.execute("PRAGMA table_info(users)")}
        if "kvkk_consent_at" not in existing_cols:
            conn.execute("ALTER TABLE users ADD COLUMN kvkk_consent_at TEXT")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS usage_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_email TEXT NOT NULL,
                event_type TEXT NOT NULL,
                metadata TEXT,
                created_at TEXT NOT NULL
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_usage_events_email ON usage_events(user_email)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_usage_events_type ON usage_events(event_type)")
        # Dedicated table (rather than folding into usage_events) since every row has
        # the same well-known shape — per-file rename outcome + how long Gemini took —
        # and a fixed schema makes "kaç dosyaya isim vermiş / ne kadar sürede" queries
        # a plain SELECT instead of a JSON-metadata dig.
        conn.execute("""
            CREATE TABLE IF NOT EXISTS ai_rename_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_email TEXT NOT NULL,
                file_id TEXT NOT NULL,
                original_name TEXT,
                new_name TEXT,
                success INTEGER NOT NULL,
                error_message TEXT,
                duration_ms INTEGER,
                batch_size INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_ai_rename_logs_email ON ai_rename_logs(user_email)")
        # Client-reported performance/bottleneck metrics (upload, ZIP packaging,
        # single-file download) — a dedicated table with a fixed shape, same
        # rationale as ai_rename_logs above: plain SELECTs/aggregates instead
        # of digging through usage_events' free-form JSON metadata.
        conn.execute("""
            CREATE TABLE IF NOT EXISTS performance_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_email TEXT NOT NULL,
                operation TEXT NOT NULL,
                page_count INTEGER,
                batch_count INTEGER,
                file_size_bytes INTEGER,
                duration_ms INTEGER,
                success INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_performance_logs_email ON performance_logs(user_email)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_performance_logs_operation ON performance_logs(operation)")


_init_db()


@contextmanager
def _connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_profile(email: str) -> dict | None:
    with _connect() as conn:
        row = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
        return dict(row) if row else None


def upsert_profile(email: str, name: str, title: str, template_id: str, il: str | None, consent_given: bool = False) -> dict:
    if template_id not in VALID_TEMPLATE_IDS:
        raise ValueError(f"Unknown template_id: {template_id}")

    now = _now()
    with _connect() as conn:
        existing = conn.execute("SELECT created_at, kvkk_consent_at FROM users WHERE email = ?", (email,)).fetchone()
        created_at = existing["created_at"] if existing else now
        # Once recorded, a consent timestamp is never cleared or overwritten by a
        # later profile edit that doesn't re-send consent — the checkboxes only
        # render (and consent_given can only be True) on the first save, or a
        # future save if it was somehow never recorded. See profile.py's
        # needs_consent check, which is what actually gates this being required.
        existing_consent_at = existing["kvkk_consent_at"] if existing else None
        consent_at = existing_consent_at or (now if consent_given else None)
        conn.execute(
            """
            INSERT INTO users (email, name, title, template_id, il, kvkk_consent_at, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(email) DO UPDATE SET
                name=excluded.name, title=excluded.title, template_id=excluded.template_id,
                il=excluded.il, kvkk_consent_at=excluded.kvkk_consent_at, updated_at=excluded.updated_at
            """,
            (email, name, title, template_id, il, consent_at, created_at, now),
        )
    return get_profile(email)


def log_event(user_email: str, event_type: str, metadata: dict | None = None) -> None:
    """Best-effort: a failure here should never break the caller's actual
    request, so callers should wrap this in a try/except (or use log_event_safe)."""
    with _connect() as conn:
        conn.execute(
            "INSERT INTO usage_events (user_email, event_type, metadata, created_at) VALUES (?, ?, ?, ?)",
            (user_email, event_type, json.dumps(metadata or {}, ensure_ascii=False), _now()),
        )


def log_event_safe(user_email: str, event_type: str, metadata: dict | None = None) -> None:
    try:
        log_event(user_email, event_type, metadata)
    except Exception:
        import logging
        logging.getLogger(__name__).warning("Failed to log usage event %s for %s", event_type, user_email, exc_info=True)


def log_gemini_rename(
    user_email: str,
    file_id: str,
    original_name: str | None,
    new_name: str | None,
    success: bool,
    error_message: str | None = None,
    duration_ms: int | None = None,
    batch_size: int = 1,
) -> None:
    """One row per AI-rename attempt (single or batch — batch_size > 1 marks
    which). duration_ms is the Gemini round-trip time (upload + generate),
    not local disk I/O, so it reflects what the user actually waited for
    after clicking "Adlandır"."""
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO ai_rename_logs
                (user_email, file_id, original_name, new_name, success, error_message, duration_ms, batch_size, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (user_email, file_id, original_name, new_name, 1 if success else 0, error_message, duration_ms, batch_size, _now()),
        )


def log_gemini_rename_safe(*args, **kwargs) -> None:
    try:
        log_gemini_rename(*args, **kwargs)
    except Exception:
        import logging
        logging.getLogger(__name__).warning("Failed to log Gemini rename event", exc_info=True)


def log_performance(
    user_email: str,
    operation: str,
    page_count: int | None = None,
    batch_count: int | None = None,
    file_size_bytes: int | None = None,
    duration_ms: int | None = None,
    success: bool = True,
) -> None:
    """One row per client-measured operation (upload / download_zip /
    download_single) — see frontend/static/js/document-builder.js's
    logPerformance(). Client-reported like usage_events, so treat the numbers
    as indicative (subject to the reporting browser's own clock/network),
    not an audited server-side measurement."""
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO performance_logs
                (user_email, operation, page_count, batch_count, file_size_bytes, duration_ms, success, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (user_email, operation, page_count, batch_count, file_size_bytes, duration_ms, 1 if success else 0, _now()),
        )


def log_performance_safe(*args, **kwargs) -> None:
    try:
        log_performance(*args, **kwargs)
    except Exception:
        import logging
        logging.getLogger(__name__).warning("Failed to log performance event", exc_info=True)


# ─── Admin metrics: read-only query helpers for backend/routers/admin.py ────

def list_usage_events(limit: int = 200) -> list[dict]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM usage_events ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]


def list_ai_rename_logs(limit: int = 200) -> list[dict]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM ai_rename_logs ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]


def list_performance_logs(limit: int = 200) -> list[dict]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM performance_logs ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]


def performance_summary() -> list[dict]:
    """One row per operation: count, success rate, and average/max duration —
    the "which action is slow / where's the bottleneck" view, computed in SQL
    rather than pulled client-side so it stays correct regardless of the
    admin page's row limit."""
    with _connect() as conn:
        rows = conn.execute("""
            SELECT
                operation,
                COUNT(*) AS count,
                SUM(success) AS success_count,
                AVG(duration_ms) AS avg_duration_ms,
                MAX(duration_ms) AS max_duration_ms,
                AVG(page_count) AS avg_page_count,
                AVG(file_size_bytes) AS avg_file_size_bytes
            FROM performance_logs
            GROUP BY operation
            ORDER BY count DESC
        """).fetchall()
        return [dict(r) for r in rows]


ALL_TABLES = {
    "usage_events": "SELECT * FROM usage_events ORDER BY id DESC",
    "ai_rename_logs": "SELECT * FROM ai_rename_logs ORDER BY id DESC",
    "performance_logs": "SELECT * FROM performance_logs ORDER BY id DESC",
}


def export_table_rows(table: str) -> list[dict]:
    """table must be a key of ALL_TABLES — callers (admin.py) validate against
    that allowlist before calling this, so the query string here is never
    built from unvalidated user input."""
    query = ALL_TABLES[table]
    with _connect() as conn:
        rows = conn.execute(query).fetchall()
        return [dict(r) for r in rows]
