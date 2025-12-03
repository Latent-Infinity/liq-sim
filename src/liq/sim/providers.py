"""Provider factory helpers for fee/slippage models."""

from decimal import Decimal

from liq.sim.config import ProviderConfig
from liq.sim.models.fee import TieredMakerTakerFee, ZeroCommissionFee
from liq.sim.models.slippage import PFOFSlippage, VolumeWeightedSlippage
from liq.sim.models.spread import SpreadBasedSlippage
from liq.sim.models.fee import PerShareFee


def fee_model_from_config(cfg: ProviderConfig):
    """Instantiate commission model from config."""
    if cfg.fee_model == "TieredMakerTaker":
        maker_bps = Decimal(str(cfg.fee_params.get("maker_bps", "0")))
        taker_bps = Decimal(str(cfg.fee_params.get("taker_bps", "0")))
        return TieredMakerTakerFee(maker_bps=maker_bps, taker_bps=taker_bps)
    if cfg.fee_model == "ZeroCommission":
        return ZeroCommissionFee()
    if cfg.fee_model == "PerShare":
        per_share = Decimal(str(cfg.fee_params.get("per_share", "0")))
        min_per_order = (
            Decimal(str(cfg.fee_params.get("min_per_order"))) if "min_per_order" in cfg.fee_params else None
        )
        return PerShareFee(per_share=per_share, min_per_order=min_per_order)
    raise ValueError(f"Unsupported fee_model: {cfg.fee_model}")


def slippage_model_from_config(cfg: ProviderConfig):
    """Instantiate slippage model from config."""
    if cfg.slippage_model == "VolumeWeighted":
        base_bps = Decimal(str(cfg.slippage_params.get("base_bps", "0")))
        volume_impact = Decimal(str(cfg.slippage_params.get("volume_impact", "0")))
        return VolumeWeightedSlippage(base_bps=base_bps, volume_impact=volume_impact)
    if cfg.slippage_model == "PFOF":
        adverse_bps = Decimal(str(cfg.slippage_params.get("adverse_bps", "0")))
        return PFOFSlippage(adverse_bps=adverse_bps)
    if cfg.slippage_model == "SpreadBased":
        # spread-based slippage uses bar spread; params optional
        return SpreadBasedSlippage()
    raise ValueError(f"Unsupported slippage_model: {cfg.slippage_model}")
