# IAA 报告 Skill 使用说明

给组员使用的 IAA 早报/晚报自动生成工具。

---

## 一、IAA 早报 Skill

### 功能
自动生成 IAA 运营早报（三段式：当前情况分析 → 处理思路 → 当前进展），包含：
- 大盘流水环比
- 分客户流水明细
- 操作分类（新单/重启单/加量/减量/停单）
- 根因分析（从 wmyy 群消息自动提取）
- 收益 gap 预警

### 触发词
对 AI 说：
- "生成 IAA 早报"
- "跑早报"
- "今天的 IAA 早报"

### 使用方式

#### 方式 1：按负责人名字（推荐）
```
"我是赵海，帮我生成今天的 IAA 早报"
"跑下汤倩的 IAA 早报"
```
AI 自动从映射表找到你负责的客户。

#### 方式 2：手动指定客户
```
"我负责 Kookeey 和 app，生成早报"
"跑 GasTech、leap4vision 的早报"
```

#### 方式 3：默认（小迪的 5 家）
```
"生成 IAA 早报"
```
默认生成小迪负责的 5 家客户。

### 负责人映射表

| 负责人 | 客户 |
|---|---|
| **我（小迪/刘恋）** | Kookeey*、app、GasTech、leap4vision、MB |
| **汤倩** | Autumn/Autumn1、selfCChange |
| **赵海** | Adprojec、BidMatrix、leanmobi、Streamly、insightPlus* |
| **张浩琪** | hivexads、keke（含 keke2） |

### 参数说明

| 参数 | 说明 | 示例 |
|---|---|---|
| `--owner` | 负责人名字 | `--owner 赵海` |
| `--clients` | 逗号分隔的客户名 | `--clients Kookeey,app` |
| `--day` | 报告日期，不传则昨天 | `--day 2026-10-09` |
| `--prev` | 对比日期，不传则报告日前一天 | `--prev 2026-10-08` |
| `--task-id` | 飞书任务 GUID。负责人不是我/小迪/刘恋时必填 | 默认小迪的任务 |
| `--dry-run` | 只打印不发送 | 测试用 |

### 命令行示例
```bash
# 赵海的早报
./iaa-morning-report/scripts/run.sh --owner 赵海 --day 2026-10-09

# 汤倩的早报
./iaa-morning-report/scripts/run.sh --owner 汤倩 --day 2026-10-09

# 手动指定客户
./iaa-morning-report/scripts/run.sh --clients Kookeey,app --day 2026-10-09

# 测试模式（只打印不发送）
DRY_RUN=1 ./iaa-morning-report/scripts/run.sh --owner 我 --day 2026-10-09
```

---

## 二、IAA 晚报 Skill

### 功能
自动生成 IAA 运营晚报（白天场复盘），包含：
- 白天场流水环比（截至数据最大小时）
- 分客户流水明细
- CAP 跑满率分析
- 失效未跑 offer（有 cap 但转化=0）
- 被拒率统计
- 0 收益包检查

### 触发词
对 AI 说：
- "生成 IAA 晚报"
- "跑晚报"
- "IAA 晚报"

### 使用方式

#### 方式 1：按负责人名字（推荐）
```
"我是赵海，帮我生成今天的 IAA 晚报"
"跑下汤倩的 IAA 晚报"
```

#### 方式 2：默认（小迪的 5 家）
```
"生成 IAA 晚报"
```

### 参数说明

| 参数 | 说明 | 示例 |
|---|---|---|
| `--owner` | 负责人名字（默认"我"） | `--owner 赵海` |
| `--clients` | 逗号分隔的客户名，优先级高于 `--owner` | `--clients Kookeey,app` |
| `--day` | 报告日期（默认今天） | `--day 2026-10-10` |
| `--cut` | 数据截止小时。不传则不超过 19 点 | `--cut 19`（0-18 点） |
| `--task-id` | 飞书任务 GUID。负责人不是我/小迪/刘恋时必填 | 默认小迪的任务 |
| `--dry-run` | 只打印不发送 | 测试用 |

### 命令行示例
```bash
# 赵海的晚报
./iaa-evening-report/scripts/run.sh --owner 赵海 --day 2026-10-10

# 汤倩的晚报
./iaa-evening-report/scripts/run.sh --owner 汤倩 --day 2026-10-10

# 指定数据截止时间（晚报通常 --cut 19 即 0-18 点）
./iaa-evening-report/scripts/run.sh --owner 我 --day 2026-10-10 --cut 19

# 测试模式
DRY_RUN=1 ./iaa-evening-report/scripts/run.sh --owner 我 --day 2026-10-10
```

