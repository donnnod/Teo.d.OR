"""Pydantic request/response schemas shared with the dashboard."""

from __future__ import annotations

from pydantic import BaseModel, Field


class Candle(BaseModel):
    """A single OHLCV bar. `time` is epoch milliseconds (Binance kline open time)."""

    time: int
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0


class ForecastRequest(BaseModel):
    symbol: str = Field(
        "BTCUSDT", description="Binance data-source symbol, e.g. BTCUSDT or PAXGUSDT"
    )
    interval: str = Field("5m", description="Kline interval, e.g. 1m/5m/15m/1h")
    horizon: int = Field(12, ge=1, le=120, description="How many future bars to forecast")
    # If candles are supplied, Teo uses them directly; otherwise it fetches recent history.
    candles: list[Candle] | None = None
    lookback: int = Field(200, ge=20, le=2000, description="Bars to fetch when candles omitted")


class ForecastPoint(BaseModel):
    step: int
    close: float
    lower: float
    upper: float


class ForecastResponse(BaseModel):
    symbol: str
    interval: str
    model: str  # "kronos:<id>" or "baseline"
    horizon: int
    last_close: float
    points: list[ForecastPoint]
    # Compact directional read the dashboard can fold into its TA grade.
    direction: str  # "up" | "down" | "flat"
    expected_return: float  # fractional return over the horizon
    confidence: float  # 0..1
    note: str | None = None


class StrategyConfig(BaseModel):
    """Mirror of the dashboard's StrategyConfig knobs relevant to replay."""

    rsi_oversold: float = 30
    rsi_overbought: float = 70
    atr_sl_mult: float = 1.5
    tp1_r: float = 1.2
    tp2_r: float = 2.5
    ema_fast: int = 9
    ema_slow: int = 21
    ema_trend: int = 50
    atr_trail_mult: float = 2.0


class BacktestRequest(BaseModel):
    symbol: str = "BTCUSDT"
    interval: str = "5m"
    start: int | None = Field(None, description="epoch ms; omit to use lookback")
    end: int | None = Field(None, description="epoch ms; omit for now")
    lookback: int = Field(1000, ge=60, le=5000)
    config: StrategyConfig = StrategyConfig()


class BacktestMetrics(BaseModel):
    trades: int
    win_rate: float
    net_points: float
    avg_win: float
    avg_loss: float
    max_drawdown: float
    profit_factor: float


class BacktestResponse(BaseModel):
    symbol: str
    interval: str
    bars: int
    metrics: BacktestMetrics
    note: str | None = None
