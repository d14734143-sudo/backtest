import json
import math
import os
import urllib.request
from datetime import datetime, timezone, timedelta

SYMBOL = os.environ.get('SYMBOL', 'BTCUSDT')
BASE = f'https://finom.github.io/static-klines/api/klines/15m/{SYMBOL}/{{date}}.json'
START = datetime(2024, 12, 30, tzinfo=timezone.utc)
END_EXCLUSIVE = datetime(2026, 9, 28, tzinfo=timezone.utc)
FRICTION_BPS = 10

# v0.2 scoring. All feature thresholds are fixed before looking at 2026 validation.
SCORE_RULES = {
    'htf_trend': '4H EMA20/EMA50 aligned with trade direction using last completed 4H bar',
    'premium_discount': 'long entry below 1H swing midpoint / short entry above midpoint',
    'sweep_quality': 'sweep penetration >= 0.10 ATR',
    'displacement_quality': 'trigger body >= 1.50 ATR and body/range >= 0.80',
    'zone_quality': 'true FVG and FVG size >= 0.15 ATR',
    'volume_confirmation': 'trigger volume >= 1.25 x prior 20-bar average volume',
    'fast_retest': 'retest occurs within 6 x 15m bars after trigger',
    'active_session': 'entry/retest time in 08:00-15:59 UTC',
}

