# Research Agent

一个面向上市公司初筛场景的 AI 投研驾驶舱。
它不是财报摘要器，也不是荐股机器人。它的目标是用 30 秒告诉用户：

- 这家公司现在值不值得继续研究
- 当前为什么还不能直接下更强判断
- 最大风险和最大缺口分别是什么
- 下一步具体应该补什么数据
- 这些结论当前是否有足够证据支撑

当前版本的产品形态是：

- 后端生成完整研究链路与 `dashboard_view`
- Streamlit 只渲染 cockpit 和折叠的 `research_memo`
- 证据、来源、判断、缺口、下一步动作全部由后端生成

## 1. 当前定位

输入：

- 一个自然语言研究问题，例如
  `我想买阿里巴巴的股票，你觉得是否值得进一步研究`

输出：

- `topic`
- `questions`
- `sources`
- `evidence`
- `variables`
- `judgment`
- `financial_snapshot`
- `report`
- `dashboard_view`

其中真正面向普通用户的产物是：

- `dashboard_view`
- `report.report_display`
- Streamlit cockpit 首页

其中真正面向开发和审计的产物是：

- `report.report_internal`
- `developer_payload`
- `raw_sources / raw_evidence / debug_stats / traces`

## 2. 当前主链

当前代码的研究主链可以概括为：

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

和这条主链对应的关键后端模块包括：

- `app/services/evidence_engine.py`
- `app/services/llm_evidence_extractor.py`
- `app/services/llm_evidence_qa.py`
- `app/services/evidence_registry.py`
- `app/services/llm_research_depth_qa.py`
- `app/services/dashboard_projector.py`
- `app/services/llm_dashboard_summarizer.py`

## 3. 当前版本解决的核心问题

### 3.1 Source Governance 收紧

系统现在不会因为标题里写了 `Annual Report`、`Revenue Model`、`Investor` 就把第三方站点抬成官方来源。

当前 hard-cap 规则重点约束：

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

这些来源最多只能进入 `professional` 或 `content`，不能进入 `official / company_ir / regulatory`。

### 3.2 Main-Chain Evidence Registry

下游模块不再直接消费 raw evidence。当前合法入口只有 registry：

- `registry.get()`
- `registry.has()`
- `registry.filter_existing()`
- `registry.project_for_display()`

进入 registry 的证据必须满足：

- `can_enter_main_chain=True`
- 非截断
- 非噪声
- 非跨主体污染
- 来源层级有效
- `quote/summary` 非空
- 能通过 grounding / entity match / off-target 检查

这保证了：

- 不会再把断裂引用渲染到用户页
- off-target report 不会进入 cockpit
- `curated_evidence` 只来自主链证据

### 3.3 Dashboard Projection

后端统一生成 `dashboard_view`，前端只渲染，不再重算逻辑。

当前 `dashboard_view` 主要包含：

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

### 3.4 Human-readable Cockpit

默认首页只展示普通用户真正需要的内容：

1. 当前建议 / 置信度 / 研究位置 / 主链证据数
2. 一句话结论
3. 下一步研究动作
4. 财务质量 / 风险压力 / 证据质量 / 缺口地图
5. 关键证据
6. 给用户的研究建议

以下内容默认折叠：

- `research_memo`
- `raw_sources`
- `raw_evidence`
- `debug_stats`
- `pressure_tests`
- `multi-agent traces`

## 4. 默认页长什么样

Streamlit 当前页面分成两层：

### 4.1 Cockpit 首页

默认展开，面向普通用户。

包含：

- Verdict / Confidence / Research Position
- Headline
- Next Action
- 四张卡
- 关键证据（默认最多 8 条）
- 四段研究建议

### 4.2 折叠层

- `展开查看研究备忘录`
- `开发者模式`

这保证 demo 首页不再像 debug dump。

## 5. Research Memo 当前内容

`research_memo` 是折叠的结构化研究备忘录，不是默认首页。

当前包含：

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

其中几块重点能力已经内建：

- `cash_flow_bridge`
  - `Operating Cash Flow - Capex = Free Cash Flow`
  - `FCF - Buybacks - Dividends = Capital Return Coverage`
- `valuation`
  - absolute
  - relative peers
  - market-implied narrative
  - rerating triggers
