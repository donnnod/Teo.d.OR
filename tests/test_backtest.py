from teo.backtest.engine import run_backtest
from teo.models import StrategyConfig


def test_backtest_runs_and_scores(uptrend_candles):
    m = run_backtest(uptrend_candles, StrategyConfig())
    assert m.trades >= 0
    assert 0.0 <= m.win_rate <= 1.0
    assert m.max_drawdown >= 0.0
    # Profit factor is non-negative and only positive when there are losing trades to divide by.
    assert m.profit_factor >= 0.0


def test_backtest_insufficient_data_is_safe():
    m = run_backtest([], StrategyConfig())
    assert m.trades == 0
    assert m.net_points == 0.0
