# Trade Journal — Original Product Specification (v1.2)

**This is the original specification document preserved for reference. See HANDOFF.md for implementation status and continuation guidance.**

---

## 1. Objective

Build a simple personal trade journal that imports IBKR trade data daily, reconstructs journal-worthy trades, displays a TradingView chart for review, supports common equity and options workflows, and captures a compact manual review so the user can improve decision quality over time.

## 2. Locked product decisions

| Area | Locked decision | Why it matters |
|------|----------------|---------------|
| Charting | TradingView is the only chart source in scope for v1. | Avoids chart-source sprawl and keeps the user experience consistent. |
| EMA interpretation | QQQ and symbol EMA context are not system-calculated requirements. | The app should not force a market-data architecture just to produce qualitative context. |
| Manual review | EMA context, TQ/TICKQ, and market notes are optional user inputs. | Keeps the journal simple and fast to use while preserving useful judgement fields. |
| TQ/TICKQ | May be sourced separately from Yahoo Finance if the developer validates a stable symbol path. | Allows lightweight automation without making it a mandatory dependency. |

Implementation note: If TQ/TICKQ retrieval is not reliable, leave it blank and allow the user to enter it manually.

## 3. Recommended platform

- Python 3.12+ for import, parsing, trade reconstruction, and business logic.
- SQLite for local single-user storage.
- Streamlit for a lightweight review interface.
- Windows Task Scheduler or cron for the daily IBKR import job.

## 4. External integrations

### 4.1 IBKR broker data
- Use IBKR Flex Web Service with a pre-configured Flex Query.
- Use Flex Query XML as the default output format.
- Run imports once daily and store the raw response for audit and debugging.
- Reject duplicate imports using a report reference, checksum, or both.

### 4.2 Charting
- Use TradingView as the only chart source for v1.
- The application must display a TradingView chart for each trade where feasible.
- Entry and exit should be visually indicated where feasible.
- The specification does not require any other chart provider.

### 4.3 TQ/TICKQ
- TQ/TICKQ is not part of the chart-source requirement.
- If included, it may be retrieved separately from Yahoo Finance after the developer validates the exact symbol and retrieval method.
- If retrieval fails or is unreliable, the field remains optional and user-editable.

## 5. Scope

### 5.1 In scope for v1
- Daily IBKR import and raw import retention.
- Fill parsing and trade reconstruction.
- Support for stock/ETF trades, single-leg options, and standard two-leg vertical debit/credit spreads.
- Auto-population of objective trade data only.
- TradingView chart display in the trade review screen.
- Optional manual review fields for context and self-assessment.
- Trade history, filtering, and basic statistics, including account-based filtering for multi-account imports.
- Backup and export.

### 5.2 Out of scope for v1
- Real-time order monitoring or broker order placement.
- Multi-broker support.
- Complex options strategies beyond standard verticals.
- Automatic EMA analytics from a mandated market-data provider.
- Cloud sync or mobile app support.
- Advanced quantitative analytics such as Greeks, IV, MAE/MFE, or portfolio-level risk.

## 6. Functional requirements

### 6.1 Daily import module
- Authenticate with stored IBKR Flex token and query ID.
- Request the report, retrieve it, archive the raw payload, and log success or failure.
- Create no duplicate fills or trades when the same report is imported twice.

### 6.2 Parsing and normalisation
- Capture broker execution ID, order ID where available, symbol, side, quantity/contracts, execution price, timestamp, commissions/fees, exchange, and security type.
- Persist the original raw payload reference for troubleshooting.
- Preserve account identity from the broker import and keep it attached to each fill.
- Normalise timestamps consistently.

### 6.3 Trade reconstruction
- Group multiple fills belonging to the same opening action into one opening event.
- Group multiple fills belonging to the same closing action into one closing event.
- Keep partial exits inside the same journal trade until the position is fully closed.
- Never merge fills or reconstructed trades across different broker accounts.
- Treat standard two-leg vertical spreads as one trade idea with child legs.
- Flag unsupported complex options structures for manual review.

### 6.4 Chart display
- Display a TradingView chart in the trade detail/review screen.
- Provide enough context for the user to visually inspect the trade setup and execution.
- Show entry and exit visually where feasible through annotation, labels, or adjacent trade details.
- If a fully automated marker overlay is not practical, the chart may be displayed alongside clearly labelled entry and exit information.

### 6.5 Manual review block
The application must provide one optional manual review block per trade. The user is allowed to leave any of these review fields blank.

Optional manual fields: setup_class (A+, A, B, C, F), manual_tags, comment, emotion, lesson_learned, execution_score, market_regime_note, confidence_rating, mistake_narrative, would_take_again, qqq_ema_note, symbol_ema_note, tq_tickq_note.

