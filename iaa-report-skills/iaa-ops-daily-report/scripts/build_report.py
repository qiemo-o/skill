#!/usr/bin/env python3
"""运营日常汇报 · 操作分类 + 流水影响计算（三段式报告的"算操作"步骤）。

口径（2026-09-24 与小迪两轮锁定，改前先看 SKILL.md §操作分类口径）：
  - **加减/新停 全部按「实际转化数」判**，不再用排班目标 cap（count）。
  - 一条回调算「转化」的判据（对齐生产日报 daily_report_new_api.js 的 tran_num）：
        channel=='4580'  且  event_name 为空  且  blocked_sub_reason 为空  且  come_from 非空
    —— 游戏内事件（upgrade_station/session/Ad_Watched…）、被拒（blocked）都不算转化。
  - 转化数 = 满足上述条件的回调行数；流水 = 这些行的 `payout` 求和。
  - 计数粒度键 = (offer_id, come_from=客户)：每家客户 offer 一般独立；两家撞同 offer_id 各算一条。
  - 门槛 |Δ转化数| >= 10（2026-09-24 小迪定，原 30→10）。
  - 新单: conv_prev==0 且 conv_day>=10 | 停单: conv_day==0 且 conv_prev>=10
    加量: Δ>=10 | 减量: Δ<=-10（加/减要求两天都有转化，否则归新/停）
  - ⚠ 会出现"排班目标加了、但实际转化反而少"→ 按本口径正确归为**减量**（反映真实），
    这正是切换口径的目的：cap 是意图、转化才是结果。
  - 头条总流水 = 自有转化行 payout + 外部(iaa_call/iaasdklab_call) payout（clickid 去重）。

依赖 fetch_data.py 先拉好数据。用法：
  python3 build_report.py --day 2026-09-23 [--prev 2026-09-22] [--indir /tmp/ops] [--json out.json]
"""
import argparse, csv, io, json, os, sys

THRESHOLD = 10  # |Δ转化数| 门槛：一次操作


