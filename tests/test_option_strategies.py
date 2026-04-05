import os
import tempfile
import unittest

import database
from database import get_connection, init_db
from importer import parse_flex_xml
from option_strategies import rebuild_option_strategies


ORDER_REFERENCE_XML = """<?xml version="1.0" encoding="UTF-8"?>
<FlexQueryResponse queryName="TradeConfirmation" type="AF">
  <FlexStatements count="1">
    <FlexStatement accountId="U1111111" fromDate="2026-03-21" toDate="2026-03-21">
      <TradeConfirmations>
        <TradeConfirmation
          accountId="U1111111"
          acctAlias="Main"
          tradeID="EX100"
          orderID="ORD100"
          orderReference="IC-REF-1"
          symbol="SPY 260417P00500000"
          underlyingSymbol="SPY"
          assetCategory="OPT"
          buySell="BOT"
          quantity="1"
          tradePrice="1.20"
          tradeDate="2026-03-21"
          tradeTime="10:15:00"
        />
      </TradeConfirmations>
    </FlexStatement>
  </FlexStatements>
</FlexQueryResponse>
"""


class OptionStrategyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmpdir.name, "trade_journal.db")
        os.environ["TJ_DB_PATH"] = self.db_path
        database.DB_PATH = self.db_path
        init_db()
        conn = get_connection()
        cur = conn.execute(
            """
            INSERT INTO imports (source_type, query_id, import_started_at, status)
            VALUES (?, ?, datetime('now'), ?)
            """,
            ("ibkr_flex", "test", "success"),
        )
        self.import_id = cur.lastrowid
        conn.commit()
        conn.close()

    def tearDown(self) -> None:
        os.environ.pop("TJ_DB_PATH", None)
        self.tmpdir.cleanup()

    def test_parse_flex_xml_captures_order_reference(self) -> None:
        fills = parse_flex_xml(ORDER_REFERENCE_XML)
        self.assertEqual(1, len(fills))
        self.assertEqual("IC-REF-1", fills[0]["order_reference"])

    def test_rebuild_option_strategies_prefers_order_reference_grouping(self) -> None:
        conn = get_connection()
        fills = [
            (
                "EX201",
                "ORD201",
                "IC-REF-2",
                "SPY 260417P00500000",
                "SPY",
                "BUY",
                1.0,
                1.20,
                "2026-03-21T10:15:00",
            ),
            (
                "EX202",
                "ORD202",
                "IC-REF-2",
                "SPY 260417P00510000",
                "SPY",
                "SELL",
                1.0,
                2.05,
                "2026-03-21T10:15:01",
            ),
            (
                "EX203",
                "ORD203",
                "IC-REF-2",
                "SPY 260417C00530000",
                "SPY",
                "SELL",
                1.0,
                2.10,
                "2026-03-21T10:15:02",
            ),
            (
                "EX204",
                "ORD204",
                "IC-REF-2",
                "SPY 260417C00540000",
                "SPY",
                "BUY",
                1.0,
                1.05,
                "2026-03-21T10:15:03",
            ),
        ]
        self._insert_option_fills(conn, fills)
        conn.commit()
        conn.close()

        strategies = rebuild_option_strategies()
        self.assertEqual(1, strategies)

        conn = get_connection()
        strategy = conn.execute(
            """
            SELECT grouping_method, order_reference, fallback_order_id, leg_count
            FROM opt_strategy
            """
        ).fetchone()
        classified = conn.execute(
            """
            SELECT tastytrade_label
            FROM v_opt_strategy_classified
            """
        ).fetchone()
        conn.close()

        self.assertEqual("order_reference", strategy["grouping_method"])
        self.assertEqual("IC-REF-2", strategy["order_reference"])
        self.assertIsNone(strategy["fallback_order_id"])
        self.assertEqual(4, strategy["leg_count"])
        self.assertEqual("Iron Condor", classified["tastytrade_label"])

    def test_rebuild_option_strategies_uses_fallback_when_order_reference_missing(self) -> None:
        conn = get_connection()
        fills = [
            (
                "EX301",
                "ORD301",
                "",
                "TSLA 260404C00250000",
                "TSLA",
                "BUY",
                1.0,
                8.20,
                "2026-03-21T09:55:00",
            ),
            (
                "EX302",
                "ORD301",
                "   ",
                "TSLA 260404C00260000",
                "TSLA",
                "SELL",
                1.0,
                4.80,
                "2026-03-21T09:55:00",
            ),
        ]
        self._insert_option_fills(conn, fills)
        conn.commit()
        conn.close()

        strategies = rebuild_option_strategies()
        self.assertEqual(1, strategies)

        conn = get_connection()
        strategy = conn.execute(
            """
            SELECT grouping_method, order_reference, fallback_order_id, fallback_close_timestamp, leg_count
            FROM opt_strategy
            """
        ).fetchone()
        classified = conn.execute(
            """
            SELECT tastytrade_label, net_premium
            FROM v_opt_strategy_classified
            """
        ).fetchone()
        conn.close()

        self.assertEqual("fallback", strategy["grouping_method"])
        self.assertIsNone(strategy["order_reference"])
        self.assertEqual("ORD301", strategy["fallback_order_id"])
        self.assertEqual("2026-03-21T09:55:00", strategy["fallback_close_timestamp"])
        self.assertEqual(2, strategy["leg_count"])
        self.assertEqual("Call Debit Spread", classified["tastytrade_label"])
        self.assertAlmostEqual(3.4, classified["net_premium"])

    def test_classifies_call_calendar(self) -> None:
        label = self._rebuild_and_fetch_label(
            "CAL-REF-1",
            [
                ("EX401", "ORD401", "CAL-REF-1", "SPY 260417C00520000", "SPY", "SELL", 1.0, 2.10, "2026-03-21T10:00:00"),
                ("EX402", "ORD402", "CAL-REF-1", "SPY 260515C00520000", "SPY", "BUY", 1.0, 3.40, "2026-03-21T10:00:01"),
            ],
        )
        self.assertEqual("Call Calendar", label)

    def test_classifies_put_diagonal(self) -> None:
        label = self._rebuild_and_fetch_label(
            "DIA-REF-1",
            [
                ("EX411", "ORD411", "DIA-REF-1", "QQQ 260417P00480000", "QQQ", "SELL", 1.0, 2.45, "2026-03-21T10:05:00"),
                ("EX412", "ORD412", "DIA-REF-1", "QQQ 260515P00470000", "QQQ", "BUY", 1.0, 2.90, "2026-03-21T10:05:01"),
            ],
        )
        self.assertEqual("Put Diagonal", label)

    def test_classifies_collar(self) -> None:
        label = self._rebuild_and_fetch_label(
            "COL-REF-1",
            [
                ("EX421", "ORD421", "COL-REF-1", "AAPL 260417P00190000", "AAPL", "BUY", 1.0, 2.20, "2026-03-21T10:10:00"),
                ("EX422", "ORD422", "COL-REF-1", "AAPL 260417C00210000", "AAPL", "SELL", 1.0, 2.30, "2026-03-21T10:10:01"),
            ],
        )
        self.assertEqual("Collar", label)

    def test_classifies_call_ratio_spread(self) -> None:
        label = self._rebuild_and_fetch_label(
            "RATIO-REF-1",
            [
                ("EX431", "ORD431", "RATIO-REF-1", "TSLA 260417C00250000", "TSLA", "BUY", 1.0, 8.10, "2026-03-21T10:15:00"),
                ("EX432", "ORD432", "RATIO-REF-1", "TSLA 260417C00260000", "TSLA", "SELL", 2.0, 4.20, "2026-03-21T10:15:01"),
            ],
        )
        self.assertEqual("Call Ratio Spread", label)

    def test_classifies_jade_lizard(self) -> None:
        label = self._rebuild_and_fetch_label(
            "JADE-REF-1",
            [
                ("EX441", "ORD441", "JADE-REF-1", "SPY 260417P00500000", "SPY", "BUY", 1.0, 1.00, "2026-03-21T10:20:00"),
                ("EX442", "ORD442", "JADE-REF-1", "SPY 260417P00510000", "SPY", "SELL", 1.0, 1.80, "2026-03-21T10:20:01"),
                ("EX443", "ORD443", "JADE-REF-1", "SPY 260417C00530000", "SPY", "SELL", 1.0, 0.90, "2026-03-21T10:20:02"),
            ],
        )
        self.assertEqual("Jade Lizard", label)

    def test_classifies_broken_wing_call_butterfly(self) -> None:
        label = self._rebuild_and_fetch_label(
            "BWB-REF-1",
            [
                ("EX451", "ORD451", "BWB-REF-1", "SPY 260417C00500000", "SPY", "BUY", 1.0, 5.40, "2026-03-21T10:25:00"),
                ("EX452", "ORD452", "BWB-REF-1", "SPY 260417C00510000", "SPY", "SELL", 2.0, 2.70, "2026-03-21T10:25:01"),
                ("EX453", "ORD453", "BWB-REF-1", "SPY 260417C00525000", "SPY", "BUY", 1.0, 1.10, "2026-03-21T10:25:02"),
            ],
        )
        self.assertEqual("Broken-Wing Call Butterfly", label)

    def test_classifies_broken_wing_iron_condor(self) -> None:
        label = self._rebuild_and_fetch_label(
            "BWIC-REF-1",
            [
                ("EX461", "ORD461", "BWIC-REF-1", "SPY 260417P00500000", "SPY", "BUY", 1.0, 0.95, "2026-03-21T10:30:00"),
                ("EX462", "ORD462", "BWIC-REF-1", "SPY 260417P00510000", "SPY", "SELL", 1.0, 1.75, "2026-03-21T10:30:01"),
                ("EX463", "ORD463", "BWIC-REF-1", "SPY 260417C00530000", "SPY", "SELL", 1.0, 1.60, "2026-03-21T10:30:02"),
                ("EX464", "ORD464", "BWIC-REF-1", "SPY 260417C00545000", "SPY", "BUY", 1.0, 0.80, "2026-03-21T10:30:03"),
            ],
        )
        self.assertEqual("Broken-Wing Iron Condor", label)

    def _rebuild_and_fetch_label(self, order_reference: str, fills: list[tuple]) -> str:
        conn = get_connection()
        self._insert_option_fills(conn, fills)
        conn.commit()
        conn.close()

        rebuild_option_strategies()

        conn = get_connection()
        row = conn.execute(
            """
            SELECT tastytrade_label
            FROM v_opt_strategy_classified
            WHERE order_reference = ?
            """,
            (order_reference,),
        ).fetchone()
        conn.close()
        self.assertIsNotNone(row)
        return row["tastytrade_label"]

    def _insert_option_fills(self, conn, fills: list[tuple]) -> None:
        for broker_execution_id, broker_order_id, order_reference, symbol, underlying_symbol, side, quantity, price, execution_timestamp in fills:
            conn.execute(
                """
                INSERT INTO fills (
                    import_id, broker_account_id, broker_account_name, conid,
                    broker_execution_id, broker_order_id, order_reference,
                    symbol, underlying_symbol, security_type, side, quantity,
                    price, execution_timestamp, commission, fees, currency,
                    exchange, raw_payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    self.import_id,
                    "U1111111",
                    "Main",
                    None,
                    broker_execution_id,
                    broker_order_id,
                    order_reference,
                    symbol,
                    underlying_symbol,
                    "OPT",
                    side,
                    quantity,
                    price,
                    execution_timestamp,
                    0.0,
                    0.0,
                    "USD",
                    "CBOE",
                    "{}",
                ),
            )


if __name__ == "__main__":
    unittest.main()
