# Teo Dashboard — Deployment Guide

Full production deployment in three parts:
- **Convex Cloud** — real-time backend (schema, mutations, HTTP actions)
- **Vercel** — React + Vite frontend
- **Railway** — Teo Python forecasting service

---

## 1. Deploy Convex Backend

### 1a. Install Convex CLI (once)
```bash
npm install -g convex
# or: bun add -g convex
```

### 1b. Initialise the project
```bash
npx convex dev
```
Follow the prompts to create/link a Convex project. This generates `convex/_generated/` locally and writes `VITE_CONVEX_URL` to `.env.local` automatically.

### 1c. Generate the auth private key
```bash
openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:2048 \
  | openssl pkcs8 -topk8 -nocrypt \
  | base64 -w0
```
Copy the output. Set it on your Convex deployment:
```bash
npx convex env set AUTH_PRIVATE_KEY "PASTE_THE_KEY_HERE"
```

### 1d. Deploy functions to production
```bash
npx convex deploy
```
Note the deployment URL printed at the end, e.g. `https://your-project.convex.site`.
The dashboard URL (for `VITE_CONVEX_URL`) is `https://your-project.convex.cloud`.

---

## 2. Deploy Frontend to Vercel

### 2a. Verify the build locally
```bash
npm install   # or: bun install
npm run build # or: bun run build
```

### 2b. Connect Vercel
1. Go to [vercel.com/new](https://vercel.com/new) and import this GitHub repo.
2. Framework preset: **Vite**
3. Add environment variable: `VITE_CONVEX_URL` = `https://your-project.convex.cloud`
4. Click **Deploy**.

Vercel auto-deploys on every push to `main`. Your permanent dashboard URL appears at the top.

---

## 3. Deploy Teo Python Service to Railway

### 3a. Connect Railway
1. Go to [railway.app/new](https://railway.app/new) → **Deploy from GitHub repo**
2. Select this repository. Railway detects the `Dockerfile` automatically.

### 3b. Set environment variables (Railway → Variables tab)
```
TEO_DASHBOARD_URL=https://your-project.convex.site
```
All other `TEO_*` variables are optional (defaults work).

### 3c. Deploy
Click **Deploy**. Railway builds the Docker image and starts the service.
Health check: `GET /health` → `{"status": "ok"}`.

---

## 4. Verify the full pipeline

Once all three services are running, test the Teo → Dashboard bridge:

```bash
curl -X POST https://your-project.convex.site/teo/propose \
  -H "Content-Type: application/json" \
  -d '{
    "direction": "LONG",
    "entryPrice": 3450,
    "stopLoss": 3420,
    "tp1": 3490,
    "tp2": 3540,
    "confidence": 72,
    "reason": "Pipeline test",
    "timeframe": "15m",
    "bias": "trend_up",
    "biasStrength": 0.75,
    "spotPrice": 3455,
    "asset": "PAXGUSDT",
    "teoScore": 0.72,
    "teoRegime": "trend_up"
  }'
```
Expected response: `{"ok": true, "id": "..."}` — the proposal appears live in the dashboard Signal Journal.

---

## Local Development

```bash
# Terminal 1: Convex backend (hot-reload + generates _generated/)
npx convex dev

# Terminal 2: Vite frontend
npm run dev     # or: bun dev

# Terminal 3: Teo Python service
pip install -e ".[dev]"
python -m uvicorn teo.main:app --reload --port 8001
```

Set `TEO_DASHBOARD_URL=http://localhost:3000` (or your local Convex site URL) in `.env` to test proposal submission locally.
