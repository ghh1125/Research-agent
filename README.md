# Research Agent

Research Agent 是一个五层投研工作流。用户输入一句自然语言问题后，系统会完成任务理解、真实数据检索、多 Agent 分析、投资判断、估值风控、报告输出和长期记忆沉淀。

这个项目默认调用真实 LLM 和真实检索 API。没有配置可用 API key 时，程序会直接报错，不会用假数据伪造投研结论。

> 说明：本项目输出是投研辅助材料，不构成投资建议。

## 1. 快速开始

进入项目目录：

```bash
cd /research-agent
```

创建并激活虚拟环境：

```bash
python3 -m venv .venv
source .venv/bin/activate
```

安装依赖：

```bash
pip install -r requirements.txt
```

可选：安装 akshare 以获得更完整的 A 股数据（财务报表、行情）：

```bash
pip install akshare
```

复制环境变量模板：

```bash
cp .env.example .env
```

编辑 `.env`，至少填入：

- 一个 LLM Provider key，推荐 `DASHSCOPE_API_KEY`
- 一个 Search Provider key，推荐 `TAVILY_API_KEY`
- 美股官方文件检索建议填写 `SEC_USER_AGENT_EMAIL`

最小运行：

```bash
python main.py "宁德时代还能买吗" --symbols 300750.SZ --market A_share --markdown
```

推荐深度运行：

```bash
python main.py "深度研究宁德时代的行业竞争、财务质量、估值和风险，判断是否值得进一步研究" \
  --symbols 300750.SZ \
  --market A_share \
  --question-type single_stock_deep_dive \
  --depth deep \
  --risk neutral \
  --quick-model deepseek-v4-flash \
  --deep-model deepseek-v4-pro \
  --agents macro,industry,fundamentals,valuation,news_event,technical_positioning \
  --max-agent-tool-rounds 1 \
  --max-followup-queries 4 \
  --max-followup-categories 2 \
  --max-debate-rounds 2 \
  --max-risk-rounds 1 \
  --search-max-results 3 \
  --llm-timeout 120 \
  --checkpoint \
  --markdown
```

## 2. 运行时会看到什么

默认会在终端显示进度，例如：

```text
[runtime] LLM quick=[dashscope:deepseek-v4-flash] deep=[dashscope:deepseek-v4-pro]
[runtime] Search tavily
[step 1/5] 任务理解与研究规划 start
[step 2/5] 数据检索与证据沉淀 start
[step 3/5] 多 Agent 专项分析 start
[step 4/5] 投资判断、估值与风险裁决 start
[step 5/5] 报告输出、记忆复盘与持续跟踪 start
```

进度日志写到 `stderr`，最终 Markdown 或 JSON 写到 `stdout`。这意味着你可以把最终报告重定向到文件，同时仍然在屏幕上看到运行进度：

```bash
python main.py "宁德时代还能买吗" --symbols 300750.SZ --market A_share --markdown > report.md
```

不想看进度日志时使用：

```bash
python main.py "宁德时代还能买吗" --quiet --markdown
```

## 3. 五层主流程

```text
用户问题
  -> 1. 任务理解与研究规划
  -> 2. 数据检索与证据沉淀
  -> 3. 多 Agent 专项分析
  -> 4. 投资判断、估值与风险裁决
  -> 5. 报告输出、记忆复盘与持续跟踪
```

以下用一个真实例子贯穿每一步：用户输入 `"深度研究宁德时代财务质量、竞争格局和估值"，--symbols 300750.SZ --market A_share --depth deep`。

---

### 第 1 步：任务理解与研究规划

**在做什么：** 把一句自然语言问题变成一张结构化的"研究任务单"，再根据任务单列出需要调查的维度。

**类比：** 用户打了一个电话给研究主任，主任在白板上写下研究对象、市场、类型和周期，然后列出要查哪些方向、从哪些数据源取证。

**这一步具体发生了什么：**

1. 系统把 `"深度研究宁德时代财务质量、竞争格局和估值"` 解析成标准化 `ResearchTask`，自动识别出：
   - `symbols = 300750.SZ`，`market = A_share`
   - `question_type = single_stock_deep_dive`（单只股票深度研究）
   - `research_depth = deep`，`horizon = 6-12个月`，`risk_preference = neutral`

2. 如果之前研究过宁德时代，系统会先读取历史记忆（上次评级、关键假设），作为本次规划的参考背景。

