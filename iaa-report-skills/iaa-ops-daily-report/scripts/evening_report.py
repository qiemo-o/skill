#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""IAA 晚报 · 白天场复盘（三段式）。

口径：
- 分客户流水 = 自有 channel4580 有效转化 payout + 外部按 offer_id→come_from 归因、(广告主,clickid) 去重。
- 跑满率 = 同时段自有有效转化数 ÷ 当日 pidPbLimitCount（每 offer 取 max 再求和）。分母是全天 cap，分子只到当前小时，数值偏低属正常。cap 为 0 不参与跑满率。
- 失效未跑 = 当日有 cap(>0) 但同时段自有转化=0 的 offer。
- 被拒率、0 收益包只统计本次负责人/客户，不带上别人的包。
- 不传 --cut 时，截止小时 = min(当日最大小时+1, 19)，标题里的白天场不会把晚场算进去。要含晚场请显式传 --cut。
- 新单/重启单：白天场同时段转化 >= 5（窗口不完整，所以低于全天早报的 10）。重启只认报告日前 14 天。
用法: evening_report.py [--day YYYY-MM-DD] [--prev ...] [--indir /tmp/ops] [--cut N] [--owner 我] [--clients a,b]
"""
import argparse
import os
import sys
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from build_report import is_conv, fnum, load_nd, load_csv
import daily_flow_group as g

# 白天窗口不满一天，新单门槛低于全天早报的 ±10。
DAYTIME_NEW_MIN = 5
# 不显式传 --cut 时，白天场最晚算到 18 点（cut=19）。
DAYTIME_CUT_CAP = 19


def money(x):
    return f'＄{x:,.2f}'


def hour_of(ts):
    try:
        return int(str(ts).split(' ')[-1].split(':')[0])
    except Exception:
        return None


def max_hour(indir, day):
    cb = load_nd(f'{indir}/wm_all_callback_{day.replace("-", "")}.ndjson') or []
    hs = [h for h in (hour_of(r.get('add_time')) for r in cb if r.get('add_time')) if h is not None]
    return max(hs) if hs else None


def pct_change(new, old):
    if old:
        return (new - old) / old * 100
    return 100.0 if new else 0.0


def compute(indir, day, cut, omap, disp):
    """返回同时段 flow / 转化 / cap / 失效 / 分客户被拒 / 分客户 0 收益包。"""
    y = day.replace('-', '')
    cb = [r for r in (load_nd(f'{indir}/wm_all_callback_{y}.ndjson') or [])
          if r.get('utcdate') == day and (hour_of(r.get('add_time')) if r.get('add_time') else 0) < cut]
    flow = defaultdict(float)
    ownconv = defaultdict(int)
    ownconv_off = defaultdict(lambda: defaultdict(int))
    pkg = defaultdict(float)
    for r in cb:
        if not is_conv(r):
            continue
        k = g.key(r.get('come_from'))
        g.remember_name(disp, r.get('come_from'))
        flow[k] += fnum(r.get('payout'))
        ownconv[k] += 1
        ownconv_off[k][str(r.get('offer_id'))] += 1
        pkg[(k, r.get('package_name'))] += fnum(r.get('payout'))
    ext = []
    for t in ('iaa_call', 'iaasdklab_call'):
        ext += [r for r in (load_csv(f'{indir}/{t}_{y}.csv') or [])
                if (hour_of(r.get('call_time') or r.get('click_time') or '0') or 0) < cut]
    seen = set()
    for r in ext:
        cid = r.get('self_click_id') or r.get('aff_click_id') or r.get('id')
        oid = str(r.get('offer_id'))
        if oid == 'offer_id':
            continue
        k = omap.get(oid) or g.key(r.get('ad_user'))
        if not k or k == 'ad_user':
            continue
        g.remember_name(disp, r.get('ad_user'))
        dk = (k, cid)
        if cid and dk in seen:
            continue
        if cid:
            seen.add(dk)
        flow[k] += fnum(r.get('payout'))
    rej_by = defaultdict(lambda: [0, 0])
    for r in cb:
        if str(r.get('channel')) != '4580':
            continue
        k = g.key(r.get('come_from'))
        if not k:
            continue
        rej_by[k][1] += 1
        if (r.get('blocked_sub_reason') or '').strip():
            rej_by[k][0] += 1
    pkg0_by = defaultdict(list)
    for (k, p), v in pkg.items():
        if p and v == 0:
            pkg0_by[k].append(p)
    tk = load_nd(f'{indir}/wm_iaasdk_task_{y}.ndjson') or []
    capoff = defaultdict(lambda: defaultdict(float))
    for r in tk:
        raw = r.get('ad_user') or ''
        nm = g.key(raw)
        if not nm:
            continue
        g.remember_name(disp, raw)
        capoff[nm][str(r.get('offer_id'))] = max(capoff[nm][str(r.get('offer_id'))], fnum(r.get('pidPbLimitCount')))
    capsum = {nm: sum(v.values()) for nm, v in capoff.items()}
    dead = {}
    for nm in capoff:
        dl = sorted(
            [(o, capoff[nm][o]) for o in capoff[nm] if ownconv_off[nm].get(o, 0) == 0 and capoff[nm][o] > 0],
            key=lambda x: -x[1],
        )
        if dl:
            dead[nm] = dl
    return {'flow': flow, 'ownconv': ownconv, 'capsum': capsum, 'dead': dead,
            'rej_by': rej_by, 'pkg0_by': pkg0_by, 'disp': disp}


def new_or_restart(indir, day, prev, cut, mine_keys, disp):
    """今日同时段转化>=DAYTIME_NEW_MIN、昨日同时段=0 → 新单或重启单。"""
    def offs(d):
        y = d.replace('-', '')
        cb = [r for r in (load_nd(f'{indir}/wm_all_callback_{y}.ndjson') or [])
              if r.get('utcdate') == d and (hour_of(r.get('add_time')) if r.get('add_time') else 0) < cut]
        m = defaultdict(int)
        for r in cb:
            if is_conv(r):
                m[(str(r.get('offer_id')), g.key(r.get('come_from')))] += 1
        return m
    c_day, c_prev = offs(day), offs(prev)
    hist = g.history_offer_keys(indir, day)
    out = []
    for (o, k), n in c_day.items():
        if k in mine_keys and n >= DAYTIME_NEW_MIN and c_prev.get((o, k), 0) == 0:
            out.append((o, disp.get(k, g.canon(k)), n, '新单' if (o, k) not in hist else '重启单'))
    return out


def resolve_mine(indir, day, prev, owner, clients):
    days = [day, prev]
    if clients:
        keys = g.expand_clients(clients, indir, days)
        if not keys:
            sys.exit('没有解析出客户，请检查 --clients')
        return sorted(keys), '指定客户'
    canon_owner = g.normalize_owner(owner or '我')
    if not canon_owner:
        sys.exit(f'不认识负责人「{owner}」。可用：我/小迪/刘恋、汤倩、赵海、张浩琪，或 --clients')
    scope = '负责客户' if canon_owner == '我' else f'{canon_owner}负责客户'
    return sorted(g.book_keys(canon_owner, indir, days)), scope


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--day', default=os.environ.get('DAY'))
    ap.add_argument('--prev', default=os.environ.get('PREV'))
    ap.add_argument('--indir', default='/tmp/ops')
    ap.add_argument('--cut', type=int, default=None, help='同时段窗上界(小时)。默认 min(最大小时+1, 19)')
    ap.add_argument('--name-pct', type=float, default=10.0, help='处理思路点名客户的降幅百分比阈值')
    ap.add_argument('--fetch', action='store_true', help='先跑 fetch_data.py 拉 prev..day')
    ap.add_argument('--owner', default='我', help='负责人。我/小迪/刘恋/汤倩/赵海/张浩琪')
    ap.add_argument('--clients', default=None, help='逗号分隔客户名，优先级高于 --owner')
    a = ap.parse_args()

    import datetime as dt
    import subprocess
    day = a.day or dt.date.today().isoformat()
    prev = a.prev or (dt.date.fromisoformat(day) - dt.timedelta(days=1)).isoformat()
    if a.fetch:
        subprocess.run([sys.executable, os.path.join(HERE, 'fetch_data.py'), '--start', prev, '--end', day,
                        '--outdir', a.indir], check=False)

    if a.cut is None:
        cut = min((max_hour(a.indir, day) or 18) + 1, DAYTIME_CUT_CAP)
    else:
        cut = a.cut
    disp = g.display_names(a.indir, [day, prev])
    omap = g.offer_map([day, prev], a.indir)
    D = compute(a.indir, day, cut, omap, disp)
    P = compute(a.indir, prev, cut, omap, disp)
    disp = {**P['disp'], **D['disp']}
    mine, scope = resolve_mine(a.indir, day, prev, a.owner, a.clients)
    print(f'客户 {len(mine)} 家，截止小时 < {cut}', file=sys.stderr)

    def show(k):
        return disp.get(k, g.canon(k))

    tot_d = sum(D['flow'].get(k, 0) for k in mine)
    tot_p = sum(P['flow'].get(k, 0) for k in mine)
    delta = tot_d - tot_p
    pct = pct_change(tot_d, tot_p)

    rows = []
    for k in mine:
        d, p = D['flow'].get(k, 0.0), P['flow'].get(k, 0.0)
        rows.append((show(k), d, p, d - p, pct_change(d, p)))
    rows.sort(key=lambda r: -r[1])
    head = rows[0][0] if rows else '头部客户'
    second = rows[1][0] if len(rows) > 1 else head

    blk = sum(D['rej_by'][k][0] for k in mine)
    tot_rej = sum(D['rej_by'][k][1] for k in mine)
    blk_p = sum(P['rej_by'][k][0] for k in mine)
    tot_rej_p = sum(P['rej_by'][k][1] for k in mine)
    rej_d = blk / tot_rej * 100 if tot_rej else 0.0
    rej_p = blk_p / tot_rej_p * 100 if tot_rej_p else 0.0
    pkg0 = [f'{show(k)} {p}' for k in mine for p in D['pkg0_by'].get(k, [])]

    caps = []
    for k in mine:
        n = D['ownconv'].get(k, 0)
        c = D['capsum'].get(k, 0)
        if c <= 0:
            continue
        caps.append((show(k), n, c, n / c * 100))
    caps.sort(key=lambda x: -x[3])

    dead = {show(k): [(o, int(cv)) for o, cv in D['dead'].get(k, [])] for k in mine if D['dead'].get(k)}
    nr = new_or_restart(a.indir, day, prev, cut, set(mine), disp)

    L = []
    mm = lambda iso: iso[5:].replace('-', '.')
    L.append(f'【IAA 晚报 · 白天场复盘】{mm(day)}（截至 {cut}:00，数据覆盖 0–{cut - 1}:59，晚场未跑完，不做全天定论）')
    L.append('')
    L.append('一、当前情况分析（白天场数据，晚场未计入）')
    L.append('')
    ward = '上升' if delta >= 0 else '下降'
    sign = '+' if delta >= 0 else '-'
    L.append(f'【大盘】 {scope}白天场合计：{money(tot_p)} → {money(tot_d)}，{ward} {sign}{money(abs(delta))}（{pct:+.1f}%）')
    L.append('')
    L.append('【分客户】（按今日流水降序，同比昨日同时段）')
    for nm, d, p, dd, dpct in rows:
        L.append(f'　　- {nm}　{money(p)} → {money(d)}　{("-" if dd < 0 else "+")}{money(abs(dd))}（{dpct:+.1f}%）')
    L.append('')
    L.append('【消耗与 CAP】')
    under = [(nm, f) for nm, n, c, f in caps if f < 99]
    if not caps:
        L.append('　　- 跑满率：当日没有可计算的 cap。')
    elif under:
        fills = '、'.join(f'{nm}{f:.1f}%' for nm, f in under)
        L.append(f'　　- 跑满率（<99% 记为未跑满，≥99% 记为跑满）：{fills}')
    else:
        L.append('　　- 跑满率（<99% 记为未跑满，≥99% 记为跑满）：各家均 ≥99%，全部跑满')
    if dead:
        seg = [f'{nm} {o}（cap{c}）' for nm, lst in dead.items() for o, c in lst]
        L.append(f'　　- 今日失效未跑（有 cap、转化=0）：{"、".join(seg)}。')
    else:
        L.append('　　- 今日无失效未跑 offer。')
    L.append('')
    rword = '改善' if rej_d <= rej_p else '走高'
    pkg0_txt = '（' + '、'.join(pkg0) + '）' if pkg0 else '（无疑似回传延迟）'
    L.append(f'【风控】 被拒率今 {rej_d:.2f}%（昨同时段 {rej_p:.2f}%，{rword}）；白天 0 收益但有转化的包 {len(pkg0)} 个{pkg0_txt}。')
    L.append('')

    L.append('二、处理思路（白天归因 + 晚场策略）')
    L.append('')
    big_drop_clients = [r for r in rows if r[4] <= -a.name_pct]
    i = 1
    if delta >= 0 and pct >= 0:
        L.append(f'{i}. 大盘 +{pct:.1f}%：白天场稳步增长，晚场继续按既有节奏放量，关注头部大盘（{head}）能否维持增长势头。')
    elif delta < 0 and pct > -15:
        L.append(f'{i}. 大盘 {pct:+.1f}%：各家同向小幅回落、非单点异常，判为白天流量自然波动 + 晚场未起量；晚场正常放量后预计回补，晚班盯头部大盘（{head}/{second}）晚场节奏是否回到昨日同期。')
    else:
        L.append(f'{i}. 大盘 {ward} {sign}{money(abs(delta))}（{pct:+.1f}%）：需结合下方重点客户归因排查。')
    i += 1
    capmap = {nm: f for nm, n, c, f in caps}
    for nm, d, p, dd, dpct in big_drop_clients:
        cmt = f'　（跑满率 {capmap.get(nm, 0):.1f}%'
        if nm in dead:
            cmt += f'，根因含失效 offer {",".join(str(o) for o, _ in dead[nm])}'
        cmt += '）'
        L.append(f'{i}. {nm} 白天下降 {money(abs(dd))}（{dpct:+.1f}%）{cmt}：晚场优先核查/复活失效 offer、按既有节奏补量。')
        i += 1
    if dead:
        seg = '、'.join(f'{nm} {o}（cap{c}）' for nm, lst in dead.items() for o, c in lst)
        L.append(f'{i}. 失效/掉线（{seg}）：晚班核实通道状态（被停/掉线/被拒），恢复后回补；若客户主动停投则记录原因。')
        i += 1
    ncnt = sum(1 for x in nr if x[3] == '新单')
    rcnt = sum(1 for x in nr if x[3] == '重启单')
    if nr:
        seg = '、'.join(f'{nm} offer {o}({t}，{n}转化)' for o, nm, n, t in sorted(nr, key=lambda x: -x[2])[:8])
        L.append(f'{i}. 新单/重启单：今日白天新落地 {ncnt} 个新单、{rcnt} 个重启单——{seg}。后续加量一律默认“客户主动加量”。')
    else:
        L.append(f'{i}. 新单/加量：今日白天无 ≥{DAYTIME_NEW_MIN} 转化的新单落地。后续加量一律默认“客户主动加量”。')
    L.append('')

    L.append('三、当前进展（白天执行结果 + 晚班/明日重点）')
    L.append('')
    L.append('白天执行结果：')
    dive = [r for r in rows if r[4] <= -15 and r[3] <= -30]
    dive_txt = '各家均小幅回落、无异常跳水' if not dive else ('其中 ' + '、'.join('%s%.0f%%' % (r[0], r[4]) for r in dive) + ' 降幅偏大')
    L.append('1. 白天场合计 %s，同比 %.1f%%；%s' % (money(tot_d), pct, dive_txt))
    L.append('2. 被拒率 %.2f%%（%s昨同时段 %.2f%%），白天 0 收益包 %d 个' % (rej_d, '优于' if rej_d <= rej_p else '高于', rej_p, len(pkg0)))
    ndead = sum(len(v) for v in dead.values())
    if ndead:
        deadtxt = '、'.join(f'{nm}{len(lst)}个' for nm, lst in dead.items())
        L.append('3. 失效未跑 offer 共 %d 个（%s），已列入晚班核查。' % (ndead, deadtxt))
    else:
        L.append('3. 无失效未跑 offer，各 offer 运转正常。')
    L.append('')
    hot = [nm for nm, n, c, f in caps if f >= 99]
    rec = '、'.join(f'{nm}{len(lst)}个' for nm, lst in dead.items())
    hot3 = ('③ 关注跑满率 ≥99%%（%s）已吃满/超 cap、是否需上调 cap。' % '、'.join(hot)) if hot else '③ 保持晚场正常放量节奏。'
    if delta >= 0:
        pt2 = '② 头部大盘晚场保持增长势头，继续放量；'
    elif pct > -15:
        pt2 = '② 头部大盘晚场回到昨日同期，收窄 %.1f%% 的缺口；' % abs(pct)
    else:
        pt2 = '② 头部大盘晚场重点关注，排查回落原因；'
    if rec:
        L.append('晚班重点（今晚跟进）：① 核查并恢复失效 offer %s；%s%s' % (rec, pt2, hot3))
    else:
        L.append('晚班重点（今晚跟进）：%s%s' % (pt2, hot3))
    L.append('')
    L.append('明日重点：晚场结算后出全天定论（本晚报仅白天场快照）。')

    print('\n'.join(L))


if __name__ == '__main__':
    main()
