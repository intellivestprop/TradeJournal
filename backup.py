"""
Backup and export utilities.
Supports SQLite backup and CSV export.
"""

import csv
import io
import os
import shutil
from datetime import datetime
from pathlib import Path

from database import DB_PATH, get_connection

BACKUP_DIR = os.environ.get("TJ_BACKUP_DIR", str(Path(__file__).parent / "data" / "backups"))


def backup_database() -> str:
    """Create a timestamped copy of the SQLite database. Returns the backup path."""
    os.makedirs(BACKUP_DIR, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = os.path.join(BACKUP_DIR, f"trade_journal_backup_{ts}.db")
    shutil.copy2(DB_PATH, backup_path)
    return backup_path


def export_trades_csv() -> str:
    """Export all trades to CSV. Returns CSV as a string."""
    conn = get_connection()
    trades = conn.execute("""
        SELECT t.*, r.setup_class, r.manual_tags_json, r.comment,
               r.emotion_json, r.lesson_learned, r.execution_score,
               r.market_regime_note, r.confidence_rating, r.mistake_narrative,
               r.would_take_again, r.qqq_ema_note, r.symbol_ema_note, r.tq_tickq_note
        FROM trades t
        LEFT JOIN trade_reviews r ON t.id = r.trade_id
        ORDER BY t.entry_datetime DESC
    """).fetchall()
    conn.close()

    if not trades:
        return ""

    output = io.StringIO()
    writer = csv.writer(output)

    # Header
    cols = trades[0].keys()
    writer.writerow(cols)

    # Data
    for t in trades:
        writer.writerow([t[c] for c in cols])

    return output.getvalue()


def list_backups() -> list[dict]:
    """List existing backups."""
    if not os.path.exists(BACKUP_DIR):
        return []

    backups = []
    for f in sorted(os.listdir(BACKUP_DIR), reverse=True):
        if f.endswith(".db"):
            path = os.path.join(BACKUP_DIR, f)
            stat = os.stat(path)
            backups.append({
                "filename": f,
                "path": path,
                "size_mb": round(stat.st_size / 1048576, 2),
                "created": datetime.fromtimestamp(stat.st_ctime).strftime("%Y-%m-%d %H:%M"),
            })
    return backups


def get_database_path() -> str:
    """Return the current database file path."""
    return DB_PATH
