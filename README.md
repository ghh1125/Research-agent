# Research Agent

`Research Agent` 是一个“先走研究流程，再给结论”的投研系统。

如果你第一次看这个项目，最重要的不是先看 UI，而是先理解它的主链：

```text
query
-> topic
-> questions
-> financial_snapshot
-> sources
-> evidence
-> evidence_registry
-> variables
-> judgment
-> dashboard_view
-> research_memo / report
```

这份 README 只做一件事：

> 帮你从 0 到 1 看懂当前版本的 pipeline，每一步在干什么，输入输出是什么。

## 1. 系统最终产物

用户输入一句话，例如：

```text
我想买阿里巴巴的股票，你觉得是否值得进一步研究
```

系统最终会产出几层结果：

1. 结构化研究过程
   - `topic`
   - `questions`
   - `sources`
   - `evidence`
   - `variables`
   - `judgment`

2. 产品化展示结果
   - `dashboard_view`
   - `report.report_display`
   - `research_memo`

3. 开发与审计结果
   - `report.report_internal`
   - `developer_payload`
   - `raw_sources`
   - `raw_evidence`
   - `debug_stats`

## 2. 主入口

当前统一入口是：

- [app/agent/pipeline.py](/Users/ghh/Documents/Code/mcpify/research-agent/app/agent/pipeline.py)

主函数：

- `research_pipeline(query)`

它负责串起所有 step，并最终返回：

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
- `report`
- `dashboard_view`

## 3. Pipeline 总览

### Step 1. `define`

模块：

- [app/agent/steps/define.py](/Users/ghh/Documents/Code/mcpify/research-agent/app/agent/steps/define.py)

输入：

- 用户原始 `query`

输出：

- `Topic`

作用：

- 识别研究对象是谁
- 识别这是公司、主题、合规问题还是一般问题
- 判断研究对象是不是上市公司
- 判断市场类型，例如 `US / HK / A_share`
- 生成后续研究要围绕的 `topic / goal`

核心输出字段：

- `id`: 主题 id
- `query`: 原始问题
- `entity`: 研究对象名称
- `topic`: 规范化主题名
- `goal`: 研究目标
- `type`: `company/theme/compliance/general`
- `research_object_type`: 研究对象类型
- `listing_status`: `listed/private/unlisted/...`
- `market_type`: `A_share/HK/US/...`

一句话理解：

> `define` 把一句自然语言问题，变成一个结构化研究对象。

### Step 2. `decompose`

模块：

- [app/agent/steps/decompose.py](/Users/ghh/Documents/Code/mcpify/research-agent/app/agent/steps/decompose.py)

输入：

- `Topic`

输出：

- `list[Question]`

作用：

- 把大问题拆成多个可检索、可判断的子问题
- 给每个问题一个 `framework_type`
- 给每个问题一个适合搜索引擎的 `search_query`

核心输出字段：

- `id`
- `topic_id`
- `content`: 分析师可读问题
- `search_query`: 检索用 query
- `priority`
- `framework_type`
- `coverage_level`

常见 `framework_type`：

- `financial`
- `credit`
- `valuation`
- `industry`
- `moat`
- `risk`
- `governance`
- `compliance`

一句话理解：

> `decompose` 决定系统接下来“要研究什么”。

### Step 3. `financial_snapshot`

模块：

- [app/services/financial_data_service.py](/Users/ghh/Documents/Code/mcpify/research-agent/app/services/financial_data_service.py)

输入：

- `Topic`
- 可能的 ticker / symbol / market

输出：

- `FinancialSnapshot`

作用：

- 补充结构化金融快照
- 在搜索之前先给系统一个金融数据底稿
- 如果拿到同行数据，也会写进 `peer_comparison`

核心输出字段：

- `entity`
- `symbol`
- `provider`
- `status`
- `provider_status`
- `provider_attempts`
- `metrics`
- `peer_symbols`
- `peer_comparison`
- `valuation`
- `note`

`metrics` 的单条结构：

- `name`
- `value`
- `unit`
- `period`
- `source`

一句话理解：

> `financial_snapshot` 是结构化市场数据层，不替代财报，但能提前给 valuation / peer / financial 维度补底。

### Step 4. `retrieve`

模块：

- [app/agent/steps/retrieve.py](/Users/ghh/Documents/Code/mcpify/research-agent/app/agent/steps/retrieve.py)
- [app/services/official_source_injector.py](/Users/ghh/Documents/Code/mcpify/research-agent/app/services/official_source_injector.py)
- [app/services/content_fetcher.py](/Users/ghh/Documents/Code/mcpify/research-agent/app/services/content_fetcher.py)
- [app/services/pdf_service.py](/Users/ghh/Documents/Code/mcpify/research-agent/app/services/pdf_service.py)