| Field | Type | Required? | Notes |
|-------|------|-----------|-------|
| manual_tags | multi-select/freeform | No | Primary manual classification field. |
| comment | text | No | General observation or trade note. |
| emotion | multi-select list | No | Examples: calm, focused, fearful, FOMO, impatient. |
| lesson_learned | text | No | Short reflective note. |
| execution_score | integer 1-5 | No | Simple self-rating. |
| market_regime_note | text | No | User view of the broader tape or environment. |
| confidence_rating | integer 1-5 | No | Confidence level at entry. |
| mistake_narrative | text | No | What went wrong, if anything. |
| would_take_again | enum | No | yes / no / with_changes. |
| qqq_ema_note | text or dropdown | No | Optional qualitative read, for example bullish, mixed, bearish, or a short note. |
| symbol_ema_note | text or dropdown | No | Optional qualitative read on the traded symbol. |
| tq_tickq_note | text | No | Optional user note or auto-filled value if Yahoo retrieval is validated. |

## 7. Data model

**imports** — id, source_type, query_id, import_started_at, import_finished_at, status, report_reference, raw_file_path, checksum, error_message

**fills** — id, import_id, broker_account_id, broker_account_name, broker_execution_id, broker_order_id, symbol, underlying_symbol, security_type, side, quantity, price, execution_timestamp, commission, fees, currency, exchange, raw_payload_json

**trades** — id, trade_code, broker_account_id, broker_account_name, trade_type, strategy_type, symbol, underlying_symbol, direction, status, entry_datetime, exit_datetime, entry_price_avg, exit_price_avg, quantity_or_contracts, gross_pnl, net_pnl, total_fees, holding_minutes, holding_days, same_day_trade_flag, partial_exit_flag, scale_in_flag, scale_out_flag, manual_review_required, review_status, created_at, updated_at

**trade_legs** — id, trade_id, leg_index, option_type, side, strike, expiry, contracts, open_price_avg, close_price_avg, multiplier, assigned_flag, exercised_flag, expired_flag

**trade_options_summary** — id, trade_id, expiry, dte_at_entry, dte_at_exit, net_debit_credit, spread_width, max_profit, max_loss, breakeven

**trade_reviews** — id, trade_id, setup_class, manual_tags_json, comment, emotion_json, lesson_learned, execution_score, market_regime_note, confidence_rating, mistake_narrative, would_take_again, qqq_ema_note, symbol_ema_note, tq_tickq_note, reviewed_at

## 8. Options logic

- Support long call and long put as single-leg strategies.
- Support call debit spread, put debit spread, call credit spread, and put credit spread as standard two-leg verticals.
- Calculate deterministic fields such as spread width, net debit/credit, max profit, max loss, breakeven, and DTE where possible.
- If a structure is rolled, broken, or otherwise too complex to classify reliably, flag it for manual review instead of forcing inference.

## 9. User interface

### 9.1 Needs Review screen
- List imported trades awaiting review.
- Support filtering by a single account, multiple selected accounts, or all accounts.
- Show account as a visible column or label in review lists where space allows.
- Show symbol, trade type, direction, entry/exit, P&L, chart access, and review status.
- Allow the user to open the review form and mark the trade reviewed.

### 9.2 Trade detail screen
- Show trade summary, options structure summary where relevant, auto-populated trade facts, TradingView chart, and the manual review block.
- Keep manual review fields grouped together to avoid clutter.

### 9.3 Trade history and stats
- Allow filtering by account, date range, symbol, trade type, strategy type, review status, win/loss, and manual tag.
- Show only basic statistics in v1: total trades, win rate, average win, average loss, total net P&L, results by trade type, results by manual tag, and account-filtered views of those metrics.

## 10. Acceptance criteria

1. A scheduled daily run retrieves IBKR Flex XML and stores the raw file.
2. Re-importing the same report does not create duplicate data.
3. Stock trades, single-leg options, and standard vertical spreads are reconstructed correctly.
4. The trade detail screen displays a TradingView chart for supported trades.
5. The user can save the optional manual review block even when most fields are left blank.
6. TQ/TICKQ can be stored either via optional retrieval or manual entry without breaking the workflow.
7. Trade history filters and the basic statistics page work against imported and reviewed data, including account-based filtering.
8. Backup/export works.

## 11. Build order

- Phase 1: schema, IBKR import, parsing, and stock trade reconstruction.
- Phase 2: options support, vertical spread logic, account-aware trade reconstruction, review status handling, and trade history.
- Phase 3: TradingView chart display, manual review block, and basic statistics.
- Phase 4: backup/export, logging, hardening, and optional TQ/TICKQ retrieval from Yahoo Finance if validated.

## 12. Summary for the developer

Build a local personal trade journal that imports IBKR Flex XML once daily, reconstructs trades from fills, supports equity trades plus simple options structures, uses TradingView as the only chart source, and captures a compact optional review block. Do not make EMA interpretation a mandatory auto-calculated feature. Treat QQQ EMA context, symbol EMA context, and TQ/TICKQ as optional review inputs, with TQ/TICKQ allowed to be auto-retrieved separately from Yahoo Finance only if the retrieval path is validated.

## Appendix A. External notes for implementation

- IBKR Flex Web Service is the intended mechanism for broker data retrieval.
- Flex Query XML is the intended report format for the import pipeline.
- TradingView is charting-only in this specification.
- Yahoo Finance is only an optional separate source for TQ/TICKQ if validated by the developer.
