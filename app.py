from __future__ import annotations

import dataclasses
import os
import tempfile
from pathlib import Path

import streamlit as st

from src.files import save_uploaded_bytes
from src.llm import RealLLMClient
from src.pipeline import BPPipeline, BPPipelineConfig
from src.report import write_node_report
from src.search import RealSearchClient
from src.settings import get_settings


def _load_streamlit_secrets_into_env() -> None:
    """On Streamlit Community Cloud, API keys configured in the dashboard's Secrets UI arrive
    via st.secrets, not os.environ — but settings.py reads os.environ (via a local .env file
    when running locally). Mirror st.secrets into os.environ so the same settings.py works
    unchanged in both places. No-op locally when no secrets.toml exists."""

    try:
        for key, value in st.secrets.items():
            os.environ.setdefault(key, str(value))
    except Exception:
        pass


_load_streamlit_secrets_into_env()

st.set_page_config(page_title="VC BP 尽调 Pipeline", layout="wide")

FUNDING_ROUNDS = ["（未指定，由材料自动识别）", "种子轮", "天使轮", "A轮", "B轮", "C轮", "Pre-IPO"]


def init_state() -> None:
    if "stage" not in st.session_state:
        st.session_state.stage = "form"
    if "work_dir" not in st.session_state:
        st.session_state.work_dir = tempfile.mkdtemp(prefix="bp_pipeline_")
    if "sections" not in st.session_state:
        st.session_state.sections = []  # [(title, markdown, out_subdir, name), ...]


def _session_settings():
    """Base settings (provider/model/base_url) come from the deployer's .env or Streamlit
    secrets as usual; only the two API keys are overridden with this session's own values,
    keeping them scoped to this user's BPPipeline instance instead of os.environ."""

    base = get_settings()
    return dataclasses.replace(
        base,
        dashscope_api_key=st.session_state.get("user_dashscope_key", "").strip(),
        serper_api_key=st.session_state.get("user_serper_key", "").strip(),
    )


def get_pipeline() -> BPPipeline:
    if "pipeline" not in st.session_state:
        out_dir = Path(st.session_state.work_dir) / "reports"
        settings = _session_settings()
        st.session_state.pipeline = BPPipeline(
            config=BPPipelineConfig(output_dir=out_dir),
            llm_client=RealLLMClient(settings=settings),
            search_client=RealSearchClient(settings=settings),
        )
    return st.session_state.pipeline


def uploads_to_paths(uploaded_files, subdir: str) -> list[str]:
    items = [(f.name, f.getvalue()) for f in (uploaded_files or [])]
    return save_uploaded_bytes(items, st.session_state.work_dir, subdir)


def add_section(entry: tuple[str, str, str, str]) -> None:
    """Append a report section, replacing any earlier entry with the same (out_subdir, name).
    Needed because a later pipeline step can fail and leave the user back on the same review
    page; clicking the approve button again must not re-add a section that's already there —
    duplicate (out_subdir, name) pairs collide on the download_button widget key downstream."""

    _, _, out_subdir, name = entry
    st.session_state.sections = [s for s in st.session_state.sections if not (s[2] == out_subdir and s[3] == name)]
    st.session_state.sections.append(entry)


def render_report_section(title: str, markdown_text: str, out_subdir: str, name: str) -> None:
    out_dir = Path(st.session_state.work_dir) / "reports" / out_subdir
    paths = write_node_report(markdown_text, out_dir, name)
    with st.expander(title, expanded=False):
        st.markdown(markdown_text)
        col1, col2 = st.columns(2)
        with col1:
            st.download_button("下载 Markdown", data=markdown_text, file_name=f"{name}.md", key=f"dl_md_{out_subdir}_{name}")
        if "docx" in paths:
            with col2:
                st.download_button(
                    "下载 DOCX", data=Path(paths["docx"]).read_bytes(), file_name=f"{name}.docx", key=f"dl_docx_{out_subdir}_{name}"
                )


def reset_session() -> None:
    for key in list(st.session_state.keys()):
        del st.session_state[key]


def has_required_api_keys() -> bool:
    return bool(st.session_state.get("user_dashscope_key", "").strip()) and bool(st.session_state.get("user_serper_key", "").strip())


