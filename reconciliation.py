"""
Position reconciliation for Phase 2.

Builds trade-derived EOD positions from imported fills, ingests IBKR statement
Open Positions rows, and compares the two position sets inside SQLite.
"""

from __future__ import annotations

import argparse
import json
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import date, datetime
from typing import Iterable

from database import get_connection, init_db


EPSILON = 1e-9


@dataclass
class ReconciliationResult:
    report_date: str
    rows_compared: int
    ok_rows: int
    exception_rows: int
    mismatch_rows: int


def parse_statement_open_positions(xml_text: str, default_report_date: str | None = None) -> list[dict]:
    """Extract IBKR statement open positions from Flex XML."""
    root = ET.fromstring(xml_text)
    report_date = default_report_date or _extract_report_date(root)
    positions: list[dict] = []
    parent_map = {child: parent for parent in root.iter() for child in parent}

    for el in root.iter():
        tag = _local_name(el.tag).lower()
        if tag not in {"openposition", "openpositionsummary", "position"}:
            continue

        quantity = _parse_float(
            el.get("position")
            or el.get("quantity")
            or el.get("qty")
            or el.get("currentQuantity")
        )
        symbol = (el.get("symbol") or el.get("description") or "").strip()
        if not symbol or quantity is None:
            continue

        conid = (el.get("conid") or el.get("conID") or el.get("contractID") or "").strip() or None
        underlying = (el.get("underlyingSymbol") or symbol).strip()
        security_type = (
            el.get("assetCategory")
            or el.get("securityType")
            or el.get("assetClass")
            or "STK"
        ).strip() or "STK"
        position = {
            "report_date": _normalize_date(
                el.get("reportDate")
                or el.get("date")
                or _inherit_attr(parent_map, el, "reportDate", "date", "toDate", "statementDate")
                or report_date
            ),
            "broker_account_id": (
                el.get("accountId")
                or el.get("acctId")
                or el.get("account")
                or _inherit_attr(parent_map, el, "accountId", "acctId", "account")
                or ""
            ).strip(),
            "broker_account_name": (
                el.get("acctAlias")
                or el.get("accountAlias")
                or _inherit_attr(parent_map, el, "acctAlias", "accountAlias")
                or ""
            ).strip(),
            "conid": conid,
            "symbol": symbol,
            "underlying_symbol": underlying,
            "security_type": security_type,
            "quantity_eod": quantity,
            "mark_price": _parse_float(el.get("markPrice") or el.get("price")),
            "position_value": _parse_float(el.get("positionValue") or el.get("marketValue")),
            "currency": (el.get("currency") or "USD").strip() or "USD",
            "raw_payload_json": json.dumps(dict(el.attrib), sort_keys=True),
        }
        position["instrument_key"] = _instrument_key(
            position["conid"], position["symbol"], position["security_type"]
        )
        if position["broker_account_id"]:
            positions.append(position)

    return positions


def _inherit_attr(parent_map: dict[ET.Element, ET.Element], el: ET.Element, *keys: str) -> str | None:
    """Walk up ancestor nodes until one of the requested attributes is found."""
    current = parent_map.get(el)
    while current is not None:
        for key in keys:
            value = current.get(key)
            if value:
                return value
        current = parent_map.get(current)
    return None


def store_statement_open_positions(positions: Iterable[dict], import_id: int | None = None) -> int:
    """Upsert statement open positions into SQLite."""
    conn = get_connection()
    inserted = 0
    for pos in positions:
        conn.execute(
            """
            INSERT INTO statement_open_positions (
                import_id, report_date, broker_account_id, broker_account_name,
                instrument_key, conid, symbol, underlying_symbol, security_type,
                quantity_eod, mark_price, position_value, currency, raw_payload_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(report_date, broker_account_id, instrument_key) DO UPDATE SET
                import_id = excluded.import_id,
                broker_account_name = excluded.broker_account_name,
                conid = excluded.conid,
                symbol = excluded.symbol,
                underlying_symbol = excluded.underlying_symbol,
                security_type = excluded.security_type,
                quantity_eod = excluded.quantity_eod,
                mark_price = excluded.mark_price,
                position_value = excluded.position_value,
                currency = excluded.currency,
                raw_payload_json = excluded.raw_payload_json
            """,
            (
                import_id,
                pos["report_date"],
                pos["broker_account_id"],
                pos.get("broker_account_name"),
                pos["instrument_key"],
                pos.get("conid"),
                pos["symbol"],
                pos.get("underlying_symbol"),
                pos.get("security_type", "STK"),
                pos["quantity_eod"],
                pos.get("mark_price"),
                pos.get("position_value"),
                pos.get("currency", "USD"),
                pos.get("raw_payload_json"),
            ),
        )
        inserted += 1

    conn.commit()
    conn.close()
    return inserted