3. 生成 `ResearchPlan`，明确六个研究维度（宏观/行业/基本面/估值/新闻事件/技术面），以及每个维度要用哪些数据源（财报、行情、公告、行业报告等）。

**输出：** 一张结构化的任务单和研究维度清单，后续所有 Agent 都基于这张单子工作。

---

### 第 2 步：数据检索与证据沉淀

**在做什么：** 去真实数据源把资料拿回来，每条数据都贴上来源标签存档，绝不让模型凭空捏造数字。

**类比：** 研究助理去彭博、巨潮、公司官网拿财报、行情和公告，每一条都夹进资料夹，注明"来源、时间、可信度"。

**这一步具体发生了什么（以宁德时代为例）：**

1. `YFinanceMarketDataTool` 拉取 300750.SZ 过去一年日线行情，并自动计算 MA20、MA60、RSI-14、52 周高低点、波动率，附在行情数据后面。
2. `YFinanceFinancialStatementsTool` 拉取利润表、资产负债表、现金流表。
3. `YFinanceValuationTool` 拉取 Forward PE、Trailing PE、EV/EBITDA 等估值倍数，以结构化 JSON 格式输出，后续估值模块直接解析使用。
4. `CNInfoFilingsTool` 访问巨潮信息网，检索 300750 的最新公告和年报文件链接。
5. 安装 akshare 后，`AKShareMarketDataTool` 和 `AKShareFinancialStatementsTool` 额外补充 A 股近年完整行情和财报数据，本次实测 artifacts 从 8 增至 11，evidence 从 4 增至 8。
6. 原生工具不够时，自动 fallback 到搜索引擎（Tavily/Serper/Google），补充新闻、行业报告等非结构化资料。

每条数据都沉淀为带有 `artifact_id`、`source_url`、`quality`（high/medium/low）标签的证据，写入本地 knowledge directory，可追溯、可复查。

**输出：** 11 条 artifact，8 条结构化 evidence，覆盖行情、财报、公告、估值、行业新闻。

---

### 第 3 步：多 Agent 专项分析

**在做什么：** 把资料分发给 6 个不同专业背景的分析师，每人只看自己领域内的证据，各写一份子报告；然后强制开一场多空辩论。

**类比：** 召开内部分析会。宏观组看利率政策，行业组看电池市占率，基本面组看财报，估值组算 PE，新闻组盯公告——各自交报告。然后让多头分析师和空头分析师当面辩，逼出"哪条逻辑最脆弱"。

**这一步具体发生了什么（以宁德时代为例）：**

1. 六位分析师各自生成结构化子报告（结论、关键点、引用的 evidence_id、置信度、待验证问题）：
   - `Macro Analyst`：中国货币政策宽松，锂矿价格下行周期有利于毛利率回升
   - `Industry Analyst`：2025 年全球动力电池市占率 39.2%，但数据来源单一
   - `Fundamentals Analyst`：财报数据不完整，非经常性损益占比存疑
   - `Valuation Analyst`：Forward PE 19.23x，但 2026 年远期 PE 仅 9.8x，存在矛盾
   - `News/Event Analyst`：海外工厂（德国/匈牙利）进展，IRA 法案 FEOC 条款悬而未决
   - `Technical Analyst`：MA20/MA60 金叉，RSI-14 处于中性区间

2. 进入多空辩论（`--max-debate-rounds 2`，共 4 轮发言）：
   - 多头：市占率新高 + Forward PE 低估，构成逆向买点
   - 空头：财务数据缺失 + 估值矛盾，信息真空期不应贸然入场

3. 如果分析师发现证据缺口，系统自动补充检索（`followup_queries`），例如补充搜索"2025 Q2 全球动力电池市占率数据"，再更新子报告。

**输出：** 4 份分析师报告 + 4 轮多空辩论记录，全部结构化，供下一步决策使用。

---

### 第 4 步：投资判断、估值与风险裁决

**在做什么：** 三层决策把分歧收敛成最终投资判断——先由研究主管拍板，再由估值师算目标价，最后由风控团队从不同立场再审一遍。

**类比：** 辩论会结束后，研究总监综合各方观点给出初步评级；CFO 算三种情景下的合理价格；风控合规再问一遍"最坏情况是什么"；基金经理给出仓位建议。

**这一步具体发生了什么（以宁德时代为例）：**

1. **Research Manager**：综合 6 份子报告和 4 轮辩论，给出 `ManagerDecision`——评级"观察"，核心逻辑是"财务数据缺失导致无法验证假设"，最脆弱假设是"市占率 39.2% 数据点来源单一"。

