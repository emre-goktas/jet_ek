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
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
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


def upsert_profile(email: str, name: str, title: str, template_id: str, il: str | None) -> dict:
    if template_id not in VALID_TEMPLATE_IDS:
        raise ValueError(f"Unknown template_id: {template_id}")

    now = _now()
    with _connect() as conn:
        existing = conn.execute("SELECT created_at FROM users WHERE email = ?", (email,)).fetchone()
        created_at = existing["created_at"] if existing else now
        conn.execute(
            """
            INSERT INTO users (email, name, title, template_id, il, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(email) DO UPDATE SET
                name=excluded.name, title=excluded.title, template_id=excluded.template_id,
                il=excluded.il, updated_at=excluded.updated_at
            """,
            (email, name, title, template_id, il, created_at, now),
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
