#!/usr/bin/env python3
"""运营日常汇报 · 周环比操作分类（周报版，复用日报的转化判据）。

与 build_report.py 同口径，唯一区别：把"单日 vs 单日"换成"**本周日均 vs 上周日均**"。
  - 转化判据 / 流水(payout) / 头条口径全部 import 自 build_report，避免两套逻辑漂移。
  - **所有数据按日均**（小迪 2026-09-28 定，含分类）：每个 (offer_id, come_from) 在一周 7 天内
    求和后 ÷7 = 本周日均；上周同理；二者做差。量级与日报完全一致 →
    **门槛直接沿用日报 |Δ日均转化| ≥ 10**，不再自造周门槛。
  - 新单: 上周日均=0 且 本周日均≥10 | 停单: 本周日均=0 且 上周日均≥10
    加量: Δ≥10 | 减量: Δ≤-10（加/减需两周都有日均转化）

用法：
  python3 weekly_roll.py --end 2026-09-27 [--threshold 10] [--indir /tmp/ops] [--json out.json]
  --end 为报告周的周日（含），上一周自动 = [end-13 .. end-7]。
"""
import argparse, datetime as dt, json, sys
from build_report import is_conv, load_nd, fnum, compute_total


def week_dates(end_iso, back_days):
    """返回该周 7 个日期的 ISO 列表（end 往前推 6 天 …… end）。back_days 用于上一周起点。"""
    end = dt.date.fromisoformat(end_iso)
    return [(end - dt.timedelta(days=7 - 1 - i + back_days)).isoformat() for i in range(7)]


def conv_by_offer_week(cb, days):
    """{(offer,come_from): {conv:日均float, pay:日均float, pkg}} —— 7 天求和后 ÷ 天数。"""
    m = {}
    for d in days:
        for r in cb.get(d, []):
            if not is_conv(r):
                continue
            k = (str(r.get('offer_id')), r.get('come_from'))
            e = m.setdefault(k, {'conv': 0, 'pay': 0.0, 'pkg': r.get('package_name') or ''})
            e['conv'] += 1
            e['pay'] += fnum(r.get('payout'))
    n = len(days) or 1
    for e in m.values():
        e['conv'] = round(e['conv'] / n, 1)
        e['pay'] = round(e['pay'] / n, 2)
    return m


