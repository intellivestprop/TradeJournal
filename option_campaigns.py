"""
Option campaign materialization for Phase 2.

Builds campaign headers and event rows from option strategies so reporting views
can expose premium-bank, break-even, size, and realised P&L summaries.
"""

from __future__ import annotations

import argparse
from collections import defaultdict

from database import get_connection, init_db


EPSILON = 1e-9
CONTRACT_MULTIPLIER = 100.0


def rebuild_option_campaigns() -> int:
    """Rebuild opt_campaign, opt_campaign_event, and opt_campaign_event_leg."""
    conn = get_connection()
    conn.execute("DELETE FROM opt_campaign_event_leg")
    conn.execute("DELETE FROM opt_campaign_event")
    conn.execute("DELETE FROM opt_campaign")

    slices = _load_strategy_slices(conn)
    campaign_count = 0

    for signature in sorted(slices):
        active_campaigns: dict[str, dict] = {}
        created_for_signature = 0

        for slice_data in slices[signature]:
            event_side = slice_data["event_side"]
            event_contracts = slice_data["event_contracts"]
            if event_contracts <= EPSILON:
                continue

            campaign = None
            delta_contracts = event_contracts

            opposite_side = "BUY" if event_side == "SELL" else "SELL"
            opposite_campaign = active_campaigns.get(opposite_side)
            if opposite_campaign and opposite_campaign["current_net_contracts"] > EPSILON:
                campaign = opposite_campaign
                delta_contracts = -event_contracts
            else:
                same_campaign = active_campaigns.get(event_side)
                if same_campaign and same_campaign["current_net_contracts"] > EPSILON:
                    campaign = same_campaign
                else:
                    created_for_signature += 1
                    campaign = _create_campaign(conn, slice_data, created_for_signature)
                    active_campaigns[event_side] = campaign

            event_id = _insert_event(conn, campaign, slice_data, delta_contracts)
            _link_event_legs(conn, event_id, slice_data["strategy_leg_ids"])

            campaign["event_index"] += 1
            campaign["current_net_contracts"] = round(
                campaign["current_net_contracts"] + delta_contracts,
                8,
            )
            campaign["closed_at"] = slice_data["event_timestamp"]
            if campaign["current_net_contracts"] <= EPSILON:
                campaign["current_net_contracts"] = 0.0
                campaign["status"] = "closed"
                active_campaigns.pop(campaign["side"], None)
            else:
                campaign["status"] = "open"

            conn.execute(
                """
                UPDATE opt_campaign
                SET closed_at = ?, status = ?
                WHERE id = ?
                """,
                (campaign["closed_at"], campaign["status"], campaign["id"]),
            )

        campaign_count += created_for_signature

    conn.commit()
    conn.close()
    return campaign_count


def _load_strategy_slices(conn) -> dict[tuple[str, str, str], list[dict]]:
    rows = conn.execute(
        """
        SELECT
            s.id AS strategy_id,
            s.broker_account_id,
            s.broker_account_name,
            s.underlying_symbol,
            l.id AS strategy_leg_id,
            l.fill_id,
            l.option_type,
            l.side,
            l.strike,
            l.expiry,
            l.quantity,
            l.price,
            l.execution_timestamp,
            COALESCE(f.commission, 0) AS commission,
            COALESCE(f.fees, 0) AS fees,
            cls.tastytrade_label
        FROM opt_strategy s
        JOIN opt_strategy_leg l ON l.strategy_id = s.id
        LEFT JOIN fills f ON f.id = l.fill_id
        LEFT JOIN v_opt_strategy_classified cls ON cls.strategy_id = s.id
        WHERE l.option_type IN ('call', 'put')
        ORDER BY
            s.broker_account_id,
            s.underlying_symbol,
            l.option_type,
            l.execution_timestamp,
            s.id,
            l.id
        """
    ).fetchall()

    grouped: dict[tuple[int, str], list[dict]] = defaultdict(list)
    for row in rows:
        grouped[(row["strategy_id"], row["option_type"])].append(dict(row))

    slices: dict[tuple[str, str, str], list[dict]] = defaultdict(list)
    for (_strategy_id, option_type), legs in grouped.items():
        first = legs[0]
        event_side = _resolve_event_side(legs)
        event_contracts = round(
            sum(float(leg["quantity"] or 0) for leg in legs if leg["side"] == event_side),
            8,
        )
        primary_legs = [leg for leg in legs if leg["side"] == event_side]
        primary_strike = None
        if primary_legs and event_contracts > EPSILON:
            primary_strike = round(
                sum(float(leg["strike"] or 0) * float(leg["quantity"] or 0) for leg in primary_legs)
                / event_contracts,
                8,
            )

        event_net_cash_flow = round(
            sum(_leg_net_cash_flow(leg) for leg in legs),
            8,
        )
        slice_data = {
            "strategy_id": first["strategy_id"],
            "broker_account_id": first["broker_account_id"],
            "broker_account_name": first["broker_account_name"],
            "underlying_symbol": first["underlying_symbol"],
            "option_type": option_type,
            "event_timestamp": max(leg["execution_timestamp"] for leg in legs),
            "event_side": event_side,
            "event_contracts": event_contracts,
            "event_primary_strike": primary_strike,
            "event_net_cash_flow": event_net_cash_flow,
            "strategy_leg_ids": [leg["strategy_leg_id"] for leg in legs],
        }
        slices[(first["broker_account_id"], first["underlying_symbol"], option_type)].append(slice_data)

    for grouped_slices in slices.values():
        grouped_slices.sort(key=lambda item: (item["event_timestamp"], item["strategy_id"]))

    return slices


