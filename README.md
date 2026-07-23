# Teo — Forecasting & Self-Healing Service

**Teo** is the Python sidecar for the [xau-scalper](https://github.com/donnnod/xau-scalper) trading dashboard.
It runs the workloads that can't live inside Convex/TypeScript:

1. **Price forecasting** with [Kronos](https://github.com/shiyu-coder/Kronos) — an open-source (MIT) foundation
   model for financial K-lines. Teo turns OHLCV history into a probabilistic forecast the dashboard can fold
   into its TA-based signal grade.
2. **Backtesting & parameter sweeps** — replays historical candles through a strategy config and scores it
   (net points, win-rate, drawdown, profit factor), so the self-healing loop can find and swap in better
   parameters when live performance degrades.

The dashboard calls Teo over plain HTTP. Teo holds **no secrets** and uses only the free, keyless Binance
data endpoint (`data-api.binance.vision`).

```
┌────────────────────┐        HTTP        ┌──────────────────────────────┐
│ xau-scalper        │  ───────────────▶  │ Teo (FastAPI)                │
│ (Convex cron)      │   /forecast        │  • Kronos inference          │
│                    │   /backtest        │  • backtest / param sweep    │
└────────────────────┘  ◀───────────────  │  • free Binance data feed    │
                          JSON forecast    └──────────────────────────────┘
```

## Quick start

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e .            # core service (no ML weights needed)
uvicorn teo.main:app --reload --port 8000
```

Then:

```bash
curl -s localhost:8000/health | jq
curl -s -X POST localhost:8000/forecast \
  -H 'content-type: application/json' \
  -d '{"symbol":"BTCUSDT","interval":"5m","horizon":12}' | jq
```

Without the Kronos weights installed, `/forecast` returns a transparent **baseline** forecast
(EMA-drift + ATR-scaled cone) and sets `"model": "baseline"` — so the whole pipeline is testable end-to-end
before any GPU/model is wired in.

## Enabling Kronos

Kronos is a PyTorch model whose `Kronos` / `KronosTokenizer` / `KronosPredictor` classes ship in the
[Kronos repo's](https://github.com/shiyu-coder/Kronos) own `model` package (they subclass
`PyTorchModelHubMixin`). So enabling real inference is two steps:

```bash
# 1) install the heavy deps
pip install -e ".[kronos]"        # torch + huggingface-hub + safetensors + pandas

# 2) make the Kronos `model` package importable (it isn't on PyPI)
#    e.g. clone it and add to PYTHONPATH, or vendor model/ into your deployment
git clone https://github.com/shiyu-coder/Kronos
export PYTHONPATH="$PWD/Kronos:$PYTHONPATH"
```

Then point Teo at the weights:

```bash
export TEO_KRONOS_MODEL=NeoQuasar/Kronos-small          # mini | small | base
export TEO_KRONOS_TOKENIZER=NeoQuasar/Kronos-Tokenizer-base   # optional; sensible default
export TEO_KRONOS_DEVICE=cuda:0                         # cpu works too, just slower
export TEO_KRONOS_MAX_CONTEXT=512                       # context window (bars)
```

On first call Teo lazily builds the predictor (tokenizer + model from HuggingFace), then runs genuine
inference via `KronosPredictor.predict(...)`: the predicted per-bar high/low become the forecast cone and
the final predicted close drives the directional read. If **anything** is missing or fails — deps, weights,
device, or an inference error — Teo raises internally and falls back to the transparent baseline, so a
`/forecast` request never hard-crashes.

> The torch-free glue (interval math, future timestamps, predicted-OHLCV → cone) lives in
> `teo/forecasting/kronos_adapt.py` and is fully unit-tested without any ML dependency; `kronos.py`
> owns only the model/torch side.

## API

| Method | Path | Purpose |
|---|---|---|
| `GET`  | `/health`   | liveness + which forecaster is active |
| `POST` | `/forecast` | OHLCV history → forecast (fetches its own candles if none supplied) |
| `POST` | `/backtest` | replay history through a strategy config → performance metrics |
| `POST` | `/optimize` | parameter sweep over recent candles → ranked configs + market regime |
| `POST` | `/selfheal` | detect degradation of the current config → propose a config swap when warranted |

See `teo/models.py` for the exact request/response schemas.

## Self-healing (the "brain + memory")

The self-healing loop is how Teo keeps adapting as markets shift, instead of running one static
config forever:

1. **Regime detection** (`teo/backtest/regime.py`) tags the recent window as trend up / down / chop
   plus a volatility band — so every judgement is made *in context*, not on raw recent bars alone.
2. **Parameter sweep** (`teo/backtest/sweep.py`, `POST /optimize`) backtests a grid of strategy
   knobs and ranks them on a **risk-adjusted score** (return per unit of drawdown, nudged by profit
   factor and win rate). Under-traded configs are pushed to the bottom so a lucky 2-trade config
   can't win.
3. **The decision** (`teo/selfheal.py`, `POST /selfheal`) scores the *current* config on recent
   data; if it has degraded (profit factor / win-rate below the thresholds) **and** the sweep finds
   a candidate that clears a minimum improvement margin, it returns `action: "propose_swap"` with the
   proposed config, the expected score gain, and the regime it fired in. Otherwise it holds.

Teo **proposes**, it doesn't silently self-modify — the dashboard owns whether to apply the swap and
logs it for auditability. Persisting per-regime winners so the loop *recalls* what worked last time
this regime appeared is the next roadmap item.

## Layout

```
teo/
  main.py             FastAPI app + routes
  config.py           env-driven settings
  models.py           pydantic request/response schemas
  data/binance.py     free keyless klines fetch (paginated)
  forecasting/
    base.py           Forecaster protocol + baseline implementation
    kronos.py         lazy Kronos wrapper (optional torch)
  backtest/
    engine.py         candle replay + metrics
    regime.py         trend / volatility regime detection
    sweep.py          parameter-sweep engine + risk-adjusted scoring
  selfheal.py         degradation detection + config-swap proposal
tests/                pytest suite (runs without ML deps)
```

## Roadmap

- [x] Service scaffold + baseline forecaster + backtest skeleton
- [x] Wire real Kronos inference (tokenizer + model + predictor, with baseline fallback)
- [x] Regime detection (trend/vol) tagging the sweep + self-heal decisions
- [x] Parameter-sweep engine (`/optimize`) — ranked risk-adjusted configs
- [x] Self-healing endpoint (`/selfheal`) — detect degradation → propose a config swap
- [ ] Persist regime-tagged outcomes so self-heal recalls per-regime winners over time
- [ ] Scheduled self-heal loop wired to the dashboard's live journal
- [ ] Multi-asset parity with the dashboard's asset registry

## License

MIT
