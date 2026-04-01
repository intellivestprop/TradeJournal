# Trade Journal — Developer Onboarding

Welcome. Read these docs in order before touching any code.

---

## Required reading

1. **[docs/HANDOFF.md](docs/HANDOFF.md)** — Full specification, database schema, architecture, what's built vs. what's missing.
2. **[TASKS.md](TASKS.md)** — Task board, status tracker, and work log. Update this as you work.
3. **[docs/AI_CONTINUATION_GUIDE.md](docs/AI_CONTINUATION_GUIDE.md)** — Quick-start guide for AI agents picking up this project.
4. **[docs/ORIGINAL_SPEC_v1.2.md](docs/ORIGINAL_SPEC_v1.2.md)** — Original product specification.

---

## Quick start

```bash
pip install -r requirements.txt
streamlit run app.py
```

Opens at `http://localhost:8501`. Upload `sample_flex.xml` in the Settings tab to populate test data and verify your setup (expect 14 fills, 7 trades).

---

## Non-negotiable rules

These are deliberate design decisions. Do not change without explicit client direction. See [docs/HANDOFF.md Section 12](docs/HANDOFF.md) for the full list.

- **Never merge fills or trades across different broker accounts.**
- **All review fields are optional** — user must be able to save a blank review.
- **EMA context is manual user input** — do not add auto-calculation.
- **Flag complex structures for manual review** — don't force inference on 3+ leg structures.
- **`trade_options_summary` stays as a separate table** — do not merge into `trades`.
- **Activity Flex Query is the data source** — not Trade Confirmation.
- **Dark terminal theme** — background `#0d1117`, monospace font.

---

## PR process

All work must be submitted as a PR to the `develop` branch for DrAider review before merging. Do not merge directly to `develop` or `main`.

---

## Project structure

```
app.py              — Streamlit UI (all 5 tabs)
database.py         — SQLite schema and connection
importer.py         — IBKR Flex XML import pipeline
reconstruction.py   — Fill → Trade grouping logic
option_parser.py    — IBKR options symbol parser
config.py           — JSON-based settings
backup.py           — Database backup and CSV export
sample_flex.xml     — Test data (2 accounts, 14 fills, 7 trades)
docs/               — Specifications and guides
```
