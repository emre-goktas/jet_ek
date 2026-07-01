import sqlite3
import threading
from pathlib import Path
from typing import Optional, Dict, Any

# Find the storage directory to keep the temporary database in the same place
STORAGE_DIR = Path(__file__).parent / "storage"
STORAGE_DIR.mkdir(exist_ok=True)
DB_PATH = STORAGE_DIR / "tasks.db"

# Thread-local storage for sqlite connections since same-thread connections are safer.
_local = threading.local()

def get_db_connection():
    """Returns a database connection for the current thread."""
    if not hasattr(_local, "conn"):
        # check_same_thread=False allows sharing but thread-local is safer for sqlite.
        # It's okay to just use thread-locals for Fastapi's sync endpoints or asyncio threadpool.
        conn = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=15.0)
        conn.row_factory = sqlite3.Row
        _local.conn = conn
    return _local.conn

def init_db():
    """Creates all tables and required initial state."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS ocr_tasks (
            task_id TEXT PRIMARY KEY,
            status TEXT NOT NULL,
            pdf_id TEXT,
            page_count INTEGER,
            filename TEXT,
            label TEXT,
            error_message TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.commit()

def cleanup_orphan_tasks():
    """Cleans up hanging tasks stuck in 'processing' state when the server restarts."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        UPDATE ocr_tasks 
        SET status = 'failed', error_message = 'Server was restarted unexpectedly.' 
        WHERE status = 'processing'
    ''')
    conn.commit()

def create_task(task_id: str, filename: str, label: str = ""):
    """Creates a new OCR task."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO ocr_tasks (task_id, status, filename, label) VALUES (?, 'processing', ?, ?)", 
        (task_id, filename, label)
    )
    conn.commit()

def update_task_success(task_id: str, pdf_id: str, page_count: int, filename: str):
    """Updates the task status when successful."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        UPDATE ocr_tasks 
        SET status = 'done', pdf_id = ?, page_count = ?, filename = ?
        WHERE task_id = ?
    ''', (pdf_id, page_count, filename, task_id))
    conn.commit()

def update_task_failure(task_id: str, error_message: str):
    """Updates the task status when failed."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        UPDATE ocr_tasks 
        SET status = 'failed', error_message = ?
        WHERE task_id = ?
    ''', (error_message, task_id))
    conn.commit()

def get_task(task_id: str) -> Optional[Dict[str, Any]]:
    """Returns the current status of the task."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM ocr_tasks WHERE task_id = ?", (task_id,))
    row = cursor.fetchone()
    if row:
        return dict(row)
    return None

