import json, math, urllib.request
from datetime import datetime, timezone, timedelta

# Historical research only. No exchange API, no live orders.
SYMBOLS=['BTCUSDT','ETHUSDT','SOLUSDT']
BASE='https://finom.github.io/static-klines/api/klines/15m/{symbol}/{date}.json'
START=datetime(2025,1,6,tzinfo=timezone.utc)
END=datetime(2026,9,21,tzinfo=timezone.utc)
MAX_TRADES_PER_MODE=1000

MODES={
 'single':[0.0],
 'ladder_1pct':[0.0,0.01,0.02],
 'ladder_1_5pct':[0.0,0.015,0.03],
}

# Parameter grid kept intentionally small enough for repeatable CI research.
GRIDS=[
 {'tf_min':15,'disp_atr':1.0,'body_ratio':0.70,'fvg_atr':0.10,'retest':12,'max_stop_pct':0.02},
 {'tf_min':30,'disp_atr':1.0,'body_ratio':0.70,'fvg_atr':0.10,'retest':8,'max_stop_pct':0.02},
 {'tf_min':60,'disp_atr':1.0,'body_ratio':0.70,'fvg_atr':0.10,'retest':6,'max_stop_pct':0.02},
]

def mondays(a,b):
    d=a
    while d.weekday()!=0: d+=timedelta(days=1)
    while d<=b:
        yield d.strftime('%Y-%m-%d'); d+=timedelta(days=7)

def get_week(symbol,d):
    try:
        with urllib.request.urlopen(BASE.format(symbol=symbol,date=d),timeout=20) as r:
            raw=json.load(r)
        return [{'t':int(x[0]),'o':float(x[1]),'h':float(x[2]),'l':float(x[3]),'c':float(x[4]),'v':float(x[5])} for x in raw]
    except Exception:
        return []

def resample(bars,mins):
    n=mins//15
    if n<=1: return bars
    out=[]
    for i in range(0,len(bars),n):
        g=bars[i:i+n]
        if len(g)<n: break
        out.append({'t':g[0]['t'],'o':g[0]['o'],'h':max(x['h'] for x in g),'l':min(x['l'] for x in g),'c':g[-1]['c'],'v':sum(x['v'] for x in g)})
    return out

def atr14(b):
    trs=[]; out=[None]*len(b)
    for i,x in enumerate(b):
        pc=b[i-1]['c'] if i else x['c']
        tr=max(x['h']-x['l'],abs(x['h']-pc),abs(x['l']-pc)); trs.append(tr)
        if i>=13: out[i]=sum(trs[i-13:i+1])/14
    return out

def pivots(b,l=2,r=2):
    ph=[False]*len(b); pl=[False]*len(b)
    for i in range(l,len(b)-r):
        ph[i]=all(b[i]['h']>b[j]['h'] for j in range(i-l,i)) and all(b[i]['h']>=b[j]['h'] for j in range(i+1,i+r+1))
        pl[i]=all(b[i]['l']<b[j]['l'] for j in range(i-l,i)) and all(b[i]['l']<=b[j]['l'] for j in range(i+1,i+r+1))
    return ph,pl

