from pathlib import Path
import json

from typer.testing import CliRunner

from liq.sim.cli import app

runner = CliRunner()


def _write_json(tmp_path: Path, name: str, data) -> Path:
    path = tmp_path / name
    path.write_text(json.dumps(data))
    return path


def test_validate_config_command(tmp_path: Path) -> None:
    provider_cfg = {
        "name": "coinbase",
        "asset_classes": ["crypto"],
        "fee_model": "ZeroCommission",
        "slippage_model": "VolumeWeighted",
    }
    sim_cfg = {"initial_capital": "1000", "min_order_delay_bars": 0}
    p_path = _write_json(tmp_path, "provider.json", provider_cfg)
    s_path = _write_json(tmp_path, "sim.json", sim_cfg)
    result = runner.invoke(app, ["validate-config", str(p_path), str(s_path)])
    assert result.exit_code == 0
    assert "Configs are valid" in result.stdout


def test_run_command_smoke(tmp_path: Path) -> None:
    provider_cfg = {
        "name": "coinbase",
        "asset_classes": ["crypto"],
        "fee_model": "ZeroCommission",
        "slippage_model": "VolumeWeighted",
        "slippage_params": {"base_bps": "0", "volume_impact": "0"},
    }
    sim_cfg = {"initial_capital": "1000", "min_order_delay_bars": 0}
    order = {
        "symbol": "BTC-USD",
        "side": "buy",
        "order_type": "market",
        "quantity": "1",
        "time_in_force": "day",
        "timestamp": "2024-01-01T00:00:00Z",
    }
    bar = {
        "symbol": "BTC-USD",
        "timestamp": "2024-01-01T00:00:00Z",
        "open": "100",
        "high": "100",
        "low": "100",
        "close": "100",
        "volume": "1000",
    }
    orders_path = _write_json(tmp_path, "orders.json", [order])
    bars_path = _write_json(tmp_path, "bars.json", [bar])
    p_path = _write_json(tmp_path, "provider.json", provider_cfg)
    s_path = _write_json(tmp_path, "sim.json", sim_cfg)

    result = runner.invoke(
        app,
        [
            "run",
            str(orders_path),
            str(bars_path),
            str(p_path),
            str(s_path),
        ],
    )
    assert result.exit_code == 0
    assert "Fills:" in result.stdout
