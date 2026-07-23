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

Kronos is a PyTorch model, so it's an optional extra:

```bash
pip install -e ".[kronos]"        # torch + huggingface-hub + safetensors
export TEO_KRONOS_MODEL=NeoQuasar/Kronos-small   # HF repo id (mini | small | base)
```

On first call Teo lazily downloads the pretrained weights from HuggingFace and caches them. If loading fails
for any reason, it falls back to the baseline and reports the reason in the response — it never hard-crashes a
forecast request.

## API

| Method | Path | Purpose |
|---|---|---|
| `GET`  | `/health`   | liveness + which forecaster is active |
| `POST` | `/forecast` | OHLCV history → forecast (fetches its own candles if none supplied) |
| `POST` | `/backtest` | replay history through a strategy config → performance metrics |

See `teo/models.py` for the exact request/response schemas.

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
  backtest/engine.py  candle replay + metrics
tests/                pytest suite (runs without ML deps)
```

## Roadmap

- [x] Service scaffold + baseline forecaster + backtest skeleton
- [ ] Wire real Kronos inference (tokenizer + model head)
- [ ] Regime-tagged outcome memory feeding the sweep
- [ ] Self-healing endpoint: detect live degradation → re-sweep → propose config swap
- [ ] Multi-asset parity with the dashboard's asset registry

## License

MIT