BASE_RULES = {
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
    'same_bar_ordering': 'SL before TP (conservative)',
    'lookahead_fix': '1H pivots use last completed 1H bar only; 4H context uses last completed 4H bar only',
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
            out.append({'t': t, 'o': float(x[1]), 'h': float(x[2]), 'l': float(x[3]), 'c': float(x[4]), 'v': float(x[5])})
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


def prior_sma(values, n):
    out = [None] * len(values)
    s = 0.0
    for i, v in enumerate(values):
        if i >= n:
            out[i] = s / n
            s -= values[i - n]
        s += v
    return out


def pivots(bars, left=2, right=2):
    ph = [False] * len(bars)
    pl = [False] * len(bars)
    for i in range(left, len(bars) - right):
        h = bars[i]['h']; l = bars[i]['l']
        if all(h > bars[j]['h'] for j in range(i-left, i)) and all(h >= bars[j]['h'] for j in range(i+1, i+right+1)):
            ph[i] = True
        if all(l < bars[j]['l'] for j in range(i-left, i)) and all(l <= bars[j]['l'] for j in range(i+1, i+right+1)):
            pl[i] = True
    return ph, pl


def aggregate(bars, n):
    out = []
    for i in range(0, len(bars), n):
        g = bars[i:i+n]
        if len(g) < n:
            break
        out.append({'t': g[0]['t'], 'o': g[0]['o'], 'h': max(x['h'] for x in g), 'l': min(x['l'] for x in g), 'c': g[-1]['c'], 'v': sum(x['v'] for x in g)})
    return out


def latest_confirmed_pivots(series):
    ph, pl = pivots(series, 2, 2)
    res = []
    last_hi = None; last_lo = None
    for k in range(len(series)):
        ci = k - 2
        if ci >= 0:
            if ph[ci]: last_hi = (ci, series[ci]['h'])
            if pl[ci]: last_lo = (ci, series[ci]['l'])
        res.append((last_hi, last_lo))
    return res


def ema(values, period):
    out = [None] * len(values)
    if len(values) < period:
        return out
    seed = sum(values[:period]) / period
    out[period - 1] = seed
    a = 2.0 / (period + 1)
    prev = seed
    for i in range(period, len(values)):
        prev = a * values[i] + (1-a) * prev
        out[i] = prev
    return out


def safe_completed_index(i, group):
    return i // group - 1


def trade_score(features):
    bits = {
        'htf_trend': features['htf_trend'],
        'premium_discount': features['premium_discount'],
        'sweep_quality': features['sweep_depth_atr'] >= 0.10,
        'displacement_quality': features['disp_body_atr'] >= 1.50 and features['disp_body_ratio'] >= 0.80,
        'zone_quality': features['zone_type'] == 'FVG' and features['fvg_atr'] >= 0.15,
        'volume_confirmation': features['volume_ratio'] >= 1.25,
        'fast_retest': features['retest_wait_bars'] <= 6,
        'active_session': 8 <= features['entry_hour_utc'] <= 15,
    }
    return sum(bool(v) for v in bits.values()), bits


def run(bars):
    atr = atr14(bars)
    volavg = prior_sma([b['v'] for b in bars], 20)
    ph15, pl15 = pivots(bars, 2, 2)

    h1 = aggregate(bars, 4)
    p1 = latest_confirmed_pivots(h1)

    h4 = aggregate(bars, 16)
    e20 = ema([x['c'] for x in h4], 20)
    e50 = ema([x['c'] for x in h4], 50)

    trades = []
    last_hi15 = None; last_lo15 = None
    pending = None

    for i, b in enumerate(bars):
        ci = i - 2
        if ci >= 0:
            if ph15[ci]: last_hi15 = (ci, bars[ci]['h'])
            if pl15[ci]: last_lo15 = (ci, bars[ci]['l'])
        if atr[i] is None:
            continue

        h1_idx = safe_completed_index(i, 4)
        if h1_idx < 0 or h1_idx >= len(p1):
            continue
        hi1, lo1 = p1[h1_idx]

        sweep = None
        if hi1 and b['h'] > hi1[1] and b['c'] < hi1[1]:
            sweep = ('short', b['h'], hi1[1])
        elif lo1 and b['l'] < lo1[1] and b['c'] > lo1[1]:
            sweep = ('long', b['l'], lo1[1])

        if sweep:
            sweep_depth = abs(sweep[1] - sweep[2]) / max(atr[i], 1e-9)
            midpoint = None
            if hi1 and lo1:
                midpoint = (hi1[1] + lo1[1]) / 2.0
            pending = {
                'dir': sweep[0], 'sweep_ext': sweep[1], 'swept_level': sweep[2], 'sweep_depth_atr': sweep_depth,
                'sweep_i': i, 'choch': False, 'zone': None, 'expires': i + 24, 'h1_midpoint': midpoint,
            }

        if not pending:
            continue
        if i > pending['expires']:
            pending = None
            continue

        body = abs(b['c'] - b['o'])
        rng = max(b['h'] - b['l'], 1e-9)
        body_atr = body / max(atr[i], 1e-9)
        body_ratio = body / rng
        disp = body_atr >= 1.0 and body_ratio >= 0.70

        trigger = False
        if pending['dir'] == 'long' and last_hi15 and b['c'] > last_hi15[1] and disp and b['c'] > b['o']:
            trigger = True
            if i >= 2 and bars[i-2]['h'] < b['l'] and (b['l'] - bars[i-2]['h']) >= 0.10 * atr[i]:
                zone = (bars[i-2]['h'], b['l']); zone_type = 'FVG'; fvg_atr = (b['l'] - bars[i-2]['h']) / atr[i]
            else:
                zone = (min(b['o'], b['c']), max(b['o'], b['c'])); zone_type = 'OB_proxy'; fvg_atr = 0.0
        elif pending['dir'] == 'short' and last_lo15 and b['c'] < last_lo15[1] and disp and b['c'] < b['o']:
            trigger = True
            if i >= 2 and bars[i-2]['l'] > b['h'] and (bars[i-2]['l'] - b['h']) >= 0.10 * atr[i]:
                zone = (b['h'], bars[i-2]['l']); zone_type = 'FVG'; fvg_atr = (bars[i-2]['l'] - b['h']) / atr[i]
            else:
                zone = (min(b['o'], b['c']), max(b['o'], b['c'])); zone_type = 'OB_proxy'; fvg_atr = 0.0

        if trigger:
            vratio = b['v'] / volavg[i] if volavg[i] and volavg[i] > 0 else 0.0
            h4_idx = safe_completed_index(i, 16)
            htf = False
            if 0 <= h4_idx < len(h4) and e20[h4_idx] is not None and e50[h4_idx] is not None:
                if pending['dir'] == 'long':
                    htf = h4[h4_idx]['c'] > e20[h4_idx] > e50[h4_idx]
                else:
                    htf = h4[h4_idx]['c'] < e20[h4_idx] < e50[h4_idx]
            pending.update({
                'choch': True, 'zone': zone, 'zone_type': zone_type, 'fvg_atr': fvg_atr,
                'trigger_i': i, 'retest_deadline': i + 12, 'disp_body_atr': body_atr,
                'disp_body_ratio': body_ratio, 'volume_ratio': vratio, 'htf_trend': htf,
            })

        if pending and pending.get('choch') and i > pending['trigger_i']:
            if i > pending['retest_deadline']:
                pending = None
                continue
            zl, zh = pending['zone']
            touched = b['l'] <= zh and b['h'] >= zl
            if not touched:
                continue

            entry = (zl + zh) / 2.0
            if pending['dir'] == 'long':
                stop = pending['sweep_ext'] - 0.15 * atr[i]
                risk = entry - stop
            else:
                stop = pending['sweep_ext'] + 0.15 * atr[i]
                risk = stop - entry
            if risk <= 0:
                pending = None
                continue

            midpoint = pending.get('h1_midpoint')
            pd_ok = False
            if midpoint is not None:
                pd_ok = entry <= midpoint if pending['dir'] == 'long' else entry >= midpoint

            entry_hour = datetime.fromtimestamp(b['t']/1000, tz=timezone.utc).hour
            features = {
                'htf_trend': pending['htf_trend'],
                'premium_discount': pd_ok,
                'sweep_depth_atr': pending['sweep_depth_atr'],
                'disp_body_atr': pending['disp_body_atr'],
                'disp_body_ratio': pending['disp_body_ratio'],
                'zone_type': pending['zone_type'],
                'fvg_atr': pending['fvg_atr'],
                'volume_ratio': pending['volume_ratio'],
                'retest_wait_bars': i - pending['trigger_i'],
                'entry_hour_utc': entry_hour,
            }
            score, score_bits = trade_score(features)

            outcomes = {2: 'open', 3: 'open'}
            exit_time = {2: None, 3: None}
            end = min(len(bars), i + 96)
            for j in range(i+1, end):
                bj = bars[j]
                for rr in (2, 3):
                    if outcomes[rr] != 'open':
                        continue
                    if pending['dir'] == 'long':
                        hit_sl = bj['l'] <= stop
                        hit_tp = bj['h'] >= entry + rr*risk
                    else:
                        hit_sl = bj['h'] >= stop
                        hit_tp = bj['l'] <= entry - rr*risk
                    if hit_sl:
                        outcomes[rr] = 'loss'; exit_time[rr] = bj['t']
                    elif hit_tp:
                        outcomes[rr] = 'win'; exit_time[rr] = bj['t']

            trade = {
                'time': datetime.fromtimestamp(b['t']/1000, tz=timezone.utc).isoformat(),
                't': b['t'], 'year': str(datetime.fromtimestamp(b['t']/1000, tz=timezone.utc).year),
                'dir': pending['dir'], 'zone_type': pending['zone_type'], 'entry': entry, 'stop': stop, 'risk': risk,
                'stop_pct': risk/entry*100, 'score': score, 'score_bits': score_bits,
                **features,
                '2R': outcomes[2], '3R': outcomes[3],
                'exit_2R': datetime.fromtimestamp(exit_time[2]/1000, tz=timezone.utc).isoformat() if exit_time[2] else None,
                'exit_3R': datetime.fromtimestamp(exit_time[3]/1000, tz=timezone.utc).isoformat() if exit_time[3] else None,
            }
            trades.append(trade)
            pending = None

    return trades


def metrics(ts, key):
    rr = 2 if key == '2R' else 3
    closed = [t for t in ts if t[key] in ('win','loss')]
    if not closed:
        return {'closed': 0, 'wins': 0, 'losses': 0, 'win_rate_pct': 0, 'expectancy_R_after_10bps': 0, 'net_R_after_10bps': 0, 'profit_factor_after_10bps': 0, 'max_drawdown_R_after_10bps': 0, 'max_loss_streak': 0}
    vals = []
    wins = 0
    gross_pos = 0.0; gross_neg = 0.0
    eq = 0.0; peak = 0.0; maxdd = 0.0; ls = 0; maxls = 0
    for t in sorted(closed, key=lambda x: x['t']):
        if t[key] == 'win': wins += 1
        gross = rr if t[key] == 'win' else -1.0
        cost_r = (FRICTION_BPS/10000.0) / max(t['risk']/t['entry'], 1e-9)
        pnl = gross - cost_r
        vals.append(pnl)
        if pnl >= 0: gross_pos += pnl
        else: gross_neg += -pnl
        eq += pnl; peak = max(peak, eq); maxdd = max(maxdd, peak-eq)
        if t[key] == 'loss':
            ls += 1; maxls = max(maxls, ls)
        else:
            ls = 0
    losses = len(closed)-wins
    return {
        'closed': len(closed), 'wins': wins, 'losses': losses,
        'win_rate_pct': round(100*wins/len(closed), 2),
        'expectancy_R_after_10bps': round(sum(vals)/len(vals), 3),
        'net_R_after_10bps': round(sum(vals), 3),
        'profit_factor_after_10bps': round(gross_pos/gross_neg, 3) if gross_neg else 'inf',
        'max_drawdown_R_after_10bps': round(maxdd, 3),
        'max_loss_streak': maxls,
    }


def threshold_report(trades, key, year=None):
    base = [t for t in trades if year is None or t['year'] == str(year)]
    out = {}
    for th in range(0, 9):
        subset = [t for t in base if t['score'] >= th]
        out[str(th)] = metrics(subset, key)
    return out


def select_threshold(trades, key='2R'):
    # Selection uses 2025 only. Require at least 20 closed trades.
    candidates = []
    for th in range(0, 9):
        subset = [t for t in trades if t['year'] == '2025' and t['score'] >= th]
        m = metrics(subset, key)
        if m['closed'] >= 20 and m['expectancy_R_after_10bps'] > 0:
            # Prefer expectancy first, then win rate, then more observations.
            candidates.append((m['expectancy_R_after_10bps'], m['win_rate_pct'], m['closed'], th, m))
    if not candidates:
        return None
    candidates.sort(reverse=True)
    _, _, _, th, train = candidates[0]
    test_subset = [t for t in trades if t['year'] == '2026' and t['score'] >= th]
    full_subset = [t for t in trades if t['score'] >= th]
    return {'threshold': th, 'train_2025': train, 'validation_2026': metrics(test_subset, key), 'full_period': metrics(full_subset, key)}


bars = []
weeks_loaded = 0
for d in mondays(START, END_EXCLUSIVE):
    w = fetch_week(d)
    if w:
        weeks_loaded += 1
        bars.extend(w)
uniq = {b['t']: b for b in bars}
bars = [uniq[k] for k in sorted(uniq)]

trades = run(bars)
result = {
    'version': '0.2', 'symbol': SYMBOL,
    'period': f'{START.date().isoformat()} to {(END_EXCLUSIVE-timedelta(days=1)).date().isoformat()} UTC',
    'bars': len(bars), 'weeks_loaded': weeks_loaded,
    'base_rules': BASE_RULES, 'score_rules': SCORE_RULES,
    'friction': f'{FRICTION_BPS} bps round-trip',
    'all_trades': {'2R': metrics(trades, '2R'), '3R': metrics(trades, '3R')},
    'thresholds': {
        '2R_2025_train': threshold_report(trades, '2R', 2025),
        '2R_2026_validation': threshold_report(trades, '2R', 2026),
        '3R_2025_train': threshold_report(trades, '3R', 2025),
        '3R_2026_validation': threshold_report(trades, '3R', 2026),
    },
    'selected_2R': select_threshold(trades, '2R'),
    'selected_3R': select_threshold(trades, '3R'),
    'trades': trades,
}
outfile = f'{SYMBOL.lower()}_v02_scoring_result.json'
with open(outfile, 'w') as f:
    json.dump(result, f, indent=2)
print(json.dumps({k: result[k] for k in ['version','symbol','period','bars','weeks_loaded','friction','all_trades','selected_2R','selected_3R']}, indent=2))
