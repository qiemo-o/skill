# IAA 早报 Skill

生成 IAA 运营早报（三段式：当前情况分析 → 处理思路 → 当前进展），自动拉数据、生成报告、发送到飞书任务评论。

## 触发词

- "生成 IAA 早报"
- "跑早报"
- "今天的 IAA 早报"

## 使用方式

### 1. 按负责人名字（推荐）

```
"我是赵海，帮我生成今天的 IAA 早报"
"跑下汤倩的 IAA 早报"
```

AI 自动从 `owner_of` 映射找到该负责人的所有客户。

### 2. 手动指定客户

```
"我负责 Kookeey 和 app，生成早报"
"跑 GasTech、leap4vision 的早报"
```

AI 用 `--clients Kookeey,app` 参数。

### 3. 默认（小迪的 5 家）

```
"生成 IAA 早报"
```

默认生成小迪负责的 5 家客户（Kookeey/app/GasTech/leap4vision/MB）。

## 负责人映射

| 负责人 | 客户 |
|---|---|
| 我（小迪/刘恋） | Kookeey*、app、GasTech、leap4vision、MB |
| 汤倩 | Autumn/Autumn1、selfCChange |
| 赵海 | Adprojec、BidMatrix、leanmobi、Streamly、insightPlus* |
| 张浩琪 | hivexads、keke（含 keke2） |

## 参数

- `--owner <名字>`：负责人（"我"/"汤倩"/"赵海"/"张浩琪"）
- `--clients <列表>`：逗号分隔的客户名（如 `Kookeey,app`），优先级高于 `--owner`
- `--day <YYYY-MM-DD>`：报告日期（不传则昨天）
- `--prev <YYYY-MM-DD>`：对比日期（不传则报告日前一天）
- `--task-id <GUID>`：飞书任务 GUID（默认小迪的 t103123）。负责人是汤倩/赵海/张浩琪时必填，否则拒绝发送
- `--dry-run`：只打印不发送
- 重启单只认报告日前 14 天的回调

## 流程

1. 拉数据（`fetch_data.py`）
2. 算操作（`build_report.py`）
3. 生成早报（`morning_report.py`，含群消息根因提取）
4. 格式校验（全角＄、必需段落）
5. 发送到飞书任务评论

## 数据源

- Report API: `http://122.9.58.86:38087`
- 凭据: `/home/claw/.config/report-api/creds.env`
- 数据目录: `/tmp/ops`

## 关键规则

- 转化口径: `channel=4580` 且 `event_name` 空 且 `blocked_sub_reason` 空 且 `come_from` 非空
- 操作门槛: |Δ转化数| ≥ 10
- 外部转化(MY2/HHKK)必须合并到自有转化再分类
- 金额用全角＄（飞书防吞字）
- 三段标题: "一、当前情况分析" "二、处理思路" "三、当前进展"

## 已知坑

- 半角 `$` 会被飞书吞字，必须用全角 `＄`
- 根因从 wmyy 群消息提取，排除日报/早报本身
- 操作按客户合并，不重复显示同一客户

## 示例

```bash
# 小迪的 5 家
./scripts/run.sh --owner 我 --day 2026-10-09

# 汤倩的客户
./scripts/run.sh --owner 汤倩 --day 2026-10-09

# 手动指定
./scripts/run.sh --clients Kookeey,app --day 2026-10-09

# 测试模式
./scripts/run.sh --owner 我 --day 2026-10-09 --dry-run
```
