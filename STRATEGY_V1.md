# ETH Strategy v1.0

Status: VALIDATED CANDIDATE
Symbol: ETHUSDT
Execution timeframe: 15m
Higher-timeframe liquidity structure: 1H
Higher-timeframe context: 4H
Primary target: 2R
Assumed round-trip friction: 10 bps
Validation period: 2026 holdout, not used for parameter selection

## Core setup

1. Detect a confirmed 1H pivot liquidity sweep. Pivots use 2 bars left / 2 bars right and only completed 1H bars; no current-hour look-ahead.
2. Within 24 x 15m bars after the sweep, require a 15m CHoCH with displacement:
   - candle body >= 1.0 ATR(14)
   - body/range >= 70%
3. Build the reaction zone from the displacement candle body when no qualifying FVG is present. In the research engine this zone is named `OB_proxy`; for publication it should be described as the displacement-body reaction zone, not a confirmed institutional order block.
4. Wait for a retest of the zone within 12 x 15m bars.
5. Entry = midpoint of the reaction zone.
6. Stop = beyond the sweep extreme by 0.15 ATR.
7. Reject trades where stop distance is below 0.75% of entry price.
8. Allow entries only from 08:00 through 15:59 UTC.
9. Require quality score >= 4 of 8.
10. Take profit = 2R.
11. Same-bar conservative rule: if SL and TP could both be touched on one bar, count SL first.

## Quality score: 8 binary points

- 4H trend alignment: last completed 4H close and EMA20/EMA50 aligned with trade direction.
- Premium/discount alignment: long entry below the latest confirmed 1H swing midpoint; short entry above it.
- Sweep penetration >= 0.10 ATR.
- Strong displacement: body >= 1.50 ATR and body/range >= 80%.
- Quality FVG: true FVG with size >= 0.15 ATR.
- Volume confirmation: trigger volume >= 1.25 x prior 20-bar average volume.
- Fast retest: retest within 6 x 15m bars after trigger.
- Active session: entry between 08:00 and 15:59 UTC.

A trade is accepted at score >= 4. The selected production profile uses the displacement-body reaction zone (`OB_proxy`) and therefore the FVG quality point is optional rather than mandatory.

## Locked production profile

- Symbol: ETHUSDT
- Direction: long and short
- Zone: displacement-body reaction zone (`OB_proxy` in the backtest engine)
- Minimum stop: 0.75%
- Session: 08:00-15:59 UTC
- Minimum quality score: 4/8
- Target: 2R
- Friction model: 10 bps round-trip

## Backtest / validation results

### 2025 H1 selection sample
- Closed trades: 14
- Wins / losses: 8 / 6
- Win rate: 57.14%
- Expectancy after 10 bps: +0.626R/trade
- Profit factor after 10 bps: 2.336
- Max drawdown: 2.172R

### 2025 H2 confirmation sample
- Closed trades: 16
- Wins / losses: 10 / 6
- Win rate: 62.50%
- Expectancy after 10 bps: +0.774R/trade
- Profit factor after 10 bps: 2.875
- Max drawdown: 2.246R

### 2026 untouched holdout validation
- Closed trades: 24
- Wins / losses: 13 / 11
- Win rate: 54.17%
- Expectancy after 10 bps: +0.535R/trade
- Net result after 10 bps: +12.841R
- Profit factor after 10 bps: 2.074
- Max drawdown: 4.437R
- Max loss streak: 4

### Full selected sample
- Closed trades: 54
- Wins / losses: 31 / 23
- Win rate: 57.41%
- Expectancy after 10 bps: +0.630R/trade
- Net result after 10 bps: +33.993R
- Profit factor after 10 bps: 2.353
- Max drawdown: 4.437R
- Max loss streak: 4

## Asset gate

BTCUSDT: NOT ENABLED in v1.0. Its selected 2026 holdout result was 39.39% win rate, +0.011R expectancy after 10 bps, profit factor 1.016.

SOLUSDT: NOT ENABLED in v1.0. Its selected 2026 holdout result was 42.11% win rate, +0.087R expectancy after 10 bps, profit factor 1.127.

ETHUSDT is the only asset that passed all predefined validation gates: at least 15 holdout trades, win rate >=45%, expectancy >=+0.10R after 10 bps, and profit factor >=1.15.
