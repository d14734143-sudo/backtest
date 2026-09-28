import json, math, urllib.request
from datetime import datetime, timezone

BASE='https://finom.github.io/static-klines/api/klines/15m/BTCUSDT'
WEEKS=['2025-02-24','2025-03-03']
START_MS=int(datetime(2025,2,24,0,0,tzinfo=timezone.utc).timestamp()*1000)
END_MS=int(datetime(2025,3,7,0,0,tzinfo=timezone.utc).timestamp()*1000)  # exclusive; includes all of Mar 6 UTC


def fetch_week(d):
    with urllib.request.urlopen(f'{BASE}/{d}.json', timeout=30) as r:
        raw=json.load(r)
    out=[]
    for x in raw:
        t=int(x[0])
        if START_MS <= t < END_MS:
            out.append({'t':t,'o':float(x[1]),'h':float(x[2]),'l':float(x[3]),'c':float(x[4]),'v':float(x[5])})
    return out


def atr14(bars):
    trs=[]; out=[None]*len(bars)
    for i,b in enumerate(bars):
        pc=bars[i-1]['c'] if i else b['c']
        tr=max(b['h']-b['l'],abs(b['h']-pc),abs(b['l']-pc))
        trs.append(tr)
        if i>=13: out[i]=sum(trs[i-13:i+1])/14
    return out


def pivots(bars,left=2,right=2):
    ph=[False]*len(bars); pl=[False]*len(bars)
    for i in range(left,len(bars)-right):
        h=bars[i]['h']; l=bars[i]['l']
        if all(h>bars[j]['h'] for j in range(i-left,i)) and all(h>=bars[j]['h'] for j in range(i+1,i+right+1)): ph[i]=True
        if all(l<bars[j]['l'] for j in range(i-left,i)) and all(l<=bars[j]['l'] for j in range(i+1,i+right+1)): pl[i]=True
    return ph,pl


def aggregate_1h(bars):
    out=[]
    for i in range(0,len(bars),4):
        g=bars[i:i+4]
        if len(g)<4: break
        out.append({'t':g[0]['t'],'o':g[0]['o'],'h':max(x['h'] for x in g),'l':min(x['l'] for x in g),'c':g[-1]['c']})
    return out


def latest_confirmed_pivots_1h(hbars):
    ph,pl=pivots(hbars,2,2)
    res=[]; last_hi=None; last_lo=None
    for i,b in enumerate(hbars):
        ci=i-2
        if ci>=0:
            if ph[ci]: last_hi=(ci,hbars[ci]['h'])
            if pl[ci]: last_lo=(ci,hbars[ci]['l'])
        res.append((last_hi,last_lo))
    return res


