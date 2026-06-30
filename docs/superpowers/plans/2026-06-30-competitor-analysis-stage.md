# Standalone Competitor Analysis Stage Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make competitor matrix analysis a standalone, report-producing stage before due-diligence uploads, and strengthen its evidence-grounded prompt.

**Architecture:** Split the existing post-selection pipeline method into one method that generates `CompetitorAnalysis` and a second method that consumes that report to run due diligence, valuation, and the final report. Keep the old method as a compatibility wrapper for CLI callers. Represent the web workflow with separate Streamlit stages for selection, report display, and due-diligence uploads.

**Tech Stack:** Python 3.10+, Pydantic 2, Streamlit, pytest, Streamlit AppTest

---

### Task 1: Split the pipeline at the competitor report boundary

**Files:**
- Modify: `src/pipeline.py:227-300`
- Modify: `tests/test_pipeline_integration.py`

- [ ] **Step 1: Write a failing test proving competitor analysis stops before due diligence**

Add this test to `tests/test_pipeline_integration.py`:

```python
def test_competitor_analysis_step_does_not_start_due_diligence(tmp_path, fake_llm_client, fake_search_client) -> None:
    pipeline = BPPipeline(
        config=BPPipelineConfig(output_dir=tmp_path / "reports", search_max_results=1),
        llm_client=fake_llm_client,
        search_client=fake_search_client,
    )
    project_input, overview, industry, discovery = pipeline.run_intake_through_discovery(
        company_name="示例科技",
        industry="人工智能",
        project_description="企业级 AI 软件",
    )
    fake_llm_client.calls.clear()

    report = pipeline.run_competitor_analysis_step(
        project_input=project_input,
        project_overview=overview,
        industry_analysis=industry,
        discovery=discovery,
        selected_ids=[discovery.candidates[0].id],
    )

    assert report.markdown
    assert fake_llm_client.calls == ["_CompetitorAnalysisLLM"]
```

- [ ] **Step 2: Run the test and verify the missing method failure**

Run:

```bash
.venv/bin/python -m pytest tests/test_pipeline_integration.py::test_competitor_analysis_step_does_not_start_due_diligence -q
```

Expected: FAIL with `AttributeError: 'BPPipeline' object has no attribute 'run_competitor_analysis_step'`.

- [ ] **Step 3: Implement the standalone competitor analysis method**

In `src/pipeline.py`, extract the existing node 3.2 block into:

```python
def run_competitor_analysis_step(
    self,
    *,
    project_input: ProjectInput,
    project_overview: ProjectOverview,
    industry_analysis: IndustryAnalysis,
    discovery: CompetitorDiscovery,
    selected_ids: list[str],
) -> CompetitorAnalysis:
    """Node 3.2 only: generate the report for the user's confirmed shortlist."""

    discovery.selected_ids = selected_ids
    if not selected_ids:
        return empty_competitor_analysis()

    self._emit("[node 3.2/7] 竞品矩阵分析 start")
    report = run_competitor_analysis(
        project_input,
        project_overview,
        industry_analysis,
        discovery,
        llm_client=self.llm_client,
        search_client=self.search_client,
        search_max_results=self.config.search_max_results,
    )
    self._emit("[node 3.2/7] 竞品矩阵分析 done")
    return report
```

- [ ] **Step 4: Run the focused test and verify it passes**

Run:

```bash
.venv/bin/python -m pytest tests/test_pipeline_integration.py::test_competitor_analysis_step_does_not_start_due_diligence -q
```

Expected: `1 passed`.

- [ ] **Step 5: Write a failing test proving later stages reuse the existing report**

Add this test:

```python
def test_after_competitor_analysis_does_not_regenerate_competitor_report(tmp_path, fake_llm_client, fake_search_client) -> None:
    pipeline = BPPipeline(
        config=BPPipelineConfig(output_dir=tmp_path / "reports", search_max_results=1),
        llm_client=fake_llm_client,
        search_client=fake_search_client,
    )
    project_input, overview, industry, discovery = pipeline.run_intake_through_discovery(
        company_name="示例科技",
        industry="人工智能",
        project_description="企业级 AI 软件",
    )
    competitor_report = pipeline.run_competitor_analysis_step(
        project_input=project_input,
        project_overview=overview,
        industry_analysis=industry,
        discovery=discovery,
        selected_ids=[discovery.candidates[0].id],
    )
    fake_llm_client.calls.clear()

    due_diligence, valuation, final_report = pipeline.run_after_competitor_analysis(
        project_input=project_input,
        project_overview=overview,
        industry_analysis=industry,
        competitor_analysis=competitor_report,
    )

    assert due_diligence.markdown
    assert valuation.markdown
    assert final_report.markdown
    assert "_CompetitorAnalysisLLM" not in fake_llm_client.calls
```

