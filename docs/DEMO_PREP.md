# TradeJournal Demo Prep

This runbook captures the commands and checks verified on April 2, 2026 for the board demo.

## Environment

- Python: `python3` 3.12.3
- App entrypoint: `streamlit run app.py`
- Batch entrypoint: `python3 daily_driver.py`
- Verified isolated environment workflow: `uv venv .venv` + `uv pip install --python .venv/bin/python -r requirements.txt pytest`

## Verified Commands

Install dependencies into a local virtual environment:

```bash
uv venv .venv
uv pip install --python .venv/bin/python -r requirements.txt pytest
```

Run the regression suite:

```bash
.venv/bin/pytest -q
```

Expected result: `21 passed`

Start the Streamlit app locally:

```bash
.venv/bin/streamlit run app.py --server.headless true --server.port 8501
```

Verified behavior: Streamlit starts cleanly and serves the app on `http://localhost:8501`.

Run the sample-data pipeline:

```bash
rm -f data/trade_journal.db
.venv/bin/python daily_driver.py --xml-file sample_flex.xml --report-date 2026-03-21
```

Verified result:

- 14 fills imported
- 7 trades reconstructed
- 5 option strategies rebuilt
- 3 option campaigns rebuilt
- 3 trade-derived end-of-day position rows produced

Run the full sample pipeline with statement reconciliation:

```bash
.venv/bin/python daily_driver.py --xml-file sample_flex.xml --statement-xml <positions.xml> --report-date 2026-03-21
```

Verified result with the regression fixture statement:

- 4 statement rows ingested
- 7 reconciliation rows produced
- 7 rows marked `EXCEPTION`

## Demo Walkthrough

Use this order during the demo:

1. Start the app with `.venv/bin/streamlit run app.py`.
2. Open the Settings tab.
3. Upload `sample_flex.xml` to populate demo data immediately.
4. Show the imported accounts and fills.
5. Walk through reconstructed trades in Needs Review and Trade Detail.
6. Show option strategy and campaign outputs already built by the batch pipeline.
7. Use History and Statistics to show account-level filtering and P&L summaries.
8. If asked about daily automation, show `daily_driver.py` as the scheduler entrypoint.

## Deployment Notes

- The app is local-first and currently verified for local execution, not packaged deployment.
- On this machine, `python` is not on `PATH`; use `python3` explicitly in docs, scripts, and cron jobs.
- `uv` is the most reliable setup path here because the system Python blocks direct global `pip` installs and `python3 -m venv` is missing `ensurepip`.

## Rough Edges

- The sample reconciliation fixture currently yields only `EXCEPTION` rows, so reconciliation is useful to demo as an exception-reporting view, not as an all-green example.
- There is no committed lockfile or bootstrap script yet, so environment setup still depends on the operator having `uv` available.
