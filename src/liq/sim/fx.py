"""FX conversion helpers for cross/quote/base handling."""

import logging
from decimal import Decimal

logger = logging.getLogger(__name__)


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
            logger.warning(
                "FX rate lookup failed",
                extra={"pair": pair, "available_rates": list(rates.keys())},
            )
            raise KeyError(f"Missing FX rate for {pair}")
        return pnl / rate
    # cross
    quote = pair.split("_")[1] if "_" in pair else pair.split("-")[1]
    usd_pair = f"USD_{quote}"
    rate = rates.get(usd_pair, None)
    if rate is None:
        logger.warning(
            "FX rate lookup failed for cross pair",
            extra={"original_pair": pair, "usd_pair": usd_pair, "available_rates": list(rates.keys())},
        )
        raise KeyError(f"Missing FX rate for {usd_pair}")
    return pnl / rate
