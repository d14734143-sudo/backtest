import json
import os
from itertools import product
from datetime import datetime

SYMBOL = os.environ.get('SYMBOL', 'BTCUSDT')
FRICTION_BPS = 10
INFILE = f'{SYMBOL.lower()}_v02_scoring_result.json'
OUTFILE = f'{SYMBOL.lower()}_v03_final_selection.json'

with open(INFILE) as f:
    data = json.load(f)
trades = data['trades']


def metrics(ts):
    closed = [t for t in ts if t['2R'] in ('win','loss')]
    if not closed:
        return {'closed':0,'wins':0,'losses':0,'win_rate_pct':0,'expectancy_R_after_10bps':0,'net_R_after_10bps':0,'profit_factor_after_10bps':0,'max_drawdown_R_after_10bps':0,'max_loss_streak':0}
    wins = 0; pos = 0.0; neg = 0.0; vals = []
    eq = 0.0; peak = 0.0; dd = 0.0; ls = 0; maxls = 0
    for t in sorted(closed, key=lambda x: x['t']):
        if t['2R'] == 'win': wins += 1
        gross = 2.0 if t['2R'] == 'win' else -1.0
        cost_r = (FRICTION_BPS/10000.0) / max(t['risk']/t['entry'], 1e-9)
        pnl = gross - cost_r
        vals.append(pnl)
        if pnl >= 0: pos += pnl
        else: neg += -pnl
        eq += pnl; peak = max(peak,eq); dd = max(dd,peak-eq)
        if t['2R'] == 'loss': ls += 1; maxls = max(maxls,ls)
        else: ls = 0
    losses = len(closed)-wins
    return {
        'closed':len(closed),'wins':wins,'losses':losses,
        'win_rate_pct':round(100*wins/len(closed),2),
        'expectancy_R_after_10bps':round(sum(vals)/len(vals),3),
        'net_R_after_10bps':round(sum(vals),3),
        'profit_factor_after_10bps':round(pos/neg,3) if neg else 'inf',
        'max_drawdown_R_after_10bps':round(dd,3),'max_loss_streak':maxls,
    }


def period(t):
    d = datetime.fromisoformat(t['time'])
    if d.year == 2025 and d.month <= 6: return '2025_H1'
    if d.year == 2025: return '2025_H2'
    if d.year == 2026: return '2026'
    return 'other'

for t in trades:
    t['_period'] = period(t)


def session_ok(t, sess):
    h = t['entry_hour_utc']
    if sess == 'all': return True
    if sess == '00-07': return 0 <= h <= 7
    if sess == '08-15': return 8 <= h <= 15
    return 16 <= h <= 23


def subset(zone, direction, min_stop, session, min_score, period_name=None):
    out=[]
    for t in trades:
        if period_name and t['_period'] != period_name: continue
        if zone != 'all' and t['zone_type'] != zone: continue
        if direction != 'all' and t['dir'] != direction: continue
        if t['stop_pct'] < min_stop: continue
        if not session_ok(t, session): continue
        if t['score'] < min_score: continue
        out.append(t)
    return out

zones=['all','FVG','OB_proxy']
directions=['all','long','short']
stops=[0.0,0.2,0.3,0.5,0.75,1.0,1.5]
sessions=['all','00-07','08-15','16-23']
scores=list(range(0,7))

candidates=[]
for zone,direction,min_stop,session,min_score in product(zones,directions,stops,sessions,scores):
    h1=metrics(subset(zone,direction,min_stop,session,min_score,'2025_H1'))
    h2=metrics(subset(zone,direction,min_stop,session,min_score,'2025_H2'))
    total_closed=h1['closed']+h2['closed']
    if h1['closed'] < 10 or h2['closed'] < 10 or total_closed < 25: continue
    if h1['expectancy_R_after_10bps'] <= 0 or h2['expectancy_R_after_10bps'] <= 0: continue
    min_wr=min(h1['win_rate_pct'],h2['win_rate_pct'])
    min_exp=min(h1['expectancy_R_after_10bps'],h2['expectancy_R_after_10bps'])
    avg_wr=(h1['win_rate_pct']+h2['win_rate_pct'])/2
    candidates.append({
        'rules':{'zone':zone,'direction':direction,'min_stop_pct':min_stop,'session_utc':session,'min_score':min_score},
        '2025_H1':h1,'2025_H2':h2,'train_closed':total_closed,
        'selection_min_win_rate':round(min_wr,2),'selection_avg_win_rate':round(avg_wr,2),'selection_min_expectancy':round(min_exp,3),
    })

# High-precision objective: maximize the weaker half-year win rate, then weaker expectancy, then sample size.
candidates.sort(key=lambda x:(x['selection_min_win_rate'],x['selection_min_expectancy'],x['train_closed']),reverse=True)

for c in candidates[:20]:
    r=c['rules']
    c['validation_2026']=metrics(subset(r['zone'],r['direction'],r['min_stop_pct'],r['session_utc'],r['min_score'],'2026'))
    c['full_period']=metrics(subset(r['zone'],r['direction'],r['min_stop_pct'],r['session_utc'],r['min_score'],None))

selected=candidates[0] if candidates else None
acceptance=None
if selected:
    v=selected['validation_2026']
    acceptance = {
        'min_validation_trades_15': v['closed'] >= 15,
        'validation_win_rate_ge_45pct': v['win_rate_pct'] >= 45.0,
        'validation_expectancy_ge_0_10R': v['expectancy_R_after_10bps'] >= 0.10,
        'validation_profit_factor_ge_1_15': isinstance(v['profit_factor_after_10bps'],(int,float)) and v['profit_factor_after_10bps'] >= 1.15,
    }
    acceptance['passes_all'] = all(acceptance.values())

result={
    'version':'0.3-final-selection','symbol':SYMBOL,'target':'2R','friction':'10 bps round-trip',
    'method':'parameters selected only from two positive 2025 half-years; 2026 used only as untouched holdout validation',
    'search_space':{'zones':zones,'directions':directions,'min_stop_pct':stops,'sessions_utc':sessions,'min_score':scores},
    'valid_robust_candidates':len(candidates),'selected':selected,'acceptance_gate':acceptance,
    'top_10':candidates[:10],
}
with open(OUTFILE,'w') as f: json.dump(result,f,indent=2)
print(json.dumps({k:result[k] for k in ['version','symbol','target','method','valid_robust_candidates','selected','acceptance_gate']},indent=2))
