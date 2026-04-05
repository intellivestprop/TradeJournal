"""
Database schema and migration management for the Trade Journal.
SQLite-based, single-user, local-first storage.
"""

from __future__ import annotations

import argparse
import os
import sqlite3
from pathlib import Path

DB_PATH = os.environ.get("TJ_DB_PATH", str(Path(__file__).parent / "data" / "trade_journal.db"))
SCHEMA_VERSION = 1

BASE_SCHEMA_SQL = """
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
    conid TEXT,
    broker_execution_id TEXT,
    broker_order_id TEXT,
    order_reference TEXT,
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

CREATE TABLE IF NOT EXISTS statement_open_positions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    import_id INTEGER REFERENCES imports(id),
    report_date TEXT NOT NULL,
    broker_account_id TEXT NOT NULL,
    broker_account_name TEXT,
    instrument_key TEXT NOT NULL,
    conid TEXT,
    symbol TEXT NOT NULL,
    underlying_symbol TEXT,
    security_type TEXT NOT NULL DEFAULT 'STK',
    quantity_eod REAL NOT NULL,
    mark_price REAL,
    position_value REAL,
    currency TEXT DEFAULT 'USD',
    raw_payload_json TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_statement_open_positions_unique
    ON statement_open_positions(report_date, broker_account_id, instrument_key);

CREATE TABLE IF NOT EXISTS reconciliation_exceptions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    report_date TEXT,
    broker_account_id TEXT NOT NULL,
    instrument_key TEXT,
    conid TEXT,
    exception_code TEXT NOT NULL,
    note TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
"""

DERIVED_TABLES_SQL = """
CREATE TABLE IF NOT EXISTS pos_eod_from_trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    report_date TEXT NOT NULL,
    broker_account_id TEXT NOT NULL,
    broker_account_name TEXT,
    instrument_key TEXT NOT NULL,
    conid TEXT,
    symbol TEXT NOT NULL,
    underlying_symbol TEXT,
    security_type TEXT NOT NULL DEFAULT 'STK',
    quantity_eod REAL NOT NULL,
    last_fill_timestamp TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_pos_eod_from_trades_unique
    ON pos_eod_from_trades(report_date, broker_account_id, instrument_key);

CREATE TABLE IF NOT EXISTS position_reconciliation (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    report_date TEXT NOT NULL,
    broker_account_id TEXT NOT NULL,
    broker_account_name TEXT,
    instrument_key TEXT NOT NULL,
    conid TEXT,
    symbol TEXT NOT NULL,
    underlying_symbol TEXT,
    security_type TEXT NOT NULL DEFAULT 'STK',
    trade_quantity_eod REAL NOT NULL DEFAULT 0,
    statement_quantity_eod REAL NOT NULL DEFAULT 0,
    quantity_diff REAL NOT NULL DEFAULT 0,
    status TEXT NOT NULL,
    exception_code TEXT,
    exception_note TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_position_reconciliation_unique
    ON position_reconciliation(report_date, broker_account_id, instrument_key);

CREATE TABLE IF NOT EXISTS opt_strategy (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    strategy_key TEXT NOT NULL UNIQUE,
    grouping_method TEXT NOT NULL,
    broker_account_id TEXT NOT NULL,
    broker_account_name TEXT,
    underlying_symbol TEXT NOT NULL,
    order_reference TEXT,
    fallback_order_id TEXT,
    fallback_close_timestamp TEXT,
    opened_at TEXT NOT NULL,
    closed_at TEXT NOT NULL,
    leg_count INTEGER NOT NULL DEFAULT 0,
    total_contracts REAL NOT NULL DEFAULT 0,
    net_premium REAL NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_opt_strategy_account
    ON opt_strategy(broker_account_id, underlying_symbol, closed_at);

CREATE TABLE IF NOT EXISTS opt_strategy_leg (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    strategy_id INTEGER NOT NULL REFERENCES opt_strategy(id) ON DELETE CASCADE,
    fill_id INTEGER NOT NULL UNIQUE REFERENCES fills(id) ON DELETE CASCADE,
    leg_index INTEGER NOT NULL,
    broker_order_id TEXT,
    order_reference TEXT,
    symbol TEXT NOT NULL,
    underlying_symbol TEXT NOT NULL,
    option_type TEXT,
    side TEXT NOT NULL,
    strike REAL,
    expiry TEXT,
    quantity REAL NOT NULL,
    price REAL NOT NULL,
    execution_timestamp TEXT NOT NULL,
    raw_payload_json TEXT
);

CREATE INDEX IF NOT EXISTS idx_opt_strategy_leg_strategy
    ON opt_strategy_leg(strategy_id, leg_index);

CREATE TABLE IF NOT EXISTS opt_campaign (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    campaign_key TEXT NOT NULL UNIQUE,
    broker_account_id TEXT NOT NULL,
    broker_account_name TEXT,
    underlying_symbol TEXT NOT NULL,
    option_type TEXT NOT NULL,
    side TEXT NOT NULL,
    opened_at TEXT NOT NULL,
    closed_at TEXT,
    status TEXT NOT NULL DEFAULT 'open',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_opt_campaign_signature
    ON opt_campaign(broker_account_id, underlying_symbol, option_type, side, opened_at);

CREATE TABLE IF NOT EXISTS opt_campaign_event (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    campaign_id INTEGER NOT NULL REFERENCES opt_campaign(id) ON DELETE CASCADE,
    strategy_id INTEGER NOT NULL REFERENCES opt_strategy(id) ON DELETE CASCADE,
    option_type TEXT NOT NULL,
    event_index INTEGER NOT NULL,
    event_timestamp TEXT NOT NULL,
    event_side TEXT NOT NULL,
    delta_contracts REAL NOT NULL,
    event_contracts REAL NOT NULL,
    event_primary_strike REAL,
    event_net_cash_flow REAL NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_opt_campaign_event_unique
    ON opt_campaign_event(campaign_id, strategy_id, option_type);

CREATE TABLE IF NOT EXISTS opt_campaign_event_leg (
    event_id INTEGER NOT NULL REFERENCES opt_campaign_event(id) ON DELETE CASCADE,
    strategy_leg_id INTEGER NOT NULL UNIQUE REFERENCES opt_strategy_leg(id) ON DELETE CASCADE,
    PRIMARY KEY (event_id, strategy_leg_id)
);
"""