输入：

- `Topic`
- `Question[]`

输出：

- `Source[]`

作用：

- 多源搜索检索候选来源
- 注入官方来源
- 去重
- 抓取正文
- enrich 网页与 PDF 内容

`Source` 的核心字段：

- `id`
- `question_id`
- `title`
- `url`
- `source_type`
- `provider`
- `source_origin_type`
- `tier`
- `source_score`
- `contains_entity`
- `is_pdf`
- `is_official_pdf`
- `is_official_target_source`
- `rejected_reason`
- `page_type`
- `pdf_parse_status`
- `content`
- `fetched_content`
- `enriched_content`

一句话理解：

> `retrieve` 决定系统“拿什么资料来研究”。

### Step 5. `source governance`

模块：

- [app/services/evidence_engine.py](/Users/ghh/Documents/Code/mcpify/research-agent/app/services/evidence_engine.py)

输入：

- 原始 `Source[]`
- `Topic`

输出：

- 重排和分层后的 `Source[]`

作用：

- 给来源打 tier
- 判断是否 official / professional / content
- 做 hard-cap，避免第三方财经站误升 official
- 判断来源是否可能是目标公司的真实官方来源

这一步会重点修复：

- `Revenue Model` 被误判 official
- `AnnualReports.com` 被误判 official
- `GuruFocus / Zacks / TradingView / Monexa / Moomoo` 被误抬 official

一句话理解：

> `source governance` 决定这些资料值不值得信。

### Step 6. `extract`

模块：

- [app/agent/steps/extract.py](/Users/ghh/Documents/Code/mcpify/research-agent/app/agent/steps/extract.py)
- [app/services/llm_evidence_extractor.py](/Users/ghh/Documents/Code/mcpify/research-agent/app/services/llm_evidence_extractor.py)

输入：

- `Topic`
- `Question[]`
- `Source[]`

输出：

- `Evidence[]`

作用：

- 从网页正文、PDF、表格中抽取结构化证据
- 抽出财务指标、期间、单位、实体、quote
- 把非结构化文本变成可以 downstream 消费的证据项

`Evidence` 核心字段：

- `id`
- `topic_id`
- `question_id`
- `source_id`
- `flow_type`
- `content`
- `evidence_type`
- `stance`
- `grounded`
- `is_noise`
- `is_truncated`
- `cross_entity_contamination`
- `can_enter_main_chain`
- `quality_score`
- `source_tier`
- `evidence_score`
- `metric_name`
- `metric_value`
- `unit`
- `period`
- `segment`
- `comparison_type`
- `yoy_qoq_flag`
- `currency`
- `entity`
- `extraction_confidence`

一句话理解：

> `extract` 把“来源”变成“能引用的证据”。

### Step 7. `evidence grounding QA`

模块：

- [app/services/llm_evidence_qa.py](/Users/ghh/Documents/Code/mcpify/research-agent/app/services/llm_evidence_qa.py)

输入：

- `target profile`
- `source metadata`
- `raw quote`
- `candidate evidence`

输出：

- evidence 通过 / 降级 / 拒绝结果

作用：

- 检查 value 是不是真的在原文里
- 检查 period 是否对得上
- 检查 metric 语义是否匹配
- 检查是不是 off-target company
- 检查是不是 forecast / estimate
- 清理脏 quote

一句话理解：

> 这一步防止 LLM 抽证“看起来像对的，实际上没落地”。

### Step 8. `evidence validation`

模块：

- `extract` 内部规则
- `reason` 前过滤

输入：

- `Evidence[]`

输出：

- 通过验证的 `Evidence[]`

作用：

- 去截断
- 去噪声
- 去跨主体污染
- 去脏 quote
- 去无法进入主链的 evidence

一句话理解：

> 这一步把候选证据收紧成可用证据。

### Step 9. `main-chain evidence registry`

模块：

- [app/services/evidence_registry.py](/Users/ghh/Documents/Code/mcpify/research-agent/app/services/evidence_registry.py)

输入：

- 验证后的 `Evidence[]`
- `Source[]`
- `Topic`

输出：

- `EvidenceRegistry`

作用：

- 形成主链证据唯一入口
- 只允许合法 evidence 进入下游
- 过滤 broken refs
- 过滤 off-target evidence
- 生成 display-safe projection

下游只能通过这些方法消费证据：

