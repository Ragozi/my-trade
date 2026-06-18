# My-Trade — BTC/USD Crypto Scalper v3

24/7 long-only **BTC/USD** on Alpaca Crypto. **$12 notional** per trade (configurable $10–$15), bracket orders, pullback-friendly rules, quiet logging.

## BTC/USD $10–15 Scalper v3 – Fixed for Alpaca crypto realities

**Problems fixed:**

| Issue | v3 fix |
|-------|--------|
| 2500+ Slack/log spam | Scans → **debug**; INFO every **5th scan** or on **near-signal**; Slack **signals/trades/exits only** |
| 5m uptrend blocked pullbacks | **Off by default** (`REQUIRE_5M_UPTREND=false`) |
| Volume=0 on crypto bars | **Skipped when `CRYPTO_MODE=true`** |
| Price > EMA9 blocked dips | **Removed** (`REQUIRE_ABOVE_EMA9=false`) |
| Too few signals | **15m trend** + VWAP/RSI/MACD/Bollinger stack |

**v3 entry (1m, all required):**

1. Price within **±1.2%** of VWAP (`VWAP_PULLBACK_PCT=0.012`)
2. **RSI(14) ≤ 42** and turning up
3. **MACD histogram > 0** and expanding
4. Price in **lower half of BB(20,2)** or touching lower band
5. **Volume spike: OFF** in crypto mode (optional via env)

**Optional trend filters:**

- 5m `close > EMA(20)` — default **false**
- 15m `close > EMA(20)` — default **true**

**Exit:** +1.7% TP, RSI ≥ 68, -0.65% stop, 15 min time stop.

**Example log (every 5th scan):**

```
SCAN [14:32:05] | BTC $76,587.12 | RSI=35.2 | VWAP dist=0.41% | Eligible? No -> 15m close $76,400 <= EMA20 $76,900
```

> **Disclaimer:** Educational software only. Crypto trading involves substantial risk.

## Default `.env` (BTC-optimized)

```env
CRYPTO_MODE=true
CRYPTO_SYMBOLS=BTC/USD
NOTIONAL_PER_TRADE=12.0
SCAN_INTERVAL_SECONDS=60
VERBOSE_DEBUG=false
LOG_EVERY_N_SCANS=5
SLACK_NOTIFY_SCANS=false

REQUIRE_5M_UPTREND=false
REQUIRE_15M_UPTREND=true
REQUIRE_VOLUME_SPIKE=false
REQUIRE_ABOVE_EMA9=false
REQUIRE_RSI_TURNING_UP=true
BOLLINGER_LOWER_HALF_ONLY=true

RSI_OVERSOLD=42
RSI_OVERBOUGHT=68
VWAP_PULLBACK_PCT=0.012
STOP_LOSS_PCT=0.0065
TAKE_PROFIT_PCT=0.017
MAX_HOLD_MINUTES=15
```

## Run

```powershell
cd D:\Projects\My-Trade
.\.venv\Scripts\Activate.ps1
python main.py status
python main.py run
python main.py backtest --days 30
```

## Tighten one filter at a time

After running defaults, enable stricter rules individually:

- `REQUIRE_5M_UPTREND=true` — fewer entries, more trend alignment
- `REQUIRE_VOLUME_SPIKE=true` — often blocks on Alpaca crypto
- `RSI_OVERSOLD=37` — stricter oversold
- `VWAP_PULLBACK_PCT=0.007` — must be closer to VWAP

## Suggested next steps

1. **Run with defaults** — `python main.py run` and watch for `SIGNAL FIRED` in logs
2. **Backtest 30–60 days** — `python main.py backtest --days 60` before changing filters
3. **Tighten gradually** — change one `.env` flag per session and compare trade count / win rate
