# Trade Journal — Developer Handoff Document

**Version:** 1.2  
**Date:** 25 March 2026  
**Purpose:** Complete handoff specification for AI or developer continuation of the Trade Journal application.  
**Status:** Partially built. Core pipeline works end-to-end. Key features need completion.

---

## 1. Project overview

A personal trade journal that imports IBKR trade data daily, reconstructs journal-worthy trades from raw fills, displays TradingView charts for visual review, and captures a compact manual review so the user can improve decision quality over time.

### Core stack

| Component | Technology |
|-----------|-----------|
| Language | Python 3.12+ |
| Database | SQLite (local, single-user) |
| UI | Streamlit (dark terminal theme) |
| Broker data | IBKR Flex Web Service (Flex Query XML) |
| Charts | TradingView embedded widget only |
| Options scope | Single-leg options + vertical debit/credit spreads |
| Scheduling | Windows Task Scheduler or cron |

### Design philosophy

- Local-first personal tool, not a SaaS product.
- Zero cost — all integrations are free tier.
- EMA context is qualitative user input, not auto-calculated.
- TQ/TICKQ is optional and manually entered unless Yahoo Finance retrieval is validated.
- All review fields are optional. User can save a blank review.
- Never merge fills or trades across different broker accounts.
- Flag complex structures for manual review rather than forcing inference.

---

## 2. What is already built

### 2.1 Working modules

| Module | File | Status | Notes |
|--------|------|--------|-------|
| Database schema | `database.py` | Complete | All 9 tables created. Default setup types seeded. |
| IBKR import | `importer.py` | Complete | XML parse, fill extraction, account tracking, checksum dedup, raw file archiving. |
| Trade reconstruction | `reconstruction.py` | Partial | Stocks and single options work. Spread detection uses time proximity heuristic. |
| Streamlit UI | `app.py` | Complete | All 5 tabs: Needs Review, Trade Detail, History, Statistics, Settings. Dark theme. |
| Configuration | `config.py` | Complete | JSON-based settings persistence. |
| Backup/export | `backup.py` | Complete | SQLite backup, CSV export. |
| Sample data | `sample_flex.xml` | Complete | 14 fills across 2 accounts, 7 trades (4 stock, 2 single option, 1 spread). |

### 2.2 Tested and verified

- 14 fills parsed from sample XML across 2 accounts (U1234567/Main, U7654321/IRA).
- 7 trades reconstructed correctly with P&L.
- Duplicate import correctly rejected via checksum.
- Review save/update works with all 12 fields.
- Backup + CSV export works.
- All modules compile and import cleanly.

### 2.3 How to run

```bash
pip install -r requirements.txt
streamlit run app.py
```

Opens at `http://localhost:8501`. Upload `sample_flex.xml` in Settings tab to populate immediately.

---

## 3. What needs to be built (priority order)

### Priority 1: Spread close matching

**Problem:** Vertical spreads are currently created as "open" when opening legs arrive. When closing fills arrive in a later import, they need to be matched to the existing open spread to compute final P&L.

**Requirements:**
- Match close fills to existing open spread trades by: same broker account, same underlying symbol, same leg structure (matching strikes/expiry if parsed).
- Update the trade's `exit_datetime`, `exit_price_avg`, `gross_pnl`, `net_pnl`, `status` to "closed".
- Update `trade_legs` with close prices.
- Handle partial closes gracefully.

**Where to implement:** `reconstruction.py` — add a function that runs after new fills are stored, scans for open spreads, and attempts to match new close fills.

### Priority 2: Options symbol parsing

**Problem:** IBKR option symbols encode strike, expiry, and option type in the symbol string (e.g., `SPY 260404C00520000` = SPY Call $520 expiring 2026-04-04), but the current code doesn't parse this.

**Requirements:**
- Parse IBKR option symbol format: `UNDERLYING YYMMDD[C|P]STRIKE` where strike is in thousandths.
- Extract: underlying symbol, expiry date, option type (call/put), strike price.
- Populate `trade_legs` table with parsed values.
- Use parsed data for better spread matching (same expiry, different strikes, opposite types).

**IBKR symbol format:**
```
SPY 260404C00520000
 │   │     │ │
 │   │     │ └── Strike: 00520000 = $520.00 (divide by 1000)
 │   │     └──── Type: C=Call, P=Put
 │   └────────── Expiry: YYMMDD = 2026-04-04
 └────────────── Underlying: SPY
```