def fnum(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def is_conv(r):
    """回调是否为一条有效转化（对齐生产 tran_num 判据）。"""
    return (str(r.get('channel')) == '4580'
            and not r.get('event_name')
            and not r.get('blocked_sub_reason')
            and r.get('come_from'))


def load_nd(path):
    if not os.path.exists(path):
        return None
    out = []
    for l in open(path, encoding='utf-8'):
        l = l.strip()
        if l and not l.startswith('__'):
            try:
                out.append(json.loads(l))
            except json.JSONDecodeError:
                pass
    return out


def load_csv(path):
    """第1行标题、第2行表头(带BOM)、第3行起数据。"""
    if not os.path.exists(path):
        return None
    lines = open(path, encoding='utf-8-sig').read().splitlines()
    if len(lines) < 2:
        return []
    hdr = next(csv.reader(lines[1:2]))
    return list(csv.DictReader(io.StringIO('\n'.join([','.join(hdr)] + lines[2:])), fieldnames=hdr))


def conv_by_offer(rows, date_iso):
    """{(offer_id, come_from): {conv:int, pay:float, pkg:str}}，按 utcdate 归日、只数有效转化。"""
    m = {}
    for r in rows:
        if r.get('utcdate') != date_iso or not is_conv(r):
            continue
        k = (str(r.get('offer_id')), r.get('come_from'))
        e = m.setdefault(k, {'conv': 0, 'pay': 0.0, 'pkg': r.get('package_name') or ''})
        e['conv'] += 1
        e['pay'] += fnum(r.get('payout'))
    return m


def ext_conv_by_offer(indir, date_iso, canon_fn=None, omap=None, disp=None):
    """外部(MY2/HHKK)转化并入自有 offer。

    归因：offer_id 能在回调映射里找到就用 come_from，否则用 ad_user。
    去重键是 (广告主, clickid)。disp 用来记住展示名，不把 GasTech 写成 gastech。
    """
    y = date_iso.replace('-', '')
    m = {}
    ext = []
    for t in ('iaa_call', 'iaasdklab_call'):
        ext += load_csv(f'{indir}/{t}_{y}.csv') or []
    seen = set()
    for r in ext:
        cid = r.get('self_click_id') or r.get('aff_click_id') or r.get('id')
        oid = str(r.get('offer_id'))
        # 跳过 CSV 表头行（offer_id 字面量 "offer_id"）
        if oid == 'offer_id':
            continue
        raw = r.get('ad_user') or ''
        if omap and oid in omap:
            normalized = omap[oid]
        else:
            normalized = canon_fn(raw).lower() if canon_fn else (raw or '').strip().lower()
        if not normalized or normalized == 'ad_user':
            continue
        if disp is not None and raw and raw.strip().lower() != 'ad_user':
            shown = canon_fn(raw) if canon_fn else raw.strip()
            # 映射到了别的 come_from 时，不要用外部 ad_user 的名字盖掉展示名
            if shown.lower() == normalized:
                old = disp.get(normalized)
                if old is None or (old == old.lower() and shown != shown.lower()):
                    disp[normalized] = shown
        pay = fnum(r.get('payout'))
        dk = (normalized, cid)
        if cid and dk in seen:
            continue
        if cid:
            seen.add(dk)
        k = (oid, normalized)
        e = m.setdefault(k, {'conv': 0, 'pay': 0.0, 'pkg': ''})
        e['conv'] += 1
        e['pay'] += pay
    return m


def dedup_payout_total(rows, key='clickid'):
    seen, s = set(), 0.0
    for r in rows:
        k = r.get(key) or r.get('aff_clickid') or r.get('self_click_id') or r.get('id')
        if k in seen:
            continue
        seen.add(k)
        s += fnum(r.get('payout'))
    return s


def compute_total(day_iso, indir):
    """头条总流水：自有转化行 payout（不重复计）+ 外部 payout（clickid 去重）。"""
    y = day_iso.replace('-', '')
    cb = load_nd(f'{indir}/wm_all_callback_{y}.ndjson') or []
    self_pay = sum(fnum(r.get('payout')) for r in cb if r.get('utcdate') == day_iso and is_conv(r))
    ext = []
    for t in ('iaa_call', 'iaasdklab_call'):
        ext += load_csv(f'{indir}/{t}_{y}.csv') or []
    return self_pay + dedup_payout_total(ext)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--day', required=True, help='报告日 YYYY-MM-DD（如昨日）')
    ap.add_argument('--prev', help='对比日，默认 day-1')
    ap.add_argument('--indir', default='/tmp/ops')
    ap.add_argument('--json', help='结构化结果落盘路径')
    a = ap.parse_args()

    import datetime as dt
    day_iso = a.day
    prev_iso = a.prev or (dt.date.fromisoformat(day_iso) - dt.timedelta(days=1)).isoformat()
    yd, yp = day_iso.replace('-', ''), prev_iso.replace('-', '')

    cb_day = load_nd(f'{a.indir}/wm_all_callback_{yd}.ndjson')
    cb_prev = load_nd(f'{a.indir}/wm_all_callback_{yp}.ndjson')
    for name, obj in [('callback(day)', cb_day), ('callback(prev)', cb_prev)]:
        if obj is None:
            sys.exit(f'缺数据文件 {name} @ {a.indir}，先跑 fetch_data.py --start {prev_iso} --end {day_iso}')

    # key 归一函数：把 come_from/ad_user 统一归一（Kookeey5→Kookeey 等）
    import re
    def _canon(name):
        s = (name or '').strip()
        if re.match(r'kookeey', s, re.I):
            return 'Kookeey'
        return s
    def norm(name):
        return _canon(name).lower() if name else ''

    # 自有回调的 key 也归一，以便跟外部合并。展示名保留原始大小写。
    disp = {}

    def remember(raw):
        if not raw:
            return
        k = norm(raw)
        if not k:
            return
        shown = _canon(raw)
        old = disp.get(k)
        if old is None or (old == old.lower() and shown != shown.lower()):
            disp[k] = shown

    def rekey(m):
        out = {}
        for (oid, adv), v in m.items():
            remember(adv)
            k2 = (oid, norm(adv))
            e = out.setdefault(k2, {'conv': 0, 'pay': 0.0, 'pkg': v.get('pkg', '')})
            e['conv'] += v['conv']
            e['pay'] += v['pay']
            if v.get('pkg') and not e.get('pkg'):
                e['pkg'] = v['pkg']
        return out

    cd_map = rekey(conv_by_offer(cb_day, day_iso))
    cp_map = rekey(conv_by_offer(cb_prev, prev_iso))
    # 合并外部(MY2/HHKK)转化。offer 映射用回调 come_from，避免 ad_user 和 come_from 不一致时拆成两家。
    import daily_flow_group as g
    omap = g.offer_map([day_iso, prev_iso], a.indir)
    ed_map = ext_conv_by_offer(a.indir, day_iso, canon_fn=_canon, omap=omap, disp=disp)
    ep_map = ext_conv_by_offer(a.indir, prev_iso, canon_fn=_canon, omap=omap, disp=disp)
    for k in set(ed_map) | set(ep_map):
        e_conv_d = ed_map.get(k, {}).get('conv', 0)
        e_pay_d = ed_map.get(k, {}).get('pay', 0.0)
        e_conv_p = ep_map.get(k, {}).get('conv', 0)
        e_pay_p = ep_map.get(k, {}).get('pay', 0.0)
        if k in cd_map:
            cd_map[k]['conv'] += e_conv_d
            cd_map[k]['pay'] += e_pay_d
        elif e_conv_d > 0:
            cd_map[k] = {'conv': e_conv_d, 'pay': e_pay_d, 'pkg': ''}
        if k in cp_map:
            cp_map[k]['conv'] += e_conv_p
            cp_map[k]['pay'] += e_pay_p
        elif e_conv_p > 0:
            cp_map[k] = {'conv': e_conv_p, 'pay': e_pay_p, 'pkg': ''}

    cats = {'new': [], 'stop': [], 'increased': [], 'decreased': []}
    for k in set(cd_map) | set(cp_map):
        oid, adv = k
        cd, cp = cd_map.get(k), cp_map.get(k)
        conv_prev = cp['conv'] if cp else 0
        conv_day = cd['conv'] if cd else 0
        d = conv_day - conv_prev
        pkg = (cd or cp)['pkg']
        f_prev = round(cp['pay'], 2) if cp else 0.0
        f_day = round(cd['pay'], 2) if cd else 0.0
        rec = {'offer_id': oid, 'ad_user': disp.get(adv) or _canon(adv), 'package': pkg,
               'conv_prev': conv_prev, 'conv_day': conv_day, 'conv_delta': d,
               'flow_prev': f_prev, 'flow_day': f_day, 'flow_delta': round(f_day - f_prev, 2)}
        if conv_prev == 0 and conv_day >= THRESHOLD:
            cats['new'].append(rec)
        elif conv_day == 0 and conv_prev >= THRESHOLD:
            cats['stop'].append(rec)
        elif d >= THRESHOLD:
            cats['increased'].append(rec)
        elif d <= -THRESHOLD:
            cats['decreased'].append(rec)

    def catsum(lst):
        return {'count': len(lst), 'conv': sum(x['conv_delta'] for x in lst),
                'flow': round(sum(x['flow_delta'] for x in lst), 2)}

    totals = {c: catsum(cats[c]) for c in cats}
    pkg_roll = {}
    for c in cats:
        for x in cats[c]:
            r = pkg_roll.setdefault(x['package'], {'new': 0, 'stop': 0, 'increased': 0, 'decreased': 0,
                                                   'conv_delta': 0, 'flow_delta': 0.0, 'ad_users': set()})
            r[c] += 1
            r['conv_delta'] += x['conv_delta']
            r['flow_delta'] += x['flow_delta']
            if x['ad_user']:
                r['ad_users'].add(x['ad_user'])
    for v in pkg_roll.values():
        v['ad_users'] = sorted(v['ad_users'])
        v['flow_delta'] = round(v['flow_delta'], 2)

    rev_day = compute_total(day_iso, a.indir)
    rev_prev = compute_total(prev_iso, a.indir)
    result = {
        'day': day_iso, 'prev': prev_iso, 'basis': 'actual_conversions',
        'headline': {
            'revenue_day': round(rev_day, 2), 'revenue_prev': round(rev_prev, 2),
            'delta': round(rev_day - rev_prev, 2),
            'headline_source': 'computed(自有转化行payout + 外部payout clickid去重) — 发布前须与早会/日报头条核对',
        },
        'operations': {'threshold_conv': THRESHOLD, 'totals': totals, 'detail': cats},
        'package_rollup': dict(sorted(pkg_roll.items(), key=lambda kv: kv[1]['conv_delta'])),
    }

    t = totals
    print(f'=== 运营操作分类 {prev_iso} → {day_iso} （按实际转化数，门槛 ±{THRESHOLD}）===')
    print(f'新单 {t["new"]["count"]} ({t["new"]["conv"]:+d}转化, {t["new"]["flow"]:+.2f}$) | '
          f'停单 {t["stop"]["count"]} ({t["stop"]["conv"]:+d}转化, {t["stop"]["flow"]:+.2f}$) | '
          f'加量 {t["increased"]["count"]} ({t["increased"]["conv"]:+d}转化, {t["increased"]["flow"]:+.2f}$) | '
          f'减量 {t["decreased"]["count"]} ({t["decreased"]["conv"]:+d}转化, {t["decreased"]["flow"]:+.2f}$)')
    op_net = t['new']['flow'] + t['stop']['flow'] + t['increased']['flow'] + t['decreased']['flow']
    print(f'操作流水净影响 ≈ {op_net:+.2f}$   （总变动 {result["headline"]["delta"]:+.2f}$，余为自然波动）')
    print(f'⚠ 头条口径: {result["headline"]["headline_source"]}')
    print('\n— 减量包级 Top5（按转化数降幅，供模板"焦点"用）—')
    dec = {k: v for k, v in result['package_rollup'].items() if v['decreased'] > 0}
    for k, v in list(dec.items())[:5]:
        print(f'  {k}  客户={",".join(v["ad_users"]) or "—"}  {v["conv_delta"]:+d}转化  {v["flow_delta"]:+.2f}$')
    if a.json:
        json.dump(result, open(a.json, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
        print(f'\n结构化结果 → {a.json}')


if __name__ == '__main__':
    main()
