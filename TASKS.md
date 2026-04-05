# Trade Journal — Task Board

This file is the task board and communication channel between the orchestrator and all developers.
Read it before picking up any work. Update it when you start, complete, or block on a task.

---

## Developer Registry

| Dev ID | Name | Type | Registered |
|--------|------|------|------------|
| DEV-01 | Claude-Cowork-Dev-01 | AI (Cowork) | 2026-03-29 |

---

## Task Numbering Note

Task IDs in this file follow the build order from `docs/HANDOFF.md` Section 11, not the priority order from Section 3:

| TASKS.md ID | HANDOFF.md Priority | Title |
|-------------|-------------------|-------|
| T1 | Priority 2 | IBKR options symbol parser |
| T2 | Priority 1 | Spread close matching |
| T3 | Priority 3 | trade_options_summary population |
| T4 | Priority 4 | Cumulative P&L chart |
| T5 | Priority 5 | TQ/TICKQ Yahoo Finance fetch |

---

## Task Board

### Status Key
- `OPEN` — Available, dependencies met
- `IN PROGRESS` — Being worked on (dev ID must be listed)
- `DONE` — Merged to develop, verified
- `BLOCKED` — Waiting on another task

---

| ID | Phase | Title | Status | Assigned | Branch | Depends On |
|----|-------|-------|--------|----------|--------|------------|
| T1 | A | IBKR options symbol parser | DONE | DEV-01 | feature/T1-options-symbol-parser | — |
| T2 | B | Spread close matching | DONE | DEV-01 | feature/T2-spread-close-matching | T1 |
| T3 | C | trade_options_summary population | DONE | DEV-01 | feature/T3-options-summary | T1, T2 |
| T4 | D | Cumulative P&L chart | DONE | DEV-01 | feature/T4-pnl-chart | — |
| T5 | E | TQ/TICKQ Yahoo Finance fetch | OPEN | — | — | — |

---

## Task Details

### T1 — IBKR Options Symbol Parser
**Phase:** A
**Priority:** Highest — blocks T2 and T3
**File:** New `option_parser.py` module
**Spec:** `docs/HANDOFF.md` §3 Priority 2, `docs/AI_CONTINUATION_GUIDE.md` §1

Parse IBKR option symbols like `SPY 260404C00520000` into structured data:
- underlying, expiry (YYYY-MM-DD), option_type (call/put), strike (float)

Then:
- Update `_detect_spreads()` in `reconstruction.py` to use parsed expiry/strike for better matching
- Update `trade_legs` INSERT to include parsed values (option_type, strike, expiry)

**Acceptance criteria:**
- [ ] `parse_ibkr_option_symbol()` handles standard format
- [ ] Handles multi-word underlyings (e.g., `BRK B`)
- [ ] Returns `None` gracefully for unparseable symbols
- [ ] `trade_legs` rows include strike, expiry, option_type after import
- [ ] Sample XML still produces 14 fills, 7 trades after change
- [ ] Real XML in `xml/` folder parses without errors

---

### T2 — Spread Close Matching
**Phase:** B
**Priority:** High — highest-impact functional gap
**File:** `reconstruction.py`
**Spec:** `docs/HANDOFF.md` §3 Priority 1, `docs/AI_CONTINUATION_GUIDE.md` §2
**Depends on:** T1 (needs parsed strike/expiry for accurate matching)

After new fills are imported, scan for open spreads and match close fills to them.

**Acceptance criteria:**
- [ ] Open spreads updated with exit_datetime, exit_price_avg, gross_pnl, net_pnl, status='closed'
- [ ] trade_legs updated with close_price_avg
- [ ] Partial closes handled gracefully
- [ ] Never matches across broker accounts

---

### T3 — trade_options_summary Population
**Phase:** C
**Priority:** Medium
**File:** `reconstruction.py`
**Spec:** `docs/HANDOFF.md` §3 Priority 3, `docs/AI_CONTINUATION_GUIDE.md` §3
**Depends on:** T1, T2

Populate `trade_options_summary` after spread creation/closure.

**Acceptance criteria:**
- [ ] spread_width, net_debit_credit, max_profit, max_loss, breakeven, DTE calculated correctly
- [ ] Called after both spread creation and closure
- [ ] Displayed in Trade Detail screen

---

### T4 — Cumulative P&L Chart
**Phase:** D
**Priority:** Medium
**File:** `app.py` (Statistics tab)
**Spec:** `docs/HANDOFF.md` §3 Priority 4
**Depends on:** None

Add a cumulative net P&L line chart to the Statistics tab.

**Acceptance criteria:**
- [ ] Line chart shows cumulative net_pnl over time
- [ ] X-axis: date, Y-axis: cumulative $
- [ ] Respects account filter
- [ ] Uses Plotly or st.line_chart

---

### T5 — TQ/TICKQ Yahoo Finance Fetch
**Phase:** E
**Priority:** Low — skip if Yahoo symbols unreliable
**File:** New `yahoo_fetch.py`, hook into `importer.py`
**Spec:** `docs/HANDOFF.md` §3 Priority 5
**Depends on:** None