def classify(wmap, pmap, thr):
    cats = {'new': [], 'stop': [], 'increased': [], 'decreased': []}
    for k in set(wmap) | set(pmap):
        oid, adv = k
        w, p = wmap.get(k), pmap.get(k)
        cw = w['conv'] if w else 0.0
        cp = p['conv'] if p else 0.0
        d = round(cw - cp, 1)
        pkg = (w or p)['pkg']
        fp = p['pay'] if p else 0.0
        fw = w['pay'] if w else 0.0
        rec = {'offer_id': oid, 'ad_user': adv, 'package': pkg,
               'conv_prev': cp, 'conv_week': cw, 'conv_delta': d,
               'flow_prev': fp, 'flow_week': fw, 'flow_delta': round(fw - fp, 2)}
        if cp == 0 and cw >= thr:
            cats['new'].append(rec)
        elif cw == 0 and cp >= thr:
            cats['stop'].append(rec)
        elif d >= thr:
            cats['increased'].append(rec)
        elif d <= -thr:
            cats['decreased'].append(rec)
    return cats


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--end', required=True, help='报告周周日 YYYY-MM-DD')
    ap.add_argument('--threshold', type=int, default=10, help='日均转化门槛（沿用日报，默认10）')
    ap.add_argument('--indir', default='/tmp/ops')
    ap.add_argument('--json')
    a = ap.parse_args()

    week_days = week_dates(a.end, 0)
    prev_days = week_dates(a.end, 7)
    all_days = set(week_days) | set(prev_days)

    cb = {}
    for d in all_days:
        rows = load_nd(f'{a.indir}/wm_all_callback_{d.replace("-","")}.ndjson')
        if rows is None:
            sys.exit(f'缺数据文件 callback {d}，先跑 fetch_data.py --start {min(all_days)} --end {max(all_days)}')
        cb[d] = rows

    wmap = conv_by_offer_week(cb, week_days)
    pmap = conv_by_offer_week(cb, prev_days)
    cats = classify(wmap, pmap, a.threshold)

    def catsum(lst):
        return {'count': len(lst), 'conv': round(sum(x['conv_delta'] for x in lst), 1),
                'flow': round(sum(x['flow_delta'] for x in lst), 2)}
    totals = {c: catsum(cats[c]) for c in cats}

    # 日均头条 = 各日 compute_total 求和 ÷ 7
    rev_w = round(sum(compute_total(d, a.indir) for d in week_days) / 7.0, 2)
    rev_p = round(sum(compute_total(d, a.indir) for d in prev_days) / 7.0, 2)

    adv_roll = {}
    for c in cats:
        for x in cats[c]:
            r = adv_roll.setdefault(x['ad_user'], {'flow_delta': 0.0, 'ops': []})
            r['flow_delta'] += x['flow_delta']
            r['ops'].append({'cat': c, 'package': x['package'], 'conv_delta': x['conv_delta'],
                             'flow_delta': x['flow_delta']})
    for v in adv_roll.values():
        v['flow_delta'] = round(v['flow_delta'], 2)
        v['ops'].sort(key=lambda o: -abs(o['flow_delta']))

    result = {
        'mode': 'week_over_week_dailyavg', 'basis': 'actual_conversions',
        'week': f'{week_days[0]}~{week_days[-1]}', 'prev_week': f'{prev_days[0]}~{prev_days[-1]}',
        'threshold_conv': a.threshold,
        'headline': {'revenue_week_avg': rev_w, 'revenue_prev_week_avg': rev_p,
                     'delta': round(rev_w - rev_p, 2),
                     'pct': round((rev_w - rev_p) / rev_p * 100, 2) if rev_p else 0.0},
        'operations': {'totals': totals, 'detail': cats},
        'advertiser_rollup': dict(sorted(adv_roll.items(), key=lambda kv: -abs(kv[1]['flow_delta']))),
    }

    t = totals
    print(f'=== 运营操作分类（周环比·日均） 上周日均[{result["prev_week"]}]  →  本周日均[{result["week"]}]  门槛 ±{a.threshold} 日均转化 ===')
    print(f'新单 {t["new"]["count"]} ({t["new"]["conv"]:+.1f}/日, {t["new"]["flow"]:+.2f}$/日) | '
          f'停单 {t["stop"]["count"]} ({t["stop"]["conv"]:+.1f}/日, {t["stop"]["flow"]:+.2f}$/日) | '
          f'加量 {t["increased"]["count"]} ({t["increased"]["conv"]:+.1f}/日, {t["increased"]["flow"]:+.2f}$/日) | '
          f'减量 {t["decreased"]["count"]} ({t["decreased"]["conv"]:+.1f}/日, {t["decreased"]["flow"]:+.2f}$/日)')
    print(f'日均流水 ${rev_w:,.2f}/日 vs 上周 ${rev_p:,.2f}/日  →  {rev_w-rev_p:+,.2f}$/日 ({result["headline"]["pct"]:+.2f}%)')
    print('\n— 广告主级 Top（日均Δ流水）—')
    for adv, v in list(result['advertiser_rollup'].items())[:8]:
        top = v['ops'][0]
        print(f'  {adv:<14} {v["flow_delta"]:+8.2f}$/日   ({top["cat"]} {top["package"]} 转化{top["conv_delta"]:+.0f}/日)')
    if a.json:
        json.dump(result, open(a.json, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
        print(f'\n结构化结果 → {a.json}')


if __name__ == '__main__':
    main()
