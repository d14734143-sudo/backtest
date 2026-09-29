import csv
from collections import defaultdict
from pathlib import Path

LOG = Path(__file__).with_name('coinglass_forward_log.csv')
BITS = [
    'cg_oi_ok','cg_net_position_ok','cg_net_delta_ok','cg_accounts_ok',
    'cg_liquidations_ok','cg_funding_ok','cg_flow_ok'
]


def truthy(v):
    return str(v).strip().lower() in {'1','true','yes','y','да'}


def fnum(v):
    try:
        return float(v)
    except Exception:
        return None


def load_rows():
    if not LOG.exists():
        return []
    out=[]
    with LOG.open(encoding='utf-8-sig', newline='') as f:
        for r in csv.DictReader(f):
            if not r.get('symbol'):
                continue
            score=sum(truthy(r.get(k,'')) for k in BITS)
            r['cg_score_calc']=score
            out.append(r)
    return out


def stats(rows):
    closed=[]
    for r in rows:
        res=(r.get('result') or '').strip().lower()
        pnl=fnum(r.get('pnl_r'))
        if res in {'win','loss'} and pnl is not None:
            closed.append((res,pnl))
    if not closed:
        return {'n':0,'wins':0,'losses':0,'wr':None,'exp':None,'net_r':0.0,'pf':None}
    wins=sum(1 for x,_ in closed if x=='win')
    losses=len(closed)-wins
    pnls=[p for _,p in closed]
    pos=sum(p for p in pnls if p>0)
    neg=-sum(p for p in pnls if p<0)
    return {
        'n':len(closed),'wins':wins,'losses':losses,
        'wr':100*wins/len(closed),'exp':sum(pnls)/len(pnls),'net_r':sum(pnls),
        'pf':(pos/neg if neg>0 else float('inf'))
    }


def fmt(s):
    if not s['n']:
        return 'n=0'
    pf='∞' if s['pf']==float('inf') else f"{s['pf']:.2f}"
    return f"n={s['n']} | WR={s['wr']:.1f}% | Exp={s['exp']:+.3f}R | Net={s['net_r']:+.2f}R | PF={pf}"


def main():
    rows=load_rows()
    if not rows:
        print('No forward-test rows yet.')
        return
    grouped=defaultdict(list)
    for r in rows:
        grouped[r['symbol'].upper()].append(r)
    for symbol in sorted(grouped):
        rs=grouped[symbol]
        print(f'\n=== {symbol} ===')
        print('TV only     :', fmt(stats(rs)))
        for th in (3,4,5,6,7):
            sub=[r for r in rs if r['cg_score_calc']>=th]
            print(f'CG score {th}+ :', fmt(stats(sub)))
        live=[r for r in rs if truthy(r.get('taken_live',''))]
        if live:
            print('Taken live  :', fmt(stats(live)))
    print('\nResearch rule: do not select a production threshold before at least 30 closed signals per symbol; prefer 50+.')

if __name__=='__main__':
    main()
