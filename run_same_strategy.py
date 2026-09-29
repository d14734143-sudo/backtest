import os
from pathlib import Path

symbol = os.environ.get('SYMBOL', 'ETHUSDT').upper()
if symbol not in {'BTCUSDT', 'ETHUSDT', 'SOLUSDT'}:
    raise SystemExit(f'Unsupported SYMBOL: {symbol}')

src = Path('btc_full_backtest.py').read_text(encoding='utf-8')
src = src.replace("SYMBOL = 'BTCUSDT'", f"SYMBOL = '{symbol}'")
src = src.replace(
    "BASE = 'https://finom.github.io/static-klines/api/klines/15m/BTCUSDT/{date}.json'",
    f"BASE = 'https://finom.github.io/static-klines/api/klines/15m/{symbol}/{{date}}.json'"
)
src = src.replace("'btc_full_result.json'", f"'{symbol.lower()}_full_result.json'")

# Execute the exact BTC strategy implementation with only the market symbol changed.
exec(compile(src, 'btc_full_backtest.py', 'exec'), {'__name__': '__main__'})