**Where to implement:** New function in `reconstruction.py` or a separate `option_parser.py` module.

### Priority 3: trade_options_summary population

**Problem:** The `trade_options_summary` table exists but is never populated.

**Requirements:**
- After a spread trade is created/closed, calculate and store:
  - `expiry` — from parsed leg data
  - `dte_at_entry` — trading days from entry to expiry
  - `dte_at_exit` — trading days from exit to expiry
  - `net_debit_credit` — net premium paid/received
  - `spread_width` — difference between strikes
  - `max_profit` — (spread_width - net_debit) × multiplier for debit spreads; net_credit × multiplier for credit spreads
  - `max_loss` — net_debit × multiplier for debit spreads; (spread_width - net_credit) × multiplier for credit spreads
  - `breakeven` — depends on spread type

**Where to implement:** `reconstruction.py` — call after spread creation/closure.

### Priority 4: Cumulative P&L chart

**Problem:** Statistics tab shows summary cards and breakdown tables but no equity curve chart.

**Requirements:**
- Line chart showing cumulative net P&L over time.
- X-axis: date. Y-axis: cumulative $ P&L.
- Respect account filter (show filtered or all-account curve).
- Use Plotly or native Streamlit charting.

**Where to implement:** `app.py` Statistics tab section.

### Priority 5: TQ/TICKQ Yahoo Finance retrieval

**Problem:** The `tq_tickq_note` review field is manual-only. The spec allows optional auto-retrieval from Yahoo Finance if the symbol path is validated.

**Requirements:**
- Validate exact Yahoo Finance symbol for TICK (NYSE) and TRIN (NYSE) or equivalent.
- If enabled in settings, auto-fetch on import and pre-populate the field.
- If fetch fails, leave blank — field remains editable.
- Use `yfinance` library.

**Implementation note:** Yahoo Finance symbols can be unreliable. If validation fails, leave this as manual-only. The spec explicitly allows this.

**Where to implement:** New `yahoo_fetch.py` module, called from `importer.py` post-import hook.

---

## 4. Architecture

### 4.1 Project structure

```
trade_journal/
├── app.py                # Streamlit UI — all 5 tabs
├── database.py           # SQLite schema, connection, init
├── importer.py           # IBKR Flex XML fetch, parse, dedup, archive
├── reconstruction.py     # Fill → Trade grouping logic
├── config.py             # JSON-based settings persistence
├── backup.py             # SQLite backup + CSV export
├── requirements.txt      # Python dependencies
├── sample_flex.xml       # Test data (2 accounts, 14 fills, 7 trades)
├── data/                 # Auto-created: SQLite DB + config.json
│   ├── trade_journal.db
│   └── config.json
└── raw_imports/          # Auto-created: archived Flex XML files
```

### 4.2 Data pipeline

```
IBKR Flex API / XML Upload
        │
        ▼
   importer.py
   ├── Fetch or read XML
   ├── Compute checksum → reject if duplicate
   ├── Archive raw file to raw_imports/
   ├── Parse XML → extract fills
   └── Store fills in DB (with account identity)
        │
        ▼
  reconstruction.py
  ├── Group fills by account (NEVER merge across accounts)
  ├── Within each account, group by symbol
  ├── Match opens to closes (order ID, then time proximity)
  ├── Detect vertical spreads (opposite sides, same underlying, <60s)
  ├── Calculate P&L, holding time, flags
  └── Create trade records + trade_fills links
        │
        ▼
     app.py (Streamlit)
     ├── Needs Review — pending trades queue
     ├── Trade Detail — facts + chart + review form
     ├── History — filtered trade list
     ├── Statistics — metrics + breakdowns
     └── Settings — IBKR config, import, backup
```

### 4.3 Module dependencies

```
app.py
  ├── database.py (get_connection, init_db)
  ├── importer.py (run_import, import_from_file)
  ├── reconstruction.py (reconstruct_all_new)
  ├── config.py (load_config, save_config)
  └── backup.py (backup_database, export_trades_csv)

importer.py
  └── database.py

reconstruction.py
  └── database.py

config.py
  └── (standalone, uses JSON file)

backup.py
  └── database.py
```

---

## 5. Database schema

### 5.1 Tables overview