- `get()`
- `has()`
- `filter_existing()`
- `project_for_display()`

一句话理解：

> registry 是“主链证据总线”，没有进 registry 的证据都不算正式证据。

### Step 10. `variable`

模块：

- [app/agent/steps/variable.py](/Users/ghh/Documents/Code/mcpify/research-agent/app/agent/steps/variable.py)

输入：

- `EvidenceRegistry`
- `Evidence[]`

输出：

- `ResearchVariable[]`

作用：

- 把离散 evidence 归并成更稳定的投研变量
- 让系统从“零散证据”过渡到“可判断的变量层”

`ResearchVariable` 核心字段：

- `name`
- `category`
- `value_summary`
- `direction`
- `direction_label`
- `evidence_ids`
- `direction_notes`

一句话理解：

> variable 层回答的是“这些证据合起来说明什么变量在变好 / 变差 / 不明确”。

### Step 11. `coverage`

模块：

- `reason` 前的 coverage 判断
- [app/services/llm_research_depth_qa.py](/Users/ghh/Documents/Code/mcpify/research-agent/app/services/llm_research_depth_qa.py)

输入：

- `Question[]`
- `EvidenceRegistry`
- `ResearchVariable[]`

输出：

- 各维度 coverage / gap 结论

作用：

- 判断研究问题是不是已经被覆盖
- 判断 valuation / industry / moat / financial 是否缺关键证据
- 生成关键 gap

一句话理解：

> coverage 不回答“好不好”，而是回答“研究到位没有”。

### Step 12. `reason`

模块：

- [app/agent/steps/reason.py](/Users/ghh/Documents/Code/mcpify/research-agent/app/agent/steps/reason.py)

输入：

- `Topic`
- `Question[]`
- `EvidenceRegistry`
- `ResearchVariable[]`

输出：

- `Judgment`

作用：

- 形成主结论
- 给出 verified facts / probable inferences / pending assumptions
- 给出风险、缺口、置信度
- 给出下一步 research actions

`Judgment` 关键字段：

- `conclusion`
- `conclusion_evidence_ids`
- `verified_facts`
- `probable_inferences`
- `pending_assumptions`
- `risk`
- `bear_theses`
- `pressure_tests`
- `unknown`
- `evidence_gaps`
- `confidence`
- `confidence_basis`
- `research_actions`
- `positioning`
- `research_scope`
- `peer_context`
- `investment_decision`
- `debug_observability`

一句话理解：

> `reason` 是“把证据转成研究判断”的核心步骤。

### Step 13. `judgment post-process`

模块：

- `reason` 内部后处理
- `dashboard_projector` 内部保守表达约束

输入：

- `Judgment`
- `EvidenceRegistry`
- `depth QA`

输出：

- 降级后的保守 judgment / headline / recommendation text

作用：

- 过滤断裂引用
- 处理 ignored counter evidence
- 处理 unsupported claims
- gap 高时强制收敛表达
- 缺估值 / 竞争数据时强制保守

一句话理解：

> 这一步防止系统“证据没到位，但话说满了”。

### Step 14. `action`

模块：

- [app/agent/steps/action.py](/Users/ghh/Documents/Code/mcpify/research-agent/app/agent/steps/action.py)

输入：

- `Judgment`

输出：

- `ResearchAction[]`

作用：

- 把 evidence gap 变成下一步研究动作

`ResearchAction` 核心字段：

- `id`
- `priority`
- `question`
- `objective`
- `reason`
- `required_data`
- `search_query`
- `query_templates`
- `target_sources`
- `source_targets`
- `status`
- `status_reason`
- `question_id`

一句话理解：

> action 层决定“下一步具体去查什么”。

### Step 15. `auto_research`

模块：

- [app/agent/steps/auto_research.py](/Users/ghh/Documents/Code/mcpify/research-agent/app/agent/steps/auto_research.py)

输入：

- 当前 `Judgment`
- `ResearchAction[]`
- 预算参数

输出：

- `AutoResearchTrace[]`
- 追加的新 `sources/evidence`

作用：

- 在低置信度或高优先级 gap 时做一轮自动补证
- 记录补证过程

`AutoResearchTrace` 关键字段：

- `round_index`
- `triggered`
- `selected_action_ids`
- `executed_queries`
- `new_source_ids`
- `new_evidence_ids`
- `covered_gap_question_ids`
- `effectiveness_status`
- `stop_reason`
- `debug_observability`

一句话理解：

> auto_research 是“有限预算下的自动追证”。

### Step 16. `investment / roles`

模块：

