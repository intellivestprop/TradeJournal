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

    # Populate options summary after initial creation
    populate_options_summary(trade_id, conn)
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


def match_close_fills_to_open_spreads(import_id: int) -> dict:
    """
    Match option fills from this import against existing open spread trades.

    Runs AFTER store_fills() so the new fills are in the DB but not yet
    assigned to any trade.  Uses a position-level approach:

      1. Parse each unassigned OPT fill to extract strike / expiry.
      2. Build a fill pool keyed by (account, underlying, strike, expiry,
         option_type, side).
      3. For each open spread whose legs have parsed strike/expiry, look for
         close fills (opposite side) for BOTH legs.
      4. If found, close the trade: update exit price, P&L, holding time,
         status.  Update trade_legs.close_price_avg.  Link fills via
         trade_fills with role='close' (FIFO allocation by contract qty).
      5. Handle partial closes: if close fills cover only some of the open
         contracts, set partial_exit_flag=1 and leave status='open'.

    Never matches across different broker accounts.

    Returns:
        {"trades_closed": int, "fills_assigned": int}
    """
    conn = get_connection()

    # ── 1. Unassigned OPT fills from this import ─────────────────────────
    rows = conn.execute("""
        SELECT f.* FROM fills f
        LEFT JOIN trade_fills tf ON f.id = tf.fill_id
        WHERE f.import_id = ?
          AND f.security_type = 'OPT'
          AND tf.fill_id IS NULL
        ORDER BY f.execution_timestamp
    """, (import_id,)).fetchall()

    if not rows:
        conn.close()
        return {"trades_closed": 0, "fills_assigned": 0}

    # ── 2. Parse fills → close-fill pool ─────────────────────────────────
    # Each pool bucket: list of {"fill": dict, "remaining_qty": float}
    close_pool: dict[tuple, list[dict]] = defaultdict(list)

    for row in rows:
        f = dict(row)
        parsed = parse_ibkr_option_symbol(f.get("symbol", ""))
        if not parsed:
            continue
        key = (
            f["broker_account_id"],
            parsed["underlying"],
            parsed["strike"],
            parsed["expiry"],
            parsed["option_type"],
            f["side"],
        )
        close_pool[key].append({"fill": f, "remaining_qty": f["quantity"]})

    if not close_pool:
        conn.close()
        return {"trades_closed": 0, "fills_assigned": 0}

    # ── 3. Open spread trades with fully-parsed legs ──────────────────────
    open_trades = conn.execute("""
        SELECT t.* FROM trades t
        WHERE t.trade_type = 'spread' AND t.status = 'open'
        ORDER BY t.entry_datetime
    """).fetchall()

    _OPP = {"BUY": "SELL", "SELL": "BUY"}
    trades_closed = 0
    fills_assigned = 0

    for trade_row in open_trades:
        trade = dict(trade_row)
        trade_id   = trade["id"]
        account_id = trade["broker_account_id"]
        underlying = trade["underlying_symbol"]
        contracts  = trade["quantity_or_contracts"]

        legs = [dict(l) for l in conn.execute(
            "SELECT * FROM trade_legs WHERE trade_id = ? ORDER BY leg_index",
            (trade_id,)
        ).fetchall()]

        if len(legs) != 2:
            continue
        if any(l["strike"] is None or l["expiry"] is None for l in legs):
            continue

        # ── 4a. Check close-fill availability for both legs ───────────────
        leg_close: dict[int, dict] = {}   # leg_index → close info
        can_close = True

        for leg in legs:
            ck = (account_id, underlying,
                  leg["strike"], leg["expiry"],
                  leg["option_type"], _OPP[leg["side"]])
            available = [e for e in close_pool.get(ck, []) if e["remaining_qty"] > 0]
            if not available:
                can_close = False
                break
            total_avail = sum(e["remaining_qty"] for e in available)
            leg_close[leg["leg_index"]] = {
                "leg":        leg,
                "close_key":  ck,
                "entries":    available,           # pool entries (mutable)
                "total_avail": total_avail,
            }

        if not can_close:
            continue

        # ── 4b. Determine how many contracts we can close ─────────────────
        min_avail = min(info["total_avail"] for info in leg_close.values())
        close_qty = min(contracts, min_avail)
        is_partial = close_qty < contracts

        # ── 4c. Consume fill pool and compute weighted-avg close prices ───
        allocated_fills: dict[int, list[tuple[dict, float]]] = defaultdict(list)
        # leg_index → [(fill_dict, qty_used), ...]

        for leg_idx, info in leg_close.items():
            qty_needed = close_qty
            for entry in info["entries"]:
                if qty_needed <= 0:
                    break
                take = min(entry["remaining_qty"], qty_needed)
                allocated_fills[leg_idx].append((entry["fill"], take))
                entry["remaining_qty"] -= take
                qty_needed -= take

        # Weighted-average close price per leg
        leg_close_price: dict[int, float] = {}
        for leg_idx, allocs in allocated_fills.items():
            total_val = sum(f["price"] * qty for f, qty in allocs)
            total_qty = sum(qty for _, qty in allocs)
            leg_close_price[leg_idx] = total_val / total_qty if total_qty else 0.0

        # ── 4d. Calculate P&L ─────────────────────────────────────────────
        # Each leg contributes independently:
        #   long (BUY)  leg: pnl = (close − open) × qty × 100
        #   short (SELL) leg: pnl = (open − close) × qty × 100
        gross_pnl = 0.0
        close_fees = 0.0
        exit_times: list[str] = []

        for leg in legs:
            li   = leg["leg_index"]
            open_px  = leg["open_price_avg"]
            close_px = leg_close_price[li]
            if leg["side"] == "BUY":
                gross_pnl += (close_px - open_px) * close_qty * 100
            else:
                gross_pnl += (open_px - close_px) * close_qty * 100

            for f, qty_used in allocated_fills[li]:
                frac = qty_used / f["quantity"] if f["quantity"] else 0
                close_fees += (f["commission"] + f["fees"]) * frac
                exit_times.append(f["execution_timestamp"])

        exit_time = max(exit_times) if exit_times else None
        net_pnl   = round(gross_pnl - close_fees, 2)
        gross_pnl = round(gross_pnl, 2)

        # Holding time
        holding_minutes, holding_days, same_day = 0, 0.0, False
        if exit_time and trade["entry_datetime"]:
            try:
                dt_in  = datetime.fromisoformat(trade["entry_datetime"])
                dt_out = datetime.fromisoformat(exit_time)
                holding_minutes = int((dt_out - dt_in).total_seconds() / 60)
                holding_days    = round(holding_minutes / 1440, 2)
                same_day        = dt_in.date() == dt_out.date()
            except (ValueError, TypeError):
                pass

        # Net close premium (for exit_price_avg)
        long_leg  = next(l for l in legs if l["side"] == "BUY")
        short_leg = next(l for l in legs if l["side"] == "SELL")
        close_net = (leg_close_price[long_leg["leg_index"]]
                     - leg_close_price[short_leg["leg_index"]])

        new_status = "open" if is_partial else "closed"
        new_fees   = round((trade["total_fees"] or 0) + close_fees, 2)

        # ── 4e. Persist changes ───────────────────────────────────────────
        conn.execute("""
            UPDATE trades SET
                status            = ?,
                exit_datetime     = ?,
                exit_price_avg    = ?,
                gross_pnl         = ?,
                net_pnl           = ?,
                total_fees        = ?,
                holding_minutes   = ?,
                holding_days      = ?,
                same_day_trade_flag = ?,
                partial_exit_flag = ?,
                updated_at        = datetime('now')
            WHERE id = ?
        """, (
            new_status,
            exit_time,
            round(abs(close_net), 4),
            gross_pnl,
            net_pnl,
            new_fees,
            holding_minutes,
            holding_days,
            1 if same_day else 0,
            1 if is_partial else 0,
            trade_id,
        ))

        # Update trade_legs with close prices
        for leg in legs:
            conn.execute(
                "UPDATE trade_legs SET close_price_avg = ? WHERE id = ?",
                (round(leg_close_price[leg["leg_index"]], 4), leg["id"])
            )

        # Link close fills to this trade (FIFO allocation)
        new_fills_linked = 0
        for leg_idx, allocs in allocated_fills.items():
            for f, _ in allocs:
                result = conn.execute(
                    "INSERT OR IGNORE INTO trade_fills (trade_id, fill_id, role) VALUES (?, ?, 'close')",
                    (trade_id, f["id"])
                )
                new_fills_linked += result.rowcount

        fills_assigned += new_fills_linked

        # Refresh options summary with updated exit data (dte_at_exit, etc.)
        populate_options_summary(trade_id, conn)

        trades_closed += 1

    conn.commit()
    conn.close()
    return {"trades_closed": trades_closed, "fills_assigned": fills_assigned}


