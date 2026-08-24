# eilaji trading bot (freqtrade + Bybit)

A [freqtrade](https://www.freqtrade.io) crypto trading bot, preconfigured for
**Bybit demo trading** so you can run the real bot on live markets with **zero
funds and zero risk** before ever touching real money.

> **Disclaimer.** Automated trading can lose money fast. This repo ships a
> deliberately simple *starter* strategy with **no proven edge**. Treat it as a
> learning scaffold. Never trade money you can't afford to lose.

---

## What each safety mode means

| Mode | `config.json` | What happens |
|------|---------------|--------------|
| **Dry-run** (default here) | `dry_run: true` | Live prices, simulated wallet. **No orders sent anywhere.** |
| **Bybit demo** | `dry_run: false` + `demo_trading: true` | Real Bybit *demo* account, live markets, fake money. Behaves like live. |
| **Live** | `dry_run: false` + `demo_trading: false` | **Real orders, real money.** Only after validation. |

This project starts in **dry-run**. To graduate to Bybit demo, see step 5.

---

## Prerequisites

- **Docker** + **Docker Compose** ([install](https://docs.docker.com/get-docker/))
- A **Bybit account** (demo mode needs no KYC/funds to start experimenting)

No Python install needed — everything runs in the Docker image.

---

## Quick start

### 1. Get Bybit demo API keys
- Log in to Bybit → account menu → **Demo Trading**.
- In the demo account: **API** → create key → enable **Trade** (spot).
  **Leave withdrawals disabled.**

### 2. Configure secrets
```bash
cp .env.example .env
# edit .env, paste your demo key + secret
```

### 3. Set the web-dashboard credentials
Open `user_data/config.json` and replace the three `CHANGE_ME` values:
```bash
# generate a jwt secret:
openssl rand -hex 32
```
Put that in `api_server.jwt_secret_key`, set a real `password`, and set any
string for `ws_token`.

### 4. Download historical data + backtest FIRST
Never run a strategy live (or even demo) before you've seen how it did on the past.
```bash
# 1000 5-minute candles for the whitelisted pairs
docker compose run --rm freqtrade download-data \
  --config user_data/config.json --timeframe 5m --days 180

# backtest the starter strategy over that data
docker compose run --rm freqtrade backtesting \
  --config user_data/config.json --strategy SampleMomentum \
  --timeframe 5m --timerange=20260101-

# check for the two classic backtest lies:
docker compose run --rm freqtrade lookahead-analysis \
  --config user_data/config.json --strategy SampleMomentum
```

### 5. Run it
**Dry-run (default, totally safe):**
```bash
docker compose up -d
docker compose logs -f          # watch it think
```

**Switch to Bybit demo** (real demo account, live markets, fake money):
in `user_data/config.json` set `"dry_run": false` (leave
`"demo_trading": true`), then `docker compose up -d --force-recreate`.

### 6. Watch it
- Web UI: <http://127.0.0.1:8080> (login = username/password from config).
- Or enable Telegram (see `.env.example`) for `/status`, `/profit`, `/balance`,
  `/forceexit`, `/stop` from your phone.

---

## Going LIVE (real money) — the checklist

Do **not** skip steps. Most losses come from skipping step 3.

1. Fund a **real** (non-demo) Bybit account. Use a **dedicated sub-account**.
2. Create a **live** API key: **Trade only, withdrawals OFF, IP-whitelisted**.
3. **Dry-run for several weeks** and confirm live results track your backtest.
   If they diverge, your backtest is wrong — fix it before risking money.
4. In `config.json`: `"dry_run": false` **and** `"demo_trading": false`.
5. Start tiny: low `max_open_trades`, small `stake_amount`, keep the
   `protections` block enabled (those are your circuit breakers).

---

## Project layout
```
freqtrade-bot/
├── docker-compose.yml            # how the bot runs
├── .env.example                  # credential template (copy → .env)
├── .gitignore                    # keeps secrets + runtime data out of git
└── user_data/
    ├── config.json               # all bot settings
    └── strategies/
        └── SampleMomentum.py      # the trading logic — edit this
```

## How the analysis works (short version)
- **Indicators / signals:** your code in `SampleMomentum.py` using TA-Lib +
  `technical` on pandas dataframes. This is where the trading logic lives.
- **Parameter tuning:** `freqtrade hyperopt` searches the `IntParameter` /
  `DecimalParameter` values using **Optuna** (genetic / Bayesian samplers).
- **Data & orders:** the **ccxt** library talks to Bybit.
- **Storage:** SQLite via SQLAlchemy (`user_data/tradesv3.sqlite`).

Full docs: <https://www.freqtrade.io>
