import csv
import json
import math
import os
from bisect import bisect_right
from datetime import datetime, timezone

SYMBOL = os.environ.get('SYMBOL', 'BTCUSDT')
BASE_FILE = os.environ.get('BASE_FILE', f'{SYMBOL.lower()}_v02_scoring_result.json')
CG_FILE = os.environ.get('CG_FILE', f'coinglass_data/{SYMBOL.lower()}_coinglass.csv')
TARGET = os.environ.get('TARGET', '2R')
FRICTION_BPS = 10

# Fixed before reading outcomes. CoinGlass rows must be CLOSED bars only.
CORE_FIELDS = [
    'oi_close', 'net_long_cum', 'net_short_cum', 'net_position_cum',
    'global_account_ratio', 'long_liq_usd', 'short_liq_usd', 'funding_rate'
]
OPTIONAL_FIELDS = ['top_account_ratio', 'taker_buy_ratio']


def fnum(x):
    if x is None or x == '':
        return None
    try:
        return float(x)
    except Exception:
        return None


def parse_time(x):
    if x is None or x == '':
        return None
    try:
        v = float(x)
        if v > 10_000_000_000:
            return int(v)
        if v > 1_000_000_000:
            return int(v * 1000)
    except Exception:
        pass
    dt = datetime.fromisoformat(str(x).replace('Z', '+00:00'))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp() * 1000)


def load_cg(path):
    rows = []
    with open(path, newline='', encoding='utf-8-sig') as f:
        for r in csv.DictReader(f):
            t = parse_time(r.get('time') or r.get('timestamp') or r.get('t'))
            if t is None:
                continue
            row = {'t': t}
            for k in CORE_FIELDS + OPTIONAL_FIELDS:
                row[k] = fnum(r.get(k))
            rows.append(row)
    rows.sort(key=lambda x: x['t'])
    return rows