- `competition`
  - 通用竞争框架
  - 同行对比
  - 护城河/竞争位置保守表达

## 6. 当前的产品约束

### 6.1 UI 只负责展示

Streamlit 不允许：

- 直接读 raw evidence 重新筛证据
- 自己重算 confidence
- 自己做 source governance
- 自己调 LLM 生成结论
- 自己拼 research judgment

### 6.2 强判断必须保守

当前版本对以下问题做了硬约束：

- 缺估值参照时，不说“便宜 / 低估 / 安全边际明确”
- 缺市场份额 / 留存 / GMV / take rate 时，不说“护城河强 / 弱”
- FCF 下滑时，不说 “Improving”
- buyback / dividend 数据不齐时，不说资本回报覆盖改善

### 6.3 用户页不暴露内部术语

默认用户页不应该出现：

- `logic_gap`
- `pt1 / pt2 / pt3`
- `registry`
- `broken refs`
- `Under Review / Improving / Healthy`
- `Revenue=996347CNY million`

## 7. 目录结构

```text
research-agent/
├── app/
│   ├── agent/
│   │   ├── pipeline.py
│   │   └── steps/
│   ├── api/
│   ├── models/
│   ├── services/
│   ├── config.py
│   └── main.py
├── tests/
├── streamlit_app.py
├── README.md
├── PRD.md
├── requirements.txt
└── .env.example
```

## 8. 安装

```bash
cd /Users/ghh/Documents/Code/mcpify/research-agent
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## 9. 环境变量

复制 `.env.example` 为 `.env`。

最小示例：

```env
DASHSCOPE_API_KEY=your_key
SEARCH_PROVIDER=auto
TAVILY_API_KEY=your_tavily_key
```

常用变量：

```env
# LLM
DASHSCOPE_API_KEY=
DASHSCOPE_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
DASHSCOPE_MODEL=qwen3.6-max-preview
OPENAI_API_KEY=
OPENAI_MODEL=gpt-5

# Search
SEARCH_PROVIDER=auto
SEARCH_TIMEOUT_SECONDS=20
RETRIEVE_MAX_SOURCES=15
RETRIEVE_PER_QUESTION_LIMIT=4
TAVILY_API_KEY=
SERPER_API_KEY=
GOOGLE_SEARCH_API_KEY=
GOOGLE_SEARCH_CX=
EXA_API_KEY=

# Financial / supplemental
FINNHUB_API_KEY=
MASSIVE_API_KEY=
SEC_USER_AGENT_EMAIL=research-agent@example.com
SUPPLEMENTAL_SEARCH_ENABLED=true
```

## 10. 启动

### 10.1 Streamlit Demo

```bash
cd /Users/ghh/Documents/Code/mcpify/research-agent
source .venv/bin/activate
streamlit run streamlit_app.py
```

默认 demo query：

```text
我想买阿里巴巴的股票，你觉得是否值得进一步研究
```

### 10.2 FastAPI

```bash
cd /Users/ghh/Documents/Code/mcpify/research-agent
source .venv/bin/activate
uvicorn app.main:app --reload
```

健康检查：

```bash
curl http://127.0.0.1:8000/health
```

## 11. API 示例

请求：

```bash
curl -X POST http://127.0.0.1:8000/research \
  -H "Content-Type: application/json" \
  -d '{"query":"研究阿里巴巴是否值得进一步研究"}'
```

关键返回：

- `topic`
- `questions`
- `sources`
- `evidence`
- `variables`
- `judgment`
- `financial_snapshot`
- `auto_research_trace`
- `executive_summary`
- `report`
- `dashboard_view`

## 12. 测试

```bash
cd /Users/ghh/Documents/Code/mcpify/research-agent
source .venv/bin/activate
pytest -q
git diff --check
python -m compileall app tests streamlit_app.py
```

## 13. 当前版本不是做什么

当前版本不做：

- 自动买卖建议
- 仓位建议
- 自动交易
- 完整估值模型替代人工研究
- 多用户审批流
- 团队权限系统

它做的是：

> 把“会生成研究报告的系统”收敛成“普通用户 30 秒能看懂的 AI 投研驾驶舱”。
