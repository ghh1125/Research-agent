# VC BP 尽调 Pipeline

一级市场投资项目（BP/早期项目）尽调自动化 pipeline，按 7 个主节点顺序执行（竞品节点拆为 3.1 竞品发现和 3.2 竞品矩阵分析）：

```text
开始 → 项目基本概况 → 行业深度分析 → 竞品发现 → 竞品矩阵分析 → 深度尽调 → 估值分析 → 综合研判与报告输出
```

每个产出报告的节点都会写出 `report.md` + `report.docx`，节点之间用结构化 Pydantic 模型传递数据。**默认调用真实 LLM 和真实搜索 API；没有配置 key 时会直接报错退出，绝不会用假数据伪造尽调结论。**

---

## 0. 整体运行逻辑（先看这一节）

网页端和命令行使用同一套分析节点，但网页端会在竞品报告生成后额外暂停一次，让用户先看报告、再上传尽调材料：

```text
第 0+1 段：自动跑 2 个节点
  开始 → 项目基本概况
  输入：你填的公司信息（+ 可选 BP 文件）

【人工节点 1】项目基本概况复核
  看一下生成结果：没问题就继续；不满意可以写反馈，系统按反馈重新生成这一步（可以反复改）

第 2 段：自动跑 1 个节点
  行业深度分析

【人工节点 2】行业深度分析复核
  同上：看结果 → 没问题继续 / 写反馈重新生成

第 3.1 段：自动跑 1 个节点
  竞品发现 → 输出候选竞品 longlist

【人工节点 3】竞品确认
  从候选竞品里勾选/选择哪些要纳入分析（可以全选/全不选）

第 3.2 段：只运行竞品矩阵分析
  对全部已选竞品生成一份统一的竞品矩阵分析报告

【网页端停靠点】只读展示竞品矩阵报告
  可以查看/下载报告；点击"进入深度尽调"后才显示材料上传页

【网页端停靠点】补充尽调材料
  上传 5 类材料（团队/财务/商业计划书/技术与知识产权/法律，全部选填）

第 4-6 段：自动跑剩余节点
  深度尽调（5 份子报告 + 1 份汇总报告）→ 估值分析 → 综合研判与报告输出
  输出：每个节点一份 report.md + report.docx，最后一份是给投委会看的完整投研报告
```

前三个人工节点的性质不一样：**项目概况、行业分析这两处是"复核+反馈重新生成"**（生成结果可能有错，让你纠正后再继续，不满意可以反复改），**竞品确认是"筛选判断"**（LLM 找到的候选名单里哪些真的算竞品，只能人来判断，不存在"重新生成"，只有选不选）。竞品报告展示页是只读停靠点，不提供反馈重新生成功能。

CLI 默认仍只在项目概况、行业分析和竞品确认三处等待操作；尽调材料通过命令行参数提前传入，因此竞品确认后会连续执行竞品分析和后续节点。想跳过前两处直接全自动跑，加 `--auto-approve-reports`；想跳过竞品确认直接自动选前 N 个，加 `--auto-select-competitors`。

两种用法的区别只是"怎么触发 + 怎么在人工节点交互"：

| | 网页端（Streamlit） | 命令行（CLI） |
| --- | --- | --- |
| 触发方式 | 填表单点"开始尽调" | 跑 `python main.py "公司名" ...` |
| 项目概况/行业分析复核怎么交互 | 页面显示报告 + 反馈输入框，"按反馈重新生成"或"确认继续"两个按钮 | 终端打印报告全文，直接回车=确认继续，输入文字=按反馈重新生成；加 `--auto-approve-reports` 完全跳过 |
| 竞品确认怎么交互 | 勾选竞品并生成矩阵报告；查看报告后再进入独立的尽调材料上传页 | 终端提示你输入要纳入的竞品编号；加 `--auto-select-competitors` 完全跳过 |
| 产物在哪看 | 页面上直接展开查看 + 下载按钮 | 写到 `--output-dir` 指定的目录，文件自己去看 |
| 适合谁 | 不熟悉命令行、需要边看边操作 | 批量跑多个项目、接入脚本/CI（建议都加上 `--auto-approve-reports --auto-select-competitors`） |