2. **Valuation Scenario**：生成 base/bull/bear 三情景估值：
   - Base（基准）：目标价 336.90，基于 Forward PE 19.23x
   - Bull（乐观）：目标价 404.28，假设年报验证毛利率回升 + PE 扩张
   - Bear（悲观）：目标价 269.52，假设盈利下修 + 估值收缩
   - 安全边际：低于 base 情景 336.90 才有安全边际

3. **Risk Debate**（1 轮，3 个视角）：
   - Aggressive：信息真空是逆向机会，年报一旦落地股价有强烈修复动能
   - Conservative：数据真空掩盖永久损失风险，任何仓位都是赌博
   - Neutral（被采纳）：赔率不可计算，应等待年报作为信息套利触发点

4. **Portfolio Manager**：最终决策 `action = 观察`，仓位建议 = 0，revisit_trigger = "2024 年报毛利率 >25% 且经营现金流/净利润 >1"。

**输出：** 评级观察，目标价区间 269.52–404.28，明确的重新评估触发条件。

---

### 第 5 步：报告输出、记忆复盘与持续跟踪

**在做什么：** 生成机构格式投研报告；把这次判断存入记忆；自动生成后续跟踪警报，下次研究同一标的时用历史判断校准新结论。

**类比：** 报告发出去之后，助理在数据库里记一笔："2026 年 5 月，观察，假设是毛利率 >25%，价格触发条件是年报验证"。三个月后再研究宁德时代，先翻上次档案，看假设有没有被证伪，上次判断对没对。

**这一步具体发生了什么（以宁德时代为例）：**

1. **报告渲染**：生成机构化 Markdown 报告，包含 11 个固定 section：结论先行、评级、目标价/估值区间、投资逻辑、关键假设、催化剂、风险、反方观点、多空辩论摘要、跟踪指标、数据来源、下一步研究问题。

2. **记忆写入**：把 `task_id`、`entity=宁德时代`、`rating=观察`、`key_assumptions`、当时股价、`revisit_triggers` 写入 `data/research_memory/memory.jsonl`。

3. **跟踪警报生成**：自动生成实体特定的监控项，包括：
   - 财报复盘警报：下次年报发布后自动提醒重查毛利率、现金流假设
   - 价格触发警报：基于 portfolio_decision 的 revisit_trigger
   - 脆弱假设监控：`市占率 39.2% 数据点来源单一` → 若被证伪立即更新研究
   - 核心指标警报（来自 manager 的 tracking_metrics）：市占率、毛利率、经营现金流比率等

4. **跨次学习**：下次再输入 `"宁德时代 2025 年报出来了，重新评估"` 时，系统会先读取这条记忆，注入研究规划（"上次评级观察，假设是毛利率 >25%，现在验证一下"）和研究经理决策，避免重复同样的信息真空问题。

**输出：** 机构化 Markdown 报告 + 本地记忆存档 + 跟踪警报清单。

## 4. main.py 参数说明

主入口是 `main.py`：

```bash
python main.py "<一句自然语言投研问题>" [参数]
```

### 任务参数

| 参数 | 是否必填 | 默认值 | 说明 | 示例 |
| --- | --- | --- | --- | --- |
| `query` | 必填 | 无 | 用户的一句话投研问题。也可以不传，程序会交互式提示输入。 | `"宁德时代还能买吗"` |
| `--symbols` | 推荐填写 | LLM 自动识别 | 逗号分隔的标的代码。A 股建议带交易所后缀。 | `--symbols 300750.SZ,NVDA` |
| `--market` | 推荐填写 | LLM 自动识别 | 市场或资产范围。 | `--market A_share`、`--market US`、`--market HK` |
| `--horizon` | 可选 | LLM 自动识别 | 投资周期。 | `--horizon 6-12个月` |
| `--time-range` | 可选 | 当前上下文 | 研究日期或时间区间。 | `--time-range 2026-05-10` |
| `--question-type` | 可选 | LLM 自动分类 | 问题类型。可选值见下方。 | `--question-type single_stock_deep_dive` |
| `--depth` | 可选 | `standard` | 研究深度。可选 `quick`、`standard`、`deep`。 | `--depth deep` |
| `--risk` | 可选 | `neutral` | 用户风险偏好。可选 `conservative`、`neutral`、`aggressive`。 | `--risk conservative` |

`--question-type` 可选值：