def simulate(bars,p,mode):
    a=atr14(bars); ph,pl=pivots(bars); last_hi=last_lo=None; setup=None; trades=[]
    for i,x in enumerate(bars):
        ci=i-2
        if ci>=0:
            if ph[ci]: last_hi=bars[ci]['h']
            if pl[ci]: last_lo=bars[ci]['l']
        if a[i] is None: continue
        # simplified research proxy: liquidity sweep of confirmed local pivot
        if last_hi and x['h']>last_hi and x['c']<last_hi: setup={'dir':'short','sweep':x['h'],'i':i,'until':i+24}
        elif last_lo and x['l']<last_lo and x['c']>last_lo: setup={'dir':'long','sweep':x['l'],'i':i,'until':i+24}
        if not setup or i>setup['until']: continue
        body=abs(x['c']-x['o']); rng=max(x['h']-x['l'],1e-9); disp=body>=p['disp_atr']*a[i] and body/rng>=p['body_ratio']
        choch=(setup['dir']=='long' and last_hi and x['c']>last_hi and x['c']>x['o']) or (setup['dir']=='short' and last_lo and x['c']<last_lo and x['c']<x['o'])
        if not (disp and choch): continue
        base=(x['o']+x['c'])/2
        offsets=MODES[mode]
        levels=[base*(1-o) if setup['dir']=='long' else base*(1+o) for o in offsets]
        filled=[]; deadline=min(len(bars),i+p['retest']+1)
        fill_end=i
        for j in range(i+1,deadline):
            y=bars[j]; fill_end=j
            for lv in levels:
                if lv in filled: continue
                if y['l']<=lv<=y['h']: filled.append(lv)
        if not filled: setup=None; continue
        entry=sum(filled)/len(filled)
        stop=setup['sweep']-0.15*a[i] if setup['dir']=='long' else setup['sweep']+0.15*a[i]
        risk=(entry-stop) if setup['dir']=='long' else (stop-entry)
        stop_pct=risk/entry
        if risk<=0 or stop_pct>p['max_stop_pct']:
            setup=None; continue
        outcomes={2:'open',3:'open'}
        for j in range(fill_end+1,min(len(bars),fill_end+97)):
            y=bars[j]
            for rr in (2,3):
                if outcomes[rr]!='open': continue
                if setup['dir']=='long':
                    sl=y['l']<=stop; tp=y['h']>=entry+rr*risk
                else:
                    sl=y['h']>=stop; tp=y['l']<=entry-rr*risk
                if sl: outcomes[rr]='loss'  # conservative same-bar ordering
                elif tp: outcomes[rr]='win'
        # leverage stress only; approximate liquidation buffer, not exchange-specific liquidation engine
        liq={str(L): max(0.0,1.0/L-stop_pct) for L in (10,20)}
        trades.append({'t':x['t'],'dir':setup['dir'],'fills':len(filled),'entry':entry,'stop_pct':stop_pct,'2R':outcomes[2],'3R':outcomes[3],'liq_buffer_proxy':liq})
        setup=None
        if len(trades)>=MAX_TRADES_PER_MODE: break
    return trades

def stats(ts,key):
    closed=[t for t in ts if t[key] in ('win','loss')]; w=sum(t[key]=='win' for t in closed); l=len(closed)-w; rr=2 if key=='2R' else 3
    return {'trades':len(ts),'closed':len(closed),'wins':w,'losses':l,'win_rate_pct':round(100*w/len(closed),2) if closed else 0,'expectancy_R':round((w*rr-l)/len(closed),3) if closed else 0,'profit_factor_R':round((w*rr/l),3) if l else ('inf' if w else 0),'avg_fills':round(sum(t['fills'] for t in ts)/len(ts),2) if ts else 0,'avg_stop_pct':round(100*sum(t['stop_pct'] for t in ts)/len(ts),3) if ts else 0}

result={'note':'historical research only; liquidation buffer is a simplified stress proxy, not exchange-specific','runs':[]}
for s in SYMBOLS:
    raw=[]
    for d in mondays(START,END): raw.extend(get_week(s,d))
    raw.sort(key=lambda x:x['t'])
    for p in GRIDS:
        b=resample(raw,p['tf_min'])
        for mode in MODES:
            ts=simulate(b,p,mode)
            result['runs'].append({'symbol':s,'tf_min':p['tf_min'],'mode':mode,'params':p,'stats_2R':stats(ts,'2R'),'stats_3R':stats(ts,'3R')})
with open('research_result.json','w') as f: json.dump(result,f,indent=2)
print(json.dumps({'runs':len(result['runs']),'summary':result['runs']},indent=2))
