"""
Trade reconstruction engine.
Groups fills into journal-level trades.
Supports: stock/ETF, single-leg options, vertical spreads.
Never merges fills across different broker accounts.
"""

import hashlib
from collections import defaultdict
from datetime import datetime

from database import get_connection
from option_parser import parse_ibkr_option_symbol


def reconstruct_all_new():
    """Find unassigned fills and reconstruct trades from them."""
    conn = get_connection()

    # Get fills not yet assigned to any trade
    unassigned = conn.execute("""
        SELECT f.* FROM fills f
        LEFT JOIN trade_fills tf ON f.id = tf.fill_id
        WHERE tf.fill_id IS NULL
        ORDER BY f.broker_account_id, f.symbol, f.execution_timestamp
    """).fetchall()

    if not unassigned:
        conn.close()
        return {"trades_created": 0, "fills_assigned": 0}

    fills = [dict(f) for f in unassigned]

    # Partition by account — NEVER merge across accounts
    by_account = defaultdict(list)
    for f in fills:
        by_account[f["broker_account_id"]].append(f)

    total_trades = 0
    total_fills = 0

    for account_id, account_fills in by_account.items():
        # Separate stocks from options
        stock_fills = [f for f in account_fills if f["security_type"] in ("STK", "")]
        option_fills = [f for f in account_fills if f["security_type"] == "OPT"]

        # Reconstruct stocks
        t, f = _reconstruct_stocks(conn, stock_fills, account_id)
        total_trades += t
        total_fills += f

        # Reconstruct options (single-leg + spreads)
        t, f = _reconstruct_options(conn, option_fills, account_id)
        total_trades += t
        total_fills += f

    conn.close()
    return {"trades_created": total_trades, "fills_assigned": total_fills}


def _reconstruct_stocks(conn, fills: list[dict], account_id: str) -> tuple[int, int]:
    """Reconstruct stock trades from fills."""
    if not fills:
        return 0, 0

    trades_created = 0
    fills_assigned = 0

    # Group by symbol
    by_symbol = defaultdict(list)
    for f in fills:
        by_symbol[f["symbol"]].append(f)

    for symbol, sym_fills in by_symbol.items():
        sym_fills.sort(key=lambda x: x["execution_timestamp"])

        # Group into open/close actions
        open_fills = []
        close_fills = []
        direction = None

        for f in sym_fills:
            if not direction:
                direction = "long" if f["side"] == "BUY" else "short"
                open_fills.append(f)
            elif (direction == "long" and f["side"] == "SELL") or \
                 (direction == "short" and f["side"] == "BUY"):
                close_fills.append(f)
            else:
                open_fills.append(f)

        if open_fills and close_fills:
            tid = _create_trade(
                conn, account_id, open_fills[0].get("broker_account_name", ""),
                symbol, symbol, "stock", None, direction,
                open_fills, close_fills, multiplier=1
            )
            if tid:
                trades_created += 1
                fills_assigned += len(open_fills) + len(close_fills)
        elif open_fills:
            tid = _create_open_trade(
                conn, account_id, open_fills[0].get("broker_account_name", ""),
                symbol, symbol, "stock", None, direction or "long", open_fills, multiplier=1
            )
            if tid:
                trades_created += 1
                fills_assigned += len(open_fills)

    return trades_created, fills_assigned


def _reconstruct_options(conn, fills: list[dict], account_id: str) -> tuple[int, int]:
    """Reconstruct option trades including vertical spread detection."""
    if not fills:
        return 0, 0

    trades_created = 0
    fills_assigned = 0

    by_underlying = defaultdict(list)
    for f in fills:
        by_underlying[f["underlying_symbol"]].append(f)

    for underlying, uf in by_underlying.items():
        uf.sort(key=lambda x: x["execution_timestamp"])

        spread_pairs, remaining = _detect_spreads(uf)

        for long_fills, short_fills in spread_pairs:
            t, f = _create_spread_trade(conn, account_id, underlying, long_fills, short_fills)
            trades_created += t
            fills_assigned += f

        t, f = _reconstruct_single_options(conn, remaining, account_id)
        trades_created += t
        fills_assigned += f

    return trades_created, fills_assigned


