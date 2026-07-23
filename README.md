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

Kronos is a PyTorch model whose `Kronos` / `KronosTokenizer` / `KronosPredictor` classes are
published on PyPI as [`kronos-model-arch`](https://pypi.org/project/kronos-model-arch/) (MIT), which
installs them under the top-level `model` package our adapter imports. So enabling real inference is
now a single step:

```bash
pip install -e ".[kronos]"   # kronos-model-arch + torch + huggingface-hub + safetensors + pandas
```

> **Note:** `kronos-model-arch` (v0.1.0) pins some transitive versions (e.g. `matplotlib==3.9.3`).
> If those clash with your environment, vendor the two model files (`model/kronos.py`,
> `model/module.py` — MIT-licensed) onto `PYTHONPATH` instead; the adapter's `from model import …`
> works identically either way. The weights themselves still download from HuggingFace on first use.

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
| `POST` | `/selfheal` | detect degradation → propose a config swap; optionally persist + recall regime memory |
| `GET`  | `/assets`   | the multi-asset registry Teo covers (filter by `?tier=` / `?source=`) |

See `teo/models.py` for the exact request/response schemas.

Run the self-heal loop across all live assets on a schedule (what the dashboard cron calls):

```bash
python -m teo.loop --interval 15m --lookback 1000     # all live tier-1 assets
python -m teo.loop --symbol BTCUSDT --interval 15m     # a single asset
```

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

4. **Regime-tagged memory** (`teo/memory.py`) — every cycle appends its outcome (symbol, regime,
   config, score) to a JSON store. On the next cycle in the *same* regime, `/selfheal` **recalls**
   the best config it ever saw in those conditions (`recalled` in the response), so adaptation
   compounds instead of re-deriving from scratch. Pass `persist: true` to record the outcome.
5. **The loop** (`teo/loop.py`, `python -m teo.loop`) fans steps 1–4 across the asset registry on a
   schedule — this is what a dashboard cron drives. Fetching is injected, so it's fully unit-tested
   without network.

Teo **proposes**, it doesn't silently self-modify — the dashboard owns whether to apply the swap and
logs it for auditability.

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
  memory.py           regime-tagged outcome store (JSON) — recall best-per-regime
  assets.py           multi-asset registry (tiers 1–3, parity with the dashboard)
  loop.py             self-heal orchestration + CLI (python -m teo.loop)
tests/                pytest suite (runs without ML deps)
```

## Roadmap

- [x] Service scaffold + baseline forecaster + backtest skeleton
- [x] Wire real Kronos inference (tokenizer + model + predictor, with baseline fallback)
- [x] Regime detection (trend/vol) tagging the sweep + self-heal decisions
- [x] Parameter-sweep engine (`/optimize`) — ranked risk-adjusted configs
- [x] Self-healing endpoint (`/selfheal`) — detect degradation → propose a config swap
- [x] Persist regime-tagged outcomes so self-heal recalls per-regime winners over time (`memory.py`)
- [x] Scheduled self-heal loop across the asset registry (`loop.py`, `python -m teo.loop`)
- [x] Multi-asset registry — tiers 1–3, parity with the dashboard (`assets.py`, `GET /assets`)
- [ ] Wire the loop's proposals into the dashboard's live journal (apply/audit on the Convex side)
- [ ] Tier-2/3 data feeds (Hyperliquid, Kraken/XMR, equities) — registry is ready, fetchers pending

## License

MIT