- [app/agent/steps/investment.py](/Users/ghh/Documents/Code/mcpify/research-agent/app/agent/steps/investment.py)
- [app/agent/steps/role.py](/Users/ghh/Documents/Code/mcpify/research-agent/app/agent/steps/role.py)

输入：

- `Judgment`

输出：

- investment layer 结果
- `ResearchRoleOutput[]`

作用：

- 把 judgment 转成研究优先级建议
- 产出多角色复核结果

一句话理解：

> 这层不是买卖建议，而是“研究流程层面的动作建议”。

### Step 17. `dashboard projection`

模块：

- [app/services/dashboard_projector.py](/Users/ghh/Documents/Code/mcpify/research-agent/app/services/dashboard_projector.py)
- [app/services/llm_dashboard_summarizer.py](/Users/ghh/Documents/Code/mcpify/research-agent/app/services/llm_dashboard_summarizer.py)

输入：

- `report_internal`
- `judgment`
- `variables`
- `registry`
- `financial_snapshot`

输出：

- `dashboard_view`

作用：

- 把研究后端产物投影成产品可展示对象
- 控制用户页默认只显示真正需要的信息
- 生成人话 headline / next action / recommendation text
- 生成 `research_memo`

一句话理解：

> projector 负责把“研究结果”变成“产品页面数据”。

### Step 18. `report`

模块：

- [app/agent/steps/report.py](/Users/ghh/Documents/Code/mcpify/research-agent/app/agent/steps/report.py)

输入：

- 全链路对象

输出：

- `ResearchReport`

`ResearchReport` 关键字段：

- `topic`
- `questions`
- `sources`
- `evidence`
- `variables`
- `roles`
- `judgment`
- `report_sections`
- `markdown`
- `report_internal`
- `report_display`

一句话理解：

> report 是统一打包层，把全链路结果组合成可落地的对象。

### Step 19. `streamlit cockpit render`

模块：

- [streamlit_app.py](/Users/ghh/Documents/Code/mcpify/research-agent/streamlit_app.py)

输入：

- `dashboard_view`
- `research_memo`
- `developer_payload`

输出：

- 默认 cockpit 页面

作用：

- 渲染默认页
- 默认折叠 `research_memo`
- 默认折叠开发者模式

注意：

- UI 不做业务逻辑
- UI 不直接消费 raw evidence
- UI 不重算 confidence
- UI 不自己调 LLM 改结论

一句话理解：

> Streamlit 只是 renderer，不是推理层。

## 4. 最重要的数据对象

如果你想快速看懂整个系统，优先看这 8 个对象：

1. `Topic`
2. `Question`
3. `Source`
4. `Evidence`
5. `ResearchVariable`
6. `FinancialSnapshot`
7. `Judgment`
8. `dashboard_view`

它们串起来，就是当前版本的完整认知路径。

## 5. 当前产品化结果

### 默认面向用户

- `dashboard_view`
- `report.report_display`

### 默认折叠

- `research_memo`
- `developer_payload`

### API 返回

定义在：

- [app/api/schemas.py](/Users/ghh/Documents/Code/mcpify/research-agent/app/api/schemas.py)

`ResearchResponse` 当前包含：

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

## 6. 如果你要继续读源码，建议顺序

按这个顺序最容易看懂：

1. [app/agent/pipeline.py](/Users/ghh/Documents/Code/mcpify/research-agent/app/agent/pipeline.py)
2. [app/models/topic.py](/Users/ghh/Documents/Code/mcpify/research-agent/app/models/topic.py)
3. [app/models/question.py](/Users/ghh/Documents/Code/mcpify/research-agent/app/models/question.py)
4. [app/models/source.py](/Users/ghh/Documents/Code/mcpify/research-agent/app/models/source.py)
5. [app/models/evidence.py](/Users/ghh/Documents/Code/mcpify/research-agent/app/models/evidence.py)
6. [app/services/evidence_registry.py](/Users/ghh/Documents/Code/mcpify/research-agent/app/services/evidence_registry.py)
7. [app/models/variable.py](/Users/ghh/Documents/Code/mcpify/research-agent/app/models/variable.py)
8. [app/models/judgment.py](/Users/ghh/Documents/Code/mcpify/research-agent/app/models/judgment.py)
9. [app/services/dashboard_projector.py](/Users/ghh/Documents/Code/mcpify/research-agent/app/services/dashboard_projector.py)
10. [streamlit_app.py](/Users/ghh/Documents/Code/mcpify/research-agent/streamlit_app.py)

这样读，你会先看到“系统怎么想”，再看到“系统怎么展示”。