def populate_options_summary(trade_id: int, conn) -> None:
    """
    Calculate and upsert trade_options_summary metrics for a spread trade.

    Computes: spread_width, net_debit_credit, max_profit, max_loss, breakeven, DTE.
    All values are per-contract (1 spread = 100 shares); multiply by contracts for totals.

    Called after spread creation (direction=debit/credit, entry_price_avg set)
    and again after closure (exit_datetime now populated → dte_at_exit updated).
    """
    trade_row = conn.execute("SELECT * FROM trades WHERE id = ?", (trade_id,)).fetchone()
    if not trade_row:
        return
    trade = dict(trade_row)

    legs = [dict(l) for l in conn.execute(
        "SELECT * FROM trade_legs WHERE trade_id = ? ORDER BY leg_index",
        (trade_id,)
    ).fetchall()]

    if len(legs) != 2:
        return
    if any(l["strike"] is None or l["expiry"] is None for l in legs):
        return

    expiry      = legs[0]["expiry"]          # Both legs share expiry (vertical spread)
    spread_width = round(abs(legs[0]["strike"] - legs[1]["strike"]), 4)

    # entry_price_avg = abs(long_avg - short_avg) = net premium per share
    net_dc    = round(float(trade.get("entry_price_avg") or 0), 4)
    direction = trade.get("direction", "debit")  # "debit" | "credit"

    # Max profit / max loss (per 1 spread contract = 100 shares)
    if direction == "debit":
        max_profit = round((spread_width - net_dc) * 100, 2)
        max_loss   = round(net_dc * 100, 2)
    else:  # credit
        max_profit = round(net_dc * 100, 2)
        max_loss   = round((spread_width - net_dc) * 100, 2)

    # Breakeven — determined by option type of the long leg
    long_leg  = next((l for l in legs if l["side"] == "BUY"),  None)
    short_leg = next((l for l in legs if l["side"] == "SELL"), None)
    breakeven = None
    if long_leg and short_leg:
        opt_type      = (long_leg.get("option_type") or "").lower()
        lower_strike  = min(long_leg["strike"], short_leg["strike"])
        higher_strike = max(long_leg["strike"], short_leg["strike"])
        if opt_type == "call":
            breakeven = round(lower_strike + net_dc, 4)
        elif opt_type == "put":
            breakeven = round(higher_strike - net_dc, 4)

    # DTE: calendar days from trade open/close date to expiry
    dte_at_entry, dte_at_exit = None, None
    try:
        expiry_dt = datetime.strptime(expiry, "%Y-%m-%d").date()
        if trade.get("entry_datetime"):
            entry_dt     = datetime.fromisoformat(trade["entry_datetime"]).date()
            dte_at_entry = (expiry_dt - entry_dt).days
        if trade.get("exit_datetime"):
            exit_dt     = datetime.fromisoformat(trade["exit_datetime"]).date()
            dte_at_exit = (expiry_dt - exit_dt).days
    except (ValueError, TypeError):
        pass

    conn.execute("""
        INSERT INTO trade_options_summary (
            trade_id, expiry, dte_at_entry, dte_at_exit,
            net_debit_credit, spread_width, max_profit, max_loss, breakeven
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(trade_id) DO UPDATE SET
            expiry           = excluded.expiry,
            dte_at_entry     = excluded.dte_at_entry,
            dte_at_exit      = excluded.dte_at_exit,
            net_debit_credit = excluded.net_debit_credit,
            spread_width     = excluded.spread_width,
            max_profit       = excluded.max_profit,
            max_loss         = excluded.max_loss,
            breakeven        = excluded.breakeven
    """, (trade_id, expiry, dte_at_entry, dte_at_exit,
          net_dc, spread_width, max_profit, max_loss, breakeven))


def _generate_trade_code(account_id: str, symbol: str, timestamp: str) -> str:
    """Generate a unique trade code."""
    raw = f"{account_id}:{symbol}:{timestamp}:{datetime.now().isoformat()}"
    return hashlib.md5(raw.encode()).hexdigest()[:12].upper()
