"""FX conversion helpers for cross/quote/base handling."""

from decimal import Decimal


def convert_to_usd(pnl: Decimal, pair: str, rates: dict[str, Decimal]) -> Decimal:
    """Convert P&L from quote currency to USD using supplied rates.

    - If quote = USD (e.g., EUR_USD): return pnl
    - If base = USD (e.g., USD_JPY): divide by rate
    - Cross (e.g., EUR_JPY): divide by USD_JPY
    """
    norm_pair = pair.replace("-", "_")
    if "_" not in norm_pair:
        return pnl
    pair = norm_pair
    if pair.endswith("USD"):
        return pnl
    if pair.startswith("USD_"):
        rate = rates.get(pair, None)
        if rate is None:
            raise KeyError(f"Missing FX rate for {pair}")
        return pnl / rate
    # cross
    quote = pair.split("_")[1] if "_" in pair else pair.split("-")[1]
    usd_pair = f"USD_{quote}"
    rate = rates.get(usd_pair, None)
    if rate is None:
        raise KeyError(f"Missing FX rate for {usd_pair}")
    return pnl / rate
