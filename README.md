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

### 1. 任务理解与研究规划

系统会把自然语言问题解析成标准化 `ResearchTask`，包括：

- `symbols`：股票代码或研究标的
- `market`：市场，例如 `A_share`、`US`、`HK`
- `time_range`：研究日期或区间
- `horizon`：投资周期
- `question_type`：问题类型
- `research_depth`：研究深度
- `risk_preference`：风险偏好
- `output_format`：输出形式

然后生成 `ResearchPlan`，明确要研究的维度、需要调用的数据源、关键假设和证据缺口。

### 2. 数据检索与证据沉淀

系统会通过 `DataToolRegistry` 调用真实数据工具：

- `market_data`：行情、价格、成交量、技术指标
- `financial_statements`：利润表、资产负债表、现金流、关键财务指标
- `filings`：公告、年报、季报、SEC 文件、A 股公告
- `news`：新闻、事件、管理层动态、行业新闻
- `macro`：利率、汇率、政策、周期、宏观数据
- `industry`：行业格局、供需、产业链、竞争对手
- `valuation`：估值倍数、可比公司、历史估值、情景估值输入

每次工具调用都会沉淀 artifact、metadata、来源链接和证据摘要，写入本地 knowledge directory，方便后续报告引用和复查。

### 3. 多 Agent 专项分析

拿到证据后，系统不会让一个模型一次性写完整报告，而是分工分析：

- `Macro Analyst`：宏观、政策、利率、汇率、周期
- `Industry Analyst`：行业供需、竞争格局、产业链、同业比较
- `Fundamentals Analyst`：收入、利润、现金流、资产负债表、财务质量
- `Valuation Analyst`：DCF、可比公司、历史估值、三情景估值
- `News/Event Analyst`：近期新闻、公告、事件影响、催化剂
- `Technical/Positioning Analyst`：价格趋势、波动、成交、技术面辅助判断

之后系统会强制进入多空辩论：

- `Bull Researcher`：生成看多逻辑、上行空间、关键催化剂
- `Bear Researcher`：生成看空逻辑、下行风险、证伪路径
- Debate Controller：按 `--max-debate-rounds` 控制辩论轮数

### 4. 投资判断、估值与风险裁决

多 Agent 子报告和多空辩论完成后，系统会继续生成：

- `Research Manager Decision`：评级、核心逻辑、关键假设、最脆弱假设、置信度
- `Valuation Scenario`：base、bull、bear 三情景估值、目标价区间、安全边际
- `Risk Debate`：aggressive、neutral、conservative 三种风控视角
- `Portfolio Decision`：可买、观察、回避、减仓、可小仓位跟踪等组合语境建议

估值模块会优先使用证据中抽取到的 EPS、P/E、Sales、P/S 等结构化指标做计算；证据不足时会在报告中明确数据缺口。

### 5. 报告输出、记忆复盘与持续跟踪

最终输出是机构化投研报告，而不是普通聊天回答。报告包括：

- 结论先行
- 投资评级
- 目标价或估值区间
- 投资逻辑
- 关键假设
- 催化剂
- 风险
- 反方观点
- 跟踪指标
- 数据来源
- 下一步研究问题

报告生成后，系统会把本次判断、当时价格、关键假设、后续跟踪项写入本地记忆。后续再次运行同一标的时，会先读取历史记忆，并尝试复盘前次判断是否被新事实证伪。

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
  graph.py                 # 五层工作流编排
  schema.py                # ResearchTask、ResearchPlan、ResearchResult 等核心 schema
  llm.py                   # OpenAI-compatible LLM Provider 路由
  understanding/           # 任务解析和研究计划
  evidence/                # DataToolRegistry、搜索、公告、财报、知识库沉淀
  analysis/                # 多 Agent 专项分析和 Bull/Bear 辩论
  decision/                # Research Manager、风险辩论、Portfolio Manager
  valuation/               # base/bull/bear 三情景估值
  continuity/              # 报告、记忆、复盘、持续跟踪、checkpoint
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

这通常是数据源覆盖问题。流程仍会继续使用公告、新闻、行业、宏观、估值等证据；但当时价格和部分技术指标会缺失。可以通过更多官方公告、搜索资料或后续接入本地行情源改善。

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
