#!/usr/bin/env bash
# 旧早报入口。转调 iaa-morning-report/scripts/run.sh，避免两套生成逻辑。
# 不传 DAY 时报告日是昨天。拉数失败会停，不会拿上次的 ops_report.json 接着发。
# env: DAY PREV INDIR TASK_GUID OWNER DRY_RUN
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RUN="$(cd "$HERE/../../iaa-morning-report/scripts" && pwd)/run.sh"

args=(--owner "${OWNER:-我}")
if [ -n "${DAY:-}" ]; then
    args+=(--day "$DAY")
fi
if [ -n "${PREV:-}" ]; then
    args+=(--prev "$PREV")
fi
if [ -n "${INDIR:-}" ]; then
    args+=(--indir "$INDIR")
fi
if [ -n "${TASK_GUID:-}" ]; then
    args+=(--task-id "$TASK_GUID")
fi
if [ -n "${DRY_RUN:-}" ]; then
    args+=(--dry-run)
fi

exec bash "$RUN" "${args[@]}"
