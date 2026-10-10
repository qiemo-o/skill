#!/bin/bash
# IAA 晚报入口。
# 用法: run.sh [--owner 负责人] [--clients a,b] [--day YYYY-MM-DD] [--cut 19] [--task-id GUID] [--dry-run]
# 负责人不是「我/小迪/刘恋」时必须传 --task-id。

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_DIR="$(cd "$SCRIPT_DIR/../../iaa-ops-daily-report" && pwd)"
TASK_GUID="934c7ff3-74a6-480c-b90d-6a25a00f371f"
TASK_SET=0
INDIR="/tmp/ops"
OWNER="我"
CLIENTS=""
DAY=""
PREV=""
CUT=""
DRY_RUN="${DRY_RUN:-}"
HIST_DAYS=14

while [[ $# -gt 0 ]]; do
    case "$1" in
        --owner) OWNER="$2"; shift 2 ;;
        --clients) CLIENTS="$2"; shift 2 ;;
        --day) DAY="$2"; shift 2 ;;
        --prev) PREV="$2"; shift 2 ;;
        --cut) CUT="$2"; shift 2 ;;
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
    DAY="$(python3 -c "import datetime; print(datetime.date.today().isoformat())")"
fi
if [ -z "$PREV" ]; then
    PREV="$(python3 -c "import datetime,sys; print((datetime.date.fromisoformat(sys.argv[1]) - datetime.timedelta(days=1)).isoformat())" "$DAY")"
fi

case "$OWNER" in
    我|小迪|刘恋) ;;
    *)
        if [ "$TASK_SET" != "1" ]; then
            echo "错误: 负责人「${OWNER}」的报告不能发到小迪的默认任务。请加 --task-id <你的任务GUID>。"
            exit 1
        fi
        ;;
esac

mkdir -p "$INDIR"
HIST_START="$(python3 -c "import datetime,sys; print((datetime.date.fromisoformat(sys.argv[1]) - datetime.timedelta(days=int(sys.argv[2]))).isoformat())" "$DAY" "$HIST_DAYS")"

echo "=== IAA 晚报 ==="
echo "报告日期: $DAY (对比 $PREV)"
echo "负责人: $OWNER"
if [ -n "$CLIENTS" ]; then
    echo "客户: $CLIENTS"
fi
if [ -n "$CUT" ]; then
    echo "数据截止: ${CUT}:00"
fi
echo ""

echo "[1/3] 拉取数据..."
python3 "$SKILL_DIR/scripts/fetch_data.py" \
    --start "$PREV" \
    --end "$DAY" \
    --outdir "$INDIR" \
    --force
python3 "$SKILL_DIR/scripts/fetch_data.py" \
    --start "$HIST_START" \
    --end "$PREV" \
    --outdir "$INDIR" \
    --types wm_all_callback \
    --lenient

echo ""
echo "[2/3] 生成晚报..."
args=(--day "$DAY" --prev "$PREV" --indir "$INDIR" --owner "$OWNER")
if [ -n "$CUT" ]; then
    args+=(--cut "$CUT")
fi
if [ -n "$CLIENTS" ]; then
    args+=(--clients "$CLIENTS")
fi
CONTENT="$(python3 "$SKILL_DIR/scripts/evening_report.py" "${args[@]}")"

if ! echo "$CONTENT" | grep -q "【IAA 晚报"; then
    echo "格式校验失败：标题必须以【IAA 晚报】开头"
    echo "内容预览："
    echo "$CONTENT" | head -20
    exit 1
fi

if echo "$CONTENT" | grep -q '\$'; then
    echo "格式校验失败：发现半角\$（飞书会吞字）"
    echo "内容预览："
    echo "$CONTENT" | head -20
    exit 1
fi

FULL_COUNT="$(echo "$CONTENT" | grep -o '＄' | wc -l)"
echo "格式校验通过（全角＄${FULL_COUNT}个）"

if [ -n "$DRY_RUN" ]; then
    echo ""
    echo "===== DRY RUN - 不会发送 ====="
    echo "$CONTENT"
    echo "===== END ====="
else
    echo ""
    echo "[3/3] 发送到任务..."
    LARK_BIN="${LARK_CLI:-}"
    if [ -z "$LARK_BIN" ]; then
        LARK_BIN="$(command -v lark-cli || true)"
    fi
    if [ -z "$LARK_BIN" ] && [ -x /home/claw/.local/bin/lark-cli ]; then
        LARK_BIN="/home/claw/.local/bin/lark-cli"
    fi
    if [ -z "$LARK_BIN" ]; then
        echo "未找到 lark-cli"
        exit 1
    fi
    "$LARK_BIN" task +comment \
        --task-id "$TASK_GUID" \
        --content "$CONTENT" \
        --as user
    echo ""
    echo "=== 晚报发送完成 ==="
fi