Auto-fetch NYSE TICK/TRIN on import if enabled in settings.

**Acceptance criteria:**
- [ ] `yfinance` returns valid data for chosen symbol
- [ ] Graceful fallback if fetch fails
- [ ] Setting toggle in Settings tab

---

## Work Log

| Date | Dev | Task | Action | Notes |
|------|-----|------|--------|-------|
| 2026-03-29 | DEV-01 | T1 | Started | Created TASKS.md, registered as DEV-01, created feature/T1-options-symbol-parser branch |
| 2026-03-29 | DEV-01 | T1 | Completed | Created option_parser.py with parse_ibkr_option_symbol() + enrich_fill_with_parsed_symbol(). Updated reconstruction.py: import, enhanced _is_spread_pair() with expiry/strike checks, trade_legs INSERT now stores option_type/strike/expiry. 11/11 unit tests pass. sample_flex.xml: 14 fills, 7 trades, TSLA spread legs have strike/expiry/type. Real XML: empty (no trades on 2026-03-27), parses cleanly. |
| 2026-03-29 | DEV-01 | T2 | Started | Created feature/T2-spread-close-matching branch. Implemented match_close_fills_to_open_spreads() in reconstruction.py. Hooked into run_import() in importer.py. |
| 2026-03-29 | DEV-01 | T2 | Completed | match_close_fills_to_open_spreads() uses position-level FIFO fill pool keyed by (account, underlying, strike, expiry, option_type, side). Updates trades.status='closed', exit_datetime, gross_pnl, net_pnl; updates trade_legs.close_price_avg; inserts trade_fills role='close'. Partial closes supported. Two-stage test: TSLA spread opened (Day 1 sample_flex.xml), closed (Day 2 close XML) → gross_pnl=+90.00 ✓. Never matches across broker accounts. |
| 2026-03-29 | DEV-01 | T3 | Started | Created feature/T3-options-summary branch. Implementing upsert_options_summary() in reconstruction.py. |
| 2026-03-29 | DEV-01 | T3 | Completed | Added populate_options_summary(trade_id, conn) to reconstruction.py. Hooked into _create_spread_trade() and match_close_fills_to_open_spreads(). Calculates spread_width, net_debit_credit, max_profit, max_loss, breakeven, dte_at_entry, dte_at_exit. Spread metrics panel added to Trade Detail tab in app.py. Verified: sample_flex.xml → TSLA width=10, max_p=660, be=253.40 ✓; real XML → 46 spreads all get summary rows ✓. |
| 2026-03-29 | DEV-01 | T4 | Started | Created feature/T4-pnl-chart branch. Adding cumulative P&L chart to Statistics tab. |
| 2026-03-29 | DEV-01 | T4 | Completed | Added Plotly cumulative P&L line chart to Statistics tab (app.py). Green/red fill based on final value. Account filter added to statistics tab. Falls back to st.line_chart if plotly not installed. Added plotly>=5.18.0 to requirements.txt. Verified with real XML: 87 closed trades, chart renders correctly. |
| 2026-04-01 | DEV-01 | LIN-39 | Completed | Added Phase 2 reconciliation scaffold: schema support for `statement_open_positions`, `pos_eod_from_trades`, `reconciliation_exceptions`, `position_reconciliation`, and summary view `v_position_reconciliation_summary`. New `reconciliation.py` builds trade-derived EOD positions, ingests IBKR Open Positions XML, applies exception classification/overrides, and stores OK/EXCEPTION/MISMATCH rows. `importer.py` now captures optional `conid`. Verified with `python3 -m unittest tests.test_reconciliation` and `python3 -m py_compile database.py importer.py reconciliation.py tests/test_reconciliation.py`. |
| 2026-04-01 | DEV-01 | LIN-42 | Completed | Expanded `v_opt_strategy_classified` to recognize calendars, diagonals, collars, jade lizards, ratio spreads, broken-wing butterflies, broken-wing iron condors, and same-type condor variants. Added contract/strike-level stats to `v_opt_strategy_leg_stats` plus 7 classification regression tests in `tests/test_option_strategies.py`. Verified with `python3 -m unittest tests.test_option_strategies` (10 tests, all passing) and `python3 -m py_compile database.py tests/test_option_strategies.py`. |
| 2026-04-01 | DEV-01 | LIN-44 | Completed | Added detailed reporting view `v_positions_eod` for direct IBKR Open Positions reconciliation. The view joins `position_reconciliation` to trade-derived EOD rows and statement rows, exposing account, instrument key, stock/option security type, trade vs statement quantity, diff, reconciliation status, mark price, market value, optional cost basis extracted from IBKR raw payload, and last fill timestamp. Added regression coverage in `tests/test_reconciliation.py`. Verified with `python3 -m unittest tests.test_reconciliation` and `python3 -m py_compile database.py reconciliation.py tests/test_reconciliation.py`. |
