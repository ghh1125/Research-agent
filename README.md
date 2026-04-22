# Research Agent MVP

一个基于 FastAPI 的投研研究引擎 demo。系统不会从 query 直接生成结论，而是把模糊研究问题依次经过 `define -> decompose -> retrieve -> extract -> reason -> action -> report` 流水线，先构建结构化 `Judgment`，再输出最终 `ResearchReport`。

## 项目简介

- 输入：自然语言研究问题
- 输出：结构化研究过程 + 最终报告（JSON）
- 检索：支持 Tavily、Serper/Google、Google Custom Search、Exa 多源搜索；未配置的 provider 自动跳过
- 检索 provider：支持 `auto` / `tavily`，默认 `auto`
- 存储：第一版使用内存 repository

这个 demo 要证明的是：LLM 不只是会聊天和总结，也可以像一个初级研究员一样，先理解问题、搭建研究框架、获取资料、提取证据、形成证据约束判断，并给出下一步研究建议与最终报告视图。

## 这不是什么

- 不是聊天机器人
- 不是直接从 query 生成答案的问答系统
- 不是投资买卖决策系统

系统必须先走完整研究流程，再生成 judgment 与 report。

## 目录结构

```text
research-agent/
├── app/
│   ├── main.py
│   ├── config.py
│   ├── dependencies.py
│   ├── api/
│   ├── agent/
│   ├── models/
│   ├── services/
│   └── db/
├── tests/
├── .env.example
├── requirements.txt
├── README.md
└── AGENTS.md
```

## 安装方法

```bash
cd /Users/ghh/Documents/Code/mcpify/research-agent
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## 环境变量

复制 `.env.example` 为 `.env`，可选配置：

```env
DASHSCOPE_API_KEY=your_dashscope_api_key_here
DASHSCOPE_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
DASHSCOPE_MODEL=qwen-plus

SEARCH_PROVIDER=auto
SEARCH_TIMEOUT_SECONDS=20
RETRIEVE_MAX_SOURCES=15
RETRIEVE_PER_QUESTION_LIMIT=4
TAVILY_API_KEY=your_tavily_api_key_here
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
```

没有配置 API Key 时，`define/reason` 会自动走 deterministic fallback，demo 仍可运行。
LLM 默认使用阿里云 DashScope 的 OpenAI-compatible 接口。最少需要配置 `DASHSCOPE_API_KEY`，模型可先用 `qwen3.6-max-preview`；如果你要更强模型，可以把 `DASHSCOPE_MODEL` 改成你账号可用的模型名。
如果 `SEARCH_PROVIDER=auto`，系统会使用已配置的多源搜索 provider。当前支持 Tavily、Serper、Google Custom Search、Exa；未配置 API key 的 provider 会自动跳过，至少需要配置其中一个真实搜索 key。
检索相关 API 参数也已经抽到 env，包括请求超时、每次 retrieve 最多保留多少 source、每个子问题最多保留多少 source、以及各搜索 provider 单次返回多少结果。

搜索 API 当前支持：

- `SEARCH_PROVIDER=auto` 或 `SEARCH_PROVIDER=tavily`
- `TAVILY_API_KEY=你的 Tavily key`
- `SERPER_API_KEY=你的 Serper key`
- `GOOGLE_SEARCH_API_KEY=你的 Google Search key`
- `GOOGLE_SEARCH_CX=你的 Google Programmable Search CX`
- `EXA_API_KEY=你的 Exa key`

如果没有任何搜索 key，真实检索会失败；请至少配置一个 provider。SEC EDGAR、Yahoo Finance、公司 IR 官网入口会作为投研对象相关的补充来源参与检索增强。

## 启动方式

### Streamlit 可视化页面

```bash
cd /Users/ghh/Documents/Code/mcpify/research-agent
source .venv/bin/activate
streamlit run streamlit_app.py
```

页面会调用已经实现好的 `research_pipeline(query)`，不重新实现运行逻辑，只把 pipeline 返回的结构化结果按步骤展示：

- 明确研究对象
- 拆解研究框架
- 多视角真实检索：事实流 / 风险流 / 反证流
- 提取有效证据
- 形成关键变量
- 综合研究判断
- 下一步研究动作
- 自动补证记录
- 执行摘要与早停原因
- 投资层处理建议
- 多角色投研团队
- 可验证研究报告

### FastAPI 服务

```bash
cd /Users/ghh/Documents/Code/mcpify/research-agent
uvicorn app.main:app --reload
```

健康检查：

```bash
curl http://127.0.0.1:8000/health
```

## 示例请求

```bash
curl -X POST http://127.0.0.1:8000/research \
  -H "Content-Type: application/json" \
  -d '{"query":"研究贸易企业违约原因"}'
