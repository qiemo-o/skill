#!/usr/bin/env python3
"""
发送【IAA 早报】到飞书任务
- 读取 ops_report.json
- 生成早报内容
- 格式校验
- 发送到任务评论
"""
import json
import argparse
import subprocess
import sys
import os
import shutil
import time
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from build_report import fnum, load_csv
import daily_flow_group as g

CHAT_ID = 'oc_c5691378120c2e2f4abffe03d54b42cb'


def lark_bin():
    env = os.environ.get('LARK_CLI')
    if env:
        return env
    found = shutil.which('lark-cli')
    if found:
        return found
    fallback = '/home/claw/.local/bin/lark-cli'
    if os.path.exists(fallback):
        return fallback
    return None


def money(x):
    return f'＄{x:,.2f}'


def signed_money(x):
    sign = '-' if x < 0 else '+'
    return sign + money(abs(x))


def sanitize(text):
    return (text or '').replace('$', '＄')


def fetch_group_messages(chat_id, day, days_back=3):
    """拉取 wmyy 群消息。窗口按报告日，而不是按今天，补跑历史早报也能对上根因。"""
    import datetime as dt
    bin_path = lark_bin()
    if not bin_path:
        print('⚠️ 未找到 lark-cli，根因留空', file=sys.stderr)
        return []
    try:
        day_date = dt.date.fromisoformat(day)
        cutoff = day_date - dt.timedelta(days=days_back)
        end = day_date + dt.timedelta(days=1)
        result = subprocess.run(
            [bin_path, 'im', '+chat-messages-list', '--chat-id', chat_id, '--as', 'user',
             '--page-all', '--page-limit', '10', '--page-size', '50'],
            capture_output=True, text=True, timeout=120
        )
        if result.returncode != 0:
            err = (result.stderr or result.stdout or '').strip()
            print(f'⚠️ 读取运营群失败：{err[:200]}', file=sys.stderr)
            return []
        data = json.loads(result.stdout)
        msgs = data.get('data', {}).get('messages', [])
        filtered = []
        for m in msgs:
            ct = m.get('create_time', '')
            msg_date_str = ct[:10]
            if len(msg_date_str) != 10:
                continue
            try:
                msg_date = dt.date.fromisoformat(msg_date_str)
            except ValueError:
                continue
            if cutoff <= msg_date <= end:
                filtered.append(m)
        return filtered
    except Exception as e:
        print(f'⚠️ 读取运营群失败：{e}', file=sys.stderr)
        return []


