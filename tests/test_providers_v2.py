from decimal import Decimal

from liq.sim.config import ProviderConfig
from liq.sim.providers import fee_model_from_config, slippage_model_from_config
from liq.sim.models.fee import PerShareFee
from liq.sim.models.spread import SpreadBasedSlippage


def test_per_share_factory() -> None:
    cfg = ProviderConfig(
        name="tradestation",
        asset_classes=["equity"],
        fee_model="PerShare",
        fee_params={"per_share": "0.005", "min_per_order": "1.00"},
        slippage_model="SpreadBased",
    )
    model = fee_model_from_config(cfg)
    assert isinstance(model, PerShareFee)


def test_spread_slippage_factory() -> None:
    cfg = ProviderConfig(
        name="oanda",
        asset_classes=["forex"],
        fee_model="ZeroCommission",
        slippage_model="SpreadBased",
    )
    model = slippage_model_from_config(cfg)
    assert isinstance(model, SpreadBasedSlippage)