- [ ] **Step 6: Run the test and verify the missing method failure**

Run:

```bash
.venv/bin/python -m pytest tests/test_pipeline_integration.py::test_after_competitor_analysis_does_not_regenerate_competitor_report -q
```

Expected: FAIL with `AttributeError` for `run_after_competitor_analysis`.

- [ ] **Step 7: Extract the remaining nodes and retain the compatibility wrapper**

Move the node 4-6 logic into:

```python
def run_after_competitor_analysis(
    self,
    *,
    project_input: ProjectInput,
    project_overview: ProjectOverview,
    industry_analysis: IndustryAnalysis,
    competitor_analysis: CompetitorAnalysis,
    team_files: list[str] | None = None,
    financial_files: list[str] | None = None,
    business_plan_files: list[str] | None = None,
    tech_ip_files: list[str] | None = None,
    legal_files: list[str] | None = None,
) -> tuple[DueDiligenceBundle, ValuationAnalysis, FinalInvestmentReport]:
    """Run nodes 4-6 using an already generated competitor report."""
```

Keep `run_after_competitor_selection(...)` with its current public signature. Its body must call `run_competitor_analysis_step(...)`, then call `run_after_competitor_analysis(...)`, and return the original four-item tuple.

- [ ] **Step 8: Run pipeline tests**

Run:

```bash
.venv/bin/python -m pytest tests/test_pipeline_integration.py -q
```

Expected: all tests pass, including the existing full seven-node CLI path.

- [ ] **Step 9: Commit the pipeline split**

```bash
git add src/pipeline.py tests/test_pipeline_integration.py
git commit -m "refactor: split competitor analysis from due diligence"
```

### Task 2: Strengthen the competitor analysis prompt and report

**Files:**
- Modify: `src/nodes/competitor_analysis.py`
- Modify: `tests/conftest.py`
- Create: `tests/test_competitor_analysis.py`

- [ ] **Step 1: Let the deterministic test client retain prompts**

In `tests/conftest.py`, extend `FakeLLMClient`:

```python
def __init__(self) -> None:
    self.calls: list[str] = []
    self.prompts: list[str] = []

def complete_json(self, prompt: str, schema: type[BaseModel], *, context: dict[str, Any] | None = None) -> BaseModel:
    self.calls.append(schema.__name__)
    self.prompts.append(prompt)
    return schema.model_validate(_fill_required(schema))
```

- [ ] **Step 2: Write a failing prompt-context test**

Create `tests/test_competitor_analysis.py` with explicit `ProjectInput`, `ProjectOverview`, `IndustryAnalysis`, and selected `CompetitorDiscovery` fixtures. Call `run_competitor_analysis(...)`, then assert the captured prompt contains:

```python
assert "企业知识库问答" in prompt
assert "金融机构合规场景" in prompt
assert "头部厂商集中，垂直场景仍分散" in prompt
assert "数据合规壁垒" in prompt
assert "竞品甲" in prompt
assert "只分析用户最终确认的竞品" in prompt
assert "事实、推断和资料不足" in prompt
assert "对业务尽调和估值可比性的影响" in prompt
```

- [ ] **Step 3: Run the test and verify missing prompt content**

Run:

```bash
.venv/bin/python -m pytest tests/test_competitor_analysis.py::test_prompt_uses_full_upstream_context_and_evidence_rules -q
```

Expected: FAIL because the current prompt omits use cases, industry barriers, and downstream-impact rules.

- [ ] **Step 4: Rewrite the prompt with strict comparison and evidence rules**

Update `_PROMPT` to include:

```text
目标公司落地场景与核心价值：{use_cases_and_value}
行业竞争格局：{competitive_landscape}
行业机会与进入壁垒：{opportunities_and_barriers}
目标公司在行业机会中的映射：{opportunity_mapping_to_target}

硬性分析规则：
1. 只分析用户最终确认的竞品，不得自行新增、替换或遗漏。
2. 目标公司与所有竞品必须采用完全一致的比较口径。
3. 每项结论区分已验证事实、基于证据的推断和资料不足。
4. 不得把融资规模、品牌知名度直接等同于产品能力或技术壁垒。
5. strengths/weaknesses 必须说明相对于目标公司的比较依据。
6. SWOT 必须结合目标公司的内部能力和行业外部环境。
7. positioning_judgment 必须包含目标定位、核心差异化、关键短板、
   竞争风险，以及对后续业务尽调和估值可比性的影响。
```

Pass all new placeholders from `project_overview` and `industry_analysis` in `_PROMPT.format(...)`.

