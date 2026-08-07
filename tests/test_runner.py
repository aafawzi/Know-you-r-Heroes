from thndr_bot.runner import _format_alert_line, _portfolio_line
from thndr_bot.strategy import Signal


def _signal(action="SELL", price=42.0, **overrides):
    fields = dict(action=action, price=price, sma_fast=1.0, sma_slow=1.0, rsi=50.0)
    fields.update(overrides)
    return Signal(**fields)


def test_alert_shows_pnl_when_held_with_cost_basis():
    line = _format_alert_line("ETEL", "Telecom Egypt", held=True, signal=_signal(price=42.0), cost_basis=30.0)

    assert "cost 30.00" in line
    assert "now 42.00" in line
    assert "+40.0%" in line


def test_alert_includes_absolute_pnl_when_quantity_given():
    line = _format_alert_line(
        "ETEL", "Telecom Egypt", held=True, signal=_signal(price=42.0), cost_basis=30.0, quantity=10
    )

    assert "+120.00 EGP" in line
    assert "10 shares" in line


def test_alert_omits_pnl_without_cost_basis():
    line = _format_alert_line("ETEL", "Telecom Egypt", held=True, signal=_signal(price=42.0))

    assert "cost" not in line
    assert "Your position" not in line


def test_alert_omits_pnl_when_not_held_even_with_cost_basis():
    # cost_basis shouldn't render for a ticker that isn't actually held.
    line = _format_alert_line("ETEL", "Telecom Egypt", held=False, signal=_signal(price=42.0), cost_basis=30.0)

    assert "Your position" not in line


def test_alert_shows_stop_loss_and_reference_take_profit_for_buy():
    signal = _signal(action="BUY", price=100.0, stop_loss=90.0, take_profit=130.0)

    line = _format_alert_line("SWDY", "Elsewedy Electric", held=False, signal=signal)

    assert "Stop-loss: 90.00" in line
    assert "Take-profit (reference only): 130.00" in line


def test_portfolio_line_shows_price_only_without_cost_basis():
    line, pnl_abs = _portfolio_line("ETEL", "Telecom Egypt", price=42.0, cost_basis=None, quantity=None)

    assert "42.00 EGP" in line
    assert "cost basis not set" in line
    assert pnl_abs is None


def test_portfolio_line_shows_pnl_pct_with_cost_basis_only():
    line, pnl_abs = _portfolio_line("ETEL", "Telecom Egypt", price=42.0, cost_basis=30.0, quantity=None)

    assert "+40.0%" in line
    assert pnl_abs is None


def test_portfolio_line_shows_absolute_pnl_with_quantity():
    line, pnl_abs = _portfolio_line("ETEL", "Telecom Egypt", price=42.0, cost_basis=30.0, quantity=10)

    assert "+120.00 EGP" in line
    assert "10 shares" in line
    assert pnl_abs == 120.0
