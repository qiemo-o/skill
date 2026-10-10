# IAA 晚报 Skill

生成 IAA 运营晚报（白天场复盘，三段式：当前情况分析 → 处理思路 → 当前进展），自动拉数据、生成报告、发送到飞书任务评论。

## 触发词

- "生成 IAA 晚报"
- "跑晚报"
- "IAA 晚报"
- "今天的 IAA 晚报"

## 使用方式

### 1. 按负责人名字（推荐）

```
"我是赵海，帮我生成今天的 IAA 晚报"
"跑下汤倩的 IAA 晚报"
```

AI 自动从 `owner_of` 映射找到该负责人的所有客户。

### 2. 手动指定客户

```
"我负责 Kookeey 和 app，生成晚报"
```

AI 用 `--clients Kookeey,app` 参数。

### 3. 默认（小迪的 5 家）

```
"生成 IAA 晚报"
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

- `--owner <名字>`：负责人（默认"我"，也认小迪/刘恋）
- `--clients <列表>`：逗号分隔的客户名，优先级高于 `--owner`
- `--day <YYYY-MM-DD>`：报告日期（默认今天）
- `--prev <YYYY-MM-DD>`：对比日期（默认昨天）
- `--cut <小时>`：数据截止小时。不传则取 min(最大小时+1, 19)，白天场不会把晚场算进去
- `--task-id <GUID>`：飞书任务 GUID（默认小迪的 t103123）。负责人是汤倩/赵海/张浩琪时必填
- `--dry-run`：只打印不发送

## 特点

- **白天场复盘**：截至当日已入库的最大小时，对比昨日同时段
- **不做全天定论**：晚场未跑完，只呈现白天数据
- **CAP 跑满率**：自有转化 ÷ pidPbLimitCount(每offer取max)
- **失效未跑**：有 cap 但转化=0 的 offer
- **被拒率**：只统计本次客户的 channel 4580 blocked 占比
- **0 收益包**：只统计本次客户

## 流程

1. 拉数据（`fetch_data.py`）
2. 生成晚报（`evening_report.py`，含 CAP/失效/被拒分析）
3. 格式校验（全角＄、必需段落）
4. 发送到飞书任务评论

## 示例

```bash
# 小迪的 5 家（默认）
./scripts/run.sh --day 2026-10-10

# 汤倩的客户
./scripts/run.sh --owner 汤倩 --day 2026-10-10

# 赵海的客户
./scripts/run.sh --owner 赵海 --day 2026-10-10

# 测试模式
./scripts/run.sh --owner 我 --day 2026-10-10 --dry-run
```
