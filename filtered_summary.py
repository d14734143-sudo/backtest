import json
import os

symbol = os.environ.get('SYMBOL', 'ETHUSDT').upper()
path = f'{symbol.lower()}_full_result.json'
with open(path, encoding='utf-8') as f:
    data = json.load(f)

trades = [t for t in data['trades'] if t['zone_type'] == 'FVG' and t['stop_pct'] >= 0.20]

def summarize(key, bps=10):
    rr = 2 if key == '2R' else 3
    closed = [t for t in trades if t[key] in ('win', 'loss')]
    wins = sum(t[key] == 'win' for t in closed)
    losses = len(closed) - wins
    gross_vals = [(rr if t[key] == 'win' else -1.0) for t in closed]
    net_vals = []
    for t, gross in zip(closed, gross_vals):
        cost_r = (bps / 10000.0) / (t['risk'] / t['entry'])
        net_vals.append(gross - cost_r)
    return {
        'setups': len(trades),
        'closed': len(closed),
        'wins': wins,
        'losses': losses,
        'win_rate_pct': round(100 * wins / len(closed), 2) if closed else 0,
        'gross_expectancy_R': round(sum(gross_vals) / len(gross_vals), 3) if gross_vals else 0,
        'gross_net_R': round(sum(gross_vals), 3),
        'profit_factor_gross': round((wins * rr) / losses, 3) if losses else ('inf' if wins else 0),
        'expectancy_R_after_10bps': round(sum(net_vals) / len(net_vals), 3) if net_vals else 0,
        'net_R_after_10bps': round(sum(net_vals), 3),
    }

out = {
    'symbol': symbol,
    'period': data['period'],
    'filter': 'FVG only + stop_pct >= 0.20%',
    'friction': '10 bps round-trip',
    '2R': summarize('2R'),
    '3R': summarize('3R'),
}

out_path = f'{symbol.lower()}_filtered_summary.json'
with open(out_path, 'w', encoding='utf-8') as f:
    json.dump(out, f, indent=2)

print(json.dumps(out, indent=2))