VIEWS_SQL = """
DROP VIEW IF EXISTS v_opt_strategy_leg_stats;
CREATE VIEW v_opt_strategy_leg_stats AS
SELECT
    s.id AS strategy_id,
    s.strategy_key,
    s.grouping_method,
    s.broker_account_id,
    s.broker_account_name,
    s.underlying_symbol,
    s.order_reference,
    s.fallback_order_id,
    s.fallback_close_timestamp,
    s.opened_at,
    s.closed_at,
    COUNT(l.id) AS leg_count,
    SUM(l.quantity) AS total_contracts,
    ROUND(SUM(CASE WHEN l.side = 'BUY' THEN l.price * l.quantity ELSE -l.price * l.quantity END), 8) AS net_premium,
    SUM(CASE WHEN l.option_type = 'call' THEN 1 ELSE 0 END) AS call_legs,
    SUM(CASE WHEN l.option_type = 'put' THEN 1 ELSE 0 END) AS put_legs,
    SUM(CASE WHEN l.side = 'BUY' THEN 1 ELSE 0 END) AS buy_legs,
    SUM(CASE WHEN l.side = 'SELL' THEN 1 ELSE 0 END) AS sell_legs,
    SUM(CASE WHEN l.option_type = 'call' AND l.side = 'BUY' THEN 1 ELSE 0 END) AS long_call_legs,
    SUM(CASE WHEN l.option_type = 'call' AND l.side = 'SELL' THEN 1 ELSE 0 END) AS short_call_legs,
    SUM(CASE WHEN l.option_type = 'put' AND l.side = 'BUY' THEN 1 ELSE 0 END) AS long_put_legs,
    SUM(CASE WHEN l.option_type = 'put' AND l.side = 'SELL' THEN 1 ELSE 0 END) AS short_put_legs,
    SUM(CASE WHEN l.option_type = 'call' AND l.side = 'BUY' THEN l.quantity ELSE 0 END) AS long_call_contracts,
    SUM(CASE WHEN l.option_type = 'call' AND l.side = 'SELL' THEN l.quantity ELSE 0 END) AS short_call_contracts,
    SUM(CASE WHEN l.option_type = 'put' AND l.side = 'BUY' THEN l.quantity ELSE 0 END) AS long_put_contracts,
    SUM(CASE WHEN l.option_type = 'put' AND l.side = 'SELL' THEN l.quantity ELSE 0 END) AS short_put_contracts,
    COUNT(DISTINCT COALESCE(l.expiry, '')) AS expiry_count,
    COUNT(DISTINCT COALESCE(l.option_type, '')) AS option_type_count,
    COUNT(DISTINCT CASE WHEN l.option_type = 'call' THEN l.strike END) AS distinct_call_strikes,
    COUNT(DISTINCT CASE WHEN l.option_type = 'put' THEN l.strike END) AS distinct_put_strikes,
    MIN(CASE WHEN l.option_type = 'call' THEN l.strike END) AS min_call_strike,
    MAX(CASE WHEN l.option_type = 'call' THEN l.strike END) AS max_call_strike,
    MIN(CASE WHEN l.option_type = 'put' THEN l.strike END) AS min_put_strike,
    MAX(CASE WHEN l.option_type = 'put' THEN l.strike END) AS max_put_strike
FROM opt_strategy s
JOIN opt_strategy_leg l ON l.strategy_id = s.id
GROUP BY s.id;

DROP VIEW IF EXISTS v_opt_strategy_classified;
CREATE VIEW v_opt_strategy_classified AS
WITH strike_levels AS (
    SELECT
        strategy_id,
        option_type,
        strike,
        ROUND(SUM(CASE WHEN side = 'BUY' THEN quantity ELSE 0 END), 8) AS buy_qty,
        ROUND(SUM(CASE WHEN side = 'SELL' THEN quantity ELSE 0 END), 8) AS sell_qty,
        ROW_NUMBER() OVER (PARTITION BY strategy_id, option_type ORDER BY strike) AS strike_rank
    FROM opt_strategy_leg
    WHERE strike IS NOT NULL
      AND option_type IN ('call', 'put')
    GROUP BY strategy_id, option_type, strike
),
call_levels AS (
    SELECT
        strategy_id,
        COUNT(*) AS call_strike_levels,
        MAX(CASE WHEN strike_rank = 1 THEN strike END) AS call_strike_1,
        MAX(CASE WHEN strike_rank = 2 THEN strike END) AS call_strike_2,
        MAX(CASE WHEN strike_rank = 3 THEN strike END) AS call_strike_3,
        MAX(CASE WHEN strike_rank = 4 THEN strike END) AS call_strike_4,
        MAX(CASE WHEN strike_rank = 1 THEN buy_qty END) AS call_buy_qty_1,
        MAX(CASE WHEN strike_rank = 2 THEN buy_qty END) AS call_buy_qty_2,
        MAX(CASE WHEN strike_rank = 3 THEN buy_qty END) AS call_buy_qty_3,
        MAX(CASE WHEN strike_rank = 4 THEN buy_qty END) AS call_buy_qty_4,
        MAX(CASE WHEN strike_rank = 1 THEN sell_qty END) AS call_sell_qty_1,
        MAX(CASE WHEN strike_rank = 2 THEN sell_qty END) AS call_sell_qty_2,
        MAX(CASE WHEN strike_rank = 3 THEN sell_qty END) AS call_sell_qty_3,
        MAX(CASE WHEN strike_rank = 4 THEN sell_qty END) AS call_sell_qty_4
    FROM strike_levels
    WHERE option_type = 'call'
    GROUP BY strategy_id
),
put_levels AS (
    SELECT
        strategy_id,
        COUNT(*) AS put_strike_levels,
        MAX(CASE WHEN strike_rank = 1 THEN strike END) AS put_strike_1,
        MAX(CASE WHEN strike_rank = 2 THEN strike END) AS put_strike_2,
        MAX(CASE WHEN strike_rank = 3 THEN strike END) AS put_strike_3,
        MAX(CASE WHEN strike_rank = 4 THEN strike END) AS put_strike_4,
        MAX(CASE WHEN strike_rank = 1 THEN buy_qty END) AS put_buy_qty_1,
        MAX(CASE WHEN strike_rank = 2 THEN buy_qty END) AS put_buy_qty_2,
        MAX(CASE WHEN strike_rank = 3 THEN buy_qty END) AS put_buy_qty_3,
        MAX(CASE WHEN strike_rank = 4 THEN buy_qty END) AS put_buy_qty_4,
        MAX(CASE WHEN strike_rank = 1 THEN sell_qty END) AS put_sell_qty_1,
        MAX(CASE WHEN strike_rank = 2 THEN sell_qty END) AS put_sell_qty_2,
        MAX(CASE WHEN strike_rank = 3 THEN sell_qty END) AS put_sell_qty_3,
        MAX(CASE WHEN strike_rank = 4 THEN sell_qty END) AS put_sell_qty_4
    FROM strike_levels
    WHERE option_type = 'put'
    GROUP BY strategy_id
)
SELECT
    stats.*,
    CASE
        WHEN stats.leg_count = 1 AND stats.long_call_legs = 1 THEN 'Long Call'
        WHEN stats.leg_count = 1 AND stats.short_call_legs = 1 THEN 'Short Call'
        WHEN stats.leg_count = 1 AND stats.long_put_legs = 1 THEN 'Long Put'
        WHEN stats.leg_count = 1 AND stats.short_put_legs = 1 THEN 'Short Put'
        WHEN stats.leg_count = 2
             AND stats.call_legs = 1
             AND stats.put_legs = 1
             AND stats.expiry_count = 1
             AND stats.long_put_legs = 1
             AND stats.short_call_legs = 1
             AND ABS(stats.long_put_contracts - stats.short_call_contracts) < 0.000001
             THEN 'Collar'
        WHEN stats.leg_count = 2
             AND stats.call_legs = 2
             AND stats.expiry_count = 2
             AND stats.long_call_legs = 1
             AND stats.short_call_legs = 1
             AND ABS(stats.long_call_contracts - stats.short_call_contracts) < 0.000001
             THEN CASE
                 WHEN stats.min_call_strike = stats.max_call_strike THEN 'Call Calendar'
                 ELSE 'Call Diagonal'
             END
        WHEN stats.leg_count = 2
             AND stats.put_legs = 2
             AND stats.expiry_count = 2
             AND stats.long_put_legs = 1
             AND stats.short_put_legs = 1
             AND ABS(stats.long_put_contracts - stats.short_put_contracts) < 0.000001
             THEN CASE
                 WHEN stats.min_put_strike = stats.max_put_strike THEN 'Put Calendar'
                 ELSE 'Put Diagonal'
             END
        WHEN stats.leg_count = 2
             AND stats.call_legs = 2
             AND stats.expiry_count = 1
             AND stats.long_call_legs = 1
             AND stats.short_call_legs = 1
             AND stats.min_call_strike IS NOT NULL
             AND stats.max_call_strike IS NOT NULL
             AND stats.min_call_strike < stats.max_call_strike
             AND ABS(stats.long_call_contracts - stats.short_call_contracts) >= 0.000001
             THEN 'Call Ratio Spread'
        WHEN stats.leg_count = 2
             AND stats.put_legs = 2
             AND stats.expiry_count = 1
             AND stats.long_put_legs = 1
             AND stats.short_put_legs = 1
             AND stats.min_put_strike IS NOT NULL
             AND stats.max_put_strike IS NOT NULL
             AND stats.min_put_strike < stats.max_put_strike
             AND ABS(stats.long_put_contracts - stats.short_put_contracts) >= 0.000001
             THEN 'Put Ratio Spread'
        WHEN stats.leg_count = 2
             AND stats.call_legs = 2
             AND stats.expiry_count = 1
             AND stats.long_call_legs = 1
             AND stats.short_call_legs = 1
             AND stats.min_call_strike IS NOT NULL
             AND stats.max_call_strike IS NOT NULL
             AND stats.min_call_strike < stats.max_call_strike
             AND ABS(stats.long_call_contracts - stats.short_call_contracts) < 0.000001
             THEN CASE
                 WHEN stats.net_premium > 0 THEN 'Call Debit Spread'
                 ELSE 'Call Credit Spread'
             END
        WHEN stats.leg_count = 2
             AND stats.put_legs = 2
             AND stats.expiry_count = 1
             AND stats.long_put_legs = 1
             AND stats.short_put_legs = 1
             AND stats.min_put_strike IS NOT NULL
             AND stats.max_put_strike IS NOT NULL
             AND stats.min_put_strike < stats.max_put_strike
             AND ABS(stats.long_put_contracts - stats.short_put_contracts) < 0.000001
             THEN CASE
                 WHEN stats.net_premium > 0 THEN 'Put Debit Spread'
                 ELSE 'Put Credit Spread'
             END
        WHEN stats.leg_count = 3
             AND stats.expiry_count = 1
             AND stats.call_legs = 1
             AND stats.put_legs = 2
             AND stats.long_put_legs = 1
             AND stats.short_put_legs = 1
             AND stats.short_call_legs = 1
             AND ABS(stats.long_put_contracts - stats.short_put_contracts) < 0.000001
             AND ABS(stats.short_put_contracts - stats.short_call_contracts) < 0.000001
             AND stats.min_put_strike IS NOT NULL
             AND stats.max_put_strike IS NOT NULL
             AND stats.min_call_strike IS NOT NULL
             AND stats.min_put_strike < stats.max_put_strike
             AND stats.min_call_strike > stats.max_put_strike
             THEN 'Jade Lizard'
        WHEN stats.leg_count = 3
             AND stats.call_legs = 3
             AND stats.expiry_count = 1
             AND stats.distinct_call_strikes = 3
             AND COALESCE(call_levels.call_strike_levels, 0) = 3
             AND (
                 (
                     COALESCE(call_levels.call_buy_qty_1, 0) > 0
                     AND COALESCE(call_levels.call_sell_qty_2, 0) > 0
                     AND COALESCE(call_levels.call_buy_qty_3, 0) > 0
                     AND COALESCE(call_levels.call_sell_qty_1, 0) = 0
                     AND COALESCE(call_levels.call_buy_qty_2, 0) = 0
                     AND COALESCE(call_levels.call_sell_qty_3, 0) = 0
                     AND ABS(COALESCE(call_levels.call_buy_qty_1, 0) - COALESCE(call_levels.call_buy_qty_3, 0)) < 0.000001
                     AND ABS(COALESCE(call_levels.call_sell_qty_2, 0) - (COALESCE(call_levels.call_buy_qty_1, 0) + COALESCE(call_levels.call_buy_qty_3, 0))) < 0.000001
                 )
                 OR
                 (
                     COALESCE(call_levels.call_sell_qty_1, 0) > 0
                     AND COALESCE(call_levels.call_buy_qty_2, 0) > 0
                     AND COALESCE(call_levels.call_sell_qty_3, 0) > 0
                     AND COALESCE(call_levels.call_buy_qty_1, 0) = 0
                     AND COALESCE(call_levels.call_sell_qty_2, 0) = 0
                     AND COALESCE(call_levels.call_buy_qty_3, 0) = 0
                     AND ABS(COALESCE(call_levels.call_sell_qty_1, 0) - COALESCE(call_levels.call_sell_qty_3, 0)) < 0.000001
                     AND ABS(COALESCE(call_levels.call_buy_qty_2, 0) - (COALESCE(call_levels.call_sell_qty_1, 0) + COALESCE(call_levels.call_sell_qty_3, 0))) < 0.000001
                 )
             )
             THEN CASE
                 WHEN ABS(
                     (COALESCE(call_levels.call_strike_2, 0) - COALESCE(call_levels.call_strike_1, 0))
                     - (COALESCE(call_levels.call_strike_3, 0) - COALESCE(call_levels.call_strike_2, 0))
                 ) < 0.000001 THEN 'Call Butterfly'
                 ELSE 'Broken-Wing Call Butterfly'
             END
        WHEN stats.leg_count = 3
             AND stats.put_legs = 3
             AND stats.expiry_count = 1
             AND stats.distinct_put_strikes = 3
             AND COALESCE(put_levels.put_strike_levels, 0) = 3
             AND (
                 (
                     COALESCE(put_levels.put_buy_qty_1, 0) > 0
                     AND COALESCE(put_levels.put_sell_qty_2, 0) > 0
                     AND COALESCE(put_levels.put_buy_qty_3, 0) > 0
                     AND COALESCE(put_levels.put_sell_qty_1, 0) = 0
                     AND COALESCE(put_levels.put_buy_qty_2, 0) = 0
                     AND COALESCE(put_levels.put_sell_qty_3, 0) = 0
                     AND ABS(COALESCE(put_levels.put_buy_qty_1, 0) - COALESCE(put_levels.put_buy_qty_3, 0)) < 0.000001
                     AND ABS(COALESCE(put_levels.put_sell_qty_2, 0) - (COALESCE(put_levels.put_buy_qty_1, 0) + COALESCE(put_levels.put_buy_qty_3, 0))) < 0.000001
                 )
                 OR
                 (
                     COALESCE(put_levels.put_sell_qty_1, 0) > 0
                     AND COALESCE(put_levels.put_buy_qty_2, 0) > 0
                     AND COALESCE(put_levels.put_sell_qty_3, 0) > 0
                     AND COALESCE(put_levels.put_buy_qty_1, 0) = 0
                     AND COALESCE(put_levels.put_sell_qty_2, 0) = 0
                     AND COALESCE(put_levels.put_buy_qty_3, 0) = 0
                     AND ABS(COALESCE(put_levels.put_sell_qty_1, 0) - COALESCE(put_levels.put_sell_qty_3, 0)) < 0.000001
                     AND ABS(COALESCE(put_levels.put_buy_qty_2, 0) - (COALESCE(put_levels.put_sell_qty_1, 0) + COALESCE(put_levels.put_sell_qty_3, 0))) < 0.000001
                 )
             )
             THEN CASE
                 WHEN ABS(
                     (COALESCE(put_levels.put_strike_2, 0) - COALESCE(put_levels.put_strike_1, 0))
                     - (COALESCE(put_levels.put_strike_3, 0) - COALESCE(put_levels.put_strike_2, 0))
                 ) < 0.000001 THEN 'Put Butterfly'
                 ELSE 'Broken-Wing Put Butterfly'
             END
        WHEN stats.leg_count = 4
             AND stats.expiry_count = 1
             AND stats.long_call_legs = 1
             AND stats.short_call_legs = 1
             AND stats.long_put_legs = 1
             AND stats.short_put_legs = 1
             THEN CASE
                 WHEN ABS(
                     (COALESCE(stats.max_put_strike, 0) - COALESCE(stats.min_put_strike, 0))
                     - (COALESCE(stats.max_call_strike, 0) - COALESCE(stats.min_call_strike, 0))
                 ) < 0.000001 THEN 'Iron Condor'
                 ELSE 'Broken-Wing Iron Condor'
             END
        WHEN stats.leg_count = 4
             AND stats.call_legs = 4
             AND stats.expiry_count = 1
             AND COALESCE(call_levels.call_strike_levels, 0) = 4
             AND (
                 (
                     COALESCE(call_levels.call_buy_qty_1, 0) > 0
                     AND COALESCE(call_levels.call_sell_qty_2, 0) > 0
                     AND COALESCE(call_levels.call_sell_qty_3, 0) > 0
                     AND COALESCE(call_levels.call_buy_qty_4, 0) > 0
                 )
                 OR
                 (
                     COALESCE(call_levels.call_sell_qty_1, 0) > 0
                     AND COALESCE(call_levels.call_buy_qty_2, 0) > 0
                     AND COALESCE(call_levels.call_buy_qty_3, 0) > 0
                     AND COALESCE(call_levels.call_sell_qty_4, 0) > 0
                 )
             )
             THEN CASE
                 WHEN ABS(
                     (COALESCE(call_levels.call_strike_2, 0) - COALESCE(call_levels.call_strike_1, 0))
                     - (COALESCE(call_levels.call_strike_4, 0) - COALESCE(call_levels.call_strike_3, 0))
                 ) < 0.000001 THEN 'Call Condor'
                 ELSE 'Broken-Wing Call Condor'
             END
        WHEN stats.leg_count = 4
             AND stats.put_legs = 4
             AND stats.expiry_count = 1
             AND COALESCE(put_levels.put_strike_levels, 0) = 4
             AND (
                 (
                     COALESCE(put_levels.put_buy_qty_1, 0) > 0
                     AND COALESCE(put_levels.put_sell_qty_2, 0) > 0
                     AND COALESCE(put_levels.put_sell_qty_3, 0) > 0
                     AND COALESCE(put_levels.put_buy_qty_4, 0) > 0
                 )
                 OR
                 (
                     COALESCE(put_levels.put_sell_qty_1, 0) > 0
                     AND COALESCE(put_levels.put_buy_qty_2, 0) > 0
                     AND COALESCE(put_levels.put_buy_qty_3, 0) > 0
                     AND COALESCE(put_levels.put_sell_qty_4, 0) > 0
                 )
             )
             THEN CASE
                 WHEN ABS(
                     (COALESCE(put_levels.put_strike_2, 0) - COALESCE(put_levels.put_strike_1, 0))
                     - (COALESCE(put_levels.put_strike_4, 0) - COALESCE(put_levels.put_strike_3, 0))
                 ) < 0.000001 THEN 'Put Condor'
                 ELSE 'Broken-Wing Put Condor'
             END
        ELSE 'Other/Complex'
    END AS tastytrade_label
FROM v_opt_strategy_leg_stats stats
LEFT JOIN call_levels ON call_levels.strategy_id = stats.strategy_id
LEFT JOIN put_levels ON put_levels.strategy_id = stats.strategy_id;

DROP VIEW IF EXISTS v_opt_campaign_legs;
CREATE VIEW v_opt_campaign_legs AS
WITH event_rollup AS (
    SELECT
        c.id AS campaign_id,
        c.campaign_key,
        c.broker_account_id,
        c.broker_account_name,
        c.underlying_symbol,
        c.option_type,
        c.side AS campaign_side,
        c.opened_at AS campaign_opened_at,
        e.id AS campaign_event_id,
        e.strategy_id,
        e.event_index,
        e.event_timestamp,
        e.event_side,
        e.delta_contracts,
        e.event_contracts,
        e.event_primary_strike,
        e.event_net_cash_flow,
        ROUND(
            SUM(e.event_net_cash_flow) OVER (
                PARTITION BY c.id
                ORDER BY e.event_index
                ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
            ),
            8
        ) AS cum_premium_bank_net,
        ROUND(
            SUM(e.delta_contracts) OVER (
                PARTITION BY c.id
                ORDER BY e.event_index
                ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
            ),
            8
        ) AS net_contracts
    FROM opt_campaign c
    JOIN opt_campaign_event e ON e.campaign_id = c.id
)
SELECT
    rollup.campaign_id,
    rollup.campaign_key,
    rollup.broker_account_id,
    rollup.broker_account_name,
    rollup.underlying_symbol,
    rollup.option_type,
    rollup.campaign_side,
    rollup.campaign_opened_at,
    rollup.campaign_event_id,
    rollup.strategy_id,
    rollup.event_index,
    rollup.event_timestamp,
    rollup.event_side,
    rollup.delta_contracts,
    rollup.event_contracts,
    rollup.event_primary_strike,
    rollup.event_net_cash_flow,
    rollup.cum_premium_bank_net,
    rollup.net_contracts,
    CASE
        WHEN ABS(rollup.net_contracts) < 0.000001 THEN NULL
        WHEN rollup.event_primary_strike IS NULL THEN NULL
        WHEN rollup.campaign_side = 'SELL' AND rollup.option_type = 'put'
            THEN ROUND(rollup.event_primary_strike - (rollup.cum_premium_bank_net / (100.0 * ABS(rollup.net_contracts))), 8)
        WHEN rollup.campaign_side = 'SELL' AND rollup.option_type = 'call'
            THEN ROUND(rollup.event_primary_strike + (rollup.cum_premium_bank_net / (100.0 * ABS(rollup.net_contracts))), 8)
        WHEN rollup.campaign_side = 'BUY' AND rollup.option_type = 'call'
            THEN ROUND(rollup.event_primary_strike - (rollup.cum_premium_bank_net / (100.0 * ABS(rollup.net_contracts))), 8)
        WHEN rollup.campaign_side = 'BUY' AND rollup.option_type = 'put'
            THEN ROUND(rollup.event_primary_strike + (rollup.cum_premium_bank_net / (100.0 * ABS(rollup.net_contracts))), 8)
        ELSE NULL
    END AS option_be_price,
    CASE
        WHEN ABS(rollup.net_contracts) < 0.000001 THEN NULL
        WHEN rollup.event_primary_strike IS NULL THEN NULL
        WHEN rollup.campaign_side = 'SELL' AND rollup.option_type = 'put'
            THEN ROUND(rollup.event_primary_strike - (rollup.cum_premium_bank_net / (100.0 * ABS(rollup.net_contracts))), 8)
        WHEN rollup.campaign_side = 'SELL' AND rollup.option_type = 'call'
            THEN ROUND(rollup.event_primary_strike + (rollup.cum_premium_bank_net / (100.0 * ABS(rollup.net_contracts))), 8)
        WHEN rollup.campaign_side = 'BUY' AND rollup.option_type = 'call'
            THEN ROUND(rollup.event_primary_strike - (rollup.cum_premium_bank_net / (100.0 * ABS(rollup.net_contracts))), 8)
        WHEN rollup.campaign_side = 'BUY' AND rollup.option_type = 'put'
            THEN ROUND(rollup.event_primary_strike + (rollup.cum_premium_bank_net / (100.0 * ABS(rollup.net_contracts))), 8)
        ELSE NULL
    END AS stock_be_price,
    CASE
        WHEN ABS(rollup.net_contracts) < 0.000001 THEN ROUND(rollup.cum_premium_bank_net, 8)
        ELSE 0.0
    END AS realised_pnl_net,
    CASE
        WHEN ABS(rollup.net_contracts) < 0.000001 THEN 'closed'
        ELSE 'open'
    END AS campaign_status,
    leg.id AS strategy_leg_id,
    leg.fill_id,
    leg.leg_index,
    leg.symbol,
    leg.side AS leg_side,
    leg.strike,
    leg.expiry,
    leg.quantity,
    leg.price
FROM event_rollup rollup
JOIN opt_campaign_event_leg cel ON cel.event_id = rollup.campaign_event_id
JOIN opt_strategy_leg leg ON leg.id = cel.strategy_leg_id;

DROP VIEW IF EXISTS v_opt_campaign_summary;
CREATE VIEW v_opt_campaign_summary AS
WITH ranked AS (
    SELECT
        *,
        ROW_NUMBER() OVER (
            PARTITION BY campaign_id
            ORDER BY event_index DESC, strategy_leg_id DESC
        ) AS row_rank
    FROM v_opt_campaign_legs
)
SELECT
    campaign_id,
    campaign_key,
    broker_account_id,
    broker_account_name,
    underlying_symbol,
    option_type,
    campaign_side,
    campaign_opened_at AS opened_at,
    event_timestamp AS latest_event_timestamp,
    option_be_price,
    stock_be_price,
    net_contracts AS current_net_contracts,
    cum_premium_bank_net,
    realised_pnl_net,
    campaign_status
FROM ranked
WHERE row_rank = 1;

DROP VIEW IF EXISTS v_position_reconciliation_summary;
CREATE VIEW v_position_reconciliation_summary AS
SELECT
    report_date,
    broker_account_id,
    broker_account_name,
    status,
    COUNT(*) AS row_count,
    SUM(ABS(quantity_diff)) AS gross_quantity_diff
FROM position_reconciliation
GROUP BY report_date, broker_account_id, broker_account_name, status;

DROP VIEW IF EXISTS v_positions_eod;
CREATE VIEW v_positions_eod AS
SELECT
    p.report_date,
    p.broker_account_id,
    COALESCE(p.broker_account_name, t.broker_account_name, s.broker_account_name) AS broker_account_name,
    p.instrument_key,
    COALESCE(p.conid, t.conid, s.conid) AS conid,
    COALESCE(p.symbol, t.symbol, s.symbol) AS symbol,
    COALESCE(p.underlying_symbol, t.underlying_symbol, s.underlying_symbol) AS underlying_symbol,
    COALESCE(p.security_type, t.security_type, s.security_type) AS security_type,
    p.trade_quantity_eod,
    p.statement_quantity_eod,
    p.quantity_diff,
    p.status AS reconciliation_status,
    s.mark_price,
    s.position_value AS market_value,
    CAST(
        COALESCE(
            json_extract(s.raw_payload_json, '$.costBasisMoney'),
            json_extract(s.raw_payload_json, '$.costBasis'),
            json_extract(s.raw_payload_json, '$.fifoCostBasis'),
            json_extract(s.raw_payload_json, '$.costBasisPrice'),
            json_extract(s.raw_payload_json, '$.averageCost'),
            json_extract(s.raw_payload_json, '$.avgCost')
        ) AS REAL
    ) AS cost_basis,
    s.currency,
    t.last_fill_timestamp,
    p.exception_code,
    p.exception_note
FROM position_reconciliation p
LEFT JOIN pos_eod_from_trades t
    ON t.report_date = p.report_date
   AND t.broker_account_id = p.broker_account_id
   AND t.instrument_key = p.instrument_key
LEFT JOIN statement_open_positions s
    ON s.report_date = p.report_date
   AND s.broker_account_id = p.broker_account_id
   AND s.instrument_key = p.instrument_key;
"""