| Table | Purpose | Records per... |
|-------|---------|---------------|
| `imports` | Tracks each daily broker import | One per import run |
| `fills` | Raw executions parsed from IBKR | One per broker execution |
| `trade_fills` | Links fills to trades with role (open/close) | Many per trade |
| `trades` | Journal-level trade records | One per trade idea |
| `trade_legs` | Child records for option legs | 2 per vertical spread |
| `trade_options_summary` | Derived options metrics | One per options/spread trade |
| `trade_reviews` | Manual review data | One per trade |
| `setup_types` | User-managed setup type library | Small lookup table |
| `accounts` | Auto-detected broker accounts | One per IBKR account |

### 5.2 Full schema (SQL)

```sql
-- Import tracking
CREATE TABLE IF NOT EXISTS imports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_type TEXT NOT NULL DEFAULT 'ibkr_flex',
    query_id TEXT,
    import_started_at TEXT,
    import_finished_at TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    report_reference TEXT,
    raw_file_path TEXT,
    checksum TEXT,
    error_message TEXT
);

-- Raw fills from broker
CREATE TABLE IF NOT EXISTS fills (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    import_id INTEGER NOT NULL REFERENCES imports(id),
    broker_account_id TEXT,
    broker_account_name TEXT,
    broker_execution_id TEXT NOT NULL,
    broker_order_id TEXT,
    symbol TEXT NOT NULL,
    underlying_symbol TEXT,
    security_type TEXT,
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
    ON fills(broker_execution_id);

-- Fill-to-trade linkage
CREATE TABLE IF NOT EXISTS trade_fills (
    trade_id INTEGER NOT NULL REFERENCES trades(id),
    fill_id INTEGER NOT NULL REFERENCES fills(id),
    role TEXT NOT NULL DEFAULT 'open',
    PRIMARY KEY (trade_id, fill_id)
);

-- Journal-level trades
CREATE TABLE IF NOT EXISTS trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trade_code TEXT UNIQUE,
    broker_account_id TEXT,
    broker_account_name TEXT,
    trade_type TEXT NOT NULL,
    strategy_type TEXT,
    setup_type TEXT,
    symbol TEXT NOT NULL,
    underlying_symbol TEXT,
    direction TEXT,
    status TEXT NOT NULL DEFAULT 'open',
    entry_datetime TEXT,
    exit_datetime TEXT,
    entry_price_avg REAL,
    exit_price_avg REAL,
    quantity_or_contracts REAL,
    gross_pnl REAL,
    net_pnl REAL,
    total_fees REAL DEFAULT 0,
    holding_minutes REAL,
    holding_days REAL,
    same_day_trade_flag INTEGER DEFAULT 0,
    partial_exit_flag INTEGER DEFAULT 0,
    scale_in_flag INTEGER DEFAULT 0,
    scale_out_flag INTEGER DEFAULT 0,
    manual_review_required INTEGER DEFAULT 0,
    review_status TEXT NOT NULL DEFAULT 'pending',
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);

-- Option legs (for spreads)
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

-- Derived options summary
CREATE TABLE IF NOT EXISTS trade_options_summary (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trade_id INTEGER NOT NULL REFERENCES trades(id) UNIQUE,
    expiry TEXT,
    dte_at_entry INTEGER,
    dte_at_exit INTEGER,
    net_debit_credit REAL,
    spread_width REAL,
    max_profit REAL,
    max_loss REAL,
    breakeven REAL
);

-- Manual review
CREATE TABLE IF NOT EXISTS trade_reviews (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trade_id INTEGER NOT NULL REFERENCES trades(id) UNIQUE,
    setup_class TEXT,
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
    reviewed_at TEXT DEFAULT (datetime('now'))
);

-- Setup types library
CREATE TABLE IF NOT EXISTS setup_types (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    created_at TEXT DEFAULT (datetime('now'))
);

-- Default setup types
INSERT OR IGNORE INTO setup_types (name) VALUES
    ('Episodic Pivot'), ('Breakout'), ('Pullback'),
    ('Parabolic Long'), ('Parabolic Short');

-- Auto-detected accounts
CREATE TABLE IF NOT EXISTS accounts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    broker_account_id TEXT NOT NULL UNIQUE,
    broker_account_name TEXT,
    alias TEXT,
    first_seen TEXT DEFAULT (datetime('now'))
);
```

### 5.3 Key constraints and indexes

