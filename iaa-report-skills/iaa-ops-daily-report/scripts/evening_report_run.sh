#!/usr/bin/env bash
# IAA 晚报一键：拉数后打印白天场复盘，不发送。
# 拉数失败会停。不传 CUT 时，脚本自己把白天场截止在 19 点以内。
# env: DAY PREV CUT NAME_PCT INDIR OWNER CLIENTS
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INDIR="${INDIR:-/tmp/ops}"
mkdir -p "$INDIR"
DAY="${DAY:-$(python3 -c "import datetime; print(datetime.date.today().isoformat())")}"
PREV="${PREV:-$(python3 -c "import datetime,sys; print((datetime.date.fromisoformat(sys.argv[1]) - datetime.timedelta(days=1)).isoformat())" "$DAY")}"
HIST_START="$(python3 -c "import datetime,sys; print((datetime.date.fromisoformat(sys.argv[1]) - datetime.timedelta(days=14)).isoformat())" "$DAY")"

python3 "$HERE/fetch_data.py" --start "$PREV" --end "$DAY" --outdir "$INDIR" --force
python3 "$HERE/fetch_data.py" --start "$HIST_START" --end "$PREV" --outdir "$INDIR" --types wm_all_callback --lenient

args=(--day "$DAY" --prev "$PREV" --indir "$INDIR" --owner "${OWNER:-我}" --name-pct "${NAME_PCT:-10}")
if [ -n "${CUT:-}" ]; then
    args+=(--cut "$CUT")
fi
if [ -n "${CLIENTS:-}" ]; then
    args+=(--clients "$CLIENTS")
fi
python3 "$HERE/evening_report.py" "${args[@]}"