def run(bars):
    atr=atr14(bars)
    ph15,pl15=pivots(bars,2,2)
    hbars=aggregate_1h(bars)
    p1=latest_confirmed_pivots_1h(hbars)
    trades=[]
    last_hi15=None; last_lo15=None
    pending=None

    for i,b in enumerate(bars):
        ci=i-2
        if ci>=0:
            if ph15[ci]: last_hi15=(ci,bars[ci]['h'])
            if pl15[ci]: last_lo15=(ci,bars[ci]['l'])
        if atr[i] is None: continue

        hi1,lo1=p1[min(i//4,len(p1)-1)]
        sweep=None
        if hi1 and b['h']>hi1[1] and b['c']<hi1[1]: sweep=('short',b['h'])
        elif lo1 and b['l']<lo1[1] and b['c']>lo1[1]: sweep=('long',b['l'])
        if sweep:
            pending={'dir':sweep[0],'sweep_ext':sweep[1],'sweep_i':i,'choch':False,'zone':None,'expires':i+24}

        if not pending: continue
        if i>pending['expires']:
            pending=None; continue

        body=abs(b['c']-b['o']); rng=max(b['h']-b['l'],1e-9); br=body/rng
        disp=body>=atr[i] and br>=0.70

        if pending['dir']=='long' and last_hi15 and b['c']>last_hi15[1] and disp and b['c']>b['o']:
            if i>=2 and bars[i-2]['h']<b['l'] and (b['l']-bars[i-2]['h'])>=0.10*atr[i]:
                zone=(bars[i-2]['h'],b['l'])
            else:
                zone=(min(b['o'],b['c']),max(b['o'],b['c']))
            pending.update({'choch':True,'zone':zone,'trigger_i':i,'retest_deadline':i+12})
        elif pending['dir']=='short' and last_lo15 and b['c']<last_lo15[1] and disp and b['c']<b['o']:
            if i>=2 and bars[i-2]['l']>b['h'] and (bars[i-2]['l']-b['h'])>=0.10*atr[i]:
                zone=(b['h'],bars[i-2]['l'])
            else:
                zone=(min(b['o'],b['c']),max(b['o'],b['c']))
            pending.update({'choch':True,'zone':zone,'trigger_i':i,'retest_deadline':i+12})

        if pending and pending.get('choch') and i>pending['trigger_i']:
            if i>pending['retest_deadline']:
                pending=None; continue
            zl,zh=pending['zone']
            touched=(b['l']<=zh and b['h']>=zl)
            if touched:
                entry=(zl+zh)/2
                if pending['dir']=='long':
                    stop=pending['sweep_ext']-0.15*atr[i]
                    risk=entry-stop
                else:
                    stop=pending['sweep_ext']+0.15*atr[i]
                    risk=stop-entry
                if risk<=0:
                    pending=None; continue
                outcome2=outcome3='open'
                end=min(len(bars),i+96)
                for j in range(i+1,end):
                    bj=bars[j]
                    if pending['dir']=='long':
                        hit_sl=bj['l']<=stop; hit2=bj['h']>=entry+2*risk; hit3=bj['h']>=entry+3*risk
                    else:
                        hit_sl=bj['h']>=stop; hit2=bj['l']<=entry-2*risk; hit3=bj['l']<=entry-3*risk
                    if outcome2=='open':
                        if hit_sl: outcome2='loss'
                        elif hit2: outcome2='win'
                    if outcome3=='open':
                        if hit_sl: outcome3='loss'
                        elif hit3: outcome3='win'
                    if outcome2!='open' and outcome3!='open': break
                trades.append({'time':datetime.fromtimestamp(b['t']/1000,tz=timezone.utc).isoformat(),'dir':pending['dir'],'entry':entry,'stop':stop,'r':risk,'2R':outcome2,'3R':outcome3})
                pending=None
    return trades

bars=[]
for w in WEEKS: bars.extend(fetch_week(w))
bars.sort(key=lambda x:x['t'])
trades=run(bars)

def stats(key):
    closed=[t for t in trades if t[key] in ('win','loss')]
    wins=sum(t[key]=='win' for t in closed); losses=sum(t[key]=='loss' for t in closed)
    wr=(wins/len(closed)*100) if closed else 0
    expectancy=((wins*(2 if key=='2R' else 3)-losses)/len(closed)) if closed else 0
    pf=((wins*(2 if key=='2R' else 3))/losses) if losses else (math.inf if wins else 0)
    return {'closed':len(closed),'wins':wins,'losses':losses,'win_rate_pct':round(wr,2),'expectancy_R':round(expectancy,3),'profit_factor_R':('inf' if math.isinf(pf) else round(pf,3))}

result={'symbol':'BTCUSDT','period':'2025-02-24 to 2025-03-06 UTC','bars':len(bars),'rules':{'pivot':'2 left / 2 right','ATR':14,'displacement_body':'>=1 ATR','body_ratio':'>=70%','FVG':'>=0.10 ATR','retest':'<=12 bars','SL':'sweep extreme +/-0.15 ATR'},'trades':trades,'stats_2R':stats('2R'),'stats_3R':stats('3R')}
with open('result.json','w') as f: json.dump(result,f,indent=2)
print(json.dumps(result,indent=2))
