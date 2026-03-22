# Trade Journal

A personal trade journal that imports IBKR trade data daily, reconstructs journal-worthy trades from raw fills, displays TradingView charts for visual review, and captures a compact manual review for decision improvement.

## Quick Start

```bash
pip install -r requirements.txt
streamlit run app.py
```

Upload `sample_flex.xml` in the Settings tab to see trades populate immediately.

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
