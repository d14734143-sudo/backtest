import json
import os
from itertools import product

symbol = os.environ.get('SYMBOL', 'BTCUSDT').upper()
path = f'{symbol.lower()}_full_result.json'
with open(path, encoding='utf-8') as f:
    data = json.load(f)

trades = data['trades']

SESSIONS = {
    'all': None,
    '00-07UTC': set(range(0, 8)),
    '08-15UTC': set(range(8, 16)),
    '16-23UTC': set(range(16, 24)),
}

ZONES = ['all', 'FVG', 'OB_proxy']
DIRECTIONS = ['all', 'long', 'short']
MIN_STOPS = [0.0, 0.20, 0.30, 0.50, 0.75, 1.00, 1.50]
TARGETS = ['2R', '3R']
MIN_TRAIN = 20
MIN_TEST = 15


def keep(t, zone, direction, min_stop, session):
    if zone != 'all' and t['zone_type'] != zone:
        return False
    if direction != 'all' and t['dir'] != direction:
        return False
    if t['stop_pct'] < min_stop:
        return False
    hours = SESSIONS[session]
    if hours is not None:
        hour = int(t['time'][11:13])
        if hour not in hours:
            return False
    return True


def metrics(ts, key, friction_bps=10):
    rr = 2 if key == '2R' else 3
    closed = [t for t in ts if t[key] in ('win', 'loss')]
    wins = sum(t[key] == 'win' for t in closed)
    losses = len(closed) - wins
    net = []
    for t in closed:
        gross = rr if t[key] == 'win' else -1.0
        cost_r = (friction_bps / 10000.0) / (t['risk'] / t['entry'])
        net.append(gross - cost_r)
    return {
        'closed': len(closed),
        'wins': wins,
        'losses': losses,
        'win_rate_pct': round(100 * wins / len(closed), 2) if closed else 0,
        'expectancy_R_after_10bps': round(sum(net) / len(net), 3) if net else 0,
        'net_R_after_10bps': round(sum(net), 3),
    }

rows = []
for target, zone, direction, min_stop, session in product(TARGETS, ZONES, DIRECTIONS, MIN_STOPS, SESSIONS):
    selected = [t for t in trades if keep(t, zone, direction, min_stop, session)]
    train = [t for t in selected if t['time'].startswith('2025-')]
    test = [t for t in selected if t['time'].startswith('2026-')]
    mt = metrics(train, target)
    mv = metrics(test, target)
    if mt['closed'] < MIN_TRAIN or mv['closed'] < MIN_TEST:
        continue
    rows.append({
        'target': target,
        'zone': zone,
        'direction': direction,
        'min_stop_pct': min_stop,
        'session': session,
        'train_2025': mt,
        'test_2026': mv,
        'train_hits_70pct': mt['win_rate_pct'] >= 70 and mt['expectancy_R_after_10bps'] > 0,
    })

# Candidate choice is based ONLY on the training period. The 2026 column is reported afterwards.
rows.sort(key=lambda r: (
    r['train_2025']['win_rate_pct'],
    r['train_2025']['expectancy_R_after_10bps'],
    r['train_2025']['closed']
), reverse=True)

out = {
    'symbol': symbol,
    'method': 'Filter candidates selected on 2025 only; 2026 is untouched out-of-sample validation',
    'minimum_samples': {'train_closed': MIN_TRAIN, 'test_closed': MIN_TEST},
    'tested_dimensions': {
        'targets': TARGETS,
        'zones': ZONES,
        'directions': DIRECTIONS,
        'minimum_stop_pct': MIN_STOPS,
        'sessions': list(SESSIONS),
        'friction': '10 bps round-trip',
    },
    'count_valid_combinations': len(rows),
    'count_train_candidates_at_or_above_70pct': sum(r['train_hits_70pct'] for r in rows),
    'top_10_by_train_precision': rows[:10],
}

out_path = f'{symbol.lower()}_precision_search.json'
with open(out_path, 'w', encoding='utf-8') as f:
    json.dump(out, f, indent=2)

print(json.dumps(out, indent=2))
