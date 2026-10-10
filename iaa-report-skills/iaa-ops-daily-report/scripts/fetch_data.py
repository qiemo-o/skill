#!/usr/bin/env python3
"""拉取 IAA 数据源到本地（与生产日报同源）。

用法:
  python3 fetch_data.py --start 2026-09-14 --end 2026-09-23 [--outdir /tmp] [--force]
  python3 fetch_data.py --start ... --end ... --types wm_all_callback --lenient

产出文件（命名与生产一致）:
  {outdir}/wm_all_callback_{YYYYMMDD}.ndjson   自有回调(channel=4580, 含 utcdate)
  {outdir}/wm_iaasdk_task_{YYYYMMDD}.ndjson    任务排班(offer/cap/时段)
  {outdir}/iaa_call_{YYYYMMDD}.csv             HHKK 外部转化
  {outdir}/iaasdklab_call_{YYYYMMDD}.csv       MY2 外部转化
"""
import argparse, datetime, json, os, sys, time, urllib.request

API_BASE = 'http://122.9.58.86:38087'
CREDS_FILE = '/home/claw/.config/report-api/creds.env'
NDJSON_TYPES = ['wm_all_callback', 'wm_iaasdk_task']
CSV_TYPES = ['iaa_call', 'iaasdklab_call', 'iaasdklab_advphone', 'iaasdklab_advxieyi']


def load_creds():
    creds = {}
    for line in open(CREDS_FILE):
        m = line.strip()
        if '=' in m and not m.startswith('#'):
            k, v = m.split('=', 1)
            creds[k] = v
    return creds.get('REPORT_API_USER'), creds.get('REPORT_API_PASS')


def post(url, payload, token=None, timeout=180):
    data = json.dumps(payload).encode()
    req = urllib.request.Request(url, data, {'Content-Type': 'application/json'})
    if token:
        req.add_header('Token', token)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def get_token():
    user, pwd = load_creds()
    body = json.loads(post(API_BASE + '/report/auth/getToken', {'username': user, 'password': pwd}))
    if body.get('code') != 1:
        sys.exit(f'Token 失败: {body.get("msg")}')
    return body['data']['token']


def daterange(a, b):
    d0 = datetime.date.fromisoformat(a)
    d1 = datetime.date.fromisoformat(b)
    while d0 <= d1:
        yield d0.isoformat()
        d0 += datetime.timedelta(days=1)


def ndjson_ok(raw):
    """一行业务 JSON 才算数。接口错误体（带 code、没有业务字段）不算。"""
    s = raw.lstrip()
    if not s or s[:1] not in (b'{', b'['):
        return False
    first = s.splitlines()[0]
    if b'"code"' in first and b'offer_id' not in first and b'come_from' not in first and b'ad_user' not in first:
        return False
    return True


def csv_ok(raw):
    """空表（只有标题）仍是成功。JSON 错误体不是 CSV。"""
    s = raw.lstrip()
    if not s or s[:1] in (b'{', b'['):
        return False
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--start', required=True, help='YYYY-MM-DD')
    ap.add_argument('--end', required=True, help='YYYY-MM-DD')
    ap.add_argument('--outdir', default='/tmp')
    ap.add_argument('--force', action='store_true', help='忽略已有文件强制重拉')
    ap.add_argument('--types', default='', help='逗号分隔，只拉这些类型，如 wm_all_callback')
    ap.add_argument('--lenient', action='store_true', help='单日失败只警告，不让整个任务失败（用于补历史）')
    a = ap.parse_args()

    os.makedirs(a.outdir, exist_ok=True)
    want = [t.strip() for t in a.types.split(',') if t.strip()]
    known = NDJSON_TYPES + CSV_TYPES
    bad = [t for t in want if t not in known]
    if bad:
        sys.exit(f'未知类型: {",".join(bad)}')
    nd_types = [t for t in NDJSON_TYPES if not want or t in want]
    csv_types = [t for t in CSV_TYPES if not want or t in want]

    token = get_token()
    ok, fail = 0, 0
    for d in daterange(a.start, a.end):
        y = d.replace('-', '')
        for t in nd_types:
            fn = os.path.join(a.outdir, f'{t}_{y}.ndjson')
            if os.path.exists(fn) and os.path.getsize(fn) > 0 and not a.force:
                ok += 1
                continue
            try:
                raw = post(API_BASE + '/report/data/export',
                           {'type': t, 'date': d, 'format': 'ndjson', 'chunk': 5000}, token)
                with open(fn, 'wb') as f:
                    f.write(raw)
                if not ndjson_ok(raw):
                    print(f'  ⚠️ {t}_{y} 响应不是 ndjson: {raw[:80]!r}')
                    try:
                        os.remove(fn)
                    except OSError:
                        pass
                    if not a.lenient:
                        fail += 1
                else:
                    ok += 1
            except Exception as e:
                print(f'  ❌ {t}_{y}: {e}')
                if not a.lenient:
                    fail += 1
        for t in csv_types:
            fn = os.path.join(a.outdir, f'{t}_{y}.csv')
            if os.path.exists(fn) and os.path.getsize(fn) > 0 and not a.force:
                ok += 1
                continue
            try:
                raw = post(API_BASE + '/report/wmdata/export',
                           {'type': t, 'format': 'csv', 'chunk': 5000, 'startDate': d, 'endDate': d}, token)
                with open(fn, 'wb') as f:
                    f.write(raw)
                if not csv_ok(raw):
                    print(f'  ⚠️ {t}_{y} 响应不是 CSV: {raw[:80]!r}')
                    try:
                        os.remove(fn)
                    except OSError:
                        pass
                    if not a.lenient:
                        fail += 1
                else:
                    ok += 1
                    if len(raw.splitlines()) < 3:
                        print(f'  ⚠️ {t}_{y} 无数据行（按空表处理）')
            except Exception as e:
                print(f'  ❌ {t}_{y}: {e}')
                if not a.lenient:
                    fail += 1
        time.sleep(0.3)
    print(f'拉取完成: ok={ok} fail={fail} outdir={a.outdir}')
    sys.exit(1 if fail else 0)


if __name__ == '__main__':
    main()
