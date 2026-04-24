# Research Agent PRD

版本：Demo 交付版  
最后更新：2026-04-24  
产品定位：AI 投研驾驶舱，不是财报摘要器，不是荐股系统

---

## 1. 一句话定义

Research Agent 的目标不是替用户直接下投资结论，而是让用户在 30 秒内看懂：

1. 这家公司现在值不值得继续研究
2. 为什么当前还不能直接下更强判断
3. 最大风险是什么
4. 缺什么关键数据
5. 下一步具体要查什么
6. 这些结论现在是否有足够证据支撑

---

## 2. 产品目标

### 2.1 主要目标

把系统从“长篇研究报告生成器”收敛成“普通用户能看懂的 AI 投研驾驶舱”。

### 2.2 当前交付目标

当前 demo 必须做到：

- 后端可信：来源、证据、判断形成闭环
- 输出稳定：后台统一生成 `dashboard_view`
- 前端专业：默认页是 cockpit，不是 debug dump
- Demo 可讲：首屏能快速讲清楚是否值得继续研究
- 缺证保守：证据不足时明确降级，不假装覆盖

### 2.3 非目标

当前版本不做：

- 买入 / 卖出 / 持仓建议
- 自动交易
- 复杂估值模型替代正式投研
- 多用户权限、审批流、任务流
- 面向外部客户的投顾系统

---

## 3. 目标用户

当前版本主要面向：

- 买方分析师
- 基金经理
- 研究主管
- 风控同学
- 家办 / 自营研究者

默认使用场景是：

> 用户输入一句研究问题，系统给出是否值得继续研究的初筛判断与下一步动作。

---

## 4. 核心体验

### 4.1 输入

用户输入一句自然语言问题，例如：

> 我想买阿里巴巴的股票，你觉得是否值得进一步研究

### 4.2 输出

系统输出两层内容：

#### A. 面向普通用户

- `dashboard_view`
- Streamlit cockpit 首页

#### B. 面向开发 / 审计

- `report.report_internal`
- `developer_payload`
- `raw_sources`
- `raw_evidence`
- `debug_stats`
- `pressure_tests`

### 4.3 默认页应该回答的问题

默认页必须直接回答：

1. 当前建议是什么
2. 为什么不是更强结论
3. 最大风险是什么
4. 最大缺口是什么
5. 下一步查什么
6. 当前证据是否可信

---

## 5. 当前系统架构

### 5.1 主链

当前主链为：

```text
define
-> decompose
-> financial_snapshot
-> retrieve
-> source governance
-> LLM structured extraction
-> evidence grounding QA
-> evidence validation
-> main-chain evidence registry
-> variable mapping
-> coverage
-> judgment generation
-> judgment post-process
-> action / auto_research
-> investment / roles
-> dashboard projection
-> report generation
-> streamlit cockpit render
```

### 5.2 核心原则

1. UI 只负责展示，不做业务逻辑
2. 所有判断必须由后端生成
3. Streamlit 不直接消费 raw evidence
4. Streamlit 不重算 confidence
5. Streamlit 不做 source governance
6. Streamlit 不直接调 LLM 生成结论
7. `dashboard_view` 是唯一默认用户产物

---

## 6. 后端能力定义

### 6.1 Source Governance

系统必须把来源分成：

- `official`
- `professional`
- `content`

并且对一批常见误判源做 hard-cap。

#### 永远不能进入 official / company_ir / regulatory 的典型来源

- `monexa.ai`
- `moomoo.com`
- `gurufocus.com`
- `zacks.com`
- `morningstar.com`
- `tradingview.com`
- `globeandmail.com`
- `theglobeandmail.com`
- `annualreports.com`
- `simplywall.st`
- `statista.com`
- `fool.com`
- `motleyfool.com`
- `seekingalpha.com`
- `revenue model`
- `makes money explained`
- `statistics facts`
- `stock analysis blog`
- 常见 SEO 内容站
- 聚合转载站

这些来源最多只能是：

- `professional`
- `content`

#### 可以进入 official 的来源

- `sec.gov`
- `hkexnews.hk`
- 交易所 / 监管披露域
- 公司官网 IR
- 公司官方 earnings release
- 公司官方 annual report / results PDF

### 6.2 Evidence Registry

系统有统一主链证据注册表，所有下游必须通过 registry 消费证据。

进入 registry 的 evidence 必须满足：

- `can_enter_main_chain=True`
- 非截断
- 非噪声
- 非跨主体污染
- 来源层级有效
- `quote/summary` 非空
- 通过 grounding
- 通过 entity match
- 非 off-target report

下游唯一合法入口：

- `registry.get()`
- `registry.has()`
- `registry.filter_existing()`
- `registry.project_for_display()`

### 6.3 Grounding QA

LLM 与规则结合做抽证 QA，但 LLM 只能降级 / 拒绝 evidence，不能越权升级。

重点检查：

- entity 是否匹配目标公司
- value 是否真在 quote / source 中
- period 是否真在原文中
- metric 是否语义匹配
- quote 是否脏、截断、乱码
- 是否 forecast / estimate
- 是否 off-target company

### 6.4 Research Depth QA

系统不允许假装已经覆盖估值、竞争、护城河。

若缺以下关键证据，就必须显式显示缺口：

- 估值：historical band / peer median / forward PE / EV-EBITDA
- 竞争：market share / GMV / take rate / retention
- 护城河：stickiness / switching cost / merchant / user data
- 治理：filing / litigation / compliance evidence

---

## 7. Judgment 与文案约束

### 7.1 Judgment 结构

当前 judgment 侧重点是：