下面第 2 节是网页端详细步骤，第 3 节是命令行详细步骤，挑一种看就够了；第 4 节往后是给想了解内部细节的人看的（七节点输入输出、代码结构等），不看也完全不影响使用。

---

## 1. 环境准备（第一次使用必做）

### 1.1 克隆并进入项目

```bash
git clone https://github.com/ghh1125/Research-agent.git
cd Research-agent
```

### 1.2 创建虚拟环境并安装依赖

```bash
python3 -m venv .venv
source .venv/bin/activate          # Windows 用 .venv\Scripts\activate
pip install -r requirements.txt
```

### 1.3 配置 API Key

这一步只对 **CLI**（第 3 节）生效。**网页版**（第 2 节，包括部署到 Streamlit Community Cloud）不读 `.env` 里的 key，每个访问者要在网页左侧栏自己填一份，见 2.1 节说明——这样部署给别人用时，消耗的是访问者自己的 API 额度，不会扣到部署者账上。

```bash
cp .env.example .env
```

打开 `.env`，至少填两个 key：

| 变量 | 用途 | 去哪儿拿 |
| --- | --- | --- |
| `DASHSCOPE_API_KEY` | LLM（推荐用阿里云百炼/DashScope，OpenAI 兼容接口） | 阿里云百炼控制台 |
| `SERPER_API_KEY` | 搜索（中文工商信息/行业新闻/竞品资料覆盖更全，比 Google CSE 配额宽松） | serper.dev 注册 |

不填会怎样：跑到第一个需要 LLM 或搜索的节点时直接报 `RuntimeError`，并提示该配哪个变量——这是有意设计的，目的是不让系统在没有真实数据时悄悄编造结论。

`.env` 已经在 `.gitignore` 里，不会被提交到 Git；只有不含真实 key 的 `.env.example` 会被跟踪。

### 1.4（可选）验证环境装好了

```bash
python -m pytest -q          # 跑离线单测，不消耗真实 API 额度
```

全部通过说明代码本身没问题；如果要验证 API key 是否真的能用，直接跑下面第 2 步或第 3 步的最小示例即可。

---

## 2. 网页端完整使用流程（推荐，分步向导）

### 2.1 启动

```bash
streamlit run app.py
```

终端会打印一个本地地址（默认 `http://localhost:8501`，被占用时会自动换成 8502 等），浏览器打开它。

打开页面后，**先在左侧栏填两个 API Key**（DashScope + Serper），不填的话下面表单的"开始尽调"按钮是灰的点不动。这两个 key 只存在你这次浏览器会话的内存里，不会写进任何文件、不会上传、不会被其他访问者看到或共用——每个人用自己的 key，互不影响、互不可见。

### 2.2 第 0 步：填写项目基本信息

页面顶部表单，逐项说明：

| 字段 | 必填 | 说明 |
| --- | --- | --- |
| 公司名称 | 是 | 后续所有检索、分析都以这个名字为主体 |
| 官网 | 否 | 没有可留空 |
| 融资轮次 | 否 | 种子轮/天使轮/A轮/B轮/C轮/Pre-IPO；影响估值节点用哪种方法 |
| 融资金额 | 否 | 用于估值节点反推隐含估值 |
| 所属行业 | 否 | 影响行业分析和竞品发现的检索方向 |
| 项目描述 | 否 | 一句话说清楚项目在做什么；没有 BP 时建议必填，否则后面节点信息会很空 |
| BP 文件 | 否 | 支持 PDF/PPT/Word，多选；会自动解析文本，补全上面留空的字段 |

填完点 **"开始尽调"**。这一步会自动跑：

1. **开始** — 把表单和 BP 解析结果归一化成结构化字段，缺什么字段会在页面上提示（比如"融资金额没有识别到"）。
2. **项目基本概况** — 调 LLM + 搜索，生成工商信息/发展历程/主营业务/产品体系/落地场景/组织架构/创始团队 7 个模块。

