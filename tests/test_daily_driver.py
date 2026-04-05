import os
import tempfile
import unittest

import config as config_module
import database
import importer
from daily_driver import main
from database import get_connection


SAMPLE_STATEMENT_XML = """<?xml version="1.0" encoding="UTF-8"?>
<FlexQueryResponse queryName="OpenPositions" type="AF">
  <FlexStatements count="1">
    <FlexStatement accountId="U7654321" toDate="2026-03-21">
      <OpenPositions>
        <OpenPosition accountId="U7654321" acctAlias="IRA" conid="TSLA-C250" symbol="TSLA 260404C00250000" underlyingSymbol="TSLA" assetCategory="OPT" position="1" markPrice="12.40" positionValue="1240.00" reportDate="2026-03-21" />
        <OpenPosition accountId="U7654321" acctAlias="IRA" conid="TSLA-C260" symbol="TSLA 260404C00260000" underlyingSymbol="TSLA" assetCategory="OPT" position="-1" markPrice="9.80" positionValue="-980.00" reportDate="2026-03-21" />
        <OpenPosition accountId="U7654321" acctAlias="IRA" conid="QQQ-C480" symbol="QQQ 260328C00480000" underlyingSymbol="QQQ" assetCategory="OPT" position="2" markPrice="6.20" positionValue="1240.00" reportDate="2026-03-21" />
        <OpenPosition accountId="U7654321" acctAlias="IRA" conid="SPY-STK" symbol="SPY" underlyingSymbol="SPY" assetCategory="STK" position="100" markPrice="510.25" positionValue="51025.00" reportDate="2026-03-21" />
      </OpenPositions>
    </FlexStatement>
  </FlexStatements>
</FlexQueryResponse>
"""


class DailyDriverTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmpdir.name, "trade_journal.db")
        self.config_path = os.path.join(self.tmpdir.name, "config.json")
        self.raw_dir = os.path.join(self.tmpdir.name, "raw_imports")
        self.statement_xml = os.path.join(self.tmpdir.name, "statement.xml")

        with open(self.statement_xml, "w", encoding="utf-8") as handle:
            handle.write(SAMPLE_STATEMENT_XML)

        os.environ["TJ_DB_PATH"] = self.db_path
        os.environ["TJ_CONFIG_PATH"] = self.config_path
        os.environ["TJ_RAW_DIR"] = self.raw_dir
        database.DB_PATH = self.db_path
        config_module.CONFIG_PATH = self.config_path
        importer.RAW_DIR = self.raw_dir

    def tearDown(self) -> None:
        os.environ.pop("TJ_DB_PATH", None)
        os.environ.pop("TJ_CONFIG_PATH", None)
        os.environ.pop("TJ_RAW_DIR", None)
        self.tmpdir.cleanup()

    def test_daily_driver_runs_full_local_pipeline(self) -> None:
        exit_code = main(
            [
                "--xml-file",
                "sample_flex.xml",
                "--statement-xml",
                self.statement_xml,
                "--report-date",
                "2026-03-21",
            ]
        )

        self.assertEqual(0, exit_code)

        conn = get_connection()
        imports_count = conn.execute("SELECT COUNT(*) AS count FROM imports").fetchone()["count"]
        fills_count = conn.execute("SELECT COUNT(*) AS count FROM fills").fetchone()["count"]
        trades_count = conn.execute("SELECT COUNT(*) AS count FROM trades").fetchone()["count"]
        strategy_count = conn.execute("SELECT COUNT(*) AS count FROM opt_strategy").fetchone()["count"]
        campaign_count = conn.execute("SELECT COUNT(*) AS count FROM opt_campaign").fetchone()["count"]
        reconciliation_rows = conn.execute(
            "SELECT COUNT(*) AS count FROM position_reconciliation WHERE report_date = ?",
            ("2026-03-21",),
        ).fetchone()["count"]
        exception_rows = conn.execute(
            "SELECT COUNT(*) AS count FROM position_reconciliation WHERE report_date = ? AND status = 'EXCEPTION'",
            ("2026-03-21",),
        ).fetchone()["count"]
        conn.close()

        self.assertEqual(1, imports_count)
        self.assertEqual(14, fills_count)
        self.assertEqual(7, trades_count)
        self.assertGreaterEqual(strategy_count, 1)
        self.assertGreaterEqual(campaign_count, 1)
        self.assertEqual(7, reconciliation_rows)
        self.assertEqual(7, exception_rows)

    def test_daily_driver_is_safe_to_rerun_same_input(self) -> None:
        first_exit = main(
            [
                "--xml-file",
                "sample_flex.xml",
                "--statement-xml",
                self.statement_xml,
                "--report-date",
                "2026-03-21",
            ]
        )
        second_exit = main(
            [
                "--xml-file",
                "sample_flex.xml",
                "--statement-xml",
                self.statement_xml,
                "--report-date",
                "2026-03-21",
            ]
        )

        self.assertEqual(0, first_exit)
        self.assertEqual(0, second_exit)

        conn = get_connection()
        import_statuses = [
            row["status"]
            for row in conn.execute("SELECT status FROM imports ORDER BY id").fetchall()
        ]
        fills_count = conn.execute("SELECT COUNT(*) AS count FROM fills").fetchone()["count"]
        trades_count = conn.execute("SELECT COUNT(*) AS count FROM trades").fetchone()["count"]
        reconciliation_rows = conn.execute(
            "SELECT COUNT(*) AS count FROM position_reconciliation WHERE report_date = ?",
            ("2026-03-21",),
        ).fetchone()["count"]
        conn.close()

        self.assertEqual(["success", "duplicate"], import_statuses)
        self.assertEqual(14, fills_count)
        self.assertEqual(7, trades_count)
        self.assertEqual(7, reconciliation_rows)


if __name__ == "__main__":
    unittest.main()
