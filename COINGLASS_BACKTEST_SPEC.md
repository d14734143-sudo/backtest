# CoinGlass confirmation backtest specification

Purpose: test whether a separate CoinGlass confirmation window improves the existing BTC/ETH/SOL TradingView-style strategy without hindsight.

## Historical CoinGlass fields required per closed bar

CSV columns:

- `time` — UTC timestamp (ISO-8601 or Unix ms)
- `oi_close` — Open Interest close
- `net_long_cum` — cumulative Net Long
- `net_short_cum` — cumulative Net Short
- `net_position_cum` — cumulative Net Delta / Net Position
- `global_account_ratio` — global Long/Short account ratio
- `top_account_ratio` — top-trader account ratio (optional context)
- `long_liq_usd` — long liquidations USD
- `short_liq_usd` — short liquidations USD
- `funding_rate` — funding rate or OI-weighted funding close
- `taker_buy_ratio` — taker buy share in percent (optional; CVD/order-flow proxy)

Expected files:

- `coinglass_data/btcusdt_coinglass.csv`
- `coinglass_data/ethusdt_coinglass.csv`
- `coinglass_data/solusdt_coinglass.csv`

## No-lookahead rule

For each strategy entry, the engine uses only the last CoinGlass bar that was already closed at the entry timestamp. Future CoinGlass bars are never used to approve a historical entry.

## Fixed confirmation factors

1. Open Interest: OI is increasing into the signal rather than collapsing.
2. Net Long / Net Short: individual cumulative changes align with the trade direction.
3. Net Delta: change in cumulative net position aligns with the trade direction.
4. Accounts: global account ratio momentum aligns with direction while avoiding the most crowded recent 20% of readings.
5. Liquidations: a recent same-side liquidation flush is at least 1.5x the rolling 20-bar median. For a long setup this is a long-liquidation flush; for a short setup it is a short-liquidation flush.
6. Funding: reject the most crowded recent 20% of funding readings in the intended direction.
7. Taker flow: optional extra point when taker-buy share >50% for long or <50% for short.

The engine tests CoinGlass score thresholds only on 2025. The chosen threshold is then applied unchanged to 2026 holdout data.

## Output

For BTCUSDT, ETHUSDT and SOLUSDT the report returns:

- number of matched trades
- wins / losses
- win rate
- expectancy after 10 bps round-trip cost
- net R after costs
- profit factor after costs
- selected CoinGlass score threshold from 2025
- untouched 2026 validation metrics

No result should be published if required historical CoinGlass fields are missing.
