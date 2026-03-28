"""
IBKR option symbol parser.

IBKR encodes option metadata in the symbol string:
    Format: UNDERLYING YYMMDD[C|P]STRIKE
    Example: SPY 260404C00520000
      - Underlying:   SPY
      - Expiry:       2026-04-04 (YYMMDD → YYYY-MM-DD)
      - Option type:  C = call, P = put
      - Strike:       00520000 → 520.00 (divide by 1000)

Edge cases handled:
  - Multi-word underlyings (e.g., 'BRK B 260404C00250000')
  - Symbols with no space before the date (shouldn't occur but guarded)
  - Unparseable symbols return None gracefully — caller must handle
"""

import re
from datetime import datetime


# Regex: last token before type/strike block is the date block (YYMMDD[C|P]STRIKE)
_IBKR_OPT_RE = re.compile(
    r'^(.+?)\s+(\d{6})([CP])(\d{8})$',
    re.IGNORECASE
)


def parse_ibkr_option_symbol(symbol: str) -> dict | None:
    """
    Parse an IBKR option symbol string into its components.

    Args:
        symbol: Raw IBKR symbol string, e.g. 'SPY 260404C00520000'

    Returns:
        dict with keys:
            underlying  (str)   — e.g. 'SPY'
            expiry      (str)   — ISO date 'YYYY-MM-DD'
            option_type (str)   — 'call' or 'put'
            strike      (float) — e.g. 520.0
        or None if the symbol cannot be parsed.
    """
    if not symbol or not isinstance(symbol, str):
        return None

    symbol = symbol.strip()
    m = _IBKR_OPT_RE.match(symbol)
    if not m:
        return None

    underlying_raw, yymmdd, cp, strike_raw = m.groups()

    # Parse expiry
    try:
        expiry_dt = datetime.strptime(yymmdd, "%y%m%d")
        expiry = expiry_dt.strftime("%Y-%m-%d")
    except ValueError:
        return None

    # Parse strike: 8-digit integer in thousandths of a dollar
    try:
        strike = int(strike_raw) / 1000.0
    except ValueError:
        return None

    return {
        "underlying": underlying_raw.strip(),
        "expiry": expiry,
        "option_type": "call" if cp.upper() == "C" else "put",
        "strike": strike,
    }


def enrich_fill_with_parsed_symbol(fill: dict) -> dict:
    """
    Attempt to parse a fill's symbol and return a copy enriched with
    parsed option fields. Original fill is not mutated.

    Extra keys added (all may be None if symbol is not an option or unparseable):
        _parsed_underlying  (str | None)
        _parsed_expiry      (str | None)
        _parsed_option_type (str | None)
        _parsed_strike      (float | None)
    """
    enriched = dict(fill)
    parsed = parse_ibkr_option_symbol(fill.get("symbol", ""))
    if parsed:
        enriched["_parsed_underlying"] = parsed["underlying"]
        enriched["_parsed_expiry"] = parsed["expiry"]
        enriched["_parsed_option_type"] = parsed["option_type"]
        enriched["_parsed_strike"] = parsed["strike"]
    else:
        enriched["_parsed_underlying"] = None
        enriched["_parsed_expiry"] = None
        enriched["_parsed_option_type"] = None
        enriched["_parsed_strike"] = None
    return enriched


# ---------------------------------------------------------------------------
# Unit tests (run directly: python option_parser.py)
# ---------------------------------------------------------------------------

def _run_tests():
    cases = [
        # (symbol, expected_underlying, expected_expiry, expected_type, expected_strike)
        ("SPY 260404C00520000",  "SPY",   "2026-04-04", "call", 520.0),
        ("SPY 260321P00520000",  "SPY",   "2026-03-21", "put",  520.0),
        ("TSLA 260404C00250000", "TSLA",  "2026-04-04", "call", 250.0),
        ("TSLA 260404C00260000", "TSLA",  "2026-04-04", "call", 260.0),
        ("QQQ 260328C00480000",  "QQQ",   "2026-03-28", "call", 480.0),
        # Multi-word underlying
        ("BRK B 260404C00250000", "BRK B", "2026-04-04", "call", 250.0),
        # Strike with cents
        ("AMZN 260404P00182500", "AMZN",  "2026-04-04", "put",  182.5),
        # Very low strike (penny stocks / micro-caps)
        ("GME 261218C00020000",  "GME",   "2026-12-18", "call",  20.0),
        # Unparseable — plain stock symbol
        ("AAPL", None, None, None, None),
        # Unparseable — empty string
        ("", None, None, None, None),
        # Unparseable — None
        (None, None, None, None, None),
    ]

    passed = 0
    failed = 0
    for sym, exp_und, exp_exp, exp_type, exp_strike in cases:
        result = parse_ibkr_option_symbol(sym)
        if exp_und is None:
            # Expect None
            if result is None:
                print(f"  PASS  {sym!r} → None")
                passed += 1
            else:
                print(f"  FAIL  {sym!r} → expected None, got {result}")
                failed += 1
        else:
            if result is None:
                print(f"  FAIL  {sym!r} → got None, expected underlying={exp_und}")
                failed += 1
                continue
            ok = (
                result["underlying"] == exp_und
                and result["expiry"] == exp_exp
                and result["option_type"] == exp_type
                and abs(result["strike"] - exp_strike) < 0.001
            )
            if ok:
                print(f"  PASS  {sym!r} → {result}")
                passed += 1
            else:
                print(f"  FAIL  {sym!r}")
                print(f"        expected: underlying={exp_und}, expiry={exp_exp}, "
                      f"type={exp_type}, strike={exp_strike}")
                print(f"        got:      {result}")
                failed += 1

    print(f"\n{passed} passed, {failed} failed out of {passed + failed} tests.")
    return failed == 0


if __name__ == "__main__":
    print("Running option_parser unit tests...\n")
    success = _run_tests()
    raise SystemExit(0 if success else 1)
