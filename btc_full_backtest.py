import json
import math
import urllib.request
from datetime import datetime, timezone, timedelta

# Full BTC historical backtest using the same logic as the corrected pilot.
SYMBOL = 'BTCUSDT'
BASE = 'https://finom.github.io/static-klines/api/klines/15m/BTCUSDT/{date}.json'
START = datetime(2024, 12, 30, tzinfo=timezone.utc)
END_EXCLUSIVE = datetime(2026, 9, 28, tzinfo=timezone.utc)  # includes all bars through Sep 27 UTC

RULES = {
    'structure': '1H confirmed pivot liquidity sweep -> 15m CHoCH',
    'pivot': '2 left / 2 right',
    'ATR': 14,
    'sweep_to_trigger': '<=24 x 15m bars',
    'displacement_body': '>=1 ATR',
    'body_ratio': '>=70%',
    'FVG': '>=0.10 ATR; otherwise displacement candle body used as OB proxy',
    'retest': '<=12 x 15m bars',
    'SL': 'sweep extreme +/-0.15 ATR',
    'outcome_horizon': '<=96 x 15m bars after retest',
    'same_bar_ordering': 'SL before TP (conservative)'
}


def mondays(a, b_exclusive):
    d = a
    while d.weekday() != 0:
        d += timedelta(days=1)
    while d < b_exclusive:
        yield d
        d += timedelta(days=7)


def fetch_week(d):
    url = BASE.format(date=d.strftime('%Y-%m-%d'))
    try:
        with urllib.request.urlopen(url, timeout=30) as r:
            raw = json.load(r)
    except Exception as e:
        print(f'WARN missing/unreadable {url}: {e}')
        return []
    out = []
    start_ms = int(START.timestamp() * 1000)
    end_ms = int(END_EXCLUSIVE.timestamp() * 1000)
    for x in raw:
        t = int(x[0])
        if start_ms <= t < end_ms:
            out.append({
                't': t,
                'o': float(x[1]),
                'h': float(x[2]),
                'l': float(x[3]),
                'c': float(x[4]),
                'v': float(x[5]),
            })
    return out


def atr14(bars):
    trs = []
    out = [None] * len(bars)
    for i, b in enumerate(bars):
        pc = bars[i - 1]['c'] if i else b['c']
        tr = max(b['h'] - b['l'], abs(b['h'] - pc), abs(b['l'] - pc))
        trs.append(tr)
        if i >= 13:
            out[i] = sum(trs[i - 13:i + 1]) / 14
    return out


def pivots(bars, left=2, right=2):
    ph = [False] * len(bars)
    pl = [False] * len(bars)
    for i in range(left, len(bars) - right):
        h = bars[i]['h']
        l = bars[i]['l']
        if all(h > bars[j]['h'] for j in range(i - left, i)) and all(h >= bars[j]['h'] for j in range(i + 1, i + right + 1)):
            ph[i] = True
        if all(l < bars[j]['l'] for j in range(i - left, i)) and all(l <= bars[j]['l'] for j in range(i + 1, i + right + 1)):
            pl[i] = True
    return ph, pl


def aggregate_1h(bars):
    out = []
    for i in range(0, len(bars), 4):
        g = bars[i:i + 4]
        if len(g) < 4:
            break
        out.append({
            't': g[0]['t'],
            'o': g[0]['o'],
            'h': max(x['h'] for x in g),
            'l': min(x['l'] for x in g),
            'c': g[-1]['c'],
        })
    return out


def latest_confirmed_pivots_1h(hbars):
    ph, pl = pivots(hbars, 2, 2)
    res = []
    last_hi = None
    last_lo = None
    for i in range(len(hbars)):
        ci = i - 2
        if ci >= 0:
            if ph[ci]:
                last_hi = (ci, hbars[ci]['h'])
            if pl[ci]:
                last_lo = (ci, hbars[ci]['l'])
        res.append((last_hi, last_lo))
    return res


