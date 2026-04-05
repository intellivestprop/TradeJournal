"""
Scheduler-friendly daily batch driver for Trade Journal.

Runs the Phase 2 pipeline end-to-end:
1. Flex fetch or local XML load
2. Import / dedup
3. Trade reconstruction
4. Trade-derived EOD positions
5. Option strategy grouping
6. Option campaign rebuild
7. Statement position ingest + reconciliation
8. Final schema/view ensure step
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import config as config_module
import database
import importer
from config import load_config
from database import get_connection, init_db
from importer import fetch_flex_report, run_import
from option_campaigns import rebuild_option_campaigns
from option_strategies import rebuild_option_strategies
from reconciliation import (
    build_pos_eod_from_trades,
    parse_statement_open_positions,
    reconcile_positions,
    store_statement_open_positions,
)
from reconstruction import reconstruct_all_new


LOG = logging.getLogger("trade_journal.daily_driver")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the Trade Journal daily batch pipeline.")
    parser.add_argument("--db-path", help="SQLite database path. Overrides TJ_DB_PATH.")
    parser.add_argument("--config-path", help="Config JSON path. Overrides TJ_CONFIG_PATH.")
    parser.add_argument("--raw-dir", help="Directory for archived Flex XML files. Overrides TJ_RAW_DIR.")
    parser.add_argument("--xml-file", help="Import from a local Flex XML file instead of fetching from IBKR.")
    parser.add_argument(
        "--statement-xml",
        help="Optional XML file to use for Open Positions ingestion. Defaults to the main XML input.",
    )
    parser.add_argument("--token", help="IBKR Flex token. Overrides TJ_IBKR_TOKEN / config.")
    parser.add_argument("--query-id", help="IBKR Flex query id. Overrides TJ_IBKR_QUERY_ID / config.")
    parser.add_argument("--report-date", help="Reconciliation date in YYYY-MM-DD. Defaults to XML/report date.")
    parser.add_argument(
        "--reset-derived",
        action="store_true",
        help="Drop and recreate derived tables/views before rebuilding them from imported data.",
    )
    parser.add_argument("--log-level", default=os.environ.get("TJ_LOG_LEVEL", "INFO"))
    return parser


def configure_runtime(args: argparse.Namespace) -> None:
    if args.db_path:
        os.environ["TJ_DB_PATH"] = args.db_path
        database.DB_PATH = args.db_path
    if args.config_path:
        os.environ["TJ_CONFIG_PATH"] = args.config_path
        config_module.CONFIG_PATH = args.config_path
    if args.raw_dir:
        os.environ["TJ_RAW_DIR"] = args.raw_dir
        importer.RAW_DIR = args.raw_dir


def resolve_setting(cli_value: str | None, env_key: str, config_key: str | None = None) -> str:
    if cli_value:
        return cli_value
    if os.environ.get(env_key):
        return os.environ[env_key]
    if config_key:
        return str(load_config().get(config_key, "") or "")
    return ""


def load_xml_text(xml_path: str | None, token: str, query_id: str) -> tuple[str, str]:
    if xml_path:
        with open(xml_path, "r", encoding="utf-8") as handle:
            return handle.read(), xml_path

    if not token or not query_id:
        raise ValueError("Flex token and query id are required when --xml-file is not provided.")

    return fetch_flex_report(token, query_id), "ibkr_flex"


def derive_report_date(xml_text: str, explicit_report_date: str | None) -> str:
    if explicit_report_date:
        return explicit_report_date

    root = ET.fromstring(xml_text)
    for el in root.iter():
        for key in ("reportDate", "toDate", "asOfDate", "statementDate", "date"):
            value = el.get(key)
            if value:
                cleaned = value.strip().replace("/", "-")
                if ";" in cleaned:
                    cleaned = cleaned.split(";", 1)[0]
                if len(cleaned) == 8 and cleaned.isdigit():
                    return f"{cleaned[:4]}-{cleaned[4:6]}-{cleaned[6:]}"
                return cleaned
    raise ValueError("Could not derive report date from XML. Pass --report-date explicitly.")


def count_rows(table_or_view: str, report_date: str | None = None) -> int:
    conn = get_connection()
    try:
        if report_date is None:
            row = conn.execute(f"SELECT COUNT(*) AS count FROM {table_or_view}").fetchone()
        else:
            row = conn.execute(
                f"SELECT COUNT(*) AS count FROM {table_or_view} WHERE report_date = ?",
                (report_date,),
            ).fetchone()
        return int(row["count"])
    finally:
        conn.close()


def log_step_start(name: str) -> None:
    LOG.info("START %s", name)


def log_step_end(name: str, **details: object) -> None:
    if details:
        rendered = ", ".join(f"{key}={value}" for key, value in details.items())
        LOG.info("END %s | %s", name, rendered)
        return
    LOG.info("END %s", name)


def run_pipeline(args: argparse.Namespace) -> int:
    configure_runtime(args)
    logging.basicConfig(
        level=getattr(logging, str(args.log_level).upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(message)s",
    )

    init_db()

    token = resolve_setting(args.token, "TJ_IBKR_TOKEN", "ibkr_token")
    query_id = resolve_setting(args.query_id, "TJ_IBKR_QUERY_ID", "ibkr_query_id")

    log_step_start("load_input")
    xml_text, xml_source = load_xml_text(args.xml_file, token, query_id)
    report_date = derive_report_date(xml_text, args.report_date)
    statement_xml_path = args.statement_xml
    statement_xml_text = None
    if statement_xml_path:
        with open(statement_xml_path, "r", encoding="utf-8") as handle:
            statement_xml_text = handle.read()
    else:
        statement_xml_text = xml_text
        statement_xml_path = xml_source
    log_step_end("load_input", source=xml_source, report_date=report_date)

    log_step_start("import")
    import_result = run_import(token=token, query_id=query_id, xml_text=xml_text)
    log_step_end(
        "import",
        status=import_result.get("status"),
        import_id=import_result.get("import_id"),
        fills=import_result.get("fills"),
        total_parsed=import_result.get("total_parsed", 0),
        spreads_closed=import_result.get("spreads_closed", 0),
    )

    log_step_start("reconstruct_trades")
    reconstruction_result = reconstruct_all_new()
    log_step_end("reconstruct_trades", **reconstruction_result)

    if args.reset_derived:
        log_step_start("reset_derived_schema")
        init_db(rebuild_derived=True)
        log_step_end("reset_derived_schema")

    log_step_start("build_trade_positions")
    trade_positions = build_pos_eod_from_trades(report_date)
    log_step_end("build_trade_positions", rows=trade_positions)

    log_step_start("rebuild_option_strategies")
    strategy_count = rebuild_option_strategies()
    log_step_end("rebuild_option_strategies", rows=strategy_count)

    log_step_start("rebuild_option_campaigns")
    campaign_count = rebuild_option_campaigns()
    log_step_end("rebuild_option_campaigns", rows=campaign_count)

    log_step_start("reconcile_positions")
    statement_positions = parse_statement_open_positions(statement_xml_text, default_report_date=report_date)
    stored_statement_rows = store_statement_open_positions(
        statement_positions,
        import_id=import_result.get("import_id"),
    ) if statement_positions else 0
    reconciliation_result = reconcile_positions(report_date)
    log_step_end(
        "reconcile_positions",
        statement_rows=stored_statement_rows,
        rows_compared=reconciliation_result.rows_compared,
        ok_rows=reconciliation_result.ok_rows,
        exception_rows=reconciliation_result.exception_rows,
        mismatch_rows=reconciliation_result.mismatch_rows,
    )

    log_step_start("refresh_views")
    init_db()
    log_step_end(
        "refresh_views",
        positions_eod_rows=count_rows("v_positions_eod", report_date=report_date),
        campaign_summary_rows=count_rows("v_opt_campaign_summary"),
    )

    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return run_pipeline(args)
    except Exception:
        LOG.exception("Daily pipeline failed")
        return 1


if __name__ == "__main__":
    sys.exit(main())