- `single_stock_deep_dive`：单只股票深度研究
- `industry_comparison`：行业比较
- `event_impact`：事件影响分析
- `portfolio_risk_review`：组合风险复盘
- `trading_decision_assist`：交易决策辅助

### Agent 和模型参数

| 参数 | 是否必填 | 默认值 | 说明 | 示例 |
| --- | --- | --- | --- | --- |
| `--agents` | 可选 | 全部启用 | 逗号分隔 selected analysts。 | `--agents macro,industry,fundamentals,valuation,news_event,technical_positioning` |
| `--model-profile` | 可选 | `default` | 写入任务对象的模型配置名，便于记录不同运行配置。 | `--model-profile production` |
| `--quick-model` | 可选 | `.env` 中 quick 配置 | 快模型，用于任务解析、研究计划、证据抽取。 | `--quick-model deepseek-v4-flash` |
| `--deep-model` | 可选 | `.env` 中 deep 配置 | 强模型，用于专项分析、辩论、裁决和报告判断。 | `--deep-model deepseek-v4-pro` |
| `--output-language` | 可选 | `zh-CN` | 输出语言。 | `--output-language zh-CN` |

quick/deep 只是路由标签，不强制必须用两个不同模型。你可以让两者都指向同一个模型；也可以用快模型处理高频轻任务，用强模型处理推理更重的任务。

### 辩论和补检索参数

| 参数 | 是否必填 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `--max-debate-rounds` | 可选 | `2` | Bull/Bear 多空辩论轮数。 |
| `--max-risk-rounds` | 可选 | `1` | aggressive/neutral/conservative 风控辩论轮数。 |
| `--max-agent-tool-rounds` | 可选 | `1` | 专项 Agent 发现证据缺口后的补充检索轮数。 |
| `--max-followup-queries` | 可选 | `6` | 每轮补检索最多 query 数，防止模型生成过多搜索。 |
| `--max-followup-categories` | 可选 | `3` | 每轮补检索最多数据源类别数。 |

### 检索和抓取参数

| 参数 | 是否必填 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `--search-max-results` | 可选 | `5` | 每类数据源最多检索结果数。 |
| `--fetch-source-content` | 可选 | 关闭 | 对搜索结果 URL 继续抓取网页/PDF 全文。默认关闭，避免慢站点导致长时间等待。 |
| `--source-fetch-timeout` | 可选 | `5.0` | 启用 `--fetch-source-content` 后，单个 URL 抓取超时秒数。 |
| `--llm-timeout` | 可选 | `.env` 中 `LLM_TIMEOUT_SECONDS` | 单次 LLM 请求超时秒数。会覆盖环境变量。 |

默认不抓取搜索结果 URL 全文。搜索 API 返回的标题、摘要、正文片段仍会进入证据链。只有需要更完整网页或 PDF 内容时，才建议打开 `--fetch-source-content`。

### 输出和恢复参数

| 参数 | 是否必填 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `--json` | 可选 | 关闭 | 输出完整 `ResearchResult` JSON。 |
| `--markdown` | 可选 | 关闭 | 只输出 Markdown 报告。 |
| `--checkpoint` | 可选 | 关闭 | 启用阶段断点，失败时保留 checkpoint，后续可恢复。 |
| `--quiet` | 可选 | 关闭 | 关闭进度日志，只输出最终结果。 |

不加 `--json` 或 `--markdown` 时，终端只输出简短摘要，包括任务类型、标的、组合建议、评级和报告路径。

`--checkpoint` 主要用于长任务排查和失败恢复。任务成功完成后，默认会清理成功 checkpoint；完整结果始终写入 `data/research_logs/`。

## 5. 环境变量说明

`.env.example` 已经写了完整模板。实际运行时复制为 `.env` 后填写真实 key。

### 必填项

| 变量 | 是否必填 | 说明 |
| --- | --- | --- |
| `LLM_PROVIDER` | 必填 | LLM 主 Provider。可选 `auto`、`dashscope`、`openai`、`openrouter`、`deepseek`。推荐先用 `dashscope`。 |
| `LLM_TIMEOUT_SECONDS` | 必填 | 单次 LLM 请求超时秒数。真实投研建议 `120` 到 `180`。 |
| `DASHSCOPE_API_KEY` 或其他 LLM key | 必填其一 | 至少配置一个 LLM Provider key。 |
| `TAVILY_API_KEY` 或其他 Search key | 必填其一 | 至少配置一个 Search Provider key。 |

### DashScope 配置