def run(bars):
    atr = atr14(bars)
    ph15, pl15 = pivots(bars, 2, 2)
    hbars = aggregate_1h(bars)
    p1 = latest_confirmed_pivots_1h(hbars)

    trades = []
    last_hi15 = None
    last_lo15 = None
    pending = None

    for i, b in enumerate(bars):
        ci = i - 2
        if ci >= 0:
            if ph15[ci]:
                last_hi15 = (ci, bars[ci]['h'])
            if pl15[ci]:
                last_lo15 = (ci, bars[ci]['l'])
        if atr[i] is None or not p1:
            continue

        hi1, lo1 = p1[min(i // 4, len(p1) - 1)]
        sweep = None
        if hi1 and b['h'] > hi1[1] and b['c'] < hi1[1]:
            sweep = ('short', b['h'])
        elif lo1 and b['l'] < lo1[1] and b['c'] > lo1[1]:
            sweep = ('long', b['l'])

        if sweep:
            pending = {
                'dir': sweep[0],
                'sweep_ext': sweep[1],
                'sweep_i': i,
                'choch': False,
                'zone': None,
                'expires': i + 24,
            }

        if not pending:
            continue
        if i > pending['expires']:
            pending = None
            continue

        body = abs(b['c'] - b['o'])
        rng = max(b['h'] - b['l'], 1e-9)
        disp = body >= atr[i] and body / rng >= 0.70

        if pending['dir'] == 'long' and last_hi15 and b['c'] > last_hi15[1] and disp and b['c'] > b['o']:
            if i >= 2 and bars[i - 2]['h'] < b['l'] and (b['l'] - bars[i - 2]['h']) >= 0.10 * atr[i]:
                zone = (bars[i - 2]['h'], b['l'])
                zone_type = 'FVG'
            else:
                zone = (min(b['o'], b['c']), max(b['o'], b['c']))
                zone_type = 'OB_proxy'
            pending.update({'choch': True, 'zone': zone, 'zone_type': zone_type, 'trigger_i': i, 'retest_deadline': i + 12})

        elif pending['dir'] == 'short' and last_lo15 and b['c'] < last_lo15[1] and disp and b['c'] < b['o']:
            if i >= 2 and bars[i - 2]['l'] > b['h'] and (bars[i - 2]['l'] - b['h']) >= 0.10 * atr[i]:
                zone = (b['h'], bars[i - 2]['l'])
                zone_type = 'FVG'
            else:
                zone = (min(b['o'], b['c']), max(b['o'], b['c']))
                zone_type = 'OB_proxy'
            pending.update({'choch': True, 'zone': zone, 'zone_type': zone_type, 'trigger_i': i, 'retest_deadline': i + 12})

        if pending and pending.get('choch') and i > pending['trigger_i']:
            if i > pending['retest_deadline']:
                pending = None
                continue

            zl, zh = pending['zone']
            touched = b['l'] <= zh and b['h'] >= zl
            if not touched:
                continue

            entry = (zl + zh) / 2
            if pending['dir'] == 'long':
                stop = pending['sweep_ext'] - 0.15 * atr[i]
                risk = entry - stop
            else:
                stop = pending['sweep_ext'] + 0.15 * atr[i]
                risk = stop - entry

            if risk <= 0:
                pending = None
                continue

            outcomes = {2: 'open', 3: 'open'}
            end = min(len(bars), i + 96)
            exit_time = {2: None, 3: None}

            for j in range(i + 1, end):
                bj = bars[j]
                for rr in (2, 3):
                    if outcomes[rr] != 'open':
                        continue
                    if pending['dir'] == 'long':
                        hit_sl = bj['l'] <= stop
                        hit_tp = bj['h'] >= entry + rr * risk
                    else:
                        hit_sl = bj['h'] >= stop
                        hit_tp = bj['l'] <= entry - rr * risk

                    if hit_sl:
                        outcomes[rr] = 'loss'
                        exit_time[rr] = bj['t']
                    elif hit_tp:
                        outcomes[rr] = 'win'
                        exit_time[rr] = bj['t']

            trades.append({
                'time': datetime.fromtimestamp(b['t'] / 1000, tz=timezone.utc).isoformat(),
                't': b['t'],
                'dir': pending['dir'],
                'zone_type': pending['zone_type'],
                'entry': entry,
                'stop': stop,
                'risk': risk,
                'stop_pct': risk / entry * 100,
                '2R': outcomes[2],
                '3R': outcomes[3],
                'exit_2R': datetime.fromtimestamp(exit_time[2] / 1000, tz=timezone.utc).isoformat() if exit_time[2] else None,
                'exit_3R': datetime.fromtimestamp(exit_time[3] / 1000, tz=timezone.utc).isoformat() if exit_time[3] else None,
            })
            pending = None

    return trades


def equity_metrics(closed, key):
    rr = 2 if key == '2R' else 3
    equity = 0.0
    peak = 0.0
    max_dd = 0.0
    max_loss_streak = 0
    cur_loss_streak = 0
    for t in sorted(closed, key=lambda x: x['t']):
        pnl = rr if t[key] == 'win' else -1
        equity += pnl
        peak = max(peak, equity)
        max_dd = max(max_dd, peak - equity)
        if pnl < 0:
            cur_loss_streak += 1
            max_loss_streak = max(max_loss_streak, cur_loss_streak)
        else:
            cur_loss_streak = 0
    return {'net_R': round(equity, 3), 'max_drawdown_R': round(max_dd, 3), 'max_loss_streak': max_loss_streak}


def stats(ts, key):
    rr = 2 if key == '2R' else 3
    closed = [t for t in ts if t[key] in ('win', 'loss')]
    wins = sum(t[key] == 'win' for t in closed)
    losses = len(closed) - wins
    base = {
        'trades': len(ts),
        'closed': len(closed),
        'open': len(ts) - len(closed),
        'wins': wins,
        'losses': losses,
        'win_rate_pct': round(100 * wins / len(closed), 2) if closed else 0,
        'expectancy_R': round((wins * rr - losses) / len(closed), 3) if closed else 0,
        'profit_factor_R': round((wins * rr) / losses, 3) if losses else ('inf' if wins else 0),
        'avg_stop_pct': round(sum(t['stop_pct'] for t in ts) / len(ts), 3) if ts else 0,
    }
    base.update(equity_metrics(closed, key))
    return base


def split_stats(ts, key, field):
    values = sorted(set(t[field] for t in ts))
    return {v: stats([t for t in ts if t[field] == v], key) for v in values}


def monthly_breakdown(ts, key):
    buckets = {}
    for t in ts:
        month = t['time'][:7]
        buckets.setdefault(month, []).append(t)
    return {m: stats(v, key) for m, v in sorted(buckets.items())}


def yearly_breakdown(ts, key):
    buckets = {}
    for t in ts:
        year = t['time'][:4]
        buckets.setdefault(year, []).append(t)
    return {y: stats(v, key) for y, v in sorted(buckets.items())}


def friction_stress(ts, key, roundtrip_bps_values=(5, 10, 20)):
    rr = 2 if key == '2R' else 3
    closed = [t for t in ts if t[key] in ('win', 'loss')]
    out = {}
    for bps in roundtrip_bps_values:
        vals = []
        for t in closed:
            gross = rr if t[key] == 'win' else -1
            cost_r = (bps / 10000.0) / (t['risk'] / t['entry'])
            vals.append(gross - cost_r)
        out[f'{bps}_bps_roundtrip'] = {
            'expectancy_R_after_friction': round(sum(vals) / len(vals), 3) if vals else 0,
            'net_R_after_friction': round(sum(vals), 3),
        }
    return out


bars = []
weeks_loaded = 0
for d in mondays(START, END_EXCLUSIVE):
    w = fetch_week(d)
    if w:
        weeks_loaded += 1
        bars.extend(w)

bars.sort(key=lambda x: x['t'])
# De-duplicate just in case the source overlaps weekly files.
uniq = {}
for b in bars:
    uniq[b['t']] = b
bars = [uniq[k] for k in sorted(uniq)]

trades = run(bars)
for t in trades:
    t['year'] = t['time'][:4]

result = {
    'symbol': SYMBOL,
    'period': f'{START.date().isoformat()} to {(END_EXCLUSIVE - timedelta(days=1)).date().isoformat()} UTC',
    'bars': len(bars),
    'weeks_loaded': weeks_loaded,
    'rules': RULES,
    'summary': {
        '2R': stats(trades, '2R'),
        '3R': stats(trades, '3R'),
    },
    'by_direction': {
        '2R': split_stats(trades, '2R', 'dir'),
        '3R': split_stats(trades, '3R', 'dir'),
    },
    'by_zone_type': {
        '2R': split_stats(trades, '2R', 'zone_type'),
        '3R': split_stats(trades, '3R', 'zone_type'),
    },
    'by_year': {
        '2R': yearly_breakdown(trades, '2R'),
        '3R': yearly_breakdown(trades, '3R'),
    },
    'by_month': {
        '2R': monthly_breakdown(trades, '2R'),
        '3R': monthly_breakdown(trades, '3R'),
    },
    'friction_stress': {
        '2R': friction_stress(trades, '2R'),
        '3R': friction_stress(trades, '3R'),
    },
    'trades': trades,
}

with open('btc_full_result.json', 'w') as f:
    json.dump(result, f, indent=2)

print(json.dumps({
    'symbol': result['symbol'],
    'period': result['period'],
    'bars': result['bars'],
    'weeks_loaded': result['weeks_loaded'],
    'rules': result['rules'],
    'summary': result['summary'],
    'by_direction': result['by_direction'],
    'by_zone_type': result['by_zone_type'],
    'by_year': result['by_year'],
    'friction_stress': result['friction_stress'],
}, indent=2))