def median(xs):
    xs = sorted(x for x in xs if x is not None)
    if not xs:
        return None
    n = len(xs)
    return xs[n//2] if n % 2 else (xs[n//2-1] + xs[n//2]) / 2


def percentile(xs, q):
    xs = sorted(x for x in xs if x is not None)
    if not xs:
        return None
    if len(xs) == 1:
        return xs[0]
    pos = (len(xs)-1) * q
    lo = int(math.floor(pos)); hi = int(math.ceil(pos))
    if lo == hi:
        return xs[lo]
    return xs[lo] + (xs[hi]-xs[lo]) * (pos-lo)


def cg_bits(rows, idx, direction):
    # Uses current CLOSED CoinGlass bar plus only prior bars.
    if idx < 1:
        return None
    cur = rows[idx]
    prev = rows[idx-1]
    missing = [k for k in CORE_FIELDS if cur.get(k) is None or prev.get(k) is None]
    if missing:
        return {'missing': missing, 'bits': None, 'score': None}

    hist20 = rows[max(0, idx-19):idx+1]
    hist4 = rows[max(0, idx-3):idx+1]

    # 1) OI: new risk is entering rather than OI collapsing into the entry.
    oi_change = cur['oi_close'] - prev['oi_close']
    oi_ok = oi_change > 0

    # 2) Net longs / shorts individually.
    d_long = cur['net_long_cum'] - prev['net_long_cum']
    d_short = cur['net_short_cum'] - prev['net_short_cum']
    if direction == 'long':
        net_ls_ok = d_long > 0 and d_short >= 0
    else:
        net_ls_ok = d_long <= 0 and d_short < 0

    # 3) Net delta / net position direction.
    d_net = cur['net_position_cum'] - prev['net_position_cum']
    net_delta_ok = d_net > 0 if direction == 'long' else d_net < 0

    # 4) Accounts: ratio momentum aligns, but avoid the most crowded 20% of recent readings.
    ar = cur['global_account_ratio']
    ar_prev = prev['global_account_ratio']
    ar_hist = [x['global_account_ratio'] for x in hist20]
    p20 = percentile(ar_hist, 0.20)
    p80 = percentile(ar_hist, 0.80)
    if direction == 'long':
        accounts_ok = ar > ar_prev and (p80 is None or ar <= p80)
    else:
        accounts_ok = ar < ar_prev and (p20 is None or ar >= p20)

    # 5) Liquidation flush. Long setup wants recent long liquidation spike; short wants short spike.
    liq_key = 'long_liq_usd' if direction == 'long' else 'short_liq_usd'
    recent_liq = max((x[liq_key] or 0.0) for x in hist4)
    baseline = median([x[liq_key] for x in hist20[:-1]])
    liquidation_ok = baseline is not None and baseline > 0 and recent_liq >= 1.5 * baseline

    # 6) Funding: do not enter in the most crowded 20% in the intended direction.
    fr = cur['funding_rate']
    fr_hist = [x['funding_rate'] for x in hist20]
    fp20 = percentile(fr_hist, 0.20)
    fp80 = percentile(fr_hist, 0.80)
    funding_ok = (fp80 is None or fr <= fp80) if direction == 'long' else (fp20 is None or fr >= fp20)

    # 7) Optional taker flow / CVD proxy when available; otherwise neutral, not a failure.
    taker = cur.get('taker_buy_ratio')
    if taker is None:
        flow_ok = None
    else:
        flow_ok = taker > 50.0 if direction == 'long' else taker < 50.0

    bits = {
        'open_interest': oi_ok,
        'net_long_short': net_ls_ok,
        'net_delta': net_delta_ok,
        'accounts': accounts_ok,
        'liquidations': liquidation_ok,
        'funding': funding_ok,
        'taker_flow_optional': flow_ok,
    }
    core_score = sum(bool(bits[k]) for k in ['open_interest','net_long_short','net_delta','accounts','liquidations','funding'])
    score = core_score + (1 if flow_ok is True else 0)
    return {
        'missing': [], 'bits': bits, 'score': score,
        'core_score': core_score,
        'oi_change': oi_change, 'net_delta_change': d_net,
        'global_account_ratio': ar, 'funding_rate': fr,
        'recent_liquidation_usd': recent_liq,
    }


def metrics(ts):
    closed = [t for t in ts if t[TARGET] in ('win','loss')]
    if not closed:
        return {'closed':0,'wins':0,'losses':0,'win_rate_pct':0,'expectancy_R_after_10bps':0,'net_R_after_10bps':0,'profit_factor_after_10bps':0}
    wins = 0; vals=[]; gp=0.0; gn=0.0
    rr = int(TARGET[0])
    for t in closed:
        if t[TARGET] == 'win':
            wins += 1; gross = rr
        else:
            gross = -1.0
        cost_r = (FRICTION_BPS/10000.0) / max(t['risk']/t['entry'], 1e-9)
        pnl = gross - cost_r
        vals.append(pnl)
        if pnl >= 0: gp += pnl
        else: gn += -pnl
    return {
        'closed': len(closed), 'wins': wins, 'losses': len(closed)-wins,
        'win_rate_pct': round(100*wins/len(closed),2),
        'expectancy_R_after_10bps': round(sum(vals)/len(vals),3),
        'net_R_after_10bps': round(sum(vals),3),
        'profit_factor_after_10bps': round(gp/gn,3) if gn else 'inf',
    }


def main():
    with open(BASE_FILE, encoding='utf-8') as f:
        base = json.load(f)
    trades = base['trades']
    rows = load_cg(CG_FILE)
    times = [r['t'] for r in rows]

    enriched=[]; skipped_missing=0; skipped_no_row=0
    for t in trades:
        # last completed CG bar at or before entry timestamp
        idx = bisect_right(times, t['t']) - 1
        if idx < 1:
            skipped_no_row += 1
            continue
        cg = cg_bits(rows, idx, t['dir'])
        if cg is None or cg['bits'] is None:
            skipped_missing += 1
            continue
        x = dict(t); x['coinglass'] = cg; x['cg_score'] = cg['score']; x['cg_core_score'] = cg['core_score']
        enriched.append(x)

    # Threshold is selected on 2025 only, 2026 untouched.
    candidates=[]
    for th in range(0,8):
        train=[t for t in enriched if t['year']=='2025' and t['cg_score']>=th]
        m=metrics(train)
        if m['closed'] >= 20 and m['expectancy_R_after_10bps'] > 0:
            candidates.append((m['expectancy_R_after_10bps'], m['win_rate_pct'], m['closed'], th, m))
    selected=None
    if candidates:
        candidates.sort(reverse=True)
        _,_,_,th,trainm=candidates[0]
        test=[t for t in enriched if t['year']=='2026' and t['cg_score']>=th]
        full=[t for t in enriched if t['cg_score']>=th]
        selected={'threshold':th,'train_2025':trainm,'validation_2026':metrics(test),'full_period':metrics(full)}

    report={
        'symbol':SYMBOL,'target':TARGET,
        'method':'CoinGlass confirmation score selected on 2025 only; 2026 untouched holdout',
        'required_fields':CORE_FIELDS,
        'optional_fields':OPTIONAL_FIELDS,
        'base_all_enriched':metrics(enriched),
        'selected':selected,
        'enriched_trades':len(enriched),
        'skipped_no_coinglass_row':skipped_no_row,
        'skipped_missing_required_fields':skipped_missing,
    }
    out=f'{SYMBOL.lower()}_coinglass_backtest_report.json'
    with open(out,'w',encoding='utf-8') as f:
        json.dump(report,f,indent=2)
    print(json.dumps(report,indent=2))

if __name__=='__main__':
    main()
