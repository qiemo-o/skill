#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""群日报 · IAA 流水昨日 vs 前日对比。
- 总流水（头条）= 自有转化行 payout + 外部(iaa_call/iaasdklab_call) payout（clickid 去重）。
- 分广告主流水：自有转化 payout 按 come_from + 外部 payout 按 offer_id→come_from 归因并入；
  名字归并 Kookeey*→Kookeey（keke2 独立）；外部按 (广告主, clickid) 去重。
- 输出：总流水环比 + 流水下降 > 阈值(默认$10) 的广告主清单。金额一律全角＄。
用法: daily_flow_group.py --day 2026-09-28 --prev 2026-09-27 --indir /tmp/ops [--drop 10] [--json out.json]
"""
import argparse, json, os, re, sys, subprocess
from datetime import datetime, timedelta
sys.path.insert(0, os.path.dirname(__file__))
from build_report import fnum, is_conv, load_nd, load_csv


def fetch_group_messages(chat_id, limit=50):
    """拉取 wmyy 群最近消息"""
    try:
        result = subprocess.run(
            ['lark-cli', 'im', '+chat-messages-list', '--chat-id', chat_id, '--as', 'user', '--limit', str(limit)],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode == 0:
            data = json.loads(result.stdout)
            return data.get('data', {}).get('messages', [])
    except Exception:
        pass
    return []


def find_root_cause(messages, client_name, day):
    """从群消息中找客户下降的根因"""
    keywords = ['下降', '跌', '停', '暂停', '预算', '未跑满', '被拒', '停投', '减量', '关', '忘', '少']
    day_date = datetime.strptime(day, '%Y-%m-%d').date()
    next_date = day_date + timedelta(days=1)
    valid_dates = {day, next_date.strftime('%Y-%m-%d')}

    for msg in messages:
        content = msg.get('content', '')
        create_time = msg.get('create_time', '')
        if not any(d in create_time for d in valid_dates):
            continue
        if client_name.lower() not in content.lower():
            continue
        for kw in keywords:
            if kw in content:
                return content.strip()
    return None


def canon(name):
    """广告主名归一：去空白；Kookeey5/Kookeey→Kookeey；其余保留。keke2 不并。"""
    s = (name or '').strip()
    # 大小写不敏感前缀：kookeey(含 Kookeey5/kookeey 等变体) 一律并到主名 Kookeey；keke/keke2 不并
    if re.match(r'kookeey', s, re.I):
        return 'Kookeey'
    return s


def key(name):
    return canon(name).lower()


# 负责人 open_id（来源：wmyy 群成员列表 member_id）
OWNER_ID = {
    '汤倩': 'ou_8f073ac6d7e74e817b06c0035c92aad4',
    '赵海': 'ou_982c1be460b3d4a5f9477f8063f6c0e4',
    '张浩琪': 'ou_761c95925991d0f07f228b7448038a82',
    '我': 'ou_31118968e191ff725644d2a235d111a0',   # 刘恋(小迪)
}
# AT_MODE: 'tag' 用飞书<at>标签(可提醒)；'text' 纯文本@名(仅可读)。用 --at 覆盖。
AT_MODE = 'tag'


# 重启单只看报告日之前这么多天，避免 /tmp 里偶然留下的旧文件改变结论。
HIST_DAYS = 14

OWNER_ALIASES = {
    '我': '我',
    '小迪': '我',
    '刘恋': '我',
    '汤倩': '汤倩',
    '赵海': '赵海',
    '张浩琪': '张浩琪',
}

STATIC_BOOK = {
    '我': ('Kookeey', 'app', 'GasTech', 'leap4vision', 'MB'),
    '汤倩': ('Autumn', 'selfCChange'),
    '赵海': ('Adprojec', 'BidMatrix', 'leanmobi', 'Streamly', 'insightPlus'),
    '张浩琪': ('hivexads', 'keke'),
}

# --clients 给到这些前缀时，带上数据里的变体（Autumn1、keke2、insightPlus2）。
# Kookeey5 已在 key() 里收成 Kookeey。
FOLD_PREFIXES = ('autumn', 'keke', 'insightplus', 'kookeey')


def owner_of(name):
    """按小迪给的负责表匹配（含前缀规则：Autumn/Kookeey/insightPlus/keke）。返回负责人或 None。"""
    n = (name or '').strip().lower()
    if n.startswith('autumn') or 'selfcchange' in n:
        return '汤倩'                              # Autumn/Autumn1、selfCChange
    if n in ('adprojec', 'bidmatrix', 'leanmobi', 'streamly') or n.startswith('insightplus'):
        return '赵海'                              # Adprojec/BidMatrix/leanmobi/Streamly/insightPlus*
    if 'hivexads' in n or n.startswith('keke'):
        return '张浩琪'                            # hivexads、keke(含keke2)
    if n.startswith('kookeey') or n in ('app', 'gastech', 'leap4vision', 'mb'):
        return '我'                                # Kookeey*、app/GasTech/leap4vision/MB
    return None


def normalize_owner(name):
    """把口述名字收成 owner_of() 的返回值。不认识则返回 None。"""
    return OWNER_ALIASES.get((name or '').strip())


def match_wanted(adv_key, wanted):
    if adv_key in wanted:
        return True
    return any(adv_key.startswith(p) and p in wanted for p in FOLD_PREFIXES)


def remember_name(disp, raw):
    """norm_key -> 展示名。已有大写名时不被小写覆盖。"""
    if not raw:
        return
    k = key(raw)
    if not k or k == 'ad_user':
        return
    shown = canon(raw)
    old = disp.get(k)
    if old is None or (old == old.lower() and shown != shown.lower()):
        disp[k] = shown


def iter_raw_names(indir, days):
    for day in days:
        y = day.replace('-', '')
        for r in load_nd(os.path.join(indir, f'wm_all_callback_{y}.ndjson')) or []:
            if r.get('come_from'):
                yield r.get('come_from')
        for r in load_nd(os.path.join(indir, f'wm_iaasdk_task_{y}.ndjson')) or []:
            if r.get('ad_user'):
                yield r.get('ad_user')
        for t in ('iaa_call', 'iaasdklab_call', 'iaasdklab_advphone', 'iaasdklab_advxieyi'):
            for r in load_csv(os.path.join(indir, f'{t}_{y}.csv')) or []:
                raw = r.get('ad_user') or ''
                if raw and raw.lower() != 'ad_user':
                    yield raw


def display_names(indir, days):
    disp = {}
    for names in STATIC_BOOK.values():
        for n in names:
            remember_name(disp, n)
    for raw in iter_raw_names(indir, days):
        remember_name(disp, raw)
    return disp


def book_keys(owner, indir, days):
    """负责人的客户键：固定名单 + 数据里命中的变体（Autumn1、keke2）。"""
    keys = {key(n) for n in STATIC_BOOK[owner]}
    for raw in iter_raw_names(indir, days):
        if owner_of(raw) == owner:
            keys.add(key(raw))
    return keys


def expand_clients(clients, indir, days):
    wanted = {key(c.strip()) for c in clients.split(',') if c.strip()}
    found = set(wanted)
    for raw in iter_raw_names(indir, days):
        k = key(raw)
        if match_wanted(k, wanted):
            found.add(k)
    return found


def history_offer_keys(indir, day, hist_days=HIST_DAYS):
    """报告日之前 hist_days 天内出现过有效转化的 (offer_id, 客户键)。不含报告日当天。"""
    import datetime as dt
    end = dt.date.fromisoformat(day)
    start = end - dt.timedelta(days=hist_days)
    found = set()
    if not os.path.isdir(indir):
        return found
    prefix = 'wm_all_callback_'
    for fn in os.listdir(indir):
        if not (fn.startswith(prefix) and fn.endswith('.ndjson')):
            continue
        stem = fn[len(prefix):-len('.ndjson')]
        if len(stem) != 8 or not stem.isdigit():
            continue
        d = dt.datetime.strptime(stem, '%Y%m%d').date()
        if d < start or d >= end:
            continue
        for r in load_nd(os.path.join(indir, fn)) or []:
            if is_conv(r):
                found.add((str(r.get('offer_id')), key(r.get('come_from') or r.get('ad_user'))))
    return found


def at(name):
    """把负责人渲染成@。tag 模式给飞书<at>标签，text 模式给纯文本。"""
    if not name:
        return ''
    if AT_MODE == 'tag':
        return f'<at user_id="{OWNER_ID[name]}"></at>'
    return f'@{name}'


def offer_map(days, indir):
    """从自有回调 offer_id→come_from 投票建映射（覆盖尽量多的天）。"""
    votes = {}
    for d in days:
        cb = load_nd(f'{indir}/wm_all_callback_{d.replace("-", "")}.ndjson') or []
        for r in cb:
            if not is_conv(r):
                continue
            oid = str(r.get('offer_id'))
            votes.setdefault(oid, {})
            nk = key(r.get('come_from'))
            votes[oid][nk] = votes[oid].get(nk, 0) + 1
    m = {}
    for oid, cnt in votes.items():
        m[oid] = max(cnt.items(), key=lambda kv: kv[1])[0]  # key(lower)
    return m


def ios_flow(day_iso, indir):
    """IOS 大盘流水 = 自有回调 channel=4584 的有效转化 payout（event_name空 且 未blocked 且 come_from非空），无外部。"""
    y = day_iso.replace('-', '')
    cb = load_nd(f'{indir}/wm_all_callback_{y}.ndjson') or []
    s = 0.0
    for r in cb:
        if (r.get('utcdate') == day_iso and str(r.get('channel')) == '4584'
                and not r.get('event_name') and not r.get('blocked_sub_reason') and r.get('come_from')):
            s += fnum(r.get('payout'))
    return s


def flow(day_iso, indir, omap, disp):
    """返回 {advertiser_key: payout}，自有转化 + 外部归因。"""
    y = day_iso.replace('-', '')
    out = {}
    cb = load_nd(f'{indir}/wm_all_callback_{y}.ndjson') or []
    for r in cb:
        if r.get('utcdate') != day_iso or not is_conv(r):
            continue
        k = key(r.get('come_from'))
        disp.setdefault(k, canon(r.get('come_from')))
        out[k] = out.get(k, 0.0) + fnum(r.get('payout'))
    ext = []
    for t in ('iaa_call', 'iaasdklab_call'):
        ext += load_csv(f'{indir}/{t}_{y}.csv') or []
    seen = set()
    for r in ext:
        cid = r.get('self_click_id') or r.get('aff_click_id') or r.get('id')
        oid = str(r.get('offer_id'))
        if oid in omap:
            k = omap[oid]
        else:
            k = key(r.get('ad_user'))
            disp.setdefault(k, canon(r.get('ad_user')))
        dk = (k, cid)
        if cid and dk in seen:
            continue
        if cid:
            seen.add(dk)
        out[k] = out.get(k, 0.0) + fnum(r.get('payout'))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--day', required=True)
    ap.add_argument('--prev', required=True)
    ap.add_argument('--indir', default='/tmp/ops')
    ap.add_argument('--drop', type=float, default=30.0, help='流水下降超过此金额(美元)则点名')
    ap.add_argument('--rise', type=float, default=20.0, help='流水上升超过此金额(美元)则点名')
    ap.add_argument('--at', choices=['tag', 'text', 'off'], default='tag', help='@负责人方式：tag飞书提醒/text纯文本/off不@')
    ap.add_argument('--json', help='把结果写 JSON')
    a = ap.parse_args()
    global AT_MODE
    AT_MODE = a.at

    disp = {}
    omap = offer_map([a.day, a.prev], a.indir)
    fd = flow(a.day, a.indir, omap, disp)
    fp = flow(a.prev, a.indir, omap, disp)

    tot_d, tot_p = sum(fd.values()), sum(fp.values())
    delta = tot_d - tot_p
    pct = (delta / tot_p * 100) if tot_p else 0.0

    allk = set(fd) | set(fp)
    rows = []
    for k in allk:
        d, p = fd.get(k, 0.0), fp.get(k, 0.0)
        rows.append((disp.get(k, k), d, p, d - p))
    rows.sort(key=lambda r: -r[1])  # 按昨日流水降序
    drops = [r for r in rows if (r[3] < 0 and -r[3] > a.drop)]
    rises = [r for r in rows if (r[3] > 0 and r[3] > a.rise)]

    def money(x):
        return f'＄{x:,.2f}'

    ios_d, ios_p = ios_flow(a.day, a.indir), ios_flow(a.prev, a.indir)
    ios_delta = ios_d - ios_p
    ios_pct = (ios_delta / ios_p * 100) if ios_p else 0.0
    ios_ward = "上升" if ios_delta >= 0 else "下降"
    # IOS 定性：波动 <3% 且 <＄5 视为小幅波动
    ios_note = "小幅波动" if abs(ios_pct) < 3 and abs(ios_delta) < 5 else ("明显上升" if ios_delta > 0 else "明显下降")

    L = []
    L.append(f'【IAA 日报 · 流水环比】{a.prev[5:].replace("-", ".")} → {a.day[5:].replace("-", ".")}')
    arrow = "上升" if delta >= 0 else "下降"
    sign = "+" if delta >= 0 else "-"
    L.append(f'• AOS大盘总流水：{money(tot_p)} → {money(tot_d)}，{arrow} {sign}{money(abs(delta))}（{pct:+.1f}%）')
    if drops:
        # 拉群消息找根因
        CHAT_ID = 'oc_c5691378120c2e2f4abffe03d54b42cb'
        group_msgs = fetch_group_messages(CHAT_ID)
        root_causes = {}
        for nm, d, p, dd in drops:
            rc = find_root_cause(group_msgs, nm, a.day)
            if rc:
                root_causes[nm] = rc

        L.append(f'流水下降超多的广告主需要注意：')
        for nm, d, p, dd in sorted(drops, key=lambda r: r[3]):
            own = owner_of(nm)
            mention = ('  ' + at(own)) if (own and a.at != 'off') else ''
            tag = '' if own else '（负责人待确认）'
            rc = root_causes.get(nm)
            rc_text = ''
            if rc:
                s = rc
                parts = []
                if '多跑' in s:
                    parts.append('多跑流水')
                if '忘关' in s:
                    parts.append('实验室任务忘关')
                if '已关闭' in s or '已关' in s:
                    parts.append('昨日已关')
                m2 = __import__('re').search(r'[少会降]?\D*(\d+)\D*流水', s)
                if m2:
                    parts.append(f'影响约＄{m2.group(1)}流水')
                if '暂停' in s:
                    parts.append('暂停')
                if '预算' in s:
                    parts.append('预算耗尽')
                if '被拒' in s or '拒绝' in s:
                    parts.append('offer被拒')
                if '减量' in s or '降量' in s:
                    parts.append('主动降量')
                if not parts:
                    parts.append(s[:30].rstrip('，。；') + ('...' if len(s) > 30 else ''))
                rc_text = '\n    原因：' + '，'.join(parts)
            L.append(f'  - {nm}：-{money(abs(dd))}（{dd / p * 100 if p else 0:+.1f}%）{tag}{mention}{rc_text}')
    else:
        L.append(f'（各广告主 AOS 流水波动均在 ＄{a.drop:g} 以内，无需反馈下降原因）')
    if rises and delta > 0:
        L.append('流水上升占大头的广告主有：')
        for nm, d, p, dd in sorted(rises, key=lambda r: -r[3]):
            L.append(f'  - {nm}：+{money(dd)}（+{dd / p * 100 if p else 0:.1f}%）')
    L.append(f'• IOS总流水：{money(ios_p)} → {money(ios_d)}，{ios_ward} {money(abs(ios_delta))}（{ios_pct:+.1f}%），{ios_note}')

    txt = '\n'.join(L)
    print(txt)

    if a.json:
        json.dump({'day': a.day, 'prev': a.prev, 'total_day': tot_d, 'total_prev': tot_p,
                   'delta': delta, 'drops': [{'ad_user': nm, 'day': d, 'prev': p, 'delta': dd}
                                             for nm, d, p, dd in drops]},
                  open(a.json, 'w'), ensure_ascii=False, indent=2)


if __name__ == '__main__':
    main()
