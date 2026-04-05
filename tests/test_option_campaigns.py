import os
import tempfile
import unittest

import database
from database import get_connection, init_db
from option_campaigns import rebuild_option_campaigns
from option_strategies import rebuild_option_strategies


class OptionCampaignTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmpdir.name, "trade_journal.db")
        os.environ["TJ_DB_PATH"] = self.db_path
        database.DB_PATH = self.db_path
        init_db()

    def tearDown(self) -> None:
        os.environ.pop("TJ_DB_PATH", None)
        self.tmpdir.cleanup()

    def test_summary_tracks_open_short_put_campaign(self) -> None:
        conn = get_connection()
        self._insert_option_fill(
            conn,
            execution_id="EX100",
            order_id="ORD100",
            order_reference="CAMP-OPEN-1",
            symbol="SPY 260417P00410000",
            underlying_symbol="SPY",
            side="SELL",
            quantity=1.0,
            price=2.00,
            executed_at="2026-03-21T10:00:00",
        )
        self._insert_option_fill(
            conn,
            execution_id="EX101",
            order_id="ORD101",
            order_reference="CAMP-OPEN-1",
            symbol="SPY 260417P00400000",
            underlying_symbol="SPY",
            side="BUY",
            quantity=1.0,
            price=0.80,
            executed_at="2026-03-21T10:00:01",
        )
        conn.commit()
        conn.close()

        rebuild_option_strategies()
        rebuild_option_campaigns()

        conn = get_connection()
        row = conn.execute(
            """
            SELECT option_be_price, stock_be_price, current_net_contracts,
                   cum_premium_bank_net, realised_pnl_net, campaign_status
            FROM v_opt_campaign_summary
            """
        ).fetchone()
        conn.close()

        self.assertAlmostEqual(408.8, row["option_be_price"])
        self.assertAlmostEqual(408.8, row["stock_be_price"])
        self.assertAlmostEqual(1.0, row["current_net_contracts"])
        self.assertAlmostEqual(120.0, row["cum_premium_bank_net"])
        self.assertAlmostEqual(0.0, row["realised_pnl_net"])
        self.assertEqual("open", row["campaign_status"])

    def test_summary_closes_campaign_and_realises_pnl(self) -> None:
        conn = get_connection()
        self._insert_short_put_credit_open(conn, "CAMP-OPEN-2", "2026-03-21T10:00:00")
        self._insert_option_fill(
            conn,
            execution_id="EX200",
            order_id="ORD200",
            order_reference="CAMP-CLOSE-2",
            symbol="SPY 260417P00410000",
            underlying_symbol="SPY",
            side="BUY",
            quantity=1.0,
            price=0.50,
            executed_at="2026-03-22T10:00:00",
        )
        self._insert_option_fill(
            conn,
            execution_id="EX201",
            order_id="ORD201",
            order_reference="CAMP-CLOSE-2",
            symbol="SPY 260417P00400000",
            underlying_symbol="SPY",
            side="SELL",
            quantity=1.0,
            price=0.20,
            executed_at="2026-03-22T10:00:01",
        )
        conn.commit()
        conn.close()

        rebuild_option_strategies()
        rebuild_option_campaigns()

        conn = get_connection()
        row = conn.execute(
            """
            SELECT current_net_contracts, cum_premium_bank_net,
                   realised_pnl_net, campaign_status, option_be_price
            FROM v_opt_campaign_summary
            """
        ).fetchone()
        conn.close()

        self.assertAlmostEqual(0.0, row["current_net_contracts"])
        self.assertAlmostEqual(90.0, row["cum_premium_bank_net"])
        self.assertAlmostEqual(90.0, row["realised_pnl_net"])
        self.assertEqual("closed", row["campaign_status"])
        self.assertIsNone(row["option_be_price"])

    def test_same_side_strategies_accumulate_into_one_campaign(self) -> None:
        conn = get_connection()
        self._insert_short_put_credit_open(conn, "CAMP-OPEN-3A", "2026-03-21T10:00:00")
        self._insert_option_fill(
            conn,
            execution_id="EX300",
            order_id="ORD300",
            order_reference="CAMP-OPEN-3B",
            symbol="SPY 260417P00410000",
            underlying_symbol="SPY",
            side="SELL",
            quantity=2.0,
            price=1.90,
            executed_at="2026-03-21T11:00:00",
        )
        self._insert_option_fill(
            conn,
            execution_id="EX301",
            order_id="ORD301",
            order_reference="CAMP-OPEN-3B",
            symbol="SPY 260417P00400000",
            underlying_symbol="SPY",
            side="BUY",
            quantity=2.0,
            price=1.00,
            executed_at="2026-03-21T11:00:01",
        )
        conn.commit()
        conn.close()

        rebuild_option_strategies()
        campaigns = rebuild_option_campaigns()

        conn = get_connection()
        row = conn.execute(
            """
            SELECT current_net_contracts, cum_premium_bank_net, option_be_price
            FROM v_opt_campaign_summary
            """
        ).fetchone()
        conn.close()

        self.assertEqual(1, campaigns)
        self.assertAlmostEqual(3.0, row["current_net_contracts"])
        self.assertAlmostEqual(300.0, row["cum_premium_bank_net"])
        self.assertAlmostEqual(409.0, row["option_be_price"])

    def _insert_short_put_credit_open(self, conn, order_reference: str, executed_at: str) -> None:
        self._insert_option_fill(
            conn,
            execution_id=f"{order_reference}-S",
            order_id=f"{order_reference}-S",
            order_reference=order_reference,
            symbol="SPY 260417P00410000",
            underlying_symbol="SPY",
            side="SELL",
            quantity=1.0,
            price=2.00,
            executed_at=executed_at,
        )
        self._insert_option_fill(
            conn,
            execution_id=f"{order_reference}-B",
            order_id=f"{order_reference}-B",
            order_reference=order_reference,
            symbol="SPY 260417P00400000",
            underlying_symbol="SPY",
            side="BUY",
            quantity=1.0,
            price=0.80,
            executed_at=self._plus_one_second(executed_at),
        )

    @staticmethod
    def _plus_one_second(timestamp: str) -> str:
        return timestamp[:-2] + "01"

    def _insert_option_fill(
        self,
        conn,
        *,
        execution_id: str,
        order_id: str,
        order_reference: str,
        symbol: str,
        underlying_symbol: str,
        side: str,
        quantity: float,
        price: float,
        executed_at: str,
    ) -> None:
        conn.execute(
            """
            INSERT INTO imports (source_type, query_id, import_started_at, status)
            VALUES ('ibkr_flex', ?, datetime('now'), 'success')
            """,
            (execution_id,),
        )
        import_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.execute(
            """
            INSERT INTO fills (
                import_id, broker_account_id, broker_account_name, conid,
                broker_execution_id, broker_order_id, order_reference, symbol,
                underlying_symbol, security_type, side, quantity, price,
                execution_timestamp, commission, fees, currency, exchange,
                raw_payload_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'OPT', ?, ?, ?, ?, 0, 0, 'USD', 'SMART', '{}')
            """,
            (
                import_id,
                "U1111111",
                "Main",
                None,
                execution_id,
                order_id,
                order_reference,
                symbol,
                underlying_symbol,
                side,
                quantity,
                price,
                executed_at,
            ),
        )


if __name__ == "__main__":
    unittest.main()