DERIVED_VIEWS = (
    "v_positions_eod",
    "v_position_reconciliation_summary",
    "v_opt_campaign_summary",
    "v_opt_campaign_legs",
    "v_opt_strategy_classified",
    "v_opt_strategy_leg_stats",
)

DERIVED_TABLES = (
    "opt_campaign_event_leg",
    "opt_campaign_event",
    "opt_campaign",
    "opt_strategy_leg",
    "opt_strategy",
    "position_reconciliation",
    "pos_eod_from_trades",
)


def get_connection() -> sqlite3.Connection:
    """Get a SQLite connection with WAL mode and foreign keys enabled."""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db(*, rebuild_derived: bool = False) -> None:
    """Apply schema migrations and ensure the latest derived objects exist."""
    conn = get_connection()
    cur = conn.cursor()

    _ensure_schema_migrations_table(cur)
    _apply_migrations(conn, cur)
    _ensure_column(cur, "fills", "conid", "TEXT")
    _ensure_column(cur, "fills", "order_reference", "TEXT")

    if rebuild_derived:
        _drop_derived_objects(cur)

    _ensure_derived_objects(cur)
    _seed_default_setup_types(cur)

    conn.commit()
    conn.close()


def get_schema_version() -> int:
    """Return the latest applied schema migration version."""
    conn = get_connection()
    try:
        _ensure_schema_migrations_table(conn.cursor())
        row = conn.execute("SELECT MAX(version) AS version FROM schema_migrations").fetchone()
        return int((row["version"] if row and row["version"] is not None else 0) or 0)
    finally:
        conn.close()


