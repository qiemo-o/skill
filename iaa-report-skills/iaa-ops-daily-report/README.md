# IAA 运营日常汇报 skill

把一天的 IAA 投放操作 + 流水变化，整理成给运营负责人看的**三段式汇报**（当前情况分析〔含操作明细〕→ 处理思路 → 当前进展），确认后发到飞书任务评论。

> 面向"人读的运营叙事"，与生产日报 `iaa-daily-report`（CPI/ROI 数据看板自动推群）不同。

## 流程
```
拉数据 (fetch_data.py) → 算操作打底 (build_report.py) → 读运营群补原因 → 套三段式模板 → 人工确认 → 发任务评论
```

## 目录
- `SKILL.md` — 技能主体：流程、字段口径、操作分类口径、已知坑、交接给组员的说明。
- `scripts/fetch_data.py` — 从 Report API 拉 4 路源数据（自有回调 / 排班任务 / HHKK / MY2）。
- `scripts/build_report.py` — 按 `(offer,客户)` diff **实际转化数**、算新/停/加/减与流水影响，输出可核对底稿。
- `references/report_template.md` — 三段式模板（情况分析含【大盘】/【操作】）+ 已确认填充示例。
- `references/test_plan.md` — 开发计划与 TC 测试用例（含独立验证步骤）。

## 快速开始
```bash
# 凭据：/home/claw/.config/report-api/creds.env（不入库）
python3 scripts/fetch_data.py   --start 2026-09-22 --end 2026-09-23 --outdir /tmp/ops
python3 scripts/build_report.py --day 2026-09-23 --indir /tmp/ops --json /tmp/ops/ops_report.json
# 再读运营群补原因 → 按 references/report_template.md 产出草稿 → 确认 → 发任务评论
```

## 口径要点（详见 SKILL.md）
- 混合口径：数据 diff 打底（可复现）+ 运营群播报修正原因；冲突以群为准并标注。
- 分类判定 = **实际转化数**（回调 `channel=4580 且 无 event_name 且 未 blocked`），门槛 ±10；流水 = 转化行 `payout`。头条 = 自有转化 payout + 外部 payout(clickid 去重)。
- 展示：广告主第一、offer 仅流水 ≥$15 才点名、转化每类标一次、③④ 段 1/2/3/4 编号（详见 `references/report_template.md`）。
- 已知：人肉版操作数无法被纯数据 diff 精确复现，本 skill 定位是"打底+可核对"，非复刻。