- [ ] **Step 5: Improve competitor evidence searches**

For each selected competitor, use dimension-specific queries:

```python
queries = [
    f"{candidate.name} 官网 产品 客户案例 商业模式",
    f"{candidate.name} 融资 收入 商业化进展",
    f"{candidate.name} 技术 专利 核心壁垒",
]
```

Include the discovery-stage relationship, product/service, website, and reason in each competitor evidence block.

- [ ] **Step 6: Render the capability matrix as a Markdown table**

Add a small `_render_capability_matrix(rows)` helper that:

1. Collects company columns in first-seen order, excluding `dimension`.
2. Escapes pipe characters and line breaks in cells.
3. Returns a Markdown table with `对比维度` as the first column.
4. Returns `- （无可用矩阵数据）` when rows are empty.

Replace the raw `f"- {row}"` rendering in `_render_markdown`.

- [ ] **Step 7: Run competitor analysis tests**

Run:

```bash
.venv/bin/python -m pytest tests/test_competitor_analysis.py -q
```

Expected: all prompt and Markdown-table tests pass.

- [ ] **Step 8: Commit prompt and report improvements**

```bash
git add src/nodes/competitor_analysis.py tests/conftest.py tests/test_competitor_analysis.py
git commit -m "feat: strengthen competitor matrix analysis"
```

### Task 3: Separate the Streamlit selection, report, and upload screens

**Files:**
- Modify: `app.py:254-320`
- Create: `tests/test_app_stages.py`

- [ ] **Step 1: Write failing AppTest coverage for the three screens**

Use `streamlit.testing.v1.AppTest` to initialize `app.py`, inject a `CompetitorDiscovery` into session state, and verify:

```python
assert [u.label for u in app.file_uploader] == []
assert "生成竞品矩阵分析报告" in [b.label for b in app.button]
```

Set `stage = "show_competitor_report"` with a `CompetitorAnalysis`, rerun, and verify the report text and “进入深度尽调” button are visible while no upload control is present.

Set `stage = "upload_due_diligence"`, rerun, and verify the five expected uploader labels are present.

- [ ] **Step 2: Run the AppTest file and verify the current combined-screen failure**

Run:

```bash
.venv/bin/python -m pytest tests/test_app_stages.py -q
```

Expected: FAIL because the selection page currently exposes five uploaders and the two new stages do not exist.

- [ ] **Step 3: Make the selection button run only competitor analysis**

In the `select_competitors` branch:

1. Remove all five upload controls.
2. Rename the button to `生成竞品矩阵分析报告`.
3. Call only `pipeline.run_competitor_analysis_step(...)`.
4. Save the result as `st.session_state.competitor_analysis`.
5. Set `stage = "show_competitor_report"` and rerun.

- [ ] **Step 4: Add the read-only competitor report screen**

The `show_competitor_report` branch must:

1. Render `competitor_analysis.markdown` directly.
2. Offer Markdown and DOCX downloads with unique widget keys.
3. Provide only one workflow action: `进入深度尽调`.
4. On click, add the competitor report to `sections`, set `stage = "upload_due_diligence"`, and rerun.

- [ ] **Step 5: Add the due-diligence upload screen**

Move the five existing uploaders into `upload_due_diligence`. Its primary button must:

1. Convert uploaded files to paths.
2. Call `pipeline.run_after_competitor_analysis(...)` with the saved report.
3. Add the five due-diligence reports, summary, valuation report, and final report to `sections`.
4. Set `stage = "done"` and rerun.

- [ ] **Step 6: Run AppTest coverage**

Run:

```bash
.venv/bin/python -m pytest tests/test_app_stages.py -q
```

Expected: all three stage tests pass.

- [ ] **Step 7: Run the complete suite**

Run:

```bash
.venv/bin/python -m pytest -q
```

Expected: all tests pass.

- [ ] **Step 8: Commit the UI state flow**

```bash
git add app.py tests/test_app_stages.py
git commit -m "feat: show competitor report before due diligence uploads"
```

### Task 4: Final verification

**Files:**
- Verify only

- [ ] **Step 1: Compile all Python modules**

Run:

```bash
.venv/bin/python -m compileall src app.py main.py tests
```

Expected: compilation completes without syntax errors.

- [ ] **Step 2: Run the complete test suite from a clean process**

Run:

```bash
.venv/bin/python -m pytest -q
```

Expected: all tests pass with no unexpected warnings or errors.

- [ ] **Step 3: Start Streamlit for manual verification**

Run:

```bash
.venv/bin/streamlit run app.py --server.headless true
```

Expected: Streamlit prints a local URL and serves the application. Verify that the visible order is selection, competitor report, then due-diligence uploads.

