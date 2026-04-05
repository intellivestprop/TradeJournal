"""
Option strategy materialization for Phase 2.

Groups option fills into strategy buckets using OrderReference when present,
otherwise falls back to IB order id + account + underlying + close timestamp.
"""

from __future__ import annotations

import argparse
from collections import defaultdict

from database import get_connection, init_db
from option_parser import parse_ibkr_option_symbol


def rebuild_option_strategies() -> int:
    """Rebuild opt_strategy and opt_strategy_leg from option fills."""
    conn = get_connection()
    conn.execute("DELETE FROM opt_strategy_leg")
    conn.execute("DELETE FROM opt_strategy")

    rows = conn.execute(
        """
        SELECT *
        FROM fills
        WHERE security_type = 'OPT'
        ORDER BY broker_account_id, execution_timestamp, id
        """
    ).fetchall()

    grouped: dict[tuple[str, ...], list[dict]] = defaultdict(list)
    for row in rows:
        fill = dict(row)
        grouped[_strategy_group_key(fill)].append(fill)

    strategies_created = 0
    for group_key in sorted(grouped):
        fills = sorted(grouped[group_key], key=lambda item: (item["execution_timestamp"], item["id"]))
        strategy_id = _insert_strategy(conn, group_key, fills)
        _insert_strategy_legs(conn, strategy_id, fills)
        strategies_created += 1

    conn.commit()
    conn.close()
    return strategies_created


def _strategy_group_key(fill: dict) -> tuple[str, ...]:
    order_reference = (fill.get("order_reference") or "").strip()
    broker_account_id = fill.get("broker_account_id") or ""
    underlying_symbol = fill.get("underlying_symbol") or fill.get("symbol") or ""
    close_timestamp = fill.get("execution_timestamp") or ""
    broker_order_id = fill.get("broker_order_id") or ""

    if order_reference:
        return ("order_reference", broker_account_id, order_reference)

    return ("fallback", broker_account_id, underlying_symbol, broker_order_id, close_timestamp)


def _insert_strategy(conn, group_key: tuple[str, ...], fills: list[dict]) -> int:
    grouping_method = group_key[0]
    first_fill = fills[0]
    broker_account_id = first_fill.get("broker_account_id") or ""
    broker_account_name = first_fill.get("broker_account_name") or ""
    underlying_symbol = first_fill.get("underlying_symbol") or first_fill.get("symbol") or ""
    order_reference = None
    fallback_order_id = None
    fallback_close_timestamp = None

    if grouping_method == "order_reference":
        order_reference = group_key[2]
        strategy_key = f"oref:{broker_account_id}:{order_reference}"
    else:
        fallback_order_id = group_key[3] or None
        fallback_close_timestamp = group_key[4] or None
        strategy_key = f"fallback:{broker_account_id}:{underlying_symbol}:{group_key[3]}:{group_key[4]}"

    opened_at = min(fill["execution_timestamp"] for fill in fills)
    closed_at = max(fill["execution_timestamp"] for fill in fills)
    total_contracts = sum(float(fill["quantity"] or 0) for fill in fills)
    net_premium = round(
        sum(
            (1 if fill["side"] == "BUY" else -1) * float(fill["price"] or 0) * float(fill["quantity"] or 0)
            for fill in fills
        ),
        8,
    )

    cur = conn.execute(
        """
        INSERT INTO opt_strategy (
            strategy_key, grouping_method, broker_account_id, broker_account_name,
            underlying_symbol, order_reference, fallback_order_id,
            fallback_close_timestamp, opened_at, closed_at, leg_count,
            total_contracts, net_premium
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            strategy_key,
            grouping_method,
            broker_account_id,
            broker_account_name,
            underlying_symbol,
            order_reference,
            fallback_order_id,
            fallback_close_timestamp,
            opened_at,
            closed_at,
            len(fills),
            total_contracts,
            net_premium,
        ),
    )
    return cur.lastrowid


def _insert_strategy_legs(conn, strategy_id: int, fills: list[dict]) -> None:
    for index, fill in enumerate(fills, start=1):
        parsed = parse_ibkr_option_symbol(fill.get("symbol", ""))
        conn.execute(
            """
            INSERT INTO opt_strategy_leg (
                strategy_id, fill_id, leg_index, broker_order_id, order_reference,
                symbol, underlying_symbol, option_type, side, strike, expiry,
                quantity, price, execution_timestamp, raw_payload_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                strategy_id,
                fill["id"],
                index,
                fill.get("broker_order_id"),
                (fill.get("order_reference") or "").strip() or None,
                fill["symbol"],
                fill.get("underlying_symbol") or fill["symbol"],
                (parsed or {}).get("option_type"),
                fill["side"],
                (parsed or {}).get("strike"),
                (parsed or {}).get("expiry"),
                fill["quantity"],
                fill["price"],
                fill["execution_timestamp"],
                fill.get("raw_payload_json"),
            ),
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="Rebuild option strategy groupings from imported fills.")
    parser.parse_args()

    init_db()
    strategies = rebuild_option_strategies()
    print(f"Rebuilt {strategies} option strategies.")


if __name__ == "__main__":
    main()
