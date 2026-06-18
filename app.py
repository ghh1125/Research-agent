from __future__ import annotations

import tempfile
from pathlib import Path

import streamlit as st

from src.files import save_uploaded_bytes
from src.pipeline import BPPipeline, BPPipelineConfig
from src.report import write_node_report

st.set_page_config(page_title="VC BP 尽调 Pipeline", layout="wide")

FUNDING_ROUNDS = ["（未指定，由材料自动识别）", "种子轮", "天使轮", "A轮", "B轮", "C轮", "Pre-IPO"]


def init_state() -> None:
    if "stage" not in st.session_state:
        st.session_state.stage = "form"
    if "work_dir" not in st.session_state:
        st.session_state.work_dir = tempfile.mkdtemp(prefix="bp_pipeline_")
    if "sections" not in st.session_state:
        st.session_state.sections = []  # [(title, markdown, out_subdir, name), ...]


def get_pipeline() -> BPPipeline:
    if "pipeline" not in st.session_state:
        out_dir = Path(st.session_state.work_dir) / "reports"
        st.session_state.pipeline = BPPipeline(config=BPPipelineConfig(output_dir=out_dir))
    return st.session_state.pipeline


def uploads_to_paths(uploaded_files, subdir: str) -> list[str]:
    items = [(f.name, f.getvalue()) for f in (uploaded_files or [])]
    return save_uploaded_bytes(items, st.session_state.work_dir, subdir)


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


init_state()
st.title("VC BP 尽调 Pipeline")
st.caption("7 个节点：开始 → 项目基本概况 → 行业深度分析 → 竞品发现/竞品矩阵分析 → 深度尽调 → 估值分析 → 综合研判与报告输出。需要在 .env 配置好 LLM 和搜索 API key 后才能运行。")

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
        submitted = st.form_submit_button("开始尽调", type="primary")

    if submitted:
        if not company_name.strip():
            st.error("公司名称是必填项，请填写后再提交。")
        else:
            try:
                pipeline = get_pipeline()
                st.session_state.company_name = company_name
                with st.spinner("[0-3.1/7] 开始 → 项目概况 → 行业分析 → 竞品发现..."):
                    project_input, project_overview, industry_analysis, discovery = pipeline.run_intake_through_discovery(
                        company_name=company_name,
                        website=website or None,
                        bp_files=uploads_to_paths(bp_files, "bp"),
                        funding_round=(funding_round if funding_round in FUNDING_ROUNDS[1:] else None),
                        funding_amount=funding_amount or None,
                        industry=industry or None,
                        project_description=project_description or None,
                    )
                st.session_state.project_input = project_input
                st.session_state.project_overview = project_overview
                st.session_state.industry_analysis = industry_analysis
                st.session_state.discovery = discovery
                if project_input.missing_fields:
                    st.info(f"提示：以下字段没有从输入或 BP 中识别到，后续报告会标记为信息缺口：{', '.join(project_input.missing_fields)}")
                st.session_state.sections.append(("项目基本概况", project_overview.markdown, "01_project_overview", "report"))
                st.session_state.sections.append(("行业深度分析", industry_analysis.markdown, "02_industry_analysis", "report"))

                st.session_state.stage = "select_competitors"
                st.rerun()
            except Exception as exc:
                st.error(f"运行出错：{type(exc).__name__}: {exc}")
                st.caption("常见原因：.env 里 LLM/搜索 API key 没配置或额度用尽，可以检查后重新提交。")

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
                st.session_state.sections.append(("竞品矩阵分析", competitor_analysis.markdown, "03_competitor_analysis", "report"))
            for sub_title, report, name in [
                ("团队尽调", due_diligence.team, "team"),
                ("业务尽调", due_diligence.business, "business"),
                ("财务尽调", due_diligence.financial, "financial"),
                ("技术与知识产权尽调", due_diligence.tech_ip, "tech_ip"),
                ("法律尽调", due_diligence.legal, "legal"),
            ]:
                st.session_state.sections.append((sub_title, report.markdown, "04_due_diligence", name))
            st.session_state.sections.append(("估值分析", valuation_analysis.markdown, "05_valuation", "report"))
            st.session_state.sections.append(("项目投研报告（最终）", final_report.markdown, "06_final_report", "report"))

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
