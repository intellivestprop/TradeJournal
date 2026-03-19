"""
Database schema and connection management for the Trade Journal.
SQLite-based, single-user, local-first storage.
"""

import sqlite3
import os
from pathlib import Path

DB_PATH = os.environ.get("TJ_DB_PATH", str(Path(__file__).parent / "data" / "trade_journal.db"))


def get_connection() -> sqlite3.Connection:
    """Get a SQLite connection with WAL mode and foreign keys enabled."""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    """Create all tables if they don't exist."""
    conn = get_connection()
    cur = conn.cursor()

    cur.executescript("""
    CREATE TABLE IF NOT EXISTS imports (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        source_type TEXT NOT NULL DEFAULT 'ibkr_flex',
        query_id TEXT,
        import_started_at TEXT NOT NULL,
        import_finished_at TEXT,
        status TEXT NOT NULL DEFAULT 'pending',
        report_reference TEXT,
        raw_file_path TEXT,
        checksum TEXT,
        error_message TEXT
    );

    CREATE UNIQUE INDEX IF NOT EXISTS idx_imports_checksum
        ON imports(checksum) WHERE checksum IS NOT NULL;

    CREATE TABLE IF NOT EXISTS fills (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        import_id INTEGER NOT NULL REFERENCES imports(id),
        broker_account_id TEXT,
        broker_account_name TEXT,
        broker_execution_id TEXT,
        broker_order_id TEXT,
        symbol TEXT NOT NULL,
        underlying_symbol TEXT,
        security_type TEXT NOT NULL DEFAULT 'STK',
        side TEXT NOT NULL,
        quantity REAL NOT NULL,
        price REAL NOT NULL,
        execution_timestamp TEXT NOT NULL,
        commission REAL DEFAULT 0,
        fees REAL DEFAULT 0,
        currency TEXT DEFAULT 'USD',
        exchange TEXT,
        raw_payload_json TEXT
    );

    CREATE UNIQUE INDEX IF NOT EXISTS idx_fills_exec_id
        ON fills(broker_execution_id) WHERE broker_execution_id IS NOT NULL;

    CREATE TABLE IF NOT EXISTS trades (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        trade_code TEXT UNIQUE NOT NULL,
        broker_account_id TEXT,
        broker_account_name TEXT,
        trade_type TEXT NOT NULL DEFAULT 'stock',
        strategy_type TEXT,
        setup_type TEXT,
        symbol TEXT NOT NULL,
        underlying_symbol TEXT,
        direction TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'open',
        entry_datetime TEXT,
        exit_datetime TEXT,
        entry_price_avg REAL,
        exit_price_avg REAL,
        quantity_or_contracts REAL,
        gross_pnl REAL,
        net_pnl REAL,
        total_fees REAL DEFAULT 0,
        holding_minutes INTEGER,
        holding_days REAL,
        same_day_trade_flag INTEGER DEFAULT 0,
        partial_exit_flag INTEGER DEFAULT 0,
        scale_in_flag INTEGER DEFAULT 0,
        scale_out_flag INTEGER DEFAULT 0,
        manual_review_required INTEGER DEFAULT 0,
        review_status TEXT NOT NULL DEFAULT 'pending',
        created_at TEXT NOT NULL DEFAULT (datetime('now')),
        updated_at TEXT NOT NULL DEFAULT (datetime('now'))
    );

    CREATE INDEX IF NOT EXISTS idx_trades_symbol ON trades(symbol);
    CREATE INDEX IF NOT EXISTS idx_trades_status ON trades(status);
    CREATE INDEX IF NOT EXISTS idx_trades_review ON trades(review_status);
    CREATE INDEX IF NOT EXISTS idx_trades_account ON trades(broker_account_id);

    CREATE TABLE IF NOT EXISTS trade_fills (
        trade_id INTEGER NOT NULL REFERENCES trades(id),
        fill_id INTEGER NOT NULL REFERENCES fills(id),
        role TEXT NOT NULL DEFAULT 'open',
        PRIMARY KEY (trade_id, fill_id)
    );

    CREATE TABLE IF NOT EXISTS trade_legs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        trade_id INTEGER NOT NULL REFERENCES trades(id),
        leg_index INTEGER NOT NULL,
        option_type TEXT,
        side TEXT,
        strike REAL,
        expiry TEXT,
        contracts REAL,
        open_price_avg REAL,
        close_price_avg REAL,
        multiplier REAL DEFAULT 100,
        assigned_flag INTEGER DEFAULT 0,
        exercised_flag INTEGER DEFAULT 0,
        expired_flag INTEGER DEFAULT 0
    );

    CREATE TABLE IF NOT EXISTS trade_options_summary (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        trade_id INTEGER UNIQUE NOT NULL REFERENCES trades(id),
        expiry TEXT,
        dte_at_entry INTEGER,
        dte_at_exit INTEGER,
        net_debit_credit REAL,
        spread_width REAL,
        max_profit REAL,
        max_loss REAL,
        breakeven REAL
    );

    CREATE TABLE IF NOT EXISTS trade_reviews (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        trade_id INTEGER UNIQUE NOT NULL REFERENCES trades(id),
        setup_class TEXT,
        setup_type TEXT,
        manual_tags_json TEXT,
        comment TEXT,
        emotion_json TEXT,
        lesson_learned TEXT,
        execution_score INTEGER,
        market_regime_note TEXT,
        confidence_rating INTEGER,
        mistake_narrative TEXT,
        would_take_again TEXT,
        qqq_ema_note TEXT,
        symbol_ema_note TEXT,
        tq_tickq_note TEXT,
        reviewed_at TEXT
    );

    CREATE TABLE IF NOT EXISTS setup_types (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE NOT NULL,
        created_at TEXT NOT NULL DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS accounts (
        broker_account_id TEXT PRIMARY KEY,
        alias TEXT,
        first_seen_at TEXT NOT NULL DEFAULT (datetime('now')),
        last_seen_at TEXT NOT NULL DEFAULT (datetime('now'))
    );
    """)

    # Seed default setup types
    defaults = ["Episodic Pivot", "Breakout", "Pullback", "Parabolic Long", "Parabolic Short"]
    for st in defaults:
        cur.execute("INSERT OR IGNORE INTO setup_types (name) VALUES (?)", (st,))

    conn.commit()
    conn.close()


if __name__ == "__main__":
    init_db()
    print(f"Database initialized at {DB_PATH}")
