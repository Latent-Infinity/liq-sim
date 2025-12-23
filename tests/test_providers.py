
import pytest

from liq.sim.config import ProviderConfig
from liq.sim.models.fee import TieredMakerTakerFee, ZeroCommissionFee
from liq.sim.models.slippage import PFOFSlippage, VolumeWeightedSlippage
from liq.sim.models.spread import SpreadBasedSlippage
from liq.sim.providers import fee_model_from_config, slippage_model_from_config


def test_fee_model_factory_tiered() -> None:
    cfg = ProviderConfig(
        name="coinbase",
        asset_classes=["crypto"],
        fee_model="TieredMakerTaker",
        fee_params={"maker_bps": "10", "taker_bps": "20"},
        slippage_model="VolumeWeighted",
        slippage_params={"base_bps": "2", "volume_impact": "50"},
    )
    model = fee_model_from_config(cfg)
    assert isinstance(model, TieredMakerTakerFee)


def test_fee_model_factory_zero() -> None:
    cfg = ProviderConfig(
        name="robinhood",
        asset_classes=["equity"],
        fee_model="ZeroCommission",
        slippage_model="PFOF",
        slippage_params={"adverse_bps": "5"},
    )
    model = fee_model_from_config(cfg)
    assert isinstance(model, ZeroCommissionFee)


def test_slippage_model_factory_volume_weighted() -> None:
    cfg = ProviderConfig(
        name="coinbase",
        asset_classes=["crypto"],
        fee_model="ZeroCommission",
        slippage_model="VolumeWeighted",
        slippage_params={"base_bps": "2", "volume_impact": "50"},
    )
    model = slippage_model_from_config(cfg)
    assert isinstance(model, VolumeWeightedSlippage)


def test_slippage_model_factory_pfof() -> None:
    cfg = ProviderConfig(
        name="robinhood",
        asset_classes=["equity"],
        fee_model="ZeroCommission",
        slippage_model="PFOF",
        slippage_params={"adverse_bps": "5"},
    )
    model = slippage_model_from_config(cfg)
    assert isinstance(model, PFOFSlippage)


def test_slippage_model_factory_spread() -> None:
    cfg = ProviderConfig(
        name="oanda",
        asset_classes=["forex"],
        fee_model="ZeroCommission",
        slippage_model="SpreadBased",
    )
    model = slippage_model_from_config(cfg)
    assert isinstance(model, SpreadBasedSlippage)


def test_unknown_fee_model_errors() -> None:
    cfg = ProviderConfig(
        name="bad",
        asset_classes=["crypto"],
        fee_model="Unknown",
        slippage_model="VolumeWeighted",
        slippage_params={"base_bps": "2", "volume_impact": "50"},
    )
    with pytest.raises(ValueError):
        fee_model_from_config(cfg)


def test_unknown_slippage_model_errors() -> None:
    cfg = ProviderConfig(
        name="bad",
        asset_classes=["crypto"],
        fee_model="ZeroCommission",
        slippage_model="Unknown",
    )
    with pytest.raises(ValueError):
        slippage_model_from_config(cfg)