def _detect_spreads(fills: list[dict]) -> tuple[list, list]:
    """Detect vertical spreads from option fills."""
    spread_pairs = []
    used = set()
    remaining = []

    for i, f1 in enumerate(fills):
        if i in used:
            continue
        for j, f2 in enumerate(fills):
            if j in used or j <= i:
                continue
            if _is_spread_pair(f1, f2):
                if f1["side"] == "BUY":
                    spread_pairs.append(([f1], [f2]))
                else:
                    spread_pairs.append(([f2], [f1]))
                used.add(i)
                used.add(j)
                break

    for i, f in enumerate(fills):
        if i not in used:
            remaining.append(f)

    return spread_pairs, remaining


def _is_spread_pair(f1: dict, f2: dict) -> bool:
    """
    Check if two option fills form a vertical spread.

    Primary checks (always applied):
      - Same underlying symbol
      - Opposite sides (one BUY, one SELL)
      - Within 60 seconds of each other

    Enhanced check (applied when symbols are parseable):
      - Same expiry date  (different expiries = calendar spread, not vertical)
      - Different strikes (same strike = not a spread)
    """
    if f1["underlying_symbol"] != f2["underlying_symbol"]:
        return False
    if f1["side"] == f2["side"]:
        return False
    try:
        t1 = datetime.fromisoformat(f1["execution_timestamp"])
        t2 = datetime.fromisoformat(f2["execution_timestamp"])
        if abs((t1 - t2).total_seconds()) > 60:
            return False
    except (ValueError, TypeError):
        return False

    # Enhanced matching using parsed option symbols
    p1 = parse_ibkr_option_symbol(f1.get("symbol", ""))
    p2 = parse_ibkr_option_symbol(f2.get("symbol", ""))
    if p1 and p2:
        # Must share the same expiry (vertical spread, not calendar)
        if p1["expiry"] != p2["expiry"]:
            return False
        # Must have different strikes (otherwise it's not a spread)
        if abs(p1["strike"] - p2["strike"]) < 0.001:
            return False

    return True


def _create_spread_trade(conn, account_id, underlying, long_fills, short_fills):
    """Create a vertical spread trade from matched legs."""
    all_fills = long_fills + short_fills
    account_name = all_fills[0].get("broker_account_name", "")

    long_avg = sum(f["price"] * f["quantity"] for f in long_fills) / sum(f["quantity"] for f in long_fills)
    short_avg = sum(f["price"] * f["quantity"] for f in short_fills) / sum(f["quantity"] for f in short_fills)
    net_premium = long_avg - short_avg
    direction = "debit" if net_premium > 0 else "credit"

    contracts = sum(f["quantity"] for f in long_fills)
    total_fees = sum(f["commission"] + f["fees"] for f in all_fills)
    entry_time = min(f["execution_timestamp"] for f in all_fills)
    symbol = f"{underlying} spread"

    strategy_type = "vertical_spread"
    trade_code = _generate_trade_code(account_id, symbol, entry_time)

    cur = conn.execute("""
        INSERT INTO trades (
            trade_code, broker_account_id, broker_account_name,
            trade_type, strategy_type, symbol, underlying_symbol,
            direction, status, entry_datetime, entry_price_avg,
            quantity_or_contracts, total_fees, review_status
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        trade_code, account_id, account_name,
        "spread", strategy_type, symbol, underlying,
        direction, "open", entry_time, abs(net_premium),
        contracts, total_fees, "pending"
    ))
    trade_id = cur.lastrowid

    # Create trade_legs — include parsed option data if available
    for i, fills in enumerate([long_fills, short_fills], 1):
        avg_price = sum(f["price"] * f["quantity"] for f in fills) / sum(f["quantity"] for f in fills)
        parsed = parse_ibkr_option_symbol(fills[0].get("symbol", ""))
        opt_type = parsed["option_type"] if parsed else None
        strike   = parsed["strike"]      if parsed else None
        expiry   = parsed["expiry"]      if parsed else None
        conn.execute("""
            INSERT INTO trade_legs (
                trade_id, leg_index, side, open_price_avg, contracts,
                option_type, strike, expiry
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            trade_id, i, fills[0]["side"], avg_price,
            sum(f["quantity"] for f in fills),
            opt_type, strike, expiry
        ))

    # Link fills
    for f in all_fills:
        conn.execute(
            "INSERT OR IGNORE INTO trade_fills (trade_id, fill_id, role) VALUES (?, ?, ?)",
            (trade_id, f["id"], "open")
        )

    conn.commit()
    return 1, len(all_fills)


