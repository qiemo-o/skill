#!/usr/bin/env bash
# 生成 IAA 每日流水环比日报 → 用 bot 身份发送到「日报AI群」。
# 成功静默(不打扰触发它的会话)，失败才打印原因。日期默认 T-1 vs T-2。
set -uo pipefail
SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
INDIR="${INDIR:-/tmp/ops}"
CHAT="${CHAT:-oc_c5691378120c2e2f4abffe03d54b42cb}"   # wmyy 运营群（2026-09-29 小迪改：日报发 wmyy，不再发日报AI群）
DAY="${DAY:-$(date -d 'yesterday' +%F)}"
PREV="${PREV:-$(date -d "${DAY} -1 day" +%F)}"
DROP="${DROP:-30}"

TMP="$(mktemp)"
# --force：早晨 T-1 已结算完整，但可能残留当天的残缺快照文件，必须重拉覆盖
python3 "$SKILL_DIR/scripts/fetch_data.py" --start "$PREV" --end "$DAY" --outdir "$INDIR" --force >/dev/null 2>&1 || true
python3 "$SKILL_DIR/scripts/daily_flow_group.py" --day "$DAY" --prev "$PREV" --indir "$INDIR" --drop "$DROP" --at tag > "$TMP" 2>"$TMP.err"
if [ ! -s "$TMP" ]; then
  echo "日报生成失败 $DAY vs $PREV：$(cat "$TMP.err" 2>/dev/null | tail -3)"; rm -f "$TMP" "$TMP.err"; exit 1
fi

python3 - "$CHAT" "$TMP" <<'PY'
import subprocess,sys,json,time
chat,path=sys.argv[1],sys.argv[2]
msg=open(path,encoding='utf-8').read().strip()
ok=False; last=''
for _ in range(10):
    p=subprocess.run(['lark-cli','im','+messages-send','--chat-id',chat,'--text',msg,'--as','bot'],capture_output=True,text=True)
    try: d=json.loads(p.stdout)
    except Exception: time.sleep(2); continue
    if d.get('ok'): ok=True; break
    e=d.get('error',{}) or {}
    last=json.dumps(e,ensure_ascii=False)[:200]
    if e.get('type')!='network': break
    time.sleep(2)
import os
os.remove(path)
if not ok:
    print(f"发送到日报AI群失败 {chat}: {last}"); sys.exit(1)
PY
rm -f "$TMP.err"