跑完这两步会停下来，进入下一节的人工复核。

### 2.3 第 1、2 个人工节点：项目基本概况 / 行业深度分析复核

页面会显示生成的项目基本概况全文，下方有一个反馈输入框和两个按钮：

- **不满意**：在反馈框里写清楚要改什么（比如"公司注册信息那段写错了，再确认一下"），点 **"按反馈重新生成"**，系统会带着这条反馈重新调用 LLM 生成这一步，新结果会替换掉旧的，可以反复改到满意为止
- **没问题**：反馈框留空，直接点 **"确认继续，跑行业深度分析"**

确认后会自动跑"行业深度分析"，跑完同样停下来，进入下一个人工节点（操作方式完全一样，反馈框 + 两个按钮，不另外展开说明）。行业深度分析确认后才会自动跑"竞品发现"，列出候选竞品进入下一节。

这两个节点单次生成耗时几十秒到 1~2 分钟，重新生成会重新计一次。

### 2.4 第 3 个人工节点：确认竞品并生成矩阵报告

页面会列出候选竞品，每条带"关系"（直接竞品/潜在竞品/替代方案）和产品简述，默认全部勾选。你需要做的事：

- 取消勾选你觉得不相关的候选
- 全部取消勾选 = 生成一份明确标注"跳过竞品矩阵分析"的报告
- 这里没有"添加自定义竞品"功能，只能从 LLM 找到的 longlist 里选

点 **"生成竞品矩阵分析报告"** 后，这一步只运行竞品矩阵分析，不会启动深度尽调。

#### 选择多个竞品时如何分析

选择多个竞品后，程序会：

1. 按竞品逐个检索产品与客户案例、商业化与融资、技术与专利等公开证据。
2. 完整保留搜索接口返回的全部证据文本，不在竞品分析节点做字符裁剪。
3. 每个竞品单独调用一次 LLM，输出画像、相对优劣和五维矩阵字段；逐家分析按顺序执行，不并行。
4. 程序确定性合并全部逐家结果，再调用一次汇总 LLM 生成竞争格局、SWOT 和定位判断。
5. 选择 N 个竞品时共调用 N+1 次 LLM，最终生成一份统一报告。

每个竞品的原始搜索证据只进入该竞品自己的 Prompt，汇总 Prompt 读取结构化结果而不重复塞入全部原始证据。

### 2.5 查看逐家结果并审核最终报告

页面先按竞品逐个展示结构化结果，包括画像、相对优势/劣势、五维矩阵字段、来源、假设、信息缺口、风险和置信度；下方展示最终 Markdown 报告并提供 Markdown/DOCX 下载。

审核不通过时必须填写具体的“审核意见 / 修改指令”，说明修改对象、当前问题、期望修改和证据线索，然后选择：

- **按反馈重新汇总**：保留逐家结构化结果，不重新搜索，只按反馈重做全局竞争格局、SWOT 和定位。
- **按反馈重新分析全部竞品**：将反馈加入检索和逐家 Prompt，重新顺序分析所有竞品，再汇总。

两个操作都不是无差别重试。与反馈无关且有证据支持的字段保持稳定；反馈缺乏证据时记录为信息缺口，不允许迎合反馈编造。

审核通过后点击 **"确认并进入深度尽调"**，才会进入材料上传页。

### 2.6 上传补充材料并运行深度尽调

页面显示 5 个文件上传框，对应深度尽调要使用的补充材料：

| 上传框 | 用在哪个尽调报告 | 建议格式 |
| --- | --- | --- |
| 创始团队资料 | 团队尽调 | PDF/Word，简历、履历 |
| 财务报表 | 财务尽调 | **xlsx**（程序会精确提取数字算比率），PDF/Word 只能靠关键词兜底 |
| 商业计划书/业务规划书 | 业务尽调 | PDF/PPT/Word |
| 技术与知识产权资料 | 技术与知识产权尽调 | PDF/Word |
| 法律文件摘要 | 法律尽调 | PDF/Word，股权结构/合同/诉讼信息 |