- `verified_facts`
- `probable_inferences`
- `pending_assumptions`
- `confidence`
- `conclusion`
- `evidence_gaps`
- `research_actions`

### 7.2 文案约束

用户页不允许出现：

- `logic_gap`
- `pt1 / pt2 / pt3`
- `registry`
- `broken refs`
- `Under Review / Improving / Healthy`
- `Weak moat`
- `cheap valuation`

### 7.3 保守表达约束

若证据不足：

- 不说“便宜 / 低估 / 安全边际明确”
- 不说“护城河强 / 护城河弱”
- 不说“自由现金流改善”如果数据其实在下滑
- 不说资本回报覆盖改善，如果 buybacks / dividends 数据不齐

---

## 8. `dashboard_view` 产物定义

### 8.1 顶层结构

当前版本 `dashboard_view` 至少包含：

```json
{
  "summary_cards": {},
  "headline": "...",
  "next_action": {},
  "financial_quality": {},
  "risk_pressure": {},
  "evidence_quality": {},
  "gap_map": {},
  "top_variables": [],
  "top_risks": [],
  "top_gaps": [],
  "curated_evidence": [],
  "recommendation_text": {},
  "source_quality": {},
  "depth_summary": {},
  "research_memo": {},
  "developer_payload": {}
}
```

### 8.2 关键字段要求

#### `summary_cards`

必须包含：

- `verdict`
- `confidence`
- `research_position`
- `evidence_count`
- `official_count`

#### `headline`

必须是普通用户能读懂的一句话总结。

#### `next_action`

必须明确：

- 查什么
- 为什么重要
- 需要哪些数据
- 查完如何影响判断

#### `curated_evidence`

要求：

- 只来自 registry
- 默认不超过 12 条
- 首页默认展示不超过 8 条

#### `developer_payload`

允许保留：

- `report_internal`
- `raw_sources`
- `raw_evidence`
- `debug_stats`
- `pressure_tests`
- `auto_research_logs`

但默认页必须折叠。

---

## 9. Research Memo 定义

`research_memo` 是折叠层，不是默认首页。

当前结构包括：

- `verdict`
- `confidence`
- `headline`
- `snapshot_dashboard`
- `financial_quality`
- `cash_flow_bridge`
- `valuation`
- `competition`
- `bull_case`
- `bear_case`
- `what_changes_my_mind`
- `evidence_gaps`
- `next_research_actions`

### 9.1 Cash Flow Bridge 要求

必须能表达：

```text
Operating Cash Flow
- Capex
= Free Cash Flow

Free Cash Flow
- Buybacks
- Dividends
= Capital Return Coverage
```

并对下列情况做保守约束：

- FCF 下滑时，不能显示“改善”
- OCF 为正但 FCF 承压时，要明确写“承压但未失控”
- 缺 buyback / dividend 数据时，只能写“覆盖能力待验证”

### 9.2 Valuation 要求

必须拆成：

- absolute
- relative peers
- market-implied narrative
- rerating triggers

若缺历史区间和同行中位数：

- 只能写“参照系缺失”
- 不能写“便宜 / 低估 / 安全边际明确”

### 9.3 Competition 要求

使用通用竞争框架：

- market share
- pricing power
- retention / stickiness
- switching cost
- innovation velocity
- distribution advantage
- cost leadership

若缺市场份额、GMV、take rate、留存等关键数据：

- 只能写“竞争位置证据不足，暂无法判断护城河强度”

---

## 10. Streamlit Cockpit 定义

### 10.1 默认页布局

默认页只显示：

1. Verdict / Confidence / Research Position / Evidence Count
2. Headline
3. Next Action
4. 四张卡
   - 财务质量
   - 风险压力
   - 证据质量
   - 缺口地图
5. 关键证据
6. 给用户的研究建议

### 10.2 默认折叠内容

必须默认折叠：

- `展开查看研究备忘录`
- `开发者模式`

### 10.3 不应默认出现的内容

- memo tabs
- raw report
- raw evidence
- raw sources
- pressure test 全文
- 多角色全文
- 重复 peer table

---

## 11. API 交付要求

FastAPI 当前返回的 `ResearchResponse` 必须包括：

- `topic`
- `questions`
- `sources`
- `evidence`
- `variables`
- `roles`
- `judgment`
- `auto_research_trace`
- `executive_summary`
- `financial_snapshot`
- `early_stop_reason`
- `report`
- `dashboard_view`

这意味着：

- 即使不打开 Streamlit，后端也能独立返回产品化结果
- `dashboard_view` 不是 UI 拼出来的中间态，而是正式产物

---

## 12. Demo 验收标准

当前 demo 以阿里巴巴 query 为主要验收样例：

> 我想买阿里巴巴的股票，你觉得是否值得进一步研究

默认页至少要满足：

1. 第三方财经博客不被算成 official
2. 不出现 FCF 下滑却状态写成 Improving
3. 不出现 `Weak moat / cheap valuation`
4. 不出现 `Revenue=996347CNY million`
5. 不出现 `logic_gap / registry / broken refs`
6. 默认页只显示 cockpit，memo 折叠
7. headline 为自然语言
8. 研究建议能清楚回答：
   - 现在能确认什么
   - 现在不能确认什么
   - 为什么当前只是观察或继续研究
   - 下一步具体查什么

---

## 13. 成功标准

本 demo 成功，不是因为它能写更长的报告，而是因为它能稳定做到：

- 有证据就说清楚
- 缺证据就明确降级
- 来源不靠谱就不抬等级
- 用户默认只看最需要的信息
- 开发调试信息不污染默认页

最终目标不是：

> 自动替代分析师做投资决定

而是：

> 成为一个知道“现在还缺什么”的 AI 投研驾驶舱。