def _resolve_event_side(legs: list[dict]) -> str:
    label = (legs[0].get("tastytrade_label") or "").strip()
    if any(token in label for token in ("Credit", "Short", "Condor", "Jade Lizard", "Collar")):
        return "SELL"
    if any(token in label for token in ("Debit", "Long", "Calendar", "Diagonal", "Butterfly")):
        return "BUY"

    sell_premium = sum(
        float(leg["price"] or 0) * float(leg["quantity"] or 0)
        for leg in legs
        if leg["side"] == "SELL"
    )
    buy_premium = sum(
        float(leg["price"] or 0) * float(leg["quantity"] or 0)
        for leg in legs
        if leg["side"] == "BUY"
    )
    return "SELL" if sell_premium >= buy_premium else "BUY"


def _leg_net_cash_flow(leg: dict) -> float:
    gross = float(leg["price"] or 0) * float(leg["quantity"] or 0) * CONTRACT_MULTIPLIER
    signed = gross if leg["side"] == "SELL" else -gross
    costs = float(leg["commission"] or 0) + float(leg["fees"] or 0)
    return signed - costs


def _create_campaign(conn, slice_data: dict, sequence_number: int) -> dict:
    campaign_key = (
        f"{slice_data['broker_account_id']}:{slice_data['underlying_symbol']}:"
        f"{slice_data['option_type']}:{slice_data['event_side']}:{sequence_number}"
    )
    cur = conn.execute(
        """
        INSERT INTO opt_campaign (
            campaign_key, broker_account_id, broker_account_name, underlying_symbol,
            option_type, side, opened_at, closed_at, status
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            campaign_key,
            slice_data["broker_account_id"],
            slice_data["broker_account_name"],
            slice_data["underlying_symbol"],
            slice_data["option_type"],
            slice_data["event_side"],
            slice_data["event_timestamp"],
            slice_data["event_timestamp"],
            "open",
        ),
    )
    return {
        "id": cur.lastrowid,
        "side": slice_data["event_side"],
        "event_index": 1,
        "current_net_contracts": 0.0,
        "closed_at": slice_data["event_timestamp"],
        "status": "open",
    }


def _insert_event(conn, campaign: dict, slice_data: dict, delta_contracts: float) -> int:
    cur = conn.execute(
        """
        INSERT INTO opt_campaign_event (
            campaign_id, strategy_id, option_type, event_index, event_timestamp,
            event_side, delta_contracts, event_contracts, event_primary_strike,
            event_net_cash_flow
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            campaign["id"],
            slice_data["strategy_id"],
            slice_data["option_type"],
            campaign["event_index"],
            slice_data["event_timestamp"],
            slice_data["event_side"],
            delta_contracts,
            slice_data["event_contracts"],
            slice_data["event_primary_strike"],
            slice_data["event_net_cash_flow"],
        ),
    )
    return cur.lastrowid


def _link_event_legs(conn, event_id: int, strategy_leg_ids: list[int]) -> None:
    for strategy_leg_id in strategy_leg_ids:
        conn.execute(
            """
            INSERT INTO opt_campaign_event_leg (event_id, strategy_leg_id)
            VALUES (?, ?)
            """,
            (event_id, strategy_leg_id),
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="Rebuild option campaigns from option strategies.")
    parser.parse_args()

    init_db()
    campaigns = rebuild_option_campaigns()
    print(f"Rebuilt {campaigns} option campaigns.")


if __name__ == "__main__":
    main()
