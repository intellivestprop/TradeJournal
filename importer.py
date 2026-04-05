"""
IBKR Flex Web Service import module.
Handles: authentication, XML fetch, parsing, dedup, fill storage.
"""

import hashlib
import json
import os
import time
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path

import requests

from database import get_connection

RAW_DIR = os.environ.get("TJ_RAW_DIR", str(Path(__file__).parent / "raw_imports"))


def fetch_flex_report(token: str, query_id: str, max_retries: int = 5, wait_seconds: int = 5) -> str | None:
    """
    Two-step Flex Web Service fetch:
    1. Request the report -> get a reference code + URL
    2. Poll the URL until the report is ready
    Returns the raw XML string, or None on failure.
    """
    # Step 1: Send request
    url = "https://gdcdyn.interactivebrokers.com/Universal/servlet/FlexStatementService.SendRequest"
    params = {"t": token, "q": query_id, "v": "3"}

    resp = requests.get(url, params=params, timeout=30)
    resp.raise_for_status()

    root = ET.fromstring(resp.text)
    status = root.findtext("Status")
    if status != "Success":
        error = root.findtext("ErrorMessage", "Unknown error")
        raise RuntimeError(f"Flex request failed: {error}")

    ref_code = root.findtext("ReferenceCode")
    base_url = root.findtext("Url")

    # Step 2: Poll for report
    for attempt in range(max_retries):
        time.sleep(wait_seconds)
        poll_resp = requests.get(base_url, params={"t": token, "q": ref_code, "v": "3"}, timeout=60)
        poll_resp.raise_for_status()

        if "FlexQueryResponse" in poll_resp.text or "FlexStatements" in poll_resp.text:
            return poll_resp.text

        poll_root = ET.fromstring(poll_resp.text)
        poll_status = poll_root.findtext("Status")
        if poll_status == "Warn" and "not yet available" in poll_root.findtext("ErrorMessage", "").lower():
            continue
        elif poll_status != "Success":
            error = poll_root.findtext("ErrorMessage", "Unknown")
            raise RuntimeError(f"Flex poll failed: {error}")

    raise RuntimeError(f"Flex report not ready after {max_retries} attempts")


def compute_checksum(xml_text: str) -> str:
    """SHA-256 checksum for dedup."""
    return hashlib.sha256(xml_text.encode("utf-8")).hexdigest()


def is_duplicate(checksum: str) -> bool:
    """Check if a report with this checksum has already been imported."""
    conn = get_connection()
    row = conn.execute(
        "SELECT id FROM imports WHERE checksum = ? AND status = 'success'",
        (checksum,)
    ).fetchone()
    conn.close()
    return row is not None


def archive_raw(xml_text: str) -> str:
    """Save raw XML to raw_imports/ with timestamp. Returns the file path."""
    os.makedirs(RAW_DIR, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = os.path.join(RAW_DIR, f"flex_{ts}.xml")
    with open(path, "w", encoding="utf-8") as f:
        f.write(xml_text)
    return path


def parse_flex_xml(xml_text: str) -> list[dict]:
    """
    Parse IBKR Flex XML into a list of fill dicts.
    Handles both TradeConfirmation and Order report structures.
    """
    root = ET.fromstring(xml_text)
    fills = []

    # Try TradeConfirmation path first, then Order path
    for tag in ["TradeConfirmation", "Trade", "Order"]:
        elements = root.iter(tag)
        for el in elements:
            fill = {
                "broker_account_id": el.get("accountId", ""),
                "broker_account_name": el.get("acctAlias", ""),
                "conid": el.get("conid") or el.get("conID") or el.get("contractID", ""),
                "broker_execution_id": el.get("tradeID") or el.get("transactionID") or el.get("execID", ""),
                "broker_order_id": el.get("orderID", ""),
                "order_reference": (
                    el.get("orderReference")
                    or el.get("orderRef")
                    or el.get("ibOrderReference")
                    or ""
                ),
                "symbol": el.get("symbol", ""),
                "underlying_symbol": el.get("underlyingSymbol") or el.get("symbol", ""),
                "security_type": el.get("assetCategory", "STK"),
                "side": "BUY" if el.get("buySell", "").upper() in ("BUY", "BOT", "B") else "SELL",
                "quantity": abs(float(el.get("quantity", 0))),
                "price": float(el.get("tradePrice") or el.get("price", 0)),
                "execution_timestamp": _normalize_timestamp(
                    el.get("tradeDate", ""), el.get("tradeTime") or el.get("orderTime", "")
                ),
                "commission": abs(float(el.get("commission") or el.get("ibCommission", 0))),
                "fees": abs(float(el.get("brokerExecutionCharge") or el.get("otherFees", 0))),
                "currency": el.get("currency", "USD"),
                "exchange": el.get("exchange", ""),
                "raw_payload_json": json.dumps(dict(el.attrib)),
            }

            if fill["broker_execution_id"] and fill["symbol"]:
                fills.append(fill)

    return fills


def _normalize_timestamp(date_str: str, time_str: str) -> str:
    """
    Combine date and time strings into ISO format.

    Handles multiple IBKR time formats:
      - "HH:MM:SS"         (TradeConfirmation reports)
      - "HHMMSS"           (6-digit compact)
      - "YYYYMMDD:HHMMSS"  (Activity/Trade reports — date prefix must be stripped)
      - "YYYYMMDD;HHMMSS"  (same with semicolon separator)
    """
    if not date_str:
        return datetime.now().isoformat()

    date_str = date_str.replace("/", "-")
    if len(date_str) == 8 and "-" not in date_str:
        date_str = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:]}"

    if time_str:
        time_str = time_str.replace(";", ":")
        # IBKR Activity format: "YYYYMMDD:HHMMSS" — strip the date prefix
        if len(time_str) == 15 and time_str[8] == ":":
            time_str = time_str[9:]   # "145842"
        # Compact 6-digit time: "HHMMSS" -> "HH:MM:SS"
        if len(time_str) == 6 and ":" not in time_str:
            time_str = f"{time_str[:2]}:{time_str[2:4]}:{time_str[4:]}"
        return f"{date_str}T{time_str}"

    return f"{date_str}T00:00:00"