def _reconstruct_single_options(conn, fills: list[dict], account_id: str) -> tuple[int, int]:
    """Reconstruct single-leg option trades."""
    if not fills:
        return 0, 0

    trades_created = 0
    fills_assigned = 0

    by_symbol = defaultdict(list)
    for f in fills:
        by_symbol[f["symbol"]].append(f)

    for symbol, sym_fills in by_symbol.items():
        sym_fills.sort(key=lambda x: x["execution_timestamp"])
        open_fills = []
        close_fills = []
        direction = None

        for f in sym_fills:
            if not direction:
                direction = "long" if f["side"] == "BUY" else "short"
                open_fills.append(f)
            elif (direction == "long" and f["side"] == "SELL") or \
                 (direction == "short" and f["side"] == "BUY"):
                close_fills.append(f)
            else:
                open_fills.append(f)

        underlying = sym_fills[0]["underlying_symbol"]
        account_name = sym_fills[0].get("broker_account_name", "")
        strategy = f"{direction}_option" if direction else "option"

        if open_fills and close_fills:
            tid = _create_trade(
                conn, account_id, account_name, symbol, underlying,
                "option", strategy, direction or "long",
                open_fills, close_fills, multiplier=100
            )
            if tid:
                trades_created += 1
                fills_assigned += len(open_fills) + len(close_fills)
        elif open_fills:
            tid = _create_open_trade(
                conn, account_id, account_name, symbol, underlying,
                "option", strategy, direction or "long", open_fills, multiplier=100
            )
            if tid:
                trades_created += 1
                fills_assigned += len(open_fills)

    return trades_created, fills_assigned