def render_api_key_sidebar() -> None:
    """Every visitor must supply their own DashScope/Serper key — this app has no shared
    deployer-side key, so usage cost/quota is never incurred on the deployer's account.

    Important: this does NOT write into os.environ. Streamlit can serve multiple concurrent
    users from the same Python process, and os.environ is process-global — writing a key
    there would leak it into every other visitor's session. Keys stay in st.session_state
    (per-session) and are only wired into this session's own LLM/search clients in
    get_pipeline() below."""

    with st.sidebar:
        st.subheader("API Key（必填）")
        st.caption("本工具不提供共享 key，请填入你自己的 DashScope 和 Serper API Key。只保存在你本次会话内存中，不会被保存到任何文件、不会上传、不会给其他访问者共享。")
        st.text_input("DashScope API Key *", type="password", key="user_dashscope_key", placeholder="必填，sk-...")
        st.text_input("Serper API Key *", type="password", key="user_serper_key", placeholder="必填")
        if not has_required_api_keys():
            st.warning("两个 key 都填完才能开始尽调。")
        elif "pipeline" in st.session_state:
            st.caption("当前会话已经在跑了，改 key 要点「重新开始一个新项目」才会用新 key。")


init_state()
render_api_key_sidebar()
st.title("VC BP 尽调 Pipeline")
st.caption("7 个节点：开始 → 项目基本概况 → 行业深度分析 → 竞品发现/竞品矩阵分析 → 深度尽调 → 估值分析 → 综合研判与报告输出。请先在左侧栏填入你自己的 DashScope 和 Serper API Key 才能运行。")

for title, markdown_text, out_subdir, name in st.session_state.sections:
    render_report_section(title, markdown_text, out_subdir, name)

if st.session_state.stage == "form":
    with st.form("intake_form"):
        st.subheader("第 0 步：项目基本信息")
        company_name = st.text_input("公司名称 *", placeholder="例如：示例科技有限公司", help="必填，会作为后续所有检索和分析的主体名称")
        website = st.text_input("官网", placeholder="例如：https://example.com", help="选填，没有可以留空，会尝试从 BP 或检索结果中补全")
        col_a, col_b = st.columns(2)
        with col_a:
            funding_round = st.selectbox("融资轮次", FUNDING_ROUNDS, help="影响估值分析节点使用的方法权重（早期看团队/天花板，后期看财务/可比交易）")
        with col_b:
            funding_amount = st.text_input("融资金额", placeholder="例如：1000万元 / $5M", help="选填，用于估值节点反推隐含估值")
        industry = st.text_input("所属行业", placeholder="例如：人工智能 / 动力电池 / 医疗器械", help="影响行业分析和竞品发现的检索方向")
        project_description = st.text_area("项目描述", placeholder="一句话说明项目在做什么、解决什么问题", help="选填，没有 BP 时尤其建议填写")
        bp_files = st.file_uploader(
            "BP 文件（PDF / PPT / Word，可多选）", accept_multiple_files=True, type=["pdf", "ppt", "pptx", "doc", "docx"], help="会自动解析文本用于补全上面留空的字段"
        )
        submitted = st.form_submit_button("开始尽调", type="primary", disabled=not has_required_api_keys())

    if submitted:
        if not has_required_api_keys():
            st.error("请先在左侧栏填入 DashScope 和 Serper API Key。")
        elif not company_name.strip():
            st.error("公司名称是必填项，请填写后再提交。")
        else:
            try:
                pipeline = get_pipeline()
                st.session_state.company_name = company_name
                with st.spinner("[0-1/7] 开始 → 项目基本概况..."):
                    project_input = pipeline.run_start_step(
                        company_name=company_name,
                        website=website or None,
                        bp_files=uploads_to_paths(bp_files, "bp"),
                        funding_round=(funding_round if funding_round in FUNDING_ROUNDS[1:] else None),
                        funding_amount=funding_amount or None,
                        industry=industry or None,
                        project_description=project_description or None,
                    )
                    project_overview = pipeline.run_project_overview_step(project_input)
                st.session_state.project_input = project_input
                st.session_state.project_overview = project_overview
                if project_input.missing_fields:
                    st.info(f"提示：以下字段没有从输入或 BP 中识别到，后续报告会标记为信息缺口：{', '.join(project_input.missing_fields)}")
                st.session_state.stage = "review_overview"
                st.rerun()
            except Exception as exc:
                st.error(f"运行出错：{type(exc).__name__}: {exc}")
                st.caption("常见原因：.env 里 LLM/搜索 API key 没配置或额度用尽，可以检查后重新提交。")