def store_fills(fills: list[dict], import_id: int) -> int:
    """Store parsed fills in the database. Returns count of inserted fills."""
    conn = get_connection()
    inserted = 0

    for fill in fills:
        try:
            conn.execute("""
                INSERT INTO fills (
                    import_id, broker_account_id, broker_account_name,
                    conid, broker_execution_id, broker_order_id, order_reference, symbol, underlying_symbol,
                    security_type, side, quantity, price, execution_timestamp,
                    commission, fees, currency, exchange, raw_payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                import_id, fill["broker_account_id"], fill["broker_account_name"],
                fill["conid"], fill["broker_execution_id"], fill["broker_order_id"], fill["order_reference"],
                fill["symbol"], fill["underlying_symbol"], fill["security_type"],
                fill["side"], fill["quantity"], fill["price"],
                fill["execution_timestamp"], fill["commission"], fill["fees"],
                fill["currency"], fill["exchange"], fill["raw_payload_json"],
            ))
            inserted += 1

            # Track account
            conn.execute("""
                INSERT INTO accounts (broker_account_id, alias)
                VALUES (?, ?)
                ON CONFLICT(broker_account_id) DO UPDATE SET
                    last_seen_at = datetime('now')
            """, (fill["broker_account_id"], fill["broker_account_name"]))

        except Exception:
            pass  # Skip duplicates (unique index on broker_execution_id)

    conn.commit()
    conn.close()
    return inserted


def run_import(token: str = "", query_id: str = "", xml_text: str | None = None) -> dict:
    """
    Full import pipeline:
    1. Fetch (or accept pre-fetched XML)
    2. Checksum + dedup
    3. Archive raw
    4. Parse fills
    5. Store fills
    Returns a summary dict.
    """
    conn = get_connection()
    started = datetime.now().isoformat()

    cur = conn.execute(
        "INSERT INTO imports (source_type, query_id, import_started_at, status) VALUES (?, ?, ?, ?)",
        ("ibkr_flex", query_id, started, "pending")
    )
    import_id = cur.lastrowid
    conn.commit()

    try:
        if xml_text is None:
            xml_text = fetch_flex_report(token, query_id)

        checksum = compute_checksum(xml_text)

        if is_duplicate(checksum):
            existing = conn.execute(
                """
                SELECT id, raw_file_path
                FROM imports
                WHERE checksum = ? AND status = 'success'
                ORDER BY id DESC
                LIMIT 1
                """,
                (checksum,),
            ).fetchone()
            conn.execute(
                """
                UPDATE imports
                SET status = ?, error_message = ?, import_finished_at = ?, report_reference = ?, raw_file_path = ?
                WHERE id = ?
                """,
                (
                    "duplicate",
                    "Report already imported",
                    datetime.now().isoformat(),
                    checksum[:12],
                    existing["raw_file_path"] if existing else None,
                    import_id,
                ),
            )
            conn.commit()
            conn.close()
            return {
                "status": "duplicate",
                "import_id": import_id,
                "fills": 0,
                "message": "Report already imported",
                "raw_file": existing["raw_file_path"] if existing else None,
                "existing_import_id": existing["id"] if existing else None,
            }

        raw_path = archive_raw(xml_text)
        fills = parse_flex_xml(xml_text)
        inserted = store_fills(fills, import_id)

        conn.execute("""
            UPDATE imports SET
                status = 'success', import_finished_at = ?,
                raw_file_path = ?, checksum = ?, report_reference = ?
            WHERE id = ?
        """, (datetime.now().isoformat(), raw_path, checksum, checksum[:12], import_id))
        conn.commit()
        conn.close()

        # Match any close fills in this import to existing open spreads
        from reconstruction import match_close_fills_to_open_spreads
        close_result = match_close_fills_to_open_spreads(import_id)

        return {
            "status": "success", "import_id": import_id,
            "fills": inserted, "total_parsed": len(fills), "raw_file": raw_path,
            "spreads_closed": close_result.get("trades_closed", 0),
        }

    except Exception as e:
        conn.execute(
            "UPDATE imports SET status = ?, error_message = ?, import_finished_at = ? WHERE id = ?",
            ("error", str(e), datetime.now().isoformat(), import_id)
        )
        conn.commit()
        conn.close()
        return {"status": "error", "import_id": import_id, "fills": 0, "message": str(e)}


def import_from_file(filepath: str) -> dict:
    """Import from a local Flex XML file (for manual upload)."""
    with open(filepath, "r", encoding="utf-8") as f:
        xml_text = f.read()
    return run_import(token="", query_id="file_upload", xml_text=xml_text)
