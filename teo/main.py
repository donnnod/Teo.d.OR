"""Teo FastAPI service: /health, /forecast, /backtest, /optimize, /selfheal."""

from __future__ import annotations

from fastapi import FastAPI, HTTPException

from teo import __version__
from teo.backtest.engine import run_backtest
from teo.backtest.regime import Regime, detect_regime
from teo.backtest.sweep import run_sweep, score_metrics
from teo.config import settings
from teo.data.binance import fetch_klines
from teo.forecasting.base import BaselineForecaster
from teo.forecasting.kronos import KronosUnavailable, get_kronos
from teo.models import (
    BacktestRequest,
    BacktestResponse,
    ForecastRequest,
    ForecastResponse,
    OptimizeRequest,
    OptimizeResponse,
    RegimeInfo,
    ScoredConfig,
    SelfHealRequest,
    SelfHealResponse,
)
from teo.selfheal import HealthThresholds, assess

app = FastAPI(title="Teo", version=__version__)

_baseline = BaselineForecaster()


def _active_forecaster_name() -> str:
    k = get_kronos()
    return k.name if k is not None else _baseline.name


@app.get("/health")
def health() -> dict:
    return {
        "status": "ok",
        "version": __version__,
        "forecaster": _active_forecaster_name(),
        "data_source": settings.binance_base_url,
    }


@app.post("/forecast", response_model=ForecastResponse)
async def forecast(req: ForecastRequest) -> ForecastResponse:
    if req.horizon > settings.max_horizon:
        raise HTTPException(400, f"horizon exceeds max {settings.max_horizon}")

    candles = req.candles
    if not candles:
        try:
            candles = await fetch_klines(req.symbol, req.interval, limit=req.lookback)
        except Exception as e:  # upstream data error
            raise HTTPException(502, f"failed to fetch candles: {e}") from e
    if len(candles) < 20:
        raise HTTPException(422, "need at least 20 candles to forecast")

    # Prefer Kronos when available; fall back to baseline transparently.
    kronos = get_kronos()
    if kronos is not None:
        try:
            return kronos.forecast(
                candles, req.horizon, symbol=req.symbol, interval=req.interval
            )
        except KronosUnavailable:
            pass  # fall through to baseline

    return _baseline.forecast(candles, req.horizon, symbol=req.symbol, interval=req.interval)


@app.post("/backtest", response_model=BacktestResponse)
async def backtest(req: BacktestRequest) -> BacktestResponse:
    try:
        candles = await fetch_klines(
            req.symbol, req.interval, limit=req.lookback, start=req.start, end=req.end
        )
    except Exception as e:
        raise HTTPException(502, f"failed to fetch candles: {e}") from e

    metrics = run_backtest(candles, req.config)
    return BacktestResponse(
        symbol=req.symbol,
        interval=req.interval,
        bars=len(candles),
        metrics=metrics,
        note=None if metrics.trades else "no trades generated over this window",
    )


def _regime_info(regime: Regime) -> RegimeInfo:
    return RegimeInfo(
        trend=regime.trend,
        volatility=regime.volatility,
        trend_strength=regime.trend_strength,
        atr_pct=regime.atr_pct,
        label=regime.label,
    )


@app.post("/optimize", response_model=OptimizeResponse)
async def optimize(req: OptimizeRequest) -> OptimizeResponse:
    """Run a parameter sweep over recent candles and return the ranked configs."""
    try:
        candles = await fetch_klines(req.symbol, req.interval, limit=req.lookback)
    except Exception as e:
        raise HTTPException(502, f"failed to fetch candles: {e}") from e

    results = run_sweep(
        candles, base=req.base, grid=req.grid, min_trades=req.min_trades, top_k=req.top_k
    )
    ranked = [
        ScoredConfig(config=r.config, metrics=r.metrics, score=r.score) for r in results
    ]
    return OptimizeResponse(
        symbol=req.symbol,
        interval=req.interval,
        bars=len(candles),
        regime=_regime_info(detect_regime(candles)),
        best=ranked[0] if ranked else None,
        ranked=ranked,
        note=None if ranked and ranked[0].metrics.trades else "no config traded over this window",
    )


@app.post("/selfheal", response_model=SelfHealResponse)
async def selfheal(req: SelfHealRequest) -> SelfHealResponse:
    """Detect live degradation of the current config and propose a swap when warranted."""
    try:
        candles = await fetch_klines(req.symbol, req.interval, limit=req.lookback)
    except Exception as e:
        raise HTTPException(502, f"failed to fetch candles: {e}") from e

    current_metrics = run_backtest(candles, req.current)
    regime = detect_regime(candles)
    sweep = run_sweep(candles, base=req.current, grid=req.grid, min_trades=req.min_trades, top_k=1)
    best = sweep[0] if sweep else None

    decision = assess(
        current_metrics,
        best,
        regime=regime,
        thresholds=HealthThresholds(
            min_profit_factor=req.min_profit_factor,
            min_win_rate=req.min_win_rate,
            min_trades=req.min_trades,
            min_score_improvement=req.min_score_improvement,
        ),
    )

    proposed = None
    if decision.proposed_config is not None and best is not None:
        proposed = ScoredConfig(
            config=decision.proposed_config, metrics=best.metrics, score=best.score
        )

    return SelfHealResponse(
        symbol=req.symbol,
        interval=req.interval,
        bars=len(candles),
        regime=_regime_info(regime),
        status=decision.status,
        action=decision.action,
        reason=decision.reason,
        current=ScoredConfig(
            config=req.current,
            metrics=current_metrics,
            score=score_metrics(current_metrics, min_trades=req.min_trades),
        ),
        proposed=proposed,
        improvement=decision.improvement,
    )
