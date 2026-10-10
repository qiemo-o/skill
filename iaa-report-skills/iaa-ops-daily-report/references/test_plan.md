# 运营日常汇报 skill · 开发计划与测试用例

## 一、分阶段开发计划

| 阶段 | 产出 | 状态 |
|---|---|---|
| P1 拉数 | `fetch_data.py`（4 源，凭据外置） | ✅ |
| P2 模板 | `references/report_template.md`（三段式 + 9.27 示例） | ✅ |
| P3 骨架 | `SKILL.md` 正文（流程/口径/坑） | ✅ |
| P4 算操作 | `build_report.py`（打底分类 + 流水影响 + 包级 Top） | ✅ |
| P5 读群修正 | LLM 步骤（非脚本）：拉运营群消息→补根因/校准群口径 |  流程已写入 SKILL，无独立脚本 |
| P6 发布 | `lark-task --as user` 发任务评论 | ⏳ 依赖小迪指定正式任务 |

> P4 的"操作分类"是 **打底**，不是复现人肉版；最终计数由 P5 群修正决定。

## 二、测试用例（TC）

约定：`--indir /tmp/ops`，样本日 day=2026-09-22 prev=2026-09-21。
每条含 **独立验证步骤**（交别人跑时，光说"通过"不算数）。

---

**TC-01 拉数正常路径**
- 前置：creds 文件存在、API 可达
- 步骤：`python3 fetch_data.py --start 2026-09-21 --end 2026-09-22 --outdir /tmp/ops`
- 预期：exit 0；`/tmp/ops` 下 4 类×2 日 = 8 个文件，非空
- 独立验证：`ls -la /tmp/ops/*_2026092{1,2}*` 数 8 个且 size>0；`head -c1 wm_iaasdk_task_20260922.ndjson` 为 `{`

**TC-02 拉数幂等/强制**
- 步骤：同 TC-01 再跑一次（不带 --force）；再带 `--force` 跑
- 预期：第二次因文件已存在跳过（ok 计数含已存在项，不重复下载）；`--force` 全重拉
- 独立验证：`stat -c %Y wm_all_callback_20260922.ndjson` 比较——不带 force 时间戳不变，force 后变新

**TC-03 脏值容错（关键回归）**
- 前置：样本回调含字面量 `{payout}` 行（实测存在）
- 步骤：跑 build_report（TC-04 同参数）
- 预期：不崩溃；金额求和跳过非数值
- 独立验证：脚本无 traceback；把某行 `self_payout` 手改 `{payout}` 后总数不变

**TC-04 操作分类正常路径**
- 步骤：`python3 build_report.py --day 2026-09-22 --prev 2026-09-21 --indir /tmp/ops --json /tmp/ops/ops_report.json`
- 预期：exit 0；打印四类计数 + 净影响；JSON 落盘
- 独立验证：
  1. `python3 -c "import json;d=json.load(open('/tmp/ops/ops_report.json'));print(d['operations']['totals'])"` → 四键 count 之和 == detail 各列表长度之和；`basis` 字段应为 `actual_conversions`
  2. 每条 detail：`conv_delta` 与 `conv_day-conv_prev` 一致；分类判据符合门槛（见 TC-06）

**TC-05 焦点正确性（语义校验，非仅"能跑"）**
- 前置：9.22 真实焦点为 die 包（多家停/减）
- 预期：9.22 减量包级 Top 首位 `com.death.puzzle.ways.to.die`；9.23 **停单 11 个全部是该 die 包**（app/selfCChange/hivexads/Autumn 四家，转化归 0）
- 独立验证：看脚本减量/停单输出包名与客户（9.22 die −681转化/−$329、9.23 die 停单 −$146 均实测命中）

**TC-06 门槛边界（按转化数，门槛=±10）**
- 输入（构造）：某 offer conv_prev=0,conv_day=9 → 不计；=10 → 新单；=11 → 新单
- 输入（构造）：conv_prev=40,conv_day=0 → 停单；conv_prev=9,conv_day=0 → 不计
- 输入（构造）：conv_prev=50,conv_day=60（Δ=10）→ 加量；conv_prev=50,conv_day=59（Δ=9）→ 不计
- 预期：边界按 `>=10 / <=-10` 闭区间计入，9 排除
- 独立验证：`grep THRESHOLD scripts/build_report.py` 应为 10；读 classify 确认判据用转化数（非 cap）

**TC-07 头条与逐单流水同字段但口径分层**
- 预期：头条 = 全体转化行 `payout` + 外部 `payout`(clickid 去重)；逐单 flow = `(offer,come_from)` 转化行 `payout` 日环比。二者字段同源(都是 payout)，但头条含外部/去重，故 `headline.revenue_day` ≠ Σ detail flow（本就应不等）
- 独立验证：输出含 `headline_source` 提示"须核对"；9.22 自算 $6,900.24 与人肉 $6,901.44 差 <2 刀

**TC-11 转化过滤器（切口径后关键回归）**
- 预期：一条回调算转化须 `channel=='4580' 且 event_name 空 且 blocked_sub_reason 空`；游戏内事件/upgraded/session/Ad_Watched 与被拒行**不计入转化**
- 独立验证：`python3 -c "..."` 跑 `is_conv` 判据，9.23 全回调 17033 行 → 有效转化 10473（实测锚点）；把某转化行加 `event_name='x'` 后该类总数应 −1

**TC-08 缺数据报错（鲁棒性）**
- 步骤：`--indir /tmp/不存在的目录`
- 预期：非 0 退出，提示先跑 fetch_data；不产生半成品 JSON
- 独立验证：echo $? 非 0；stderr 含"缺数据文件"

**TC-09 日期默认值**
- 步骤：`build_report.py --day 2026-09-22`（不给 --prev）
- 预期：prev 自动取 2026-09-21
- 独立验证：输出标题行显示 `2026-09-21 → 2026-09-22`

**TC-10 端到端（人工闸门在位）**
- 步骤：fetch → build_report → 套模板出草稿 → 交小迪确认（**不自动发**）
- 预期：草稿三段齐全（情况分析含【大盘】/【操作】两块）；头条数字带"待与早会核对"标注；未经确认不发任务评论
- 独立验证：确认前任务评论数不变；确认后才 +1 条

---

## 三、验收标准（ Definition of Done）
- TC-01..11 全绿；TC-05 焦点命中、TC-06 边界正确、**TC-11 转化过滤器**为硬性项。
- **展示规则（人工核草稿）**：广告主第一、offer 仅流水 ≥$15 才点名；转化每类只标一次、下面每单只写流水；数字带单位不裸挤；③④ 段 1/2/3/4 编号。
- 已知限制如实标注：逐类计数与人肉版有差属打底设计预期；头条自算 ±几十刀需人工核对——不得为"对上数"偷偷改成 sum 或硬凑。