```

示例响应：

```json
{
  "topic": {"id": "topic_xxxxxxxx", "query": "研究贸易企业违约原因", "entity": null, "topic": "贸易企业违约原因", "goal": "...", "type": "theme", "hypothesis": null},
  "questions": [{"id": "q1", "topic_id": "topic_xxxxxxxx", "content": "...", "priority": 1, "covered": false}],
  "sources": [{"id": "s1", "question_id": "q1", "title": "...", "url": "https://example.com/...", "source_type": "website", "provider": "tavily", "tier": "professional", "source_score": 0.72, "contains_entity": true, "is_recent": true, "published_at": null, "content": "..."}],
  "evidence": [{"id": "e1", "topic_id": "topic_xxxxxxxx", "question_id": "q1", "source_id": "s1", "content": "...", "evidence_type": "data", "stance": "support", "source_tier": "professional", "source_score": 0.72, "relevance_score": 0.8, "clarity_score": 0.76, "recency_score": 1.0, "evidence_score": 0.76, "timestamp": null}],
  "judgment": {
    "topic_id": "topic_xxxxxxxx",
    "conclusion": "基于当前证据，贸易企业违约原因的初步判断是：现金流承压、高杠杆、客户或业务集中是最值得优先解释的问题。",
    "conclusion_evidence_ids": ["e1", "e2"],
    "clusters": [{"theme": "高杠杆风险", "support_evidence_ids": ["e1"], "counter_evidence_ids": []}],
    "risk": [{"text": "高杠杆风险", "evidence_ids": ["e1"]}],
    "unknown": ["样本覆盖范围仍有限"],
    "evidence_gaps": [{"question_id": "q2", "text": "子问题证据不足：...", "importance": "high"}],
    "confidence": "low",
    "confidence_basis": {"source_count": 2, "source_diversity": "medium", "conflict_level": "partial", "evidence_gap_level": "high", "effective_evidence_count": 2, "has_official_source": false, "official_evidence_count": 0, "weak_source_only": true},
    "research_actions": [{"id": "a1", "priority": "high", "objective": "补齐现金流和财报数据", "reason": "...", "required_data": ["营收", "净利润", "经营现金流"], "query_templates": ["{entity} 财报 营收 净利润 现金流"], "source_targets": ["official filings", "investor relations"], "status": "pending"}]
  },
  "auto_research_trace": [{"round_index": 1, "triggered": true, "selected_action_ids": ["a1"], "executed_queries": ["贸易企业 财报 营收 净利润 现金流"], "new_source_ids": ["s6"], "new_evidence_ids": ["e9"], "covered_gap_question_ids": ["q1"], "effectiveness_status": "effective", "stop_reason": "完成本轮补证，final_confidence=low"}],
  "executive_summary": {"one_line_conclusion": "...", "top_risk": "...", "next_action": "...", "confidence": "low", "research_time_minutes": 120},
  "early_stop_reason": null,
  "report": {
    "id": "report_xxxxxxxx",
    "generated_at": "2026-04-17T00:00:00+00:00",
    "report_sections": [
      {"title": "研究问题", "section_type": "background", "body": "...", "evidence_ids": []},
      {"title": "研究框架", "section_type": "framework", "body": "...", "evidence_ids": []},
      {"title": "核心发现", "section_type": "finding", "body": "...", "evidence_ids": ["e1", "e2"]},
      {"title": "主要风险", "section_type": "risk", "body": "...", "evidence_ids": ["e1"]},
      {"title": "不确定性与证据缺口", "section_type": "gap", "body": "...", "evidence_ids": []},
      {"title": "初步判断", "section_type": "judgment", "body": "...", "evidence_ids": ["e1", "e2"]},
      {"title": "下一步研究建议", "section_type": "action", "body": "...", "evidence_ids": []}
    ]
  }
}
```

## 测试方式

```bash
cd /Users/ghh/Documents/Code/mcpify/research-agent
pytest
```
