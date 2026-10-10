#!/usr/bin/env bash
# 一键：拉「昨日 + 前日」IAA 数据 → 跑 daily_flow_group.py → 打印群日报文本。
# 日期默认 T-1 vs T-2；可用 DAY=YYYY-MM-DD PREV=YYYY-MM-DD 覆盖。
set -euo pipefail
SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
INDIR="${INDIR:-/tmp/ops}"
DAY="${DAY:-$(date -d 'yesterday' +%F)}"
PREV="${PREV:-$(date -d "${DAY} -1 day" +%F)}"
DROP="${DROP:-30}"

python3 "$SKILL_DIR/scripts/fetch_data.py" --start "$PREV" --end "$DAY" --outdir "$INDIR" >/dev/null 2>&1 || true
python3 "$SKILL_DIR/scripts/daily_flow_group.py" --day "$DAY" --prev "$PREV" --indir "$INDIR" --drop "$DROP"