elif st.session_state.stage == "review_overview":
    st.subheader("第 1 步人工复核：项目基本概况")
    st.caption("看一下生成结果，没问题就点右边按钮继续；不满意就写反馈，点左边按钮按反馈重新生成这一步。")
    st.markdown(st.session_state.project_overview.markdown)
    feedback = st.text_area("反馈（留空 = 没问题）", key="overview_feedback", placeholder="例如：公司注册信息那段写错了，再确认一下")
    col1, col2 = st.columns(2)
    with col1:
        if st.button("按反馈重新生成", key="overview_regenerate"):
            if not feedback.strip():
                st.warning("没填反馈内容，要继续的话点右边的按钮就行。")
            else:
                try:
                    pipeline = get_pipeline()
                    with st.spinner("按反馈重新生成项目基本概况..."):
                        st.session_state.project_overview = pipeline.run_project_overview_step(st.session_state.project_input, feedback=feedback.strip())
                    st.rerun()
                except Exception as exc:
                    st.error(f"运行出错：{type(exc).__name__}: {exc}")
    with col2:
        if st.button("确认继续，跑行业深度分析", type="primary", key="overview_approve"):
            add_section(("项目基本概况", st.session_state.project_overview.markdown, "01_project_overview", "report"))
            try:
                pipeline = get_pipeline()
                with st.spinner("[2/7] 行业深度分析..."):
                    st.session_state.industry_analysis = pipeline.run_industry_analysis_step(
                        st.session_state.project_input, st.session_state.project_overview
                    )
                st.session_state.stage = "review_industry"
                st.rerun()
            except Exception as exc:
                st.error(f"运行出错：{type(exc).__name__}: {exc}")

elif st.session_state.stage == "review_industry":
    st.subheader("第 2 步人工复核：行业深度分析")
    st.caption("看一下生成结果，没问题就点右边按钮继续；不满意就写反馈，点左边按钮按反馈重新生成这一步。")
    st.markdown(st.session_state.industry_analysis.markdown)
    feedback = st.text_area("反馈（留空 = 没问题）", key="industry_feedback", placeholder="例如：市场规模数据来源不可靠，再核实一下")
    col1, col2 = st.columns(2)
    with col1:
        if st.button("按反馈重新生成", key="industry_regenerate"):
            if not feedback.strip():
                st.warning("没填反馈内容，要继续的话点右边的按钮就行。")
            else:
                try:
                    pipeline = get_pipeline()
                    with st.spinner("按反馈重新生成行业深度分析..."):
                        st.session_state.industry_analysis = pipeline.run_industry_analysis_step(
                            st.session_state.project_input, st.session_state.project_overview, feedback=feedback.strip()
                        )
                    st.rerun()
                except Exception as exc:
                    st.error(f"运行出错：{type(exc).__name__}: {exc}")
    with col2:
        if st.button("确认继续，跑竞品发现", type="primary", key="industry_approve"):
            add_section(("行业深度分析", st.session_state.industry_analysis.markdown, "02_industry_analysis", "report"))
            try:
                pipeline = get_pipeline()
                with st.spinner("[3.1/7] 竞品发现..."):
                    st.session_state.discovery = pipeline.run_competitor_discovery_step(
                        st.session_state.project_input, st.session_state.project_overview, st.session_state.industry_analysis
                    )
                st.session_state.stage = "select_competitors"
                st.rerun()
            except Exception as exc:
                st.error(f"运行出错：{type(exc).__name__}: {exc}")