- `fills.broker_execution_id` has a UNIQUE index — prevents duplicate fills even across imports.
- `imports.checksum` is checked before import — prevents duplicate report processing.
- `trade_reviews.trade_id` is UNIQUE — one review per trade.
- `trade_options_summary.trade_id` is UNIQUE — one summary per trade.
- `trade_fills` has a composite primary key `(trade_id, fill_id)`.

---

## 6. Trade reconstruction logic

### 6.1 Core principles

1. **Account partitioning first.** Group all fills by `broker_account_id` before any other grouping. Never merge across accounts.
2. **Symbol grouping.** Within each account, group fills by symbol (for stocks) or `underlying_symbol` (for options).
3. **Open/close matching.** Match opens to closes using `broker_order_id` first. If no order ID, use time proximity (fills within 2 seconds on the same side are grouped as one action).
4. **Spread detection.** Two option fills on the same underlying, opposite sides, within 60 seconds = vertical spread candidate.
5. **Escape hatch.** If a structure is too complex (3+ legs, rolls, broken structures), flag `manual_review_required = 1` and don't force inference.

### 6.2 Stock/ETF trades

```
For each (account, symbol):
  Sort fills by timestamp
  Track running position (quantity)
  Group same-side fills close in time as one "action"
  When position crosses zero → create closed trade
    entry_price_avg = weighted average of open fills
    exit_price_avg = weighted average of close fills
    gross_pnl = (exit - entry) × quantity × direction_multiplier
    net_pnl = gross_pnl - sum(commissions + fees)
  If position doesn't return to zero → trade remains "open"
```

### 6.3 Single-leg options

Same logic as stocks, but:
- Multiplier is 100 (P&L = price_diff × contracts × 100).
- `strategy_type` inferred from side: BUY → `long_call` or `long_put`; SELL → `short_call` or `short_put`.
- `security_type` must be `OPT` in the fill.

### 6.4 Vertical spreads

```
Detection:
  For each pair of option fills on the same underlying:
    - Opposite sides (one BUY, one SELL)
    - Within 60 seconds
    - Same or close expiry (if parseable)
  → Match as spread

Creation:
  - trade_type = "spread"
  - strategy_type = "call_debit_spread" / "put_credit_spread" / etc.
  - direction = "debit" if net premium paid > 0, else "credit"
  - Create 2 trade_legs records (leg_index 1 and 2)
  - P&L from net premium difference

Known limitation:
  - Spread detection relies on time proximity, not parsed strike/expiry
  - Priority 2 (options symbol parsing) will improve this significantly
```

### 6.5 P&L calculation

```
gross_pnl:
  Stock/option: (exit_avg - entry_avg) × quantity × multiplier × direction_sign
  Spread: (close_net_premium - open_net_premium) × contracts × multiplier

net_pnl: gross_pnl - total_fees

total_fees: sum of (commission + fees) from all fills in the trade

holding_minutes: (last_close_fill_timestamp - first_open_fill_timestamp) in minutes
holding_days: holding_minutes / 1440

same_day_trade_flag: 1 if entry and exit on same calendar date
```

---

## 7. User interface specification

### 7.1 Global UI decisions

- **Theme:** Dark terminal (background `#0d1117`, card `#161b22`, inputs `#1c2129`).
- **Font:** Monospace (`SF Mono`, `Fira Code`, `Cascadia Code`).
- **Color coding:** Green for positive P&L / long / wins. Red for negative P&L / short / losses. Blue for info / stocks. Purple for options. Amber for spreads. Teal for account tags.
- **Layout:** 5 tabs across the top. Hybrid tables with expandable chart rows.
- **Review form:** 3 sub-tabs (Notes / Mental State / Outcome).

### 7.2 Needs Review screen

**Summary metrics row:** Awaiting review count, today's imports, today's P&L, last import timestamp.

**Filter bar:** Account dropdown (All / specific accounts), Type dropdown (All / Stock / Single option / Spread), Setup type dropdown.

**Trade table columns:** Account tag, Symbol (bold), Type badge, Setup type, Direction badge, Entry price, Exit price, P&L (color-coded), Setup class, Review status badge, Expand button.

**Expand row:** Click the arrow button to reveal: TradingView chart embed area, entry/exit labels with colored dots, "Open review" button linking to Trade Detail.

### 7.3 Trade detail screen

**Trade selector:** Dropdown at top showing all trades with symbol, type, P&L, date, account, status.

