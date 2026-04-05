# Trade Journal

A personal trade journal that imports IBKR trade data daily, reconstructs journal-worthy trades from raw fills, displays TradingView charts for visual review, and captures a compact manual review for decision improvement.

## Quick Start

```bash
pip install -r requirements.txt
streamlit run app.py
```

Upload `sample_flex.xml` in the Settings tab to see trades populate immediately.

For scheduler-driven daily runs, use the batch driver:

```bash
python daily_driver.py --xml-file sample_flex.xml --report-date 2026-03-21
```

Or fetch directly from IBKR Flex:

```bash
python daily_driver.py --token "$TJ_IBKR_TOKEN" --query-id "$TJ_IBKR_QUERY_ID"
```

Useful overrides:

- `--db-path` or `TJ_DB_PATH`
- `--raw-dir` or `TJ_RAW_DIR`
- `--statement-xml` for a separate Open Positions XML
- `--reset-derived` to drop and recreate derived tables/views before rebuilding them
- `--report-date` when the XML does not carry the intended reconciliation date

Schema-only maintenance:

```bash
python database.py --rebuild-derived
```

That command reapplies the tracked schema, drops the derived layer (`pos_eod_from_trades`, `position_reconciliation`, `opt_strategy*`, `opt_campaign*`, and reporting views), and recreates it empty so the batch pipeline can rebuild from raw imports.

## Features

- **IBKR Flex Import** — Fetches daily trade data via Flex Web Service or manual XML upload
- **Trade Reconstruction** — Groups fills into journal trades (stocks, single options, vertical spreads)
- **Multi-Account** — Tracks and filters by broker account
- **TradingView Charts** — Embedded chart per trade with entry/exit labels
- **Manual Review** — Setup class (A+ to F), setup type, tags, emotions, scores, and notes
- **Statistics** — Win rate, P&L by type/setup/class/tag
- **Backup & Export** — SQLite backup and CSV export

## Project Structure

```
├── app.py              # Streamlit UI (main entry point)
├── database.py         # SQLite schema and connection
├── importer.py         # IBKR Flex fetch, parse, dedup
├── reconstruction.py   # Fill → Trade grouping logic
├── config.py           # JSON-based settings
├── backup.py           # Backup and export utilities
├── requirements.txt
├── sample_flex.xml     # Test data (2 accounts, 14 fills)
├── docs/               # Handoff documentation
│   ├── HANDOFF.md
│   ├── AI_CONTINUATION_GUIDE.md
│   ├── UI_WIREFRAMES.md
│   └── ORIGINAL_SPEC_v1.2.md
├── data/               # Auto-created: SQLite DB + config
└── raw_imports/        # Auto-created: archived Flex XML
```

## Requirements

- Python 3.12+
- No external database (SQLite bundled with Python)
- No paid APIs (IBKR Flex is free, TradingView embed is free)
- Runs entirely locally

## Documentation

See `docs/HANDOFF.md` for the full developer handoff specification including schema, architecture, known limitations, and continuation guide.

See `docs/PHASE2_ARCHITECTURE.md` for the implemented Phase 2 module inventory, data flow, design decisions, and dependency map.

See `docs/DEMO_PREP.md` for the verified demo/deployment runbook, walkthrough order, and currently known rough edges.