def _create_trade(conn, account_id, account_name, symbol, underlying,
                  trade_type, strategy_type, direction,
                  open_fills, close_fills, multiplier=1) -> int | None:
    """Create a completed trade record with P&L calculation."""
    entry_avg = sum(f["price"] * f["quantity"] for f in open_fills) / sum(f["quantity"] for f in open_fills)
    exit_avg = sum(f["price"] * f["quantity"] for f in close_fills) / sum(f["quantity"] for f in close_fills)
    quantity = sum(f["quantity"] for f in open_fills)
    total_fees = sum(f["commission"] + f["fees"] for f in open_fills + close_fills)

    dir_sign = 1 if direction == "long" else -1
    gross_pnl = (exit_avg - entry_avg) * quantity * multiplier * dir_sign
    net_pnl = gross_pnl - total_fees

    entry_time = min(f["execution_timestamp"] for f in open_fills)
    exit_time = max(f["execution_timestamp"] for f in close_fills)

    try:
        dt_entry = datetime.fromisoformat(entry_time)
        dt_exit = datetime.fromisoformat(exit_time)
        holding_minutes = int((dt_exit - dt_entry).total_seconds() / 60)
        holding_days = holding_minutes / 1440
        same_day = dt_entry.date() == dt_exit.date()
    except (ValueError, TypeError):
        holding_minutes = 0
        holding_days = 0
        same_day = False

    scale_in = len(_group_by_time(open_fills)) > 1
    scale_out = len(_group_by_time(close_fills)) > 1
    trade_code = _generate_trade_code(account_id, symbol, entry_time)

    cur = conn.execute("""
        INSERT INTO trades (
            trade_code, broker_account_id, broker_account_name,
            trade_type, strategy_type, symbol, underlying_symbol,
            direction, status, entry_datetime, exit_datetime,
            entry_price_avg, exit_price_avg, quantity_or_contracts,
            gross_pnl, net_pnl, total_fees,
            holding_minutes, holding_days, same_day_trade_flag,
            scale_in_flag, scale_out_flag, review_status
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        trade_code, account_id, account_name,
        trade_type, strategy_type, symbol, underlying,
        direction, "closed", entry_time, exit_time,
        entry_avg, exit_avg, quantity,
        round(gross_pnl, 2), round(net_pnl, 2), round(total_fees, 2),
        holding_minutes, round(holding_days, 2), 1 if same_day else 0,
        1 if scale_in else 0, 1 if scale_out else 0, "pending"
    ))
    trade_id = cur.lastrowid

    for f in open_fills:
        conn.execute("INSERT OR IGNORE INTO trade_fills (trade_id, fill_id, role) VALUES (?, ?, ?)",
                      (trade_id, f["id"], "open"))
    for f in close_fills:
        conn.execute("INSERT OR IGNORE INTO trade_fills (trade_id, fill_id, role) VALUES (?, ?, ?)",
                      (trade_id, f["id"], "close"))

    conn.commit()
    return trade_id


def _create_open_trade(conn, account_id, account_name, symbol, underlying,
                       trade_type, strategy_type, direction, open_fills, multiplier=1) -> int | None:
    """Create an open (not yet closed) trade."""
    entry_avg = sum(f["price"] * f["quantity"] for f in open_fills) / sum(f["quantity"] for f in open_fills)
    quantity = sum(f["quantity"] for f in open_fills)
    total_fees = sum(f["commission"] + f["fees"] for f in open_fills)
    entry_time = min(f["execution_timestamp"] for f in open_fills)
    trade_code = _generate_trade_code(account_id, symbol, entry_time)

    cur = conn.execute("""
        INSERT INTO trades (
            trade_code, broker_account_id, broker_account_name,
            trade_type, strategy_type, symbol, underlying_symbol,
            direction, status, entry_datetime, entry_price_avg,
            quantity_or_contracts, total_fees, review_status
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        trade_code, account_id, account_name,
        trade_type, strategy_type, symbol, underlying,
        direction, "open", entry_time, entry_avg,
        quantity, round(total_fees, 2), "pending"
    ))
    trade_id = cur.lastrowid

    for f in open_fills:
        conn.execute("INSERT OR IGNORE INTO trade_fills (trade_id, fill_id, role) VALUES (?, ?, ?)",
                      (trade_id, f["id"], "open"))

    conn.commit()
    return trade_id


def _group_by_time(fills: list[dict]) -> list[list[dict]]:
    """Group fills by time proximity (2-second window)."""
    if not fills:
        return []
    groups = []
    current = [fills[0]]
    for i in range(1, len(fills)):
        prev = fills[i - 1]
        curr = fills[i]
        try:
            t1 = datetime.fromisoformat(prev["execution_timestamp"])
            t2 = datetime.fromisoformat(curr["execution_timestamp"])
            if abs((t2 - t1).total_seconds()) <= 2 and prev["side"] == curr["side"]:
                current.append(curr)
            else:
                groups.append(current)
                current = [curr]
        except (ValueError, TypeError):
            groups.append(current)
            current = [curr]
    groups.append(current)
    return groups


def _generate_trade_code(account_id: str, symbol: str, timestamp: str) -> str:
    """Generate a unique trade code."""
    raw = f"{account_id}:{symbol}:{timestamp}:{datetime.now().isoformat()}"
    return hashlib.md5(raw.encode()).hexdigest()[:12].upper()