**Trade summary card:** 4×3 grid of fact boxes: Entry, Exit, Quantity/Contracts, Spread width (if spread), Max profit, Max loss, Gross P&L, Net P&L, Holding time, DTE at entry (if options), Breakeven (if spread), Fees.

**Legs table (spreads only):** Columns: Leg, Type, Side, Strike, Expiry, Open price, Close price.

**TradingView chart card:** Embedded widget with symbol auto-set. Entry/exit labels below the chart as colored dots with price and timestamp.

**Manual review card:** Three sub-tabs:
- **Notes tab:** Setup class (A+/A/B/C/F selector), Setup type dropdown, Tags input, Comment textarea, QQQ EMA note, Symbol EMA note, TQ/TICKQ note.
- **Mental state tab:** Emotion multi-select (Calm/Focused/FOMO/Fearful/Impatient), Confidence rating 1-5, Market regime note.
- **Outcome tab:** Execution score 1-5, Would take again (Yes/No/With changes), Lesson learned textarea, Mistake narrative textarea.
- **Save review button** at bottom.

### 7.4 Trade history screen

**Filter bar:** Account, Type, Status (All/Reviewed/Needs review), P&L (All/Winners/Losers), Symbol text input, Date range (From/To), Setup type.

**Trade table columns:** Date, Account, Symbol, Type, Setup type, Direction, P&L, Setup class, Review status.

### 7.5 Statistics screen

**Metric cards (row 1):** Total trades, Win rate, Avg winner, Avg loser.
**Metric cards (row 2):** Net P&L, Profit factor, Best trade, Worst trade.

**Breakdown tables (2-column grid):**
- By trade type: Type / Trades / Win% / Net P&L.
- By setup type: Setup / Trades / Win% / Net P&L.
- By setup class: Class / Trades / Win% / Net P&L.
- By manual tag: Tag / Trades / Win% / Net P&L.

**Planned:** Cumulative P&L line chart (Priority 4).

### 7.6 Settings screen

**IBKR connection card:** Flex token (password field), Query ID, Save button.

**Import controls:** Run import now button, Upload XML file button.

**Accounts card:** Auto-detected accounts with editable alias field.

**Setup types card:** Current types as badges, Add new input + button.

**TQ/TICKQ card:** Enable/disable toggle, Yahoo symbol input.

**Backup & export card:** Backup database button, Export CSV button, Export SQLite button.

**Import history table:** Date, Status, Fill count, Trade count, Filename.

---

## 8. External integrations

### 8.1 IBKR Flex Web Service

**Authentication:** Stored Flex token + query ID in config.json.

**Flow:**
1. POST to `https://gdcdyn.interactivebrokers.com/Universal/servlet/FlexStatementService.SendRequest` with token and query ID.
2. Parse response for reference code.
3. Poll `FlexStatementService.GetStatement` with reference code until ready.
4. Download XML report.
5. Archive raw XML to `raw_imports/` directory.

**Deduplication:** SHA-256 checksum of raw XML. Reject if checksum already exists in `imports` table. Fill-level dedup via UNIQUE index on `broker_execution_id`.

**XML parsing:** Extract `<Trade>` elements. Map attributes to fill columns. Handle both `TradeConfirmation` and `Order` report types.

### 8.2 TradingView

**Method:** Embedded advanced chart widget (free, no API key).

**Implementation:** Streamlit `st.components.v1.html()` with TradingView widget script. Symbol auto-set from trade's symbol.

**Limitations:** Cannot programmatically overlay entry/exit markers on the chart. Entry/exit shown as text labels beside/below the chart with colored dots (green = entry, red = exit). This is per the spec's "where feasible" language.

### 8.3 Yahoo Finance (optional, not yet implemented)

**Purpose:** Auto-retrieve TQ/TICKQ data for the review field.

**Symbol candidates:** `^TICK` (NYSE TICK), `^TRIN` (NYSE TRIN/Arms Index). Must be validated — Yahoo Finance symbols change.

**Library:** `yfinance` (pip install yfinance).

**Fallback:** If retrieval fails, field stays blank and remains user-editable. The spec explicitly allows this.

---

## 9. Acceptance criteria