---

## 三、报告格式说明

### 早报格式（三段式）

```
【IAA 早报】MM.DD

一、当前情况分析

〔大盘〕负责客户合计 ＄X → ＄Y，±＄Z（±X%），整体走强/走弱/持平。
  - 客户A ＄X（±＄Y，±X%）
  - 客户B ＄X（±＄Y，±X%）

〔整体情况〕头部客户贡献主要流水...

〔预警〕收益 gap（真机 vs 协议 adPrice）
  - 客户A：真机X vs 协议Y，gap Z% >2%

〔操作〕重启单 N、新单 N、加量 N、停单/减量 N。
  - 客户A：重启单（+X转化、+＄Y）
  - 客户B（+X转化、+＄Y）  系客户主动加量
  - 客户C（-X转化、-＄Y）  根因：...

二、处理思路
1. ...
2. ...

三、当前进展
1. ...
2. ...
```

### 晚报格式（白天场复盘）

```
【IAA 晚报 · 白天场复盘】MM.DD（截至 N:00，数据覆盖 0–N:59，晚场未跑完，不做全天定论）

一、当前情况分析（白天场数据，晚场未计入）

【大盘】 负责客户白天场合计：＄X → ＄Y，上升/下降 ±＄Z（±X%）

【分客户】（按今日流水降序，同比昨日同时段）
  - 客户A ＄X → ＄Y ±＄Z（±X%）

【消耗与 CAP】
  - 跑满率（<99% 记为未跑满，≥99% 记为跑满）：...
  - 今日失效未跑（有 cap、转化=0）：...

【风控】 被拒率...；白天 0 收益包...

二、处理思路（白天归因 + 晚场策略）
1. ...
2. ...

三、当前进展（白天执行结果 + 晚班/明日重点）
1. ...
2. ...
```

---

## 四、关键规则

### 转化口径
- `channel=4580`（AOS）
- `event_name` 为空
- `blocked_sub_reason` 为空
- `come_from` 非空

### 操作门槛
- 早报：|Δ转化数| ≥ 10 才算一次操作
- 晚报白天新单：同时段转化 ≥ 5（窗口不满一天）
- 重启单只认报告日前 14 天内出现过的 offer，不看 `/tmp` 里更早的残留文件

### 金额格式
- **必须用全角＄**（飞书防吞字），不能用半角 `$`

### 外部转化合并
- MY2/HHKK 外部转化必须合并到自有转化再分类
- Key 归一：Kookeey5 → Kookeey

---

## 五、数据源

- Report API: `http://122.9.58.86:38087`
- 凭据: `/home/claw/.config/report-api/creds.env`
- 数据目录: `/tmp/ops`

---

## 六、常见问题

### Q: 为什么报告里没有我的客户？
A: 检查客户名是否正确匹配映射表。可以用 `--clients` 手动指定。

### Q: 如何修改发送到哪个任务？
A: 用 `--task-id <你的任务GUID>`。负责人不是我/小迪/刘恋时，这个参数必填，否则不会发到小迪的任务里。

### Q: 如何只看不发送？
A: 加 `--dry-run` 参数或设置环境变量 `DRY_RUN=1`。

### Q: 群消息里没有根因怎么办？
A: 报告会标"原因待确认"，可以手动编辑或创建 `root_cause_override.json` 覆盖。

---

## 七、文件位置

仓库根目录就是这三份 skill。入口脚本用自己的相对路径找 `iaa-ops-daily-report`，不写死机器上的目录。装到 claw 上时同样是这层结构：

```
/home/claw/work-main/.claude/skills/
├── iaa-morning-report/
│   ├── SKILL.md              # Skill 说明
│   └── scripts/
│       └── run.sh            # 早报入口脚本
├── iaa-evening-report/
│   ├── SKILL.md              # Skill 说明
│   └── scripts/
│       └── run.sh            # 晚报入口脚本
└── iaa-ops-daily-report/
    └── scripts/
        ├── fetch_data.py     # 拉数据
        ├── build_report.py   # 算操作
        ├── morning_report.py # 早报生成
        └── evening_report.py # 晚报生成
```

---

## 八、联系

有问题找小迪（刘恋）。
