# ETH Liquidity Score v1.0 — TradingView

## What this script does

- Intended chart: ETHUSDT, 15m.
- Detects the locked ETH v1.0 sequence: confirmed 1H liquidity sweep -> 15m CHoCH + displacement -> displacement-body reaction zone -> midpoint retest.
- Uses last completed 1H / 4H information for higher-timeframe context.
- Applies the locked filters: minimum stop 0.75%, entry only 08:00-15:59 UTC, minimum TradingView quality score 4/8, target 2R.
- Draws sweep / armed / entry labels, the reaction zone, midpoint, SL and 2R target.
- Shows a top-right dashboard with the current score components and custom historical statistics: closed trades, win rate, Net R after 10 bps round-trip friction, profit factor, max drawdown and timeouts.
- Sends two alert stages: `SETUP ARMED` and `ENTRY`. CoinGlass remains a separate manual confirmation window.

## Install in TradingView

1. Open an ETHUSDT chart and set timeframe to 15 minutes.
2. Open Pine Editor.
3. Copy the full contents of `ETH_Liquidity_Score_v1.pine` into the editor.
4. Save the script and click `Add to chart`.
5. Keep the defaults for the first forward-test phase.

## Alerts

Create alerts from the script for either:

- `ETH v1.0 SETUP ARMED` — early warning that the displacement zone is ready; open CoinGlass and prepare the metrics.
- `ETH v1.0 ENTRY` — the midpoint retest has satisfied the structural filters; now check CoinGlass before any live decision.

The script also emits dynamic alert text with direction, midpoint and, for the entry alert, score / Entry / SL / TP2R.

## Dashboard interpretation

`TV Score` is 0-8 from:

1. last completed 4H trend alignment;
2. premium / discount alignment;
3. sweep penetration >= 0.10 ATR;
4. strong displacement >= 1.50 ATR and body/range >= 80%;
5. FVG bonus — production OB profile currently scores 0 here by design;
6. trigger volume >= 1.25 x prior 20-bar average;
7. retest within 6 x 15m bars;
8. entry during 08:00-15:59 UTC.

Production entry requires score >=4/8.

## Forward-test workflow

When `ENTRY` appears:

1. Take a TradingView screenshot with the signal label and dashboard visible.
2. Open the CoinGlass Supercharts layout.
3. Capture OI / OI Delta, Net Long / Net Short, Net Delta, Long/Short Accounts, Liquidations, Funding, and CVD / Taker flow if visible.
4. Save the signal even if CoinGlass later rejects it. The research sample must contain both accepted and rejected signals.

## Backtest convention

The built-in custom backtest uses the same structural signal logic shown on the chart. Entry is the reaction-zone midpoint. SL is beyond the sweep extreme by 0.15 ATR measured on the retest bar. TP is 2R. When SL and TP can both be touched on the same candle, SL is counted first. Outcomes that hit neither SL nor TP within 96 x 15m bars are counted as timeouts and excluded from win-rate calculations. Friction is modeled as 10 bps round-trip and converted into R from each trade's stop distance.

This is a research / forward-test tool, not an automatic trading system. CoinGlass confirmation is intentionally not embedded in the Pine script.