def build_pos_eod_from_trades(report_date: str) -> int:
    """Rebuild trade-driven EOD positions for a given report date."""
    conn = get_connection()
    conn.execute("DELETE FROM pos_eod_from_trades WHERE report_date = ?", (report_date,))

    rows = conn.execute(
        """
        SELECT
            broker_account_id,
            MAX(broker_account_name) AS broker_account_name,
            COALESCE(NULLIF(conid, ''), symbol) AS instrument_key,
            NULLIF(conid, '') AS conid,
            symbol,
            underlying_symbol,
            security_type,
            ROUND(SUM(CASE WHEN side = 'BUY' THEN quantity ELSE -quantity END), 8) AS quantity_eod,
            MAX(execution_timestamp) AS last_fill_timestamp
        FROM fills
        WHERE date(execution_timestamp) <= date(?)
        GROUP BY broker_account_id, COALESCE(NULLIF(conid, ''), symbol), symbol, underlying_symbol, security_type
        HAVING ABS(quantity_eod) > ?
        """,
        (report_date, EPSILON),
    ).fetchall()

    for row in rows:
        record = dict(row)
        conn.execute(
            """
            INSERT INTO pos_eod_from_trades (
                report_date, broker_account_id, broker_account_name, instrument_key,
                conid, symbol, underlying_symbol, security_type, quantity_eod, last_fill_timestamp
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                report_date,
                record["broker_account_id"],
                record["broker_account_name"],
                _instrument_key(record["conid"], record["symbol"], record["security_type"], record["instrument_key"]),
                record["conid"],
                record["symbol"],
                record["underlying_symbol"],
                record["security_type"],
                record["quantity_eod"],
                record["last_fill_timestamp"],
            ),
        )

    conn.commit()
    conn.close()
    return len(rows)


def reconcile_positions(report_date: str) -> ReconciliationResult:
    """Compare trade-derived positions against statement open positions."""
    conn = get_connection()
    conn.execute("DELETE FROM position_reconciliation WHERE report_date = ?", (report_date,))

    trade_rows = {
        (row["broker_account_id"], row["instrument_key"]): dict(row)
        for row in conn.execute(
            "SELECT * FROM pos_eod_from_trades WHERE report_date = ?",
            (report_date,),
        ).fetchall()
    }
    statement_rows = {
        (row["broker_account_id"], row["instrument_key"]): dict(row)
        for row in conn.execute(
            "SELECT * FROM statement_open_positions WHERE report_date = ?",
            (report_date,),
        ).fetchall()
    }

    ok_rows = 0
    exception_rows = 0
    mismatch_rows = 0

    for key in sorted(set(trade_rows) | set(statement_rows)):
        trade = trade_rows.get(key)
        statement = statement_rows.get(key)
        trade_qty = float((trade or {}).get("quantity_eod") or 0)
        statement_qty = float((statement or {}).get("quantity_eod") or 0)
        diff = round(trade_qty - statement_qty, 8)

        override = _load_exception_override(conn, report_date, key[0], key[1], (trade or statement or {}).get("conid"))
        status = "OK"
        exception_code = None
        exception_note = None

        if abs(diff) <= EPSILON:
            ok_rows += 1
        elif override:
            status = "EXCEPTION"
            exception_code = override["exception_code"]
            exception_note = override["note"]
            exception_rows += 1
        else:
            auto_code, auto_note = _classify_auto_exception(report_date, trade, statement)
            if auto_code:
                status = "EXCEPTION"
                exception_code = auto_code
                exception_note = auto_note
                exception_rows += 1
            else:
                status = "MISMATCH"
                mismatch_rows += 1

        basis = trade or statement or {}
        conn.execute(
            """
            INSERT INTO position_reconciliation (
                report_date, broker_account_id, broker_account_name, instrument_key,
                conid, symbol, underlying_symbol, security_type,
                trade_quantity_eod, statement_quantity_eod, quantity_diff,
                status, exception_code, exception_note
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                report_date,
                key[0],
                basis.get("broker_account_name"),
                key[1],
                basis.get("conid"),
                basis.get("symbol"),
                basis.get("underlying_symbol"),
                basis.get("security_type", "STK"),
                trade_qty,
                statement_qty,
                diff,
                status,
                exception_code,
                exception_note,
            ),
        )

    conn.commit()
    conn.close()
    return ReconciliationResult(
        report_date=report_date,
        rows_compared=len(set(trade_rows) | set(statement_rows)),
        ok_rows=ok_rows,
        exception_rows=exception_rows,
        mismatch_rows=mismatch_rows,
    )