elif st.session_state.stage == "select_competitors":
    discovery = st.session_state.discovery
    st.subheader("第 3.1 步：竞品发现 — 请确认要纳入竞品矩阵分析的竞品")
    st.caption("这是 pipeline 里唯一需要人工确认的环节：下面是 LLM 找到的候选竞品 longlist，勾选你认为相关的，取消勾选你认为不相关的。")
    selected_ids: list[str] = []
    if not discovery.candidates:
        st.warning("没有发现候选竞品（可能是检索没有命中），将跳过竞品矩阵分析，直接进入深度尽调。")
    else:
        for candidate in discovery.candidates:
            label = f"**{candidate.name}**　|　关系：{candidate.relationship}　|　{candidate.product_or_service}"
            checked = st.checkbox(label, value=True, key=f"cand_{candidate.id}", help=candidate.reason)
            if checked:
                selected_ids.append(candidate.id)
        st.caption("提示：至少勾选 1 个才会生成竞品矩阵分析；全部取消勾选等同于跳过该节点。")

    st.markdown("---")
    st.subheader("第 4 步预告：深度尽调补充材料（选填）")
    st.caption("确认竞品后会立即用到这些文件，没有就留空，对应尽调报告会标记资料不足。")
    team_files = st.file_uploader("创始团队资料", accept_multiple_files=True, key="team_upload", help="简历、过往履历等，用于团队尽调")
    financial_files = st.file_uploader(
        "财务报表（建议 xlsx，便于程序自动算财务比率）", accept_multiple_files=True, key="financial_upload", type=["xlsx", "xls", "pdf", "docx"], help="收入/成本/净利润/经营现金流相关数据；xlsx 表格能被精确提取，PDF/Word 只能做关键词匹配兜底"
    )
    business_plan_files = st.file_uploader("商业计划书 / 业务规划书", accept_multiple_files=True, key="bizplan_upload", help="用于业务尽调")
    tech_ip_files = st.file_uploader("技术与知识产权资料", accept_multiple_files=True, key="techip_upload", help="技术架构、专利、软著清单等")
    legal_files = st.file_uploader("法律文件摘要", accept_multiple_files=True, key="legal_upload", help="股权结构、核心合同、未决诉讼等")

    if st.button("确认竞品，继续后续分析", type="primary"):
        try:
            pipeline = get_pipeline()
            with st.spinner("[3.2-6/7] 竞品矩阵分析 → 深度尽调 → 估值分析 → 综合报告..."):
                competitor_analysis, due_diligence, valuation_analysis, final_report = pipeline.run_after_competitor_selection(
                    project_input=st.session_state.project_input,
                    project_overview=st.session_state.project_overview,
                    industry_analysis=st.session_state.industry_analysis,
                    discovery=discovery,
                    selected_ids=selected_ids,
                    team_files=uploads_to_paths(team_files, "team"),
                    financial_files=uploads_to_paths(financial_files, "financial"),
                    business_plan_files=uploads_to_paths(business_plan_files, "bizplan"),
                    tech_ip_files=uploads_to_paths(tech_ip_files, "techip"),
                    legal_files=uploads_to_paths(legal_files, "legal"),
                )

            if selected_ids:
                add_section(("竞品矩阵分析", competitor_analysis.markdown, "03_competitor_analysis", "report"))
            for sub_title, report, name in [
                ("团队尽调", due_diligence.team, "team"),
                ("业务尽调", due_diligence.business, "business"),
                ("财务尽调", due_diligence.financial, "financial"),
                ("技术与知识产权尽调", due_diligence.tech_ip, "tech_ip"),
                ("法律尽调", due_diligence.legal, "legal"),
            ]:
                add_section((sub_title, report.markdown, "04_due_diligence", name))
            add_section(("深度尽调汇总", due_diligence.markdown, "04_due_diligence", "summary"))
            add_section(("估值分析", valuation_analysis.markdown, "05_valuation", "report"))
            add_section(("项目投研报告（最终）", final_report.markdown, "06_final_report", "report"))

            st.session_state.stage = "done"
            st.rerun()
        except Exception as exc:
            st.error(f"运行出错：{type(exc).__name__}: {exc}")
            st.caption("常见原因：.env 里 LLM/搜索 API key 没配置或额度用尽，可以检查后点击下方按钮重新开始。")
            if st.button("重新开始一个新项目", key="restart_on_error"):
                reset_session()
                st.rerun()

elif st.session_state.stage == "done":
    st.success("Pipeline 已全部完成，上面每个节点的报告都可以展开查看并下载 Markdown/DOCX。")
    if st.button("重新开始一个新项目"):
        reset_session()
        st.rerun()