def _strip_html_tags(text):
    """去掉消息中的 HTML 标签"""
    import re
    text = re.sub(r'<[^>]+>', '', text)
    text = re.sub(r'&nbsp;', ' ', text)
    text = re.sub(r'&amp;', '&', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def _summarize_root_cause(raw):
    """从群消息原文中提炼关键原因，不照搬原文"""
    import re
    s = _strip_html_tags(raw)
    parts = []
    if '多跑' in s:
        parts.append('多跑流水')
    if '忘关' in s:
        parts.append('实验室任务忘关')
    if '已关闭' in s or '已关' in s:
        parts.append('昨日已关')
    m2 = re.search(r'[少会降]?\D*(\d+)\D*流水', s)
    if m2:
        parts.append(f'影响约＄{m2.group(1)}流水')
    if '暂停' in s:
        parts.append('暂停')
    if '预算' in s:
        parts.append('预算耗尽')
    if '被拒' in s or '拒绝' in s:
        parts.append('offer被拒')
    if '减量' in s:
        parts.append('主动减量')
    # 注意：不用"降量"关键词（"一降量单"是降量类型的offer，非主动降量操作）
    if not parts:
        parts.append(s[:30].rstrip('，。；') + ('...' if len(s) > 30 else ''))
    return sanitize('，'.join(parts))


def find_root_cause(messages, client_name, day):
    """从群消息中找客户下降的根因，返回总结后的文字"""
    import datetime as dt
    keywords = ['下降', '下跌', '暂停', '预算', '未跑满', '被拒', '停投', '停单', '减量', '降量', '忘关', '多跑', '关闭', '已关', '掉量', '少跑']
    # 匹配报告日期 D 或 D+1（值班人常在 D+1 早上播报）
    day_date = dt.date.fromisoformat(day)
    next_date = day_date + dt.timedelta(days=1)
    valid_dates = {day, next_date.isoformat()}

    # 排除日报/早报类消息（本身是报告，不是根因）
    report_markers = ['【IAA 日报', '【IAA 早报', 'AOS大盘总流水', '流水下降超多的广告主']

    for msg in messages:
        content = msg.get('content', '')
        create_time = msg.get('create_time', '')
        # 消息时间要匹配报告日期或次日
        if not any(d in create_time for d in valid_dates):
            continue
        # 排除日报/早报类消息
        if any(marker in content for marker in report_markers):
            continue
        # 检查是否提到该客户（大小写不敏感）
        if client_name.lower() not in content.lower():
            continue
        # 检查是否有关键词
        for kw in keywords:
            if kw in content:
                return _summarize_root_cause(content)
    return None


def validate_format(content, required_sections):
    """格式校验"""
    errors = []

    if not content.startswith('【IAA 早报】'):
        errors.append('标题必须以【IAA 早报】开头')

    if '$' in content:
        errors.append('发现半角$（飞书会吞字）')

    if '＄' not in content:
        errors.append('金额必须用全角＄')

    for section in required_sections:
        if section not in content:
            errors.append(f'缺少"{section}"段')

    if '〔预警〕' not in content:
        errors.append('缺少〔预警〕段')

    return errors


def resolve_keys(indir, day, prev, owner, clients):
    days = [day, prev]
    if clients:
        keys = g.expand_clients(clients, indir, days)
        if not keys:
            sys.exit('没有解析出客户，请检查 --clients')
        return keys, '指定客户'
    canon_owner = g.normalize_owner(owner or '我')
    if not canon_owner:
        sys.exit(f'不认识负责人「{owner}」。可用：我/小迪/刘恋、汤倩、赵海、张浩琪，或 --clients')
    return g.book_keys(canon_owner, indir, days), canon_owner


def scope_label(label):
    if label == '指定客户':
        return '指定客户'
    if label == '我':
        return '负责客户'
    return f'{label}负责客户'


def generate_morning_report(indir, day, prev, owner=None, clients=None):
    """生成早报内容

    Args:
        owner: 负责人名字（如'我'/'小迪'/'汤倩'/'赵海'/'张浩琪'）
        clients: 逗号分隔的客户名列表（如'Kookeey,app'），优先级高于 owner
    """
    mine_keys, label = resolve_keys(indir, day, prev, owner, clients)
    names = []
    disp = g.display_names(indir, [day, prev])
    omap = g.offer_map([day, prev], indir)
    f_d = g.flow(day, indir, omap, disp)
    f_p = g.flow(prev, indir, omap, disp)
    for k in sorted(mine_keys, key=lambda x: -f_d.get(x, 0)):
        names.append(disp.get(k, g.canon(k)))
    print(f'客户 {len(mine_keys)} 家：{"、".join(names)}', file=sys.stderr)

    ops_path = os.path.join(indir, 'ops_report.json')
    if not os.path.exists(ops_path):
        sys.exit(f'缺少 {ops_path}，先跑 build_report.py')
    with open(ops_path, encoding='utf-8') as f:
        ops_data = json.load(f)

    sum_d = sum(f_d.get(k, 0) for k in mine_keys)
    sum_p = sum(f_p.get(k, 0) for k in mine_keys)
    delta = sum_d - sum_p
    pct = (delta / sum_p * 100) if sum_p else (100 if sum_d else 0)

    # 收益 gap。客户键走 g.key，Kookeey5 才能对上 Kookeey。
    warnings = []
    y = day.replace('-', '')
    phone_path = os.path.join(indir, f'iaasdklab_advphone_{y}.csv')
    xieyi_path = os.path.join(indir, f'iaasdklab_advxieyi_{y}.csv')

    if os.path.exists(phone_path) and os.path.exists(xieyi_path):
        phone_data = load_csv(phone_path) or []
        xieyi_data = load_csv(xieyi_path) or []
        phone_sum = defaultdict(float)
        xieyi_sum = defaultdict(float)
        for r in phone_data:
            u = g.key(r.get('ad_user', ''))
            if u in mine_keys:
                phone_sum[u] += fnum(r.get('adPrice'))
        for r in xieyi_data:
            u = g.key(r.get('ad_user', ''))
            if u in mine_keys:
                xieyi_sum[u] += fnum(r.get('adPrice'))
        for k in sorted(mine_keys):
            p = phone_sum.get(k, 0)
            x = xieyi_sum.get(k, 0)
            if p == 0 and x == 0:
                continue
            gap = abs(p - x) / max(p, x) * 100 if max(p, x) > 0 else 0
            if gap > 2:
                nm = disp.get(k, g.canon(k))
                warnings.append(f'  - {nm}：真机{p:.2f} vs 协议{x:.2f}，gap {gap:.1f}% >2%')

    warn_block = '\n'.join(warnings) if warnings else '  无'

    det = ops_data.get('operations', {}).get('detail', {})

    def mine_list(cat):
        return [x for x in det.get(cat, []) if g.key(x.get('ad_user') or x.get('come_from')) in mine_keys]

    mine_new = mine_list('new')
    mine_inc = mine_list('increased')
    mine_dec = mine_list('decreased')
    mine_stop = mine_list('stop')

    # 只认报告日前 14 天的回调，不用 /tmp 里更老的残留文件
    hist = g.history_offer_keys(indir, day)
    for it in mine_new:
        oid = str(it['offer_id'])
        k = g.key(it.get('ad_user') or it.get('come_from'))
        it['_label'] = '新单' if (oid, k) not in hist else '重启单'

    n_restart = sum(1 for it in mine_new if it.get('_label') == '重启单')
    n_true_new = sum(1 for it in mine_new if it.get('_label') == '新单')
    n_inc = len(mine_inc)
    n_dec, n_stop = len(mine_dec), len(mine_stop)

    L = []
    L.append(f'【IAA 早报】{day[5:].replace("-", ".")}')
    L.append('')
    L.append('一、当前情况分析')
    L.append('')

    ward = '走强' if delta > 0 else ('走弱' if delta < 0 else '持平')
    L.append(f'〔大盘〕{scope_label(label)}合计 {money(sum_p)} → {money(sum_d)}，{signed_money(delta)}（{pct:+.1f}%），整体{ward}。')

    for k in sorted(mine_keys, key=lambda x: -f_d.get(x, 0)):
        nm = disp.get(k, g.canon(k))
        d, fprev = f_d.get(k, 0), f_p.get(k, 0)
        dd = d - fprev
        pp = (dd / fprev * 100) if fprev else (100 if d > 0 else 0)
        L.append(f'  - {nm} {money(d)}（{signed_money(dd)}，{pp:+.1f}%）')

    L.append('')
    summary_parts = []
    mentioned = set()
    top_k = sorted(mine_keys, key=lambda x: -f_d.get(x, 0))[0]
    top_nm = disp.get(top_k, g.canon(top_k))
    top_d, top_p = f_d.get(top_k, 0), f_p.get(top_k, 0)
    top_pct = (top_d - top_p) / top_p * 100 if top_p else (100 if top_d else 0)
    if abs(top_pct) < 2:
        summary_parts.append(f'头部 {top_nm} 贡献主要流水且基本持平')
    elif top_pct > 0:
        summary_parts.append(f'头部 {top_nm} 贡献主要流水且正涨')
    else:
        summary_parts.append(f'头部 {top_nm} 贡献主要流水但下降')
    mentioned.add(top_k)

    big_drops = []
    for k in mine_keys:
        prev_v = f_p.get(k, 0)
        if prev_v <= 0 or k in mentioned:
            continue
        drop_pct = (f_d.get(k, 0) - prev_v) / prev_v * 100
        if drop_pct <= -15:
            big_drops.append((k, disp.get(k, g.canon(k)), f_d.get(k, 0), prev_v))
    if big_drops:
        drop_text = '、'.join(f'{nm}降幅{(d - p) / p * 100:.0f}%' for k, nm, d, p in big_drops)
        summary_parts.append(f'{drop_text} 是今日显著异常')
        for k, _, _, _ in big_drops:
            mentioned.add(k)

    growers = []
    for k in mine_keys:
        prev_v = f_p.get(k, 0)
        if prev_v <= 0 or k in mentioned:
            continue
        if (f_d.get(k, 0) - prev_v) / prev_v * 100 > 0:
            growers.append(disp.get(k, g.canon(k)))
    if growers:
        summary_parts.append(f'{"、".join(growers)} 正增长')

    L.append('〔整体情况〕' + '；'.join(summary_parts) + '。')
    L.append('')
    L.append('〔预警〕收益 gap（真机 vs 协议 adPrice）')
    L.append(warn_block)
    L.append('')

    group_msgs = fetch_group_messages(CHAT_ID, day)
    override_path = os.path.join(indir, 'root_cause_override.json')
    overrides = {}
    if os.path.exists(override_path):
        try:
            with open(override_path, encoding='utf-8') as f:
                overrides = json.load(f)
        except Exception as e:
            print(f'⚠️ 读取 root_cause_override.json 失败：{e}', file=sys.stderr)
    overrides_lower = {ok.lower(): sanitize(ov) for ok, ov in overrides.items()}
    root_causes = {}
    for k in mine_keys:
        nm = disp.get(k, g.canon(k))
        if nm.lower() in overrides_lower:
            root_causes[k] = overrides_lower[nm.lower()]
            continue
        if k.lower() in overrides_lower:
            root_causes[k] = overrides_lower[k.lower()]
            continue
        rc = find_root_cause(group_msgs, nm, day)
        if rc:
            root_causes[k] = rc

    L.append(f'〔操作〕重启单 {n_restart}、新单 {n_true_new}、加量 {n_inc}、停单/减量 {n_dec + n_stop}。')
    for it in mine_new:
        nm = disp.get(g.key(it.get('ad_user') or it.get('come_from')), g.canon(it.get('ad_user') or it.get('come_from')))
        cv = it.get('conv_delta', 0)
        pl = fnum(it.get('flow_delta', 0))
        item_label = it.get('_label', '重启单')
        L.append(f'  - {nm}：{item_label}（{cv:+d}转化、{signed_money(pl)}）')

    def group_by_client(items):
        out = {}
        for it in items:
            k = g.key(it.get('ad_user') or it.get('come_from'))
            nm = disp.get(k, g.canon(it.get('ad_user') or it.get('come_from')))
            cv = it.get('conv_delta', 0)
            pl = fnum(it.get('flow_delta', 0))
            out.setdefault(nm, []).append((cv, pl, k))
        return out

    for nm, items in group_by_client(mine_inc).items():
        total_cv = sum(c for c, _, _ in items)
        total_pl = sum(p for _, p, _ in items)
        k = items[0][2]
        rc = root_causes.get(k)
        tail = f'  {rc}' if rc else '  系客户主动加量'
        L.append(f'  - {nm}（{total_cv:+d}转化、{signed_money(total_pl)}）{tail}')

    dec_by_client = group_by_client(mine_dec)
    for nm, items in dec_by_client.items():
        total_cv = sum(c for c, _, _ in items)
        total_pl = sum(p for _, p, _ in items)
        k = items[0][2]
        rc = root_causes.get(k)
        rc_text = f'  {rc}' if rc else '  原因待确认'
        L.append(f'  - {nm}（{total_cv:+d}转化、{signed_money(total_pl)}）{rc_text}')

    stop_by_client = group_by_client(mine_stop)
    for nm, items in stop_by_client.items():
        total_cv = sum(c for c, _, _ in items)
        total_pl = sum(p for _, p, _ in items)
        k = items[0][2]
        rc = root_causes.get(k)
        rc_text = f'  {rc}' if rc else '  原因待确认'
        L.append(f'  - {nm}（{total_cv:+d}转化、{signed_money(total_pl)}）{rc_text}')

    L.append('')
    L.append('二、处理思路')
    ideas = []
    seen_clients = set()
    if mine_new:
        ideas.append('重启单/新单恢复，观察量与质量能否稳住；')
    for nm in group_by_client(mine_inc):
        if nm not in seen_clients:
            ideas.append(f'{nm} 客户主动加量，流水正涨，维持并盯 eCPM/留存稳定性；')
            seen_clients.add(nm)

    small_names = []

    def add_move_ideas(grouped, verb):
        for nm, items in grouped.items():
            total_pl = abs(sum(p for _, p, _ in items))
            k = items[0][2]
            rc = root_causes.get(k)
            if total_pl >= 15:
                if verb == '停单':
                    reason = rc if rc else '需确认是客户停投还是掉线'
                    ideas.append(f'{nm} 停单，流水减少{money(total_pl)}，{reason}；')
                elif rc:
                    ideas.append(f'{nm} 下降{money(total_pl)}，{rc}；')
                else:
                    ideas.append(f'{nm} 下降{money(total_pl)}，需排查原因；')
                seen_clients.add(nm)
            else:
                small_names.append(nm)

    add_move_ideas(dec_by_client, '下降')
    add_move_ideas(stop_by_client, '停单')
    if small_names:
        ideas.append('小额波动（<＄15，' + '、'.join(small_names) + '）量级小，先忽略；')

    if not ideas:
        ideas.append('整体平稳，维持现有节奏；')

    for i, idea in enumerate(ideas, 1):
        L.append(f'{i}. {idea}')

    L.append('')
    L.append('三、当前进展')

    big_alert = []
    for k in mine_keys:
        prev_v = f_p.get(k, 0)
        cur_v = f_d.get(k, 0)
        base = prev_v if prev_v else (cur_v if cur_v else 1)
        if cur_v > 0 and (cur_v - prev_v) / base * 100 <= -10:
            big_alert.append(k)
    alert_text = '无下降告警' if not big_alert else '需关注：' + ','.join(disp.get(k, g.canon(k)) for k in big_alert)
    L.append(f'1. {len(mine_keys)} 家整体 {pct:+.1f}%，{alert_text}；')
    progress_idx = 2
    if mine_new or mine_inc:
        L.append(f'{progress_idx}. 新单/重启单/加量均为客户主动加量；')
        progress_idx += 1

    focus = []
    for it in mine_new:
        k = g.key(it.get('ad_user') or it.get('come_from'))
        focus.append(disp.get(k, g.canon(it.get('ad_user') or it.get('come_from'))))
    focus_text = '、'.join(focus) + ' 稳定性' if focus else '维持现有节奏'
    L.append(f'{progress_idx}. 明日重点：{focus_text}。')

    return '\n'.join(L)


def send_comment(task_id, content, as_user):
    bin_path = lark_bin()
    if not bin_path:
        return False, '未找到 lark-cli'
    cmd = [bin_path, 'task', '+comment', '--task-id', task_id, '--content', content, '--as', as_user]
    last = ''
    for attempt in range(3):
        result = subprocess.run(cmd, capture_output=True, text=True)
        last = ((result.stdout or '') + (result.stderr or '')).strip()
        if result.returncode == 0:
            try:
                data = json.loads(result.stdout or '{}')
            except json.JSONDecodeError:
                return True, last
            if data.get('ok') is True or data.get('code') == 0:
                return True, last
            failed = data.get('ok') is False or (isinstance(data.get('code'), int) and data.get('code') != 0)
            if failed:
                err = data.get('error') or {}
                kind = err.get('type') if isinstance(err, dict) else ''
                if kind != 'network':
                    return False, last
            elif 'ok' not in data and 'code' not in data:
                return True, last
        if attempt < 2:
            time.sleep(2)
    return False, last


def main():
    parser = argparse.ArgumentParser(description='发送 IAA 早报')
    parser.add_argument('--task-id', required=True, help='任务 GUID')
    parser.add_argument('--indir', required=True, help='数据目录')
    parser.add_argument('--day', required=True, help='报告日期')
    parser.add_argument('--prev', required=True, help='对比日期')
    parser.add_argument('--as', dest='as_user', default='user', help='身份')
    parser.add_argument('--owner', help='负责人（我/小迪/刘恋/汤倩/赵海/张浩琪）')
    parser.add_argument('--clients', help='逗号分隔的客户名（如"Kookeey,app"），优先级高于 --owner')
    parser.add_argument('--dry-run', action='store_true', help='只打印不发送')
    args = parser.parse_args()

    content = generate_morning_report(args.indir, args.day, args.prev, owner=args.owner, clients=args.clients)

    required_sections = ['当前情况分析', '处理思路', '当前进展']
    errors = validate_format(content, required_sections)

    if errors:
        print('格式校验失败，不发送：')
        for e in errors:
            print(f'  - {e}')
        print(f'\n内容预览：\n{content[:600]}')
        sys.exit(1)

    half = content.count('$')
    full = content.count('＄')
    print(f'✅ 格式校验通过（{len(content)}字，全角＄{full}个，半角${half}个）')

    if args.dry_run or os.environ.get('DRY_RUN'):
        print('===== DRY RUN - 不会发送 =====')
        print(content)
        print('===== END =====')
        return

    ok, detail = send_comment(args.task_id, content, args.as_user)
    if ok:
        print(f'✅ 已发送【IAA 早报】到任务 {args.task_id}')
    else:
        print(f'❌ 发送失败：{detail}')
        sys.exit(1)


if __name__ == '__main__':
    main()
