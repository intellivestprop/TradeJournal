import os
import tempfile
import unittest

import database
from database import get_connection, get_schema_version, init_db


class DatabaseMigrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmpdir.name, "trade_journal.db")
        os.environ["TJ_DB_PATH"] = self.db_path
        database.DB_PATH = self.db_path

    def tearDown(self) -> None:
        os.environ.pop("TJ_DB_PATH", None)
        self.tmpdir.cleanup()

    def test_init_db_records_schema_version(self) -> None:
        init_db()

        conn = get_connection()
        migrations = conn.execute(
            "SELECT version, name FROM schema_migrations ORDER BY version"
        ).fetchall()
        conn.close()

        self.assertEqual(1, get_schema_version())
        self.assertEqual([(1, "initial_schema")], [(row["version"], row["name"]) for row in migrations])

    def test_rebuild_derived_drops_data_and_recreates_views(self) -> None:
        init_db()
        conn = get_connection()
        conn.execute(
            """
            INSERT INTO imports (source_type, query_id, import_started_at, status)
            VALUES ('ibkr_flex', 'seed', datetime('now'), 'success')
            """
        )
        import_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.execute(
            """
            INSERT INTO fills (
                import_id, broker_account_id, broker_account_name, broker_execution_id,
                broker_order_id, order_reference, symbol, underlying_symbol, security_type,
                side, quantity, price, execution_timestamp, raw_payload_json
            ) VALUES (?, 'U1111111', 'Main', 'EX1', 'ORD1', 'REF1',
                      'SPY 260417P00500000', 'SPY', 'OPT',
                      'SELL', 1, 2.15, '2026-03-21T10:00:00', '{}')
            """,
            (import_id,),
        )
        conn.execute(
            """
            INSERT INTO opt_strategy (
                strategy_key, grouping_method, broker_account_id, broker_account_name,
                underlying_symbol, order_reference, fallback_order_id, fallback_close_timestamp,
                opened_at, closed_at, leg_count, total_contracts, net_premium
            ) VALUES (
                'oref:U1111111:REF1', 'order_reference', 'U1111111', 'Main',
                'SPY', 'REF1', NULL, NULL,
                '2026-03-21T10:00:00', '2026-03-21T10:00:00', 1, 1, -2.15
            )
            """
        )
        strategy_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.execute(
            """
            INSERT INTO opt_strategy_leg (
                strategy_id, fill_id, leg_index, broker_order_id, order_reference,
                symbol, underlying_symbol, option_type, side, strike, expiry,
                quantity, price, execution_timestamp, raw_payload_json
            ) VALUES (?, 1, 1, 'ORD1', 'REF1',
                      'SPY 260417P00500000', 'SPY', 'put', 'SELL', 500, '2026-04-17',
                      1, 2.15, '2026-03-21T10:00:00', '{}')
            """,
            (strategy_id,),
        )
        conn.execute(
            """
            INSERT INTO pos_eod_from_trades (
                report_date, broker_account_id, broker_account_name, instrument_key,
                conid, symbol, underlying_symbol, security_type, quantity_eod, last_fill_timestamp
            ) VALUES (
                '2026-03-21', 'U1111111', 'Main', 'SPY 260417P00500000',
                NULL, 'SPY 260417P00500000', 'SPY', 'OPT', -1, '2026-03-21T10:00:00'
            )
            """
        )
        conn.commit()
        conn.close()

        init_db(rebuild_derived=True)

        conn = get_connection()
        strategy_count = conn.execute("SELECT COUNT(*) AS count FROM opt_strategy").fetchone()["count"]
        strategy_leg_count = conn.execute("SELECT COUNT(*) AS count FROM opt_strategy_leg").fetchone()["count"]
        pos_count = conn.execute("SELECT COUNT(*) AS count FROM pos_eod_from_trades").fetchone()["count"]
        view_row = conn.execute("SELECT COUNT(*) AS count FROM v_opt_strategy_classified").fetchone()
        conn.close()

        self.assertEqual(0, strategy_count)
        self.assertEqual(0, strategy_leg_count)
        self.assertEqual(0, pos_count)
        self.assertEqual(0, view_row["count"])


if __name__ == "__main__":
    unittest.main()
