# TradingView + CoinGlass Forward Test Protocol

## Purpose
Measure whether CoinGlass confirmation improves the existing TradingView strategy on BTCUSDT, ETHUSDT and SOLUSDT without hindsight.

## Workflow
1. TradingView produces the base setup. CoinGlass never creates the setup by itself.
2. At signal time, record the last completed 15m CoinGlass values and the preceding 15m values.
3. Save every TradingView setup, including those that CoinGlass would reject.
4. Freeze the CoinGlass assessment before the trade outcome is known. Never edit confirmation bits after the fact.
5. Record the hypothetical strategy outcome at the normal SL / 2R target even when the live trade was skipped.
6. Keep `taken_live` separate from the research sample.

## Seven CoinGlass confirmation blocks
Each block is recorded as 0/1. The first version is intentionally simple so it can be applied consistently from the Supercharts window.

### 1. Open Interest / OI Delta
- Long: after the downside sweep, OI has stopped contracting and is flat/rising into confirmation.
- Short: after the upside sweep, OI has stopped contracting and is flat/rising into confirmation.
- Score 0 when OI is still collapsing at the intended entry.

### 2. Net Long / Net Short positioning
- Long: Net Long improves and Net Short does not expand aggressively against the setup.
- Short: Net Short improves and Net Long does not expand aggressively against the setup.

### 3. Net Delta
- Long: Net Delta improves / turns positive versus T-15.
- Short: Net Delta deteriorates / turns negative versus T-15.

### 4. Accounts positioning
Use Global Accounts and, when visible, Top Accounts.
- Long: account positioning improves toward long without an obvious one-sided crowding extreme.
- Short: account positioning improves toward short without an obvious one-sided crowding extreme.
- When Global and Top Accounts strongly disagree, score 0 and note the divergence.

### 5. Liquidation context
Look back roughly 30-60 minutes before entry.
- Long: downside sweep is accompanied by a visible long-liquidation flush; preferably liquidation activity is clearly above the recent background.
- Short: upside sweep is accompanied by a visible short-liquidation flush.

### 6. Funding
- Long: funding is neutral, negative, or at least not visibly stretched positive.
- Short: funding is neutral, positive, or at least not visibly stretched negative.
- The purpose is to avoid entering in the most crowded direction.

### 7. Flow confirmation: CVD / Taker Buy-Sell
- Long: CVD stops falling / turns up / shows bullish divergence and taker buying strengthens.
- Short: CVD stops rising / turns down / shows bearish divergence and taker selling strengthens.
- If only one of CVD or taker flow is visible, use the available one and note it.

## Score
`CG Score = sum of the seven confirmation blocks`, from 0 to 7.

During the data-collection phase, do NOT impose a production threshold. The analyzer compares:
- TradingView only
- CG Score >= 3
- CG Score >= 4
- CG Score >= 5
- CG Score >= 6
- CG Score = 7

## Sample-size rule
- First preliminary review: 30 closed TradingView signals per symbol.
- Preferred decision sample: 50+ closed signals per symbol.
- BTC, ETH and SOL are evaluated separately.

## Outcome fields
For every signal record:
- result: `win` or `loss`
- pnl_r: realized/hypothetical R after the normal strategy outcome rule
- taken_live: whether the trader actually entered; this does not change inclusion in the research sample

## Anti-bias rules
- Use only values visible at or before the signal time.
- Do not use T+15 data to score the entry.
- Do not delete losing or skipped setups.
- Do not change the score after seeing the outcome.
- Do not choose the final CoinGlass threshold before the minimum sample is reached.
