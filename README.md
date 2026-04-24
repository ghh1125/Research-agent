# Research Agent MVP

一个“先研究、再结论”的投研引擎 demo。系统不会从 query 直接回答，而是按固定 pipeline 先产出结构化研究过程，再给出 `Judgment`、`ExecutiveSummary` 和 `ResearchReport`。

## 项目定位

- 输入：自然语言研究问题
- 输出：`topic/questions/sources/evidence/variables/judgment/report` 全链路结构化结果
- 目标：把结论绑定到来源与证据，支持复核和追溯
- 存储：当前版本使用内存 repository（`InMemoryResearchRepository`）

这个项目不是聊天问答机器人，也不是投资买卖决策系统。

## 端到端 Pipeline

当前 `research_pipeline(query)` 的实际顺序是：

1. `define`：定义研究对象、目标、对象类型与上市状态
2. `decompose`：把大问题拆成研究子问题（财务、行业、估值、风险等）
3. `financial_snapshot`：拉取结构化金融快照（可用时）
4. `retrieve`：注入官方源 + 多源检索 + 去重 + 富化 + 排序
5. `extract`：从来源文本中提取结构化证据
6. `variable`：把证据归纳成关键变量
7. `reason`：生成初步判断、风险、不确定性、置信度与证据缺口
8. `action`：生成下一步补证动作
9. `auto_research`：低置信度时自动补证
10. `investment`：输出研究流程层面的处理建议（非买卖建议）
11. `roles`：多角色复核与补充视角
12. `report`：生成最终报告与执行摘要

早停逻辑：

- 检索来源为空且金融快照不可用，会直接生成“研究不足”报告
- 自动补证后有效证据仍不足（<3），会标记低置信度早停原因

## 证据提取是怎么做的

`extract` 不是简单摘要，而是“LLM 提名 + 规则审计 + 主链路过滤”：

1. 来源文本准备

- 优先使用富化后的正文（`enriched_content`），其次使用抓取正文与原始 content
- PDF 来源会先经过 PDF 解析服务再进入抽取

2. LLM 结构化抽取（候选证据）

- 使用固定 prompt 输出 JSON schema，不允许自由发挥
- 每条候选包含：`metric_name/metric_value/unit/period/entity/segment/quote/extraction_confidence`
- 同时标记：`is_estimate`、`requires_cross_check`

3. 规则校验（硬门槛）

- 跨主体污染过滤：候选实体与目标研究对象不一致会被拒绝
- 引句落地校验：抽出的数值必须能在 quote 中对上
- 截断数字过滤：不完整数字片段拒绝进入主链路
- period 格式校验：格式异常拒绝
- 弱来源加严：弱来源在低置信度下会被拒绝

4. 去重与编号

- 按 `metric_name + metric_value + period + segment` 去重
- 通过校验后生成标准 `Evidence`，统一编号 `e1/e2/...`

5. 补充结构化金融证据

- `financial_snapshot` 的指标会额外转成 evidence，和抽取证据一起参与后续判断

6. 判断前二次过滤

- `reason` 阶段会再次筛选主链路证据：去噪、去截断、去跨主体、要求 grounded、要求最低分

## LLM 与规则分别做什么

- LLM：理解问题、拆解问题、结构化抽取候选证据、生成判断草案
- 规则层：来源治理、证据校验、覆盖度判定、置信度收敛、早停控制

目标是减少“看起来像答案但无法验证”的输出。

## 目录结构

```text
research-agent/
├── app/
│   ├── main.py
│   ├── config.py
│   ├── dependencies.py
│   ├── api/
│   ├── agent/
│   │   ├── pipeline.py
│   │   └── steps/
│   ├── models/
│   ├── services/
│   └── db/
├── tests/
├── streamlit_app.py
├── .env.example
├── requirements.txt
├── README.md
└── AGENTS.md
```

## 安装

```bash
cd /Users/ghh/Documents/Code/mcpify/research-agent
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## 环境变量

复制 `.env.example` 为 `.env`。

最小可用配置：

```env
DASHSCOPE_API_KEY=your_key
SEARCH_PROVIDER=auto
TAVILY_API_KEY=your_tavily_key
```

常用变量（按模块分组）：

```env
# LLM
DASHSCOPE_API_KEY=
DASHSCOPE_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
DASHSCOPE_MODEL=qwen3.6-max-preview
OPENAI_API_KEY=
OPENAI_MODEL=gpt-5

# 检索
SEARCH_PROVIDER=auto
SEARCH_TIMEOUT_SECONDS=20
RETRIEVE_MAX_SOURCES=15
RETRIEVE_PER_QUESTION_LIMIT=4
TAVILY_API_KEY=
TAVILY_BASE_URL=https://api.tavily.com/search
TAVILY_MAX_RESULTS=8
TAVILY_DAYS=180
SERPER_API_KEY=
SERPER_BASE_URL=https://google.serper.dev/search
SERPER_MAX_RESULTS=8
GOOGLE_SEARCH_API_KEY=
GOOGLE_SEARCH_CX=
GOOGLE_SEARCH_BASE_URL=https://www.googleapis.com/customsearch/v1
GOOGLE_SEARCH_MAX_RESULTS=8
EXA_API_KEY=
EXA_BASE_URL=https://api.exa.ai/search
EXA_MAX_RESULTS=8

# 金融/补充源
FINNHUB_API_KEY=
FINNHUB_BASE_URL=https://finnhub.io/api/v1
MASSIVE_API_KEY=
MASSIVE_BASE_URL=https://api.massive.com
SEC_USER_AGENT_EMAIL=research-agent@example.com
SUPPLEMENTAL_SEARCH_ENABLED=true
```

说明：

- `define/reason` 的 LLM 调用失败时，系统会走 deterministic fallback，demo 可继续运行
- 搜索 provider 按 key 自动启用，未配置 key 的 provider 会自动跳过

## 启动方式

### Streamlit 可视化页面

```bash
cd /Users/ghh/Documents/Code/mcpify/research-agent
source .venv/bin/activate
streamlit run streamlit_app.py
```

页面只负责展示，底层仍调用同一个 `research_pipeline(query)`。

### FastAPI 服务

```bash
cd /Users/ghh/Documents/Code/mcpify/research-agent
source .venv/bin/activate
uvicorn app.main:app --reload
```

健康检查：

```bash
curl http://127.0.0.1:8000/health
```

## API 示例

请求：

```bash
curl -X POST http://127.0.0.1:8000/research \
  -H "Content-Type: application/json" \
  -d '{"query":"研究宁德时代是否值得进一步研究"}'
```

返回字段（核心）：

- `topic`
- `questions`
- `sources`
- `evidence`
- `variables`
- `judgment`
- `auto_research_trace`
- `executive_summary`
- `financial_snapshot`
- `early_stop_reason`
- `report`

## 测试

```bash
cd /Users/ghh/Documents/Code/mcpify/research-agent
source .venv/bin/activate
pytest
```