| 变量 | 是否必填 | 说明 |
| --- | --- | --- |
| `DASHSCOPE_API_KEY` | 推荐必填 | 阿里云百炼/DashScope API key。 |
| `DASHSCOPE_BASE_URL` | 推荐保留默认 | OpenAI-compatible endpoint。 |
| `DASHSCOPE_MODEL` | 可选 | 默认模型，quick/deep 没配置时才使用。 |
| `DASHSCOPE_QUICK_MODEL` | 推荐填写 | 快模型，例如 `deepseek-v4-flash`。 |
| `DASHSCOPE_DEEP_MODEL` | 推荐填写 | 强模型，例如 `deepseek-v4-pro`。 |

如果遇到 `AllocationQuota.FreeTierOnly`，说明模型免费额度或控制台权限限制，不是代码问题。需要在控制台关闭“仅使用免费额度”或换成已开通的模型。

### 其他 LLM Provider

| 变量 | 是否必填 | 说明 |
| --- | --- | --- |
| `OPENAI_API_KEY` | 可选 | 使用 OpenAI 时填写。 |
| `OPENAI_BASE_URL` | 可选 | 兼容 OpenAI API 的自定义地址。 |
| `OPENAI_MODEL` | 可选 | OpenAI 默认模型。 |
| `OPENAI_QUICK_MODEL` | 可选 | OpenAI 快模型。 |
| `OPENAI_DEEP_MODEL` | 可选 | OpenAI 强模型。 |
| `OPENROUTER_API_KEY` | 可选 | 使用 OpenRouter 时填写。 |
| `OPENROUTER_BASE_URL` | 可选 | OpenRouter API 地址。 |
| `OPENROUTER_MODEL` | 可选 | OpenRouter 模型名。 |
| `DEEPSEEK_API_KEY` | 可选 | 使用 DeepSeek 官方 API 时填写。 |
| `DEEPSEEK_BASE_URL` | 可选 | DeepSeek API 地址。 |
| `DEEPSEEK_MODEL` | 可选 | DeepSeek 模型名。 |
| `LLM_FALLBACK_PROVIDERS` | 可选 | 备用 Provider 顺序，例如 `openai,openrouter`。 |

### Search Provider

| 变量 | 是否必填 | 说明 |
| --- | --- | --- |
| `TAVILY_API_KEY` | 推荐必填 | Tavily 搜索 API key，默认优先使用。 |
| `TAVILY_BASE_URL` | 推荐保留默认 | Tavily endpoint。 |
| `SERPER_API_KEY` | 可选备用 | Serper Google Search API key。 |
| `SERPER_BASE_URL` | 可选 | Serper endpoint。 |
| `GOOGLE_SEARCH_API_KEY` | 可选备用 | Google Custom Search API key。 |
| `GOOGLE_SEARCH_CX` | 可选备用 | Google Custom Search CX。 |
| `GOOGLE_SEARCH_BASE_URL` | 可选 | Google Custom Search endpoint。 |

### 官方文件数据源

| 变量 | 是否必填 | 说明 |
| --- | --- | --- |
| `SEC_USER_AGENT_EMAIL` | 推荐填写 | SEC 官方接口要求 User-Agent 中包含可联系邮箱。研究美股 filings/companyfacts 时会用到。 |

## 6. 常用命令

单只 A 股深度研究：

```bash
python main.py "深度研究宁德时代的财务质量、行业竞争、估值和风险" \
  --symbols 300750.SZ \
  --market A_share \
  --question-type single_stock_deep_dive \
  --depth deep \
  --markdown
```

美股研究：

```bash
python main.py "研究英伟达的增长质量、估值和主要风险" \
  --symbols NVDA \
  --market US \
  --depth deep \
  --markdown
```

行业比较：

```bash
python main.py "比较中国动力电池行业龙头公司的竞争格局和盈利质量" \
  --symbols 300750.SZ,002594.SZ \
  --market A_share \
  --question-type industry_comparison \
  --markdown
```

事件影响分析：

```bash
python main.py "分析某项产业政策对新能源车产业链利润分配的影响" \
  --market A_share \
  --question-type event_impact \
  --depth standard \
  --markdown
```

输出完整 JSON：

```bash
python main.py "宁德时代还能买吗" --symbols 300750.SZ --market A_share --json
```

提高稳定性，减少外部抓取：

```bash
python main.py "宁德时代还能买吗" \
  --symbols 300750.SZ \
  --market A_share \
  --search-max-results 3 \
  --max-followup-queries 3 \
  --max-followup-categories 2 \
  --llm-timeout 180 \
  --markdown
```

