from thndr_bot.commands import HELP_TEXT, _find_ticker, _handle_command


def _tickers():
    return [
        {"symbol": "TALM", "yahoo_symbol": "TALM.CA", "name": "Taaleem", "held": True,
         "cost_basis": 19.25, "quantity": 52},
        {"symbol": "SWDY", "yahoo_symbol": "SWDY.CA", "name": "Elsewedy Electric", "held": False,
         "cost_basis": None, "quantity": None},
    ]


def test_find_ticker_matches_case_insensitively():
    tickers = _tickers()

    assert _find_ticker(tickers, "talm") is tickers[0]
    assert _find_ticker(tickers, "TALM") is tickers[0]
    assert _find_ticker(tickers, "NOPE") is None


def test_non_command_text_is_ignored():
    reply, changed = _handle_command("just chatting", _tickers())

    assert reply is None
    assert changed is False


def test_help_command():
    reply, changed = _handle_command("/help", _tickers())

    assert reply == HELP_TEXT
    assert changed is False


def test_update_command_sets_cost_basis_quantity_and_held():
    tickers = _tickers()

    reply, changed = _handle_command("/update SWDY 12.50 40", tickers)

    assert changed is True
    swdy = _find_ticker(tickers, "SWDY")
    assert swdy["cost_basis"] == 12.50
    assert swdy["quantity"] == 40
    assert swdy["held"] is True
    assert "Updated SWDY" in reply


def test_update_command_unknown_symbol():
    reply, changed = _handle_command("/update NOPE 12.50 40", _tickers())

    assert changed is False
    assert "Unknown symbol NOPE" in reply


def test_update_command_wrong_arg_count():
    reply, changed = _handle_command("/update TALM 12.50", _tickers())

    assert changed is False
    assert "Usage" in reply


def test_update_command_non_numeric_args():
    reply, changed = _handle_command("/update TALM abc 40", _tickers())

    assert changed is False
    assert "must be numbers" in reply


def test_sell_command_clears_position():
    tickers = _tickers()

    reply, changed = _handle_command("/sell TALM", tickers)

    assert changed is True
    talm = _find_ticker(tickers, "TALM")
    assert talm["held"] is False
    assert talm["cost_basis"] is None
    assert talm["quantity"] is None
    assert "Marked TALM as sold" in reply


def test_sell_command_unknown_symbol():
    reply, changed = _handle_command("/sell NOPE", _tickers())

    assert changed is False
    assert "Unknown symbol NOPE" in reply


def test_portfolio_command_lists_held_positions():
    reply, changed = _handle_command("/portfolio", _tickers())

    assert changed is False
    assert "TALM: cost 19.25, qty 52" in reply
    assert "SWDY" not in reply


def test_portfolio_command_with_no_held_positions():
    tickers = [{"symbol": "SWDY", "yahoo_symbol": "SWDY.CA", "name": "Elsewedy Electric",
                "held": False, "cost_basis": None, "quantity": None}]

    reply, changed = _handle_command("/portfolio", tickers)

    assert reply == "No held positions."
    assert changed is False


def test_unknown_command():
    reply, changed = _handle_command("/frobnicate", _tickers())

    assert changed is False
    assert "Unknown command /frobnicate" in reply


def test_command_with_bot_name_suffix_is_stripped():
    tickers = _tickers()

    reply, changed = _handle_command("/sell@MyEgxBot TALM", tickers)

    assert changed is True
    assert _find_ticker(tickers, "TALM")["held"] is False
