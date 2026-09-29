import json

with open('btc_full_result.json') as f:
    data = json.load(f)

trades = data['trades']
THRESHOLDS = [0.0, 0.1, 0.2, 0.3, 0.5]
ZONES = ['ALL', 'FVG', 'OB_proxy']
BPS = [0, 5, 10]


def calc(ts, key, min_stop_pct, bps):
    rr = 2 if key == '2R' else 3
    xs = [t for t in ts if t['stop_pct'] >= min_stop_pct and t[key] in ('win', 'loss')]
    wins = sum(t[key] == 'win' for t in xs)
    losses = len(xs) - wins
    vals = []
    for t in xs:
        gross = rr if t[key] == 'win' else -1
        cost_r = (bps / 10000.0) / (t['risk'] / t['entry']) if bps else 0.0
        vals.append(gross - cost_r)
    return {
        'closed': len(xs),
        'wins': wins,
        'losses': losses,
        'win_rate_pct': round(100 * wins / len(xs), 2) if xs else 0,
        'expectancy_R': round(sum(vals) / len(vals), 3) if xs else 0,
        'net_R': round(sum(vals), 3),
    }


def year_calc(ts, key, min_stop_pct, bps):
    years = sorted(set(t['time'][:4] for t in ts if t['time'][:4] in ('2025', '2026')))
    return {y: calc([t for t in ts if t['time'].startswith(y)], key, min_stop_pct, bps) for y in years}

out = {'grid': [], 'candidate_check': {}}
for zone in ZONES:
    zts = trades if zone == 'ALL' else [t for t in trades if t['zone_type'] == zone]
    for min_stop in THRESHOLDS:
        for key in ('2R', '3R'):
            row = {'zone': zone, 'min_stop_pct': min_stop, 'target': key}
            for bps in BPS:
                row[f'{bps}_bps'] = calc(zts, key, min_stop, bps)
            out['grid'].append(row)

# Not an optimized production rule: a practical robustness checkpoint chosen to remove micro-stop artifacts.
# 0.2% is evaluated because a 10 bps round-trip then costs at most about 0.5R before any extra slippage.
candidate = [t for t in trades if t['zone_type'] == 'FVG']
out['candidate_check'] = {
    'definition': 'FVG only; minimum stop distance 0.20%; no claim of optimization',
    '2R_10bps': calc(candidate, '2R', 0.2, 10),
    '3R_10bps': calc(candidate, '3R', 0.2, 10),
    '2R_by_year_10bps': year_calc(candidate, '2R', 0.2, 10),
    '3R_by_year_10bps': year_calc(candidate, '3R', 0.2, 10),
}

with open('btc_robustness_result.json', 'w') as f:
    json.dump(out, f, indent=2)

print(json.dumps(out, indent=2))
