#!/bin/bash
# IAA 早报入口。
# 用法: run.sh [--owner 负责人] [--clients a,b] [--day YYYY-MM-DD] [--task-id GUID] [--dry-run]
# 不传 --day 时报告日是昨天。负责人不是「我/小迪/刘恋」时必须传 --task-id。

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_DIR="$(cd "$SCRIPT_DIR/../../iaa-ops-daily-report" && pwd)"
TASK_GUID="934c7ff3-74a6-480c-b90d-6a25a00f371f"
TASK_SET=0
INDIR="/tmp/ops"
OWNER=""
CLIENTS=""
DAY=""
PREV=""
DRY_RUN="${DRY_RUN:-}"
HIST_DAYS=14

while [[ $# -gt 0 ]]; do
    case "$1" in
        --owner) OWNER="$2"; shift 2 ;;
        --clients) CLIENTS="$2"; shift 2 ;;
        --day) DAY="$2"; shift 2 ;;
        --prev) PREV="$2"; shift 2 ;;
        --task-id) TASK_GUID="$2"; TASK_SET=1; shift 2 ;;
        --indir) INDIR="$2"; shift 2 ;;
        --dry-run) DRY_RUN=1; shift ;;
        *)
            echo "未知参数: $1"
            exit 1
            ;;
    esac
done

if [ -z "$DAY" ]; then
    DAY="$(python3 -c "import datetime; print((datetime.date.today() - datetime.timedelta(days=1)).isoformat())")"
fi
if [ -z "$PREV" ]; then
    PREV="$(python3 -c "import datetime,sys; print((datetime.date.fromisoformat(sys.argv[1]) - datetime.timedelta(days=1)).isoformat())" "$DAY")"
fi

case "$OWNER" in
    ""|我|小迪|刘恋) ;;
    *)
        if [ "$TASK_SET" != "1" ]; then
            echo "错误: 负责人「${OWNER}」的报告不能发到小迪的默认任务。请加 --task-id <你的任务GUID>。"
            exit 1
        fi
        ;;
esac

if [ -z "$OWNER" ] && [ -z "$CLIENTS" ]; then
    OWNER="我"
fi

mkdir -p "$INDIR"
HIST_START="$(python3 -c "import datetime,sys; print((datetime.date.fromisoformat(sys.argv[1]) - datetime.timedelta(days=int(sys.argv[2]))).isoformat())" "$DAY" "$HIST_DAYS")"

echo "=== IAA 早报 ==="
echo "报告日期: $DAY (对比 $PREV)"
if [ -n "$OWNER" ]; then
    echo "负责人: $OWNER"
fi
if [ -n "$CLIENTS" ]; then
    echo "客户: $CLIENTS"
fi
echo ""

echo "[1/4] 拉取数据..."
python3 "$SKILL_DIR/scripts/fetch_data.py" \
    --start "$PREV" \
    --end "$DAY" \
    --outdir "$INDIR" \
    --force
# 重启单判定需要报告日前的回调。旧日期缺失只警告，不挡住今天的早报。
python3 "$SKILL_DIR/scripts/fetch_data.py" \
    --start "$HIST_START" \
    --end "$PREV" \
    --outdir "$INDIR" \
    --types wm_all_callback \
    --lenient

echo ""
echo "[2/4] 算操作..."
python3 "$SKILL_DIR/scripts/build_report.py" \
    --day "$DAY" \
    --prev "$PREV" \
    --indir "$INDIR" \
    --json "$INDIR/ops_report.json"

echo ""
echo "[3/4] 生成早报..."
args=(--task-id "$TASK_GUID" --indir "$INDIR" --day "$DAY" --prev "$PREV" --as user)
if [ -n "$OWNER" ]; then
    args+=(--owner "$OWNER")
fi
if [ -n "$CLIENTS" ]; then
    args+=(--clients "$CLIENTS")
fi
if [ -n "$DRY_RUN" ]; then
    args+=(--dry-run)
fi
python3 "$SKILL_DIR/scripts/morning_report.py" "${args[@]}"

echo ""
echo "[4/4] 完成!"