def run_reconciliation(report_date: str, statement_xml_path: str | None = None, import_id: int | None = None) -> ReconciliationResult:
    """End-to-end helper for CLI and importable use."""
    init_db()
    if statement_xml_path:
        with open(statement_xml_path, "r", encoding="utf-8") as handle:
            xml_text = handle.read()
        positions = parse_statement_open_positions(xml_text, default_report_date=report_date)
        store_statement_open_positions(positions, import_id=import_id)

    build_pos_eod_from_trades(report_date)
    return reconcile_positions(report_date)


def _classify_auto_exception(report_date: str, trade: dict | None, statement: dict | None) -> tuple[str | None, str | None]:
    if statement and not trade:
        return (
            "external_activity",
            "Statement shows an open position without matching trade history; likely transfer, corporate action, or pre-system inventory.",
        )

    if trade and not statement:
        last_fill = (trade.get("last_fill_timestamp") or "")[:10]
        if last_fill == report_date:
            return (
                "statement_cutoff",
                "Trade-built position exists from same-day executions, but the statement snapshot is flat; likely timing or statement cutoff.",
            )

    return None, None


def _load_exception_override(
    conn,
    report_date: str,
    broker_account_id: str,
    instrument_key: str,
    conid: str | None,
) -> dict | None:
    rows = conn.execute(
        """
        SELECT exception_code, note
        FROM reconciliation_exceptions
        WHERE broker_account_id = ?
          AND (report_date = ? OR report_date IS NULL)
          AND (
                instrument_key = ?
                OR (instrument_key IS NULL AND conid IS NOT NULL AND conid = ?)
              )
        ORDER BY CASE WHEN report_date = ? THEN 0 ELSE 1 END
        LIMIT 1
        """,
        (broker_account_id, report_date, instrument_key, conid, report_date),
    ).fetchone()
    return dict(rows) if rows else None


def _extract_report_date(root: ET.Element) -> str:
    for el in root.iter():
        for key in ("reportDate", "toDate", "asOfDate", "statementDate", "date"):
            value = el.get(key)
            if value:
                return _normalize_date(value)
    return date.today().isoformat()


def _normalize_date(value: str) -> str:
    cleaned = value.strip().replace("/", "-")
    if ";" in cleaned:
        cleaned = cleaned.split(";", 1)[0]
    if len(cleaned) == 8 and cleaned.isdigit():
        return f"{cleaned[:4]}-{cleaned[4:6]}-{cleaned[6:]}"
    return cleaned


def _instrument_key(conid: str | None, symbol: str | None, security_type: str | None, fallback: str | None = None) -> str:
    return (conid or fallback or symbol or "").strip() or f"UNKNOWN:{security_type or 'NA'}"


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _parse_float(value: str | None) -> float | None:
    if value in (None, ""):
        return None
    cleaned = value.replace(",", "").strip()
    if not cleaned:
        return None
    return float(cleaned)


def main() -> None:
    parser = argparse.ArgumentParser(description="Reconcile trade-built positions with IBKR statement open positions.")
    parser.add_argument("--report-date", required=True, help="Report date in YYYY-MM-DD format.")
    parser.add_argument("--statement-xml", help="Path to an IBKR statement XML containing OpenPosition rows.")
    parser.add_argument("--import-id", type=int, help="Optional imports.id to link stored statement positions.")
    args = parser.parse_args()

    result = run_reconciliation(args.report_date, statement_xml_path=args.statement_xml, import_id=args.import_id)
    print(json.dumps(result.__dict__, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
