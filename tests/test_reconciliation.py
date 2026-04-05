import os
import tempfile
import unittest

import database
from database import get_connection, init_db
from importer import import_from_file
from reconciliation import (
    build_pos_eod_from_trades,
    parse_statement_open_positions,
    reconcile_positions,
    store_statement_open_positions,
)


SAMPLE_STATEMENT_XML = """<?xml version="1.0" encoding="UTF-8"?>
<FlexQueryResponse queryName="OpenPositions" type="AF">
  <FlexStatements count="1">
    <FlexStatement accountId="U7654321" toDate="2026-03-21">
      <OpenPositions>
        <OpenPosition accountId="U7654321" acctAlias="IRA" conid="TSLA-C250" symbol="TSLA 260404C00250000" underlyingSymbol="TSLA" assetCategory="OPT" position="1" markPrice="12.40" positionValue="1240.00" costBasisMoney="980.00" reportDate="2026-03-21" />
        <OpenPosition accountId="U7654321" acctAlias="IRA" conid="TSLA-C260" symbol="TSLA 260404C00260000" underlyingSymbol="TSLA" assetCategory="OPT" position="-1" markPrice="9.80" positionValue="-980.00" costBasisMoney="-640.00" reportDate="2026-03-21" />
        <OpenPosition accountId="U7654321" acctAlias="IRA" conid="QQQ-C480" symbol="QQQ 260328C00480000" underlyingSymbol="QQQ" assetCategory="OPT" position="2" markPrice="6.20" positionValue="1240.00" costBasisMoney="1100.00" reportDate="2026-03-21" />
        <OpenPosition accountId="U7654321" acctAlias="IRA" conid="SPY-STK" symbol="SPY" underlyingSymbol="SPY" assetCategory="STK" position="100" markPrice="510.25" positionValue="51025.00" costBasisMoney="49500.00" reportDate="2026-03-21" />
      </OpenPositions>
    </FlexStatement>
  </FlexStatements>
</FlexQueryResponse>
"""

SAMPLE_STATEMENT_XML_INHERITED_ACCOUNT = """<?xml version="1.0" encoding="UTF-8"?>
<FlexQueryResponse queryName="OpenPositions" type="AF">
  <FlexStatements count="1">
    <FlexStatement accountId="U9999999" toDate="2026-04-01">
      <OpenPositions>
        <OpenPosition acctAlias="Swing Trading" conid="861518220" symbol="ANET 24APR26 115 P" underlyingSymbol="ANET" assetCategory="OPT" position="-3" markPrice="2.61" positionValue="-783.63" reportDate="2026-04-01" />
      </OpenPositions>
    </FlexStatement>
  </FlexStatements>
</FlexQueryResponse>
"""


class ReconciliationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmpdir.name, "trade_journal.db")
        os.environ["TJ_DB_PATH"] = self.db_path
        database.DB_PATH = self.db_path
        init_db()

    def tearDown(self) -> None:
        os.environ.pop("TJ_DB_PATH", None)
        self.tmpdir.cleanup()

    def test_parse_statement_open_positions(self) -> None:
        positions = parse_statement_open_positions(SAMPLE_STATEMENT_XML)
        self.assertEqual(4, len(positions))
        self.assertEqual("2026-03-21", positions[0]["report_date"])
        self.assertEqual("TSLA-C250", positions[0]["instrument_key"])
        self.assertEqual(-1.0, positions[1]["quantity_eod"])

    def test_parse_statement_open_positions_inherits_account_id(self) -> None:
        positions = parse_statement_open_positions(SAMPLE_STATEMENT_XML_INHERITED_ACCOUNT)
        self.assertEqual(1, len(positions))
        self.assertEqual("U9999999", positions[0]["broker_account_id"])
        self.assertEqual("Swing Trading", positions[0]["broker_account_name"])
        self.assertEqual("2026-04-01", positions[0]["report_date"])
        self.assertEqual("861518220", positions[0]["instrument_key"])

    def test_reconciliation_generates_ok_and_exception_rows(self) -> None:
        result = import_from_file("sample_flex.xml")
        self.assertEqual("success", result["status"])

        conn = get_connection()
        conn.execute(
            "UPDATE fills SET conid = ? WHERE broker_execution_id = ?",
            ("TSLA-C250", "EX012"),
        )
        conn.execute(
            "UPDATE fills SET conid = ? WHERE broker_execution_id = ?",
            ("TSLA-C260", "EX013"),
        )
        conn.execute(
            "UPDATE fills SET conid = ? WHERE broker_execution_id = ?",
            ("QQQ-C480", "EX014"),
        )
        conn.commit()
        conn.close()

        inserted = build_pos_eod_from_trades("2026-03-21")
        self.assertEqual(3, inserted)

        stored = store_statement_open_positions(parse_statement_open_positions(SAMPLE_STATEMENT_XML))
        self.assertEqual(4, stored)

        summary = reconcile_positions("2026-03-21")
        self.assertEqual(4, summary.rows_compared)
        self.assertEqual(3, summary.ok_rows)
        self.assertEqual(1, summary.exception_rows)
        self.assertEqual(0, summary.mismatch_rows)

        conn = get_connection()
        rows = conn.execute(
            """
            SELECT instrument_key, status, exception_code
            FROM position_reconciliation
            WHERE report_date = ?
            ORDER BY instrument_key
            """,
            ("2026-03-21",),
        ).fetchall()
        conn.close()

        results = [dict(row) for row in rows]
        self.assertEqual(
            [
                {"instrument_key": "QQQ-C480", "status": "OK", "exception_code": None},
                {"instrument_key": "SPY-STK", "status": "EXCEPTION", "exception_code": "external_activity"},
                {"instrument_key": "TSLA-C250", "status": "OK", "exception_code": None},
                {"instrument_key": "TSLA-C260", "status": "OK", "exception_code": None},
            ],
            results,
        )

    def test_positions_eod_view_exposes_reporting_ready_rows(self) -> None:
        result = import_from_file("sample_flex.xml")
        self.assertEqual("success", result["status"])

        conn = get_connection()
        conn.execute(
            "UPDATE fills SET conid = ? WHERE broker_execution_id = ?",
            ("TSLA-C250", "EX012"),
        )
        conn.execute(
            "UPDATE fills SET conid = ? WHERE broker_execution_id = ?",
            ("TSLA-C260", "EX013"),
        )
        conn.execute(
            "UPDATE fills SET conid = ? WHERE broker_execution_id = ?",
            ("QQQ-C480", "EX014"),
        )
        conn.commit()
        conn.close()

        build_pos_eod_from_trades("2026-03-21")
        store_statement_open_positions(parse_statement_open_positions(SAMPLE_STATEMENT_XML))
        reconcile_positions("2026-03-21")

        conn = get_connection()
        rows = conn.execute(
            """
            SELECT
                instrument_key,
                security_type,
                trade_quantity_eod,
                statement_quantity_eod,
                quantity_diff,
                reconciliation_status,
                mark_price,
                market_value,
                cost_basis
            FROM v_positions_eod
            WHERE report_date = ?
            ORDER BY instrument_key
            """,
            ("2026-03-21",),
        ).fetchall()
        conn.close()

        results = [dict(row) for row in rows]
        self.assertEqual(4, len(results))
        self.assertEqual(
            {
                "instrument_key": "QQQ-C480",
                "security_type": "OPT",
                "trade_quantity_eod": 2.0,
                "statement_quantity_eod": 2.0,
                "quantity_diff": 0.0,
                "reconciliation_status": "OK",
                "mark_price": 6.2,
                "market_value": 1240.0,
                "cost_basis": 1100.0,
            },
            results[0],
        )
        self.assertEqual("EXCEPTION", results[1]["reconciliation_status"])
        self.assertEqual(51025.0, results[1]["market_value"])


if __name__ == "__main__":
    unittest.main()