需要网页/PDF 全文时：

```bash
python main.py "研究某公司最新年报和公告中的风险因素" \
  --symbols NVDA \
  --market US \
  --fetch-source-content \
  --source-fetch-timeout 8 \
  --markdown
```

## 7. 运行产物

运行产物默认写在 `data/` 目录：

| 路径 | 内容 |
| --- | --- |
| `data/research_logs/*.json` | 完整研究结果，包括 task、plan、evidence、agent reports、debate、decision、report。 |
| `data/research_memory/memory.jsonl` | 历史研究记忆，包括当时价格、关键假设、跟踪项和复盘状态。 |
| `data/knowledge/records.jsonl` | 证据链记录，包括来源、metadata、URL、摘要和 artifact id。 |
| `data/checkpoints/*.json` | 启用 `--checkpoint` 后的阶段断点。 |

这些运行产物不会提交到 Git。`.env` 也不会提交到 Git。

## 8. 代码结构

```text
main.py
research_flow/
  graph.py                 # 五层工作流编排，memory_context 贯穿规划和裁决阶段
  schema.py                # 核心 Pydantic schema（ResearchTask、ScenarioAnalysis 等）
  llm.py                   # OpenAI-compatible LLM Provider 路由（DashScope/OpenAI/OpenRouter/DeepSeek）
  understanding/           # 任务解析和研究计划，支持历史记忆注入
  evidence/
    tools.py               # 8 个原生数据工具：yfinance 行情+技术指标、yfinance 财务报表、
                           # yfinance 估值指标、akshare A股行情（可选）、akshare A股财报（可选）、
                           # CNInfo A股公告、SEC EDGAR 美股公告、HKEX 港股公告
    registry.py            # DataToolRegistry，原生工具优先 + 搜索兜底
    search.py              # 多 Search Provider 路由（Tavily/Serper/Google）
    knowledge.py           # 证据链沉淀
  analysis/                # 多 Agent 专项分析和 Bull/Bear 辩论
  decision/
    synthesis.py           # Research Manager、ScenarioAnalysis、风险辩论、Portfolio Manager
  valuation/
    models.py              # 三路径估值指标提取 + base/bull/bear 情景计算
  continuity/
    watchlist.py           # 实体绑定的跟踪警报生成
    memory.py              # 记忆读写和 P&L 复盘
    report.py              # 机构化报告渲染
    checkpoint.py          # 阶段断点读写
tests/
  test_main_flow.py
  test_research_flow_contracts.py
  test_equivalence_extensions.py
```

## 9. 测试

运行单元测试：

```bash
python -m pytest -q
```

语法检查：

```bash
python -m compileall main.py research_flow tests
```

检查 CLI 参数：

```bash
python main.py --help
```

## 10. 常见问题

### LLM 请求超时

报错示例：

```text
APITimeoutError: Request timed out.
```

处理方式：

- 增加超时：`--llm-timeout 180`
- 使用更快的 quick 模型：`--quick-model deepseek-v4-flash`
- 降低检索和补检索规模：`--search-max-results 3 --max-followup-queries 3`

### DashScope 免费额度限制

报错示例：

```text
AllocationQuota.FreeTierOnly
```

处理方式：

- 在 DashScope/百炼控制台关闭“仅使用免费额度”
- 换成账号已开通的模型
- 配置其他 LLM Provider 作为备用

### A 股价格提示 possibly delisted

`yfinance` 对部分 A 股代码可能返回：

```text
possibly delisted; no price data found
```

这通常是数据源覆盖问题。推荐安装 akshare 作为补充：

```bash
pip install akshare
```

安装后 `AKShareMarketDataTool` 和 `AKShareFinancialStatementsTool` 会自动启用，提供 A 股近年完整行情和财务数据，大幅改善证据覆盖。未安装时流程仍会继续，但 A 股财务指标会有缺失。

### 运行很慢

优先不要开启 `--fetch-source-content`。如果已经开启，可以降低：

```bash
--source-fetch-timeout 5 --search-max-results 3 --max-followup-queries 3
```

### checkpoint 跑完后看不到

成功完成后默认清理成功 checkpoint，避免下次误恢复旧中间态。完整结果看：

```text
data/research_logs/<task_id>.json
```

失败或中断时，checkpoint 会保留在：

```text
data/checkpoints/<task_id>.json
```
