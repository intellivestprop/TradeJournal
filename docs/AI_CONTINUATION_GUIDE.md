# Trade Journal — AI Continuation Guide

**Read this first if you are an AI agent (Cowork, Claude Code, etc.) picking up this project.**

---

## Quick orientation

This is a partially-built Python/Streamlit trade journal. The core pipeline (import → parse → reconstruct → review) works end-to-end. You need to finish 5 features in priority order.

### Files you must read before changing anything

1. `HANDOFF.md` — Full spec, schema, architecture, and what's built vs. what's missing.
2. `database.py` — All 9 table schemas. Read the CREATE statements.
3. `reconstruction.py` — Trade grouping logic. This is where most of your work happens.
4. `app.py` — Streamlit UI. Large file. All 5 tabs are here.

### Run and verify first

```bash
pip install -r requirements.txt
streamlit run app.py
# Upload sample_flex.xml in Settings tab
# Verify: 14 fills parsed, 7 trades reconstructed, all 5 tabs render
```

---

## What to build (in order)

### 1. Options symbol parser

Add to `reconstruction.py` (or new `option_parser.py`):

```python
def parse_ibkr_option_symbol(symbol: str) -> dict:
    """
    Parse 'SPY 260404C00520000' into:
    {
        'underlying': 'SPY',
        'expiry': '2026-04-04',
        'option_type': 'call',  # or 'put'
        'strike': 520.0
    }
    
    Format: UNDERLYING YYMMDD[C|P]STRIKE
    Strike is in thousandths (00520000 = $520.00)
    Underlying may have spaces (e.g., 'BRK B')
    """
```

Then update `_detect_spreads()` to use parsed expiry/strike for better matching. Update `trade_legs` INSERT to include parsed values.

### 2. Spread close matching

After `store_fills()` in `importer.py`, add a step:

```python
def match_close_fills_to_open_spreads(import_id: int):
    """
    Find fills from this import that are closes for existing open spreads.
    Match by: same account, same underlying, opposite side to open legs,
    same strike/expiry (from parsed symbol).
    Update trade: exit_datetime, exit_price_avg, gross_pnl, net_pnl, status='closed'.
    Update trade_legs: close_price_avg.
    """
```

### 3. trade_options_summary population

After creating or closing a spread, call:

```python
def populate_options_summary(trade_id: int):
    """
    Read trade_legs for this trade.
    Calculate: spread_width, net_debit_credit, max_profit, max_loss, breakeven, DTE.
    INSERT OR REPLACE into trade_options_summary.
    """
```

Formulas:
- spread_width = abs(leg1_strike - leg2_strike)
- For debit spreads: max_profit = (spread_width - net_debit) × 100; max_loss = net_debit × 100
- For credit spreads: max_profit = net_credit × 100; max_loss = (spread_width - net_credit) × 100
- breakeven: for call debit = lower_strike + net_debit; for put debit = higher_strike - net_debit

### 4. Cumulative P&L chart

In `app.py` Statistics tab, add after the breakdown tables:

```python
# Query trades ordered by exit_datetime, compute running sum of net_pnl
# Plot with st.line_chart or plotly
```

### 5. TQ/TICKQ Yahoo fetch (skip if unreliable)

Only implement if you can verify `yfinance` returns valid data for NYSE TICK/TRIN. If not, leave as manual-only.

---

## Rules you must follow

- **Never merge fills across accounts.** Every query must include account filter.
- **All review fields stay optional.** Don't add validation.
- **Don't add market data dependencies** for EMA calculation.
- **Don't change the schema** unless absolutely necessary. Add columns, don't restructure.
- **Keep the dark theme.** Background `#0d1117`.
- **trade_options_summary stays as a separate table.** Don't merge into trades.
- **Test with sample_flex.xml after every change.** Verify fill count and trade count.

---

## Gotchas

1. `reconstruction.py` groups fills by order_id first, then by time proximity (2s window). If you change grouping logic, existing trades may reconstruct differently on re-import.

2. The TradingView embed uses `st.components.v1.html()`. It loads a third-party script — don't add any sensitive data to the embed URL.

3. `config.py` stores settings in `data/config.json` alongside the DB. The Flex token is stored in plaintext — this is acceptable for a local-only personal tool.

4. `backup.py` copies the entire SQLite file. If the DB is open during backup, SQLite's WAL mode handles it safely, but warn the user if they're mid-import.

5. The `accounts` table is auto-populated from fills during import. Account aliases are set in Settings. Don't require account setup before import.