def _ensure_schema_migrations_table(cur: sqlite3.Cursor) -> None:
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            applied_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
        """
    )


def _apply_migrations(conn: sqlite3.Connection, cur: sqlite3.Cursor) -> None:
    applied_versions = {
        row["version"]
        for row in cur.execute("SELECT version FROM schema_migrations").fetchall()
    }
    migrations = (
        (1, "initial_schema", _apply_initial_schema),
    )
    for version, name, migration in migrations:
        if version in applied_versions:
            continue
        migration(cur)
        cur.execute(
            "INSERT INTO schema_migrations (version, name) VALUES (?, ?)",
            (version, name),
        )
    conn.commit()


def _apply_initial_schema(cur: sqlite3.Cursor) -> None:
    cur.executescript(BASE_SCHEMA_SQL)
    _ensure_derived_objects(cur)


def _ensure_derived_objects(cur: sqlite3.Cursor) -> None:
    cur.executescript(DERIVED_TABLES_SQL)
    cur.executescript(VIEWS_SQL)


def _drop_derived_objects(cur: sqlite3.Cursor) -> None:
    for view_name in DERIVED_VIEWS:
        cur.execute(f"DROP VIEW IF EXISTS {view_name}")
    for table_name in DERIVED_TABLES:
        cur.execute(f"DROP TABLE IF EXISTS {table_name}")


def _seed_default_setup_types(cur: sqlite3.Cursor) -> None:
    defaults = ["Episodic Pivot", "Breakout", "Pullback", "Parabolic Long", "Parabolic Short"]
    for setup_type in defaults:
        cur.execute("INSERT OR IGNORE INTO setup_types (name) VALUES (?)", (setup_type,))


def _ensure_column(cur: sqlite3.Cursor, table: str, column: str, definition: str) -> None:
    columns = {row[1] for row in cur.execute(f"PRAGMA table_info({table})").fetchall()}
    if column not in columns:
        cur.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Apply Trade Journal schema migrations.")
    parser.add_argument(
        "--rebuild-derived",
        action="store_true",
        help="Drop and recreate derived tables/views before exiting.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    init_db(rebuild_derived=args.rebuild_derived)
    if args.rebuild_derived:
        print(f"Database initialized at {DB_PATH} (derived schema rebuilt, version {get_schema_version()})")
    else:
        print(f"Database initialized at {DB_PATH} (version {get_schema_version()})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