1. A scheduled daily run retrieves IBKR Flex XML and stores the raw file. ✅ Built (manual trigger + file upload work; scheduled via cron/Task Scheduler is documented).
2. Re-importing the same report does not create duplicate data. ✅ Built and tested.
3. Stock trades, single-leg options, and standard vertical spreads are reconstructed correctly. ⚠️ Partial — stocks and single options work; spread detection works but spread *closure* (matching later close fills) is not implemented.
4. The trade detail screen displays a TradingView chart for supported trades. ✅ Built — widget embed with text labels.
5. The user can save the optional manual review block even when most fields are left blank. ✅ Built and tested.
6. TQ/TICKQ can be stored either via optional retrieval or manual entry without breaking the workflow. ⚠️ Partial — manual entry works; auto-retrieval not implemented.
7. Trade history filters and statistics work against imported and reviewed data, including account-based filtering. ✅ Built.
8. Backup/export works. ✅ Built and tested.

---

## 10. Known limitations and technical debt

1. **Spread closure matching** — Vertical spreads created from opening fills don't get updated when close fills arrive in a later import. This is the highest-priority gap.

2. **Options symbol parsing** — IBKR symbols like `SPY 260404C00520000` encode strike/expiry but aren't parsed. The spread detector uses only time proximity and opposite sides. Parsing would improve both spread detection accuracy and trade_legs data quality.

3. **trade_options_summary empty** — Table exists but is never populated. Needs calculated fields from trade_legs data.

4. **No equity curve chart** — Statistics screen has cards and tables but no cumulative P&L line chart.

5. **TradingView marker limitation** — The free embedded widget doesn't support programmatic price annotations. Entry/exit are text labels beside the chart.

6. **Yahoo Finance reliability** — TQ/TICKQ auto-fetch is not implemented because symbol paths need validation and the API has reliability issues.

7. **Scheduled import not auto-configured** — Cron/Task Scheduler setup is documented in README but requires manual OS-level setup.

---

## 11. Build order for continuation

Follow this order. Each phase builds on the previous.

### Phase A: Options symbol parser (enables everything else)
- Implement IBKR symbol parsing (underlying, expiry, type, strike).
- Populate `trade_legs` with parsed values for existing trades.
- Add unit tests for symbol edge cases.

### Phase B: Spread close matching
- After new fills are imported, scan for open spreads.
- Match close fills by account + underlying + leg structure.
- Update trade with exit data and P&L.
- Handle partial closes.

### Phase C: Options summary population
- After spread creation/closure, calculate and store: spread_width, net_debit_credit, max_profit, max_loss, breakeven, DTE.
- Display in Trade Detail screen.

### Phase D: Cumulative P&L chart
- Add Plotly or Streamlit line chart to Statistics tab.
- Cumulative net P&L over time.
- Respect account filters.

### Phase E: TQ/TICKQ Yahoo fetch (lowest priority)
- Validate Yahoo Finance symbol path.
- Add optional auto-fetch on import.
- Pre-populate review field if enabled.
- Graceful fallback to manual entry.

---

## 12. Design decisions to preserve

These decisions were made deliberately. Don't change them without explicit user direction.

1. **Never merge fills or trades across broker accounts.** Account partitioning happens before any grouping.
2. **All review fields are optional.** User must be able to save a review with every field blank.
3. **TradingView is chart-only.** No market data dependency for charting. No other chart provider.
4. **EMA context is qualitative user input, not auto-calculated.** Don't add a market data architecture for EMA computation.
5. **Setup types are user-manageable.** The preset list (Episodic Pivot, Breakout, Pullback, Parabolic Long, Parabolic Short) can be extended by the user in Settings.
6. **Flag complex structures for manual review.** Don't force inference on 3+ leg structures, rolls, or broken spreads.
7. **Dark terminal theme.** Background `#0d1117`, monospace font, color-coded badges.
8. **trade_options_summary stays separate from trades.** This was an explicit user decision — do not merge into the trades table.
9. **All 12 review fields stay.** This was an explicit user decision — do not reduce the field count.

---

## 13. Dependencies

### requirements.txt

```
streamlit>=1.30.0
requests>=2.31.0
```

Additional for future features:
```
yfinance>=0.2.30   # Only if TQ/TICKQ auto-fetch is implemented
plotly>=5.18.0      # For cumulative P&L chart (or use st.line_chart)
```

### System requirements

- Python 3.12+
- No external database (SQLite is bundled with Python)
- No paid APIs
- Windows, macOS, or Linux