全部选填，不上传对应报告会写"资料不足"并在信息缺口里说明，不会编造内容。

点 **"开始深度尽调"**，会自动顺序跑完剩下的节点：

1. **深度尽调** — 5 份子报告顺序执行（不是互相隔离的）：团队尽调先跑；业务尽调会参考团队尽调的关键人风险；财务尽调单独算比率；法律尽调会参考团队+业务+财务的发现判断合规风险；技术与知识产权尽调会参考团队尽调交叉验证研发能力；最后生成一份**深度尽调汇总报告**（把 5 份报告的风险按严重度排序汇总成一张清单 + 去重后的证据来源列表，纯数据整理，不调 LLM）。
2. **估值分析** — 按融资轮次自动调整方法权重（早期看团队/天花板，C 轮及以后看财务/可比交易）。
3. **综合研判与报告输出** — 汇总成 12 模块的最终投研报告。

这一步是整个流程里最耗时的部分，通常 3~8 分钟，中间不会再停下来。

### 2.7 完成：查看和下载报告

跑完后页面顶部会按顺序列出每个节点的报告（可展开的折叠区），每个都有：

- 页面内 Markdown 渲染
- "下载 Markdown" 按钮
- "下载 DOCX" 按钮

最后一个折叠区"项目投研报告（最终）"就是给投委会/立项用的完整报告。

想测下一个项目，点底部 **"重新开始一个新项目"**，会清空当前会话状态（包括已上传文件的临时目录）。

### 2.8 部署到 Streamlit Community Cloud（公开链接，不用一直开着自己电脑）

本地 `streamlit run app.py` 只要电脑关机/断网就会下线，临时隧道（serveo 等）同理。要一个不依赖个人电脑、长期能用的公开链接，最简单的免费方式是部署到 Streamlit 官方的 Community Cloud：

1. 确认代码已经 `git push` 到 GitHub（`.env` 不会被推上去，`.gitignore` 已排除）。
2. 浏览器打开 [share.streamlit.io](https://share.streamlit.io)，用 GitHub 账号登录并授权。
3. 点 "New app"，选这个仓库、`main` 分支、主文件填 `app.py`，点 "Deploy"。
4. 部署完会拿到一个永久链接（形如 `xxx.streamlit.app`），跟本地电脑开不开机无关。
5. **不需要在 Streamlit Cloud 后台配置任何 Secrets**——因为每个访问者（包括部署者自己）都要在网页左侧栏自己填 DashScope/Serper key 才能用，详见 2.1 节，部署者的 key 不会被别人占用额度。
6. 免费版有资源限制：长时间没人访问会自动休眠，有新访问会自动唤醒（首次唤醒要等几十秒）。

---

## 3. CLI 完整使用流程

### 3.1 最小示例（只填必要信息）

```bash
python main.py "示例科技有限公司" --industry 人工智能 --funding-round A轮 --funding-amount 1000万元
```

默认会在 3 处停下来等你操作（跟网页端的 3 个人工节点一一对应）：

**第 1/2 处 — 项目基本概况、行业深度分析复核**，跑完节点 1（或节点 2）会打印报告全文，然后提示：

```text
----- 项目基本概况生成结果 -----
（报告全文……）
----- 项目基本概况结果结束 -----
没问题直接回车继续；要修改就输入反馈文字后回车（会按反馈重新生成这一步）：
```

直接回车 = 确认继续；输入一段反馈文字（比如"公司注册信息那段写错了"）回车 = 带着这条反馈重新生成这一步，重新生成后还会再问一遍，可以反复改到满意为止。行业深度分析的提示完全一样。

**第 3 处 — 竞品确认**，跑到竞品发现节点时列出候选竞品并提示你输入编号：

```text
竞品候选列表（竞品发现节点）：
  [1] 公司A | 直接竞品 | xxx
  [2] 公司B | 潜在竞品 | xxx
请输入要纳入竞品矩阵分析的编号（逗号分隔，留空=全选，1-2）：
```

输入 `1,2`（纳入两个）、输入 `1`（只纳入第一个）、或直接回车（全选），回车后继续跑剩下的节点，直到打印最终报告并提示报告写入目录。

### 3.2 完整示例（带 BP 和全部 5 类尽调文件）

```bash
python main.py "示例科技有限公司" \
  --website https://example.com \
  --bp-file ./bp.pdf \
  --funding-round A轮 \
  --funding-amount 1000万元 \
  --industry 人工智能 \
  --team-file ./团队资料.docx \
  --financial-file ./财务报表.xlsx \
  --business-plan-file ./商业计划书.pdf \
  --tech-ip-file ./技术资料.pdf \
  --legal-file ./法律文件摘要.docx \
  --output-dir data/my_project_reports \
  --markdown
```

`--bp-file`/`--team-file` 等都支持重复传入多个文件路径。`--markdown` 会在终端直接打印最终报告全文（不加的话只会打印"报告已写入：xxx"的提示，报告内容去 `--output-dir` 里看）。

### 3.3 跳过人工确认（适合批量跑/CI 场景）

```bash
python main.py "示例科技有限公司" --auto-select-competitors --auto-approve-reports --max-competitors 5
```

`--auto-select-competitors` 跳过竞品确认，自动选取候选竞品里的前 `--max-competitors`（默认 5）个；`--auto-approve-reports` 跳过项目概况/行业分析的复核，生成后直接往下跑。两个都加上才是完全无人值守模式，适合脚本/CI。

### 3.4 所有参数

```bash
python main.py --help
```

| 参数 | 说明 |
| --- | --- |
| `company_name` | 位置参数，公司名称，必填 |
| `--website` | 官网 |
| `--bp-file` | BP 文件路径，可重复 |
| `--funding-round` | 种子轮/天使轮/A轮/B轮/C轮/Pre-IPO |
| `--funding-amount` | 融资金额 |
| `--industry` | 所属行业 |
| `--description` | 项目描述 |
| `--team-file` / `--financial-file` / `--business-plan-file` / `--tech-ip-file` / `--legal-file` | 5 类尽调补充文件，各自可重复 |
| `--auto-select-competitors` | 跳过竞品人工确认，自动选竞品 |
| `--max-competitors` | 配合上一项，自动选取数量上限（默认 5） |
| `--auto-approve-reports` | 跳过项目概况/行业分析的人工复核，生成后直接往下跑 |
| `--output-dir` | 报告输出目录（默认 `data/bp_reports`） |
| `--search-max-results` | 每类检索最多返回结果数（默认 5） |
| `--json` | 额外打印完整 `PipelineState` JSON |
| `--quiet` | 关闭运行进度日志 |

---

## 4. 七个节点

| 节点 | 输入 | 输出 | 模块 |
| --- | --- | --- | --- |
| 0. 开始 | 用户输入 + BP 文件 | `ProjectInput`（归一化字段 + BP 解析文本 + 文件清单 + 缺口） | `src/nodes/start.py` |
| 1. 项目基本概况 | ProjectInput | 工商信息/发展历程/主营业务/产品体系/落地场景/组织架构/创始团队 | `src/nodes/project_overview.py` |
| 2. 行业深度分析 | 0+1 | 行业定义/趋势/市场规模/产业链/竞争格局/政策/机会映射 | `src/nodes/industry_analysis.py` |
| 3.1 竞品发现 | 0+1+2 | 候选竞品 longlist（人工确认 shortlist） | `src/nodes/competitor_discovery.py` |
| 3.2 竞品矩阵分析 | 0+1+2+已选竞品 | 竞品画像/能力矩阵/SWOT/定位判断 | `src/nodes/competitor_analysis.py` |
| 4. 深度尽调 | 0+1+2+3.2+用户上传文件 | 团队/业务/财务/技术与知识产权/法律 5 份报告 + 1 份汇总报告（风险清单按严重度排序 + 去重证据索引，纯数据整理不调 LLM） | `src/nodes/due_diligence/` |
| 5. 估值分析 | 0+1+2+3.2+4 | 按融资轮次调整方法权重的估值报告（情景分析/可比公司法/可比交易法等） | `src/nodes/valuation.py` |
| 6. 综合研判与报告输出 | 1+2+3.2+4+5 | 12 模块投研报告（直接复用/综合生成/二次分析三类） | `src/nodes/final_report.py` |

财务尽调的比率（毛利率/净利率/营收同比等）由 `src/nodes/due_diligence/financial.py` 中的 `compute_financial_ratios` 在 Python 里从上传的 xlsx/文本中确定性提取计算，LLM 只负责解释，不参与算数。

### 深度尽调里的 5 个 agent 如何协作

5 份尽调报告不是完全孤立跑的，按以下顺序执行，后面的 agent 会拿到前面 agent 的初步发现作为 `peer_findings` 上下文，据此判断跨领域风险（而不是简单拼接 risk_register）：

```text
团队尽调
  └─ 业务尽调（参考团队的关键人风险，判断增长可持续性）
财务尽调
  └─ 法律尽调（参考团队 + 业务 + 财务的发现，判断合规/纠纷风险）
团队尽调
  └─ 技术与知识产权尽调（参考团队的能力评估，交叉验证研发团队评估）
```

对应 `src/nodes/due_diligence/__init__.py` 里的 `summarize_team`/`summarize_business`/`summarize_financial` 等摘要函数，由 `pipeline.py`/`app.py` 在调用顺序里组装成 `peer_findings` 字符串传给下游 agent。

5 份报告全部跑完后，`build_due_diligence_bundle()` 再做一次纯数据汇总（不调 LLM）：把所有风险按严重度（高/中/低）排序成统一的风险清单，把 5 份报告各自的引用来源去重合并，渲染成第 6 份报告"深度尽调汇总"。

---

## 5. 代码结构

```text
main.py                          # CLI 入口
app.py                           # Streamlit 网页端入口（分步向导，纯展示层，不含业务逻辑）
src/
  settings.py                    # .env 加载 + LLM/Search Provider key
  llm.py                         # OpenAI-compatible 多 Provider JSON 路由，带 schema 校验失败自动修复重试
  search.py                      # Serper/Tavily/Google CSE 路由 + collect_evidence 辅助函数
  files.py                       # BP/财务文件解析（pdf/docx/pptx/xlsx）+ 上传文件落盘
  report.py                      # markdown 渲染 + docx 导出（每个节点共用）
  schema.py                      # 7 个节点的全部 Pydantic 模型 + NodeMeta 公共信封
  pipeline.py                    # BPPipeline：每个节点拆成独立方法，写报告文件
  nodes/
    start.py
    project_overview.py
    industry_analysis.py
    competitor_discovery.py
    competitor_analysis.py
    due_diligence/
      team.py / business.py / financial.py / tech_ip.py / legal.py
    valuation.py
    final_report.py
tests/
  conftest.py                    # FakeLLMClient / FakeSearchClient，测试不打真实 API
  test_app_stages.py             # Streamlit 竞品选择/报告展示/尽调上传阶段测试
  test_competitor_analysis.py    # 竞品 prompt、证据预算和 Markdown 矩阵测试
  test_files.py
  test_financial_ratios.py
  test_report.py
  test_pipeline_integration.py
  test_cli.py
```

`BPPipeline` 把每个节点拆成独立方法。竞品确认后的流程有两个明确边界：

- `run_competitor_analysis_step(...)`：只分析用户已选竞品并返回 `CompetitorAnalysis`，不启动深度尽调。
- `run_competitor_synthesis_step(...)`：保留逐家结果，按人工审核意见重新汇总最终报告。
- `run_after_competitor_analysis(...)`：接收已经生成的竞品报告和五类尽调文件，继续运行深度尽调、估值分析和综合报告。
- `run_after_competitor_selection(...)`：兼容 CLI 的一次性包装器，内部依次调用上面两个方法。

调用方可以决定在哪一步停下来等人工操作。这样同一套节点逻辑既支持 CLI 的阻塞式终端交互，也支持 Streamlit 跨多次页面请求的暂停确认，不需要写两套业务逻辑：

- `run_project_overview_step` / `run_industry_analysis_step` 都接受一个可选的 `feedback` 参数，传了就把这条反馈带进 prompt 重新生成；外面还各包一层 `*_with_review`（接受 `ReviewCallback`：返回 `None` 表示通过、返回字符串表示反馈内容）方便 CLI 写"循环直到通过"的阻塞式交互
- `run_intake_through_discovery()` / `run()` 是为了不强制每个调用方都写完整的逐步调用而保留的便捷封装，默认不传 review callback 就是无人值守直接跑完，CLI 和 Streamlit 都是在这些方法之上各自接自己的交互逻辑

最终 `CompetitorAnalysis`（逐家结果、画像、矩阵、SWOT、定位、Markdown 和 meta）会完整序列化并传给业务尽调、估值分析和综合研判，不再只传 `positioning_judgment`。

---

## 6. 报告输出

每次运行会把每个节点的报告写到 `--output-dir`（CLI 默认 `data/bp_reports/`，Streamlit 网页端写到当次会话的临时目录）：

```text
data/bp_reports/
  00_start/project_input.json
  01_project_overview/report.md / report.docx
  02_industry_analysis/report.md / report.docx
  03_competitor_discovery/candidates.json
  03_competitor_analysis/report.md / report.docx
  04_due_diligence/{team,business,financial,tech_ip,legal,summary}.md / .docx
  05_valuation/report.md / report.docx
  06_final_report/report.md / report.docx
```

每份 markdown 报告末尾都带"来源与置信度"附录（引用来源/关键假设/信息缺口/风险标记），对应 `sources`/`assumptions`/`confidence`/`missing_info`/`risk_flags` 这套标准信封。这些运行产物不会提交到 Git（`data/` 已在 `.gitignore` 里）。

---

## 7. 测试

```bash
python -m pytest -q
python -m compileall src main.py app.py tests
```

测试全部基于 `FakeLLMClient`/`FakeSearchClient`（见 `tests/conftest.py`），不会请求真实 LLM/搜索 API，可以离线运行，也不消耗任何 API 额度。

---

## 8. 常见问题

**没配置 API key 直接运行会怎样？**
跑到第一个需要 LLM 或搜索的节点会抛 `RuntimeError`，报错信息里会写清楚该配 `DASHSCOPE_API_KEY` 还是 `SERPER_API_KEY`。这是设计行为，不是 bug。

**为什么有些字段写"资料不足"或"未公开"？**
说明 LLM 在上传文件、检索结果里都没找到依据，按规则不编造具体数字或事实，会同时在"信息缺口"里列出来。

**财务比率不准/缺失？**
财务比率只从结构化数据里算：优先用 `.xlsx` 表格（按"营业收入/营业成本/净利润/经营活动现金流"等关键词匹配行），PDF/Word 走文本关键词兜底，准确率明显更低。建议尽量提供 xlsx 格式的财务报表。

**竞品发现节点没找到候选/候选不相关？**
说明 Serper 搜索没有命中足够信息，常见于公司名称太新、太小众，或者所属行业填得太宽泛。可以把"项目描述"写得更具体一些再试。

**运行很慢？**
主要耗时在 LLM 调用和搜索请求上，可以调小 `--search-max-results`（CLI）减少每类检索的结果数。

**CLI 跑起来要我确认好几次，能不能一次跑到底？**
可以，加 `--auto-approve-reports --auto-select-competitors` 跳过全部 3 个人工节点（项目概况复核、行业分析复核、竞品确认），适合批量跑/CI 场景。
