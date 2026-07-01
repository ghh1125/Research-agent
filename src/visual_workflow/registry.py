from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, field, replace
from typing import Any, Callable

from src.llm_config import (
    DEFAULT_DASHSCOPE_MODEL,
    LLMCallConfig,
    SUPPORTED_DASHSCOPE_MODELS,
    prompt_variables,
    validate_prompt_template,
)
from src.nodes.competitor_analysis import (
    _SINGLE_PROMPT as COMPETITOR_SINGLE_PROMPT,
    _SYNTHESIS_PROMPT as COMPETITOR_SYNTHESIS_PROMPT,
)
from src.nodes.competitor_discovery import _PROMPT as COMPETITOR_DISCOVERY_PROMPT
from src.nodes.due_diligence import (
    build_due_diligence_bundle,
    run_business_due_diligence,
    run_financial_due_diligence,
    run_legal_due_diligence,
    run_team_due_diligence,
    run_tech_ip_due_diligence,
    summarize_business,
    summarize_financial,
    summarize_team,
)
from src.nodes.due_diligence.business import _PROMPT as BUSINESS_DD_PROMPT
from src.nodes.due_diligence.financial import _PROMPT as FINANCIAL_DD_PROMPT
from src.nodes.due_diligence.legal import _PROMPT as LEGAL_DD_PROMPT
from src.nodes.due_diligence.team import _PROMPT as TEAM_DD_PROMPT
from src.nodes.due_diligence.tech_ip import _PROMPT as TECH_IP_DD_PROMPT
from src.nodes.final_report import _PROMPT as FINAL_REPORT_PROMPT, run_final_report
from src.nodes.industry_analysis import _PROMPT as INDUSTRY_ANALYSIS_PROMPT
from src.nodes.project_overview import _PROMPT as PROJECT_OVERVIEW_PROMPT
from src.nodes.start import _NORMALIZE_PROMPT as START_NORMALIZATION_PROMPT
from src.nodes.valuation import _PROMPT as VALUATION_ANALYSIS_PROMPT, run_valuation_analysis
from src.pipeline import BPPipeline
from src.prompt_variable_help import variable_help

WorkflowState = dict[str, Any]
Runner = Callable[[WorkflowState, dict[str, Any], "WorkflowServices", dict[str, Any]], dict[str, Any]]


@dataclass(frozen=True)
class FileField:
    key: str
    label: str
    accept: tuple[str, ...] = (".pdf", ".docx", ".pptx", ".xlsx", ".xls")
    multiple: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "accept": list(self.accept),
            "multiple": self.multiple,
        }


@dataclass(frozen=True)
class ConfigField:
    key: str
    label: str
    kind: str = "text"
    required: bool = False
    options: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "kind": self.kind,
            "required": self.required,
            "options": list(self.options),
        }


@dataclass(frozen=True)
class WorkflowServices:
    pipeline: BPPipeline


@dataclass(frozen=True)
class LLMStepSpec:
    id: str
    name: str
    default_prompt: str
    default_model: str = DEFAULT_DASHSCOPE_MODEL

    def to_dict(self) -> dict[str, Any]:
        variables = prompt_variables(self.default_prompt)
        return {
            "id": self.id,
            "name": self.name,
            "defaultModel": self.default_model,
            "defaultPrompt": self.default_prompt,
            "variables": list(variables),
            "variableHelp": variable_help(variables),
            "models": list(SUPPORTED_DASHSCOPE_MODELS),
        }


@dataclass(frozen=True)
class NodeDefinition:
    type: str
    name: str
    required_inputs: tuple[str, ...]
    outputs: tuple[str, ...]
    runner: Runner = field(repr=False)
    file_fields: tuple[FileField, ...] = ()
    config_fields: tuple[ConfigField, ...] = ()
    checkpoint: str | None = None
    required_any: tuple[tuple[str, ...], ...] = ()
    description: str = ""
    llm_steps: tuple[LLMStepSpec, ...] = ()

    def to_catalog_item(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "name": self.name,
            "description": self.description,
            "inputs": list(self.required_inputs),
            "requiredAny": [list(group) for group in self.required_any],
            "outputs": list(self.outputs),
            "fileFields": [item.to_dict() for item in self.file_fields],
            "configFields": [item.to_dict() for item in self.config_fields],
            "checkpoint": self.checkpoint,
            "llmSteps": [step.to_dict() for step in self.llm_steps],
        }


def _step(step_id: str, name: str, prompt: str) -> LLMStepSpec:
    return LLMStepSpec(step_id, name, prompt)


def _llm_configs(config: dict[str, Any]) -> dict[str, LLMCallConfig]:
    result: dict[str, LLMCallConfig] = {}
    for step_id, value in (config.get("llm_steps") or {}).items():
        if not isinstance(value, dict):
            raise ValueError(f"LLM 步骤配置必须是对象: {step_id}")
        result[step_id] = LLMCallConfig(
            model=value.get("model"),
            prompt=value.get("prompt"),
        )
    return result


def _llm_config(config: dict[str, Any], step_id: str) -> LLMCallConfig | None:
    return _llm_configs(config).get(step_id)


def validate_node_config(definition: NodeDefinition, config: dict[str, Any] | None) -> None:
    raw_steps = (config or {}).get("llm_steps") or {}
    if not isinstance(raw_steps, dict):
        raise ValueError(f"{definition.name}：llm_steps 必须是对象")
    specs = {step.id: step for step in definition.llm_steps}
    for step_id, value in raw_steps.items():
        if step_id not in specs:
            raise ValueError(f"{definition.name}：未知 LLM 步骤 {step_id}")
        if not isinstance(value, dict):
            raise ValueError(f"{definition.name} / {specs[step_id].name}：配置必须是对象")
        try:
            LLMCallConfig(model=value.get("model"), prompt=value.get("prompt"))
            if "prompt" in value:
                validate_prompt_template(
                    str(value.get("prompt") or ""),
                    prompt_variables(specs[step_id].default_prompt),
                )
        except ValueError as exc:
            raise ValueError(f"{definition.name} / {specs[step_id].name}：{exc}") from exc


def validate_workflow_node_configs(
    workflow: dict[str, Any],
    registry: Mapping[str, NodeDefinition],
) -> None:
    for node in workflow.get("nodes", []):
        definition = registry.get(node.get("type"))
        if definition is not None:
            validate_node_config(definition, node.get("config"))


def _start(state: WorkflowState, config: dict[str, Any], services: WorkflowServices, runtime: dict[str, Any]) -> dict[str, Any]:
    project_input = services.pipeline.run_start_step(
        company_name=config.get("company_name", ""),
        website=config.get("website") or None,
        bp_files=config.get("bp_files") or None,
        funding_round=config.get("funding_round") or None,
        funding_amount=config.get("funding_amount") or None,
        industry=config.get("industry") or None,
        project_description=config.get("project_description") or None,
        llm_config=_llm_config(config, "start_normalization"),
    )
    return {"project_input": project_input}


def _overview(state: WorkflowState, config: dict[str, Any], services: WorkflowServices, runtime: dict[str, Any]) -> dict[str, Any]:
    result = services.pipeline.run_project_overview_step(
        state["project_input"],
        feedback=runtime.get("feedback"),
        llm_config=_llm_config(config, "project_overview"),
    )
    return {"project_overview": result}


def _industry(state: WorkflowState, config: dict[str, Any], services: WorkflowServices, runtime: dict[str, Any]) -> dict[str, Any]:
    result = services.pipeline.run_industry_analysis_step(
        state["project_input"],
        state["project_overview"],
        feedback=runtime.get("feedback"),
        llm_config=_llm_config(config, "industry_analysis"),
    )
    return {"industry_analysis": result}


def _discovery(state: WorkflowState, config: dict[str, Any], services: WorkflowServices, runtime: dict[str, Any]) -> dict[str, Any]:
    result = services.pipeline.run_competitor_discovery_step(
        state["project_input"],
        state["project_overview"],
        state["industry_analysis"],
        llm_config=_llm_config(config, "competitor_discovery"),
    )
    return {"competitor_discovery": result}


def _competitor(state: WorkflowState, config: dict[str, Any], services: WorkflowServices, runtime: dict[str, Any]) -> dict[str, Any]:
    current = state.get("competitor_analysis")
    if runtime.get("mode") == "resynthesize":
        result = services.pipeline.run_competitor_synthesis_step(
            project_input=state["project_input"],
            project_overview=state["project_overview"],
            industry_analysis=state["industry_analysis"],
            competitor_analysis=current,
            feedback=runtime["feedback"],
            llm_config=_llm_config(config, "competitor_synthesis"),
        )
    else:
        selected_ids = runtime.get("selected_ids") or state["competitor_discovery"].selected_ids
        result = services.pipeline.run_competitor_analysis_step(
            project_input=state["project_input"],
            project_overview=state["project_overview"],
            industry_analysis=state["industry_analysis"],
            discovery=state["competitor_discovery"],
            selected_ids=selected_ids,
            feedback=runtime.get("feedback"),
            current_analysis=current if runtime.get("mode") == "reanalyze" else None,
            single_llm_config=_llm_config(config, "competitor_single"),
            synthesis_llm_config=_llm_config(config, "competitor_synthesis"),
        )
    return {"competitor_analysis": result}


def _deep_dd(state: WorkflowState, config: dict[str, Any], services: WorkflowServices, runtime: dict[str, Any]) -> dict[str, Any]:
    bundle = services.pipeline.run_due_diligence_step(
        project_input=state["project_input"],
        project_overview=state["project_overview"],
        industry_analysis=state["industry_analysis"],
        competitor_analysis=state["competitor_analysis"],
        team_files=config.get("team_files"),
        financial_files=config.get("financial_files"),
        business_plan_files=config.get("business_plan_files"),
        tech_ip_files=config.get("tech_ip_files"),
        legal_files=config.get("legal_files"),
        llm_steps=_llm_configs(config),
    )
    return _bundle_outputs(bundle)


def _team_dd(state: WorkflowState, config: dict[str, Any], services: WorkflowServices, runtime: dict[str, Any]) -> dict[str, Any]:
    report = run_team_due_diligence(
        state["project_input"],
        state["project_overview"],
        state["industry_analysis"],
        team_files=config.get("team_files"),
        llm_client=services.pipeline.llm_client,
        search_client=services.pipeline.search_client,
        llm_config=_llm_config(config, "team_due_diligence"),
    )
    return {"team_due_diligence": report}


def _business_dd(state: WorkflowState, config: dict[str, Any], services: WorkflowServices, runtime: dict[str, Any]) -> dict[str, Any]:
    team = state.get("team_due_diligence")
    report = run_business_due_diligence(
        state["project_input"],
        state["project_overview"],
        state["industry_analysis"],
        state["competitor_analysis"],
        business_plan_files=config.get("business_plan_files"),
        llm_client=services.pipeline.llm_client,
        peer_findings=summarize_team(team) if team else None,
        llm_config=_llm_config(config, "business_due_diligence"),
    )
    return {"business_due_diligence": report}


def _financial_dd(state: WorkflowState, config: dict[str, Any], services: WorkflowServices, runtime: dict[str, Any]) -> dict[str, Any]:
    report = run_financial_due_diligence(
        state["project_input"],
        state["project_overview"],
        state["industry_analysis"],
        financial_files=config.get("financial_files"),
        llm_client=services.pipeline.llm_client,
        llm_config=_llm_config(config, "financial_due_diligence"),
    )
    return {"financial_due_diligence": report}


def _tech_dd(state: WorkflowState, config: dict[str, Any], services: WorkflowServices, runtime: dict[str, Any]) -> dict[str, Any]:
    team = state.get("team_due_diligence")
    report = run_tech_ip_due_diligence(
        state["project_input"],
        state["project_overview"],
        state["industry_analysis"],
        tech_ip_files=config.get("tech_ip_files"),
        llm_client=services.pipeline.llm_client,
        peer_findings=summarize_team(team) if team else None,
        llm_config=_llm_config(config, "tech_ip_due_diligence"),
    )
    return {"tech_ip_due_diligence": report}


def _legal_dd(state: WorkflowState, config: dict[str, Any], services: WorkflowServices, runtime: dict[str, Any]) -> dict[str, Any]:
    findings = []
    if state.get("team_due_diligence"):
        findings.append(summarize_team(state["team_due_diligence"]))
    if state.get("business_due_diligence"):
        findings.append(summarize_business(state["business_due_diligence"]))
    if state.get("financial_due_diligence"):
        findings.append(summarize_financial(state["financial_due_diligence"]))
    report = run_legal_due_diligence(
        state["project_input"],
        state["project_overview"],
        state["industry_analysis"],
        legal_files=config.get("legal_files"),
        llm_client=services.pipeline.llm_client,
        peer_findings="\n".join(findings) or None,
        llm_config=_llm_config(config, "legal_due_diligence"),
    )
    return {"legal_due_diligence": report}


def _bundle_outputs(bundle) -> dict[str, Any]:
    return {
        "team_due_diligence": bundle.team,
        "business_due_diligence": bundle.business,
        "financial_due_diligence": bundle.financial,
        "tech_ip_due_diligence": bundle.tech_ip,
        "legal_due_diligence": bundle.legal,
        "due_diligence": bundle,
    }


def _ensure_bundle(state: WorkflowState):
    if state.get("due_diligence") is not None:
        return state["due_diligence"]
    bundle = build_due_diligence_bundle(
        state.get("team_due_diligence"),
        state.get("business_due_diligence"),
        state.get("financial_due_diligence"),
        state.get("tech_ip_due_diligence"),
        state.get("legal_due_diligence"),
    )
    state["due_diligence"] = bundle
    return bundle


def _valuation(state: WorkflowState, config: dict[str, Any], services: WorkflowServices, runtime: dict[str, Any]) -> dict[str, Any]:
    bundle = _ensure_bundle(state)
    result = run_valuation_analysis(
        state["project_input"],
        state["project_overview"],
        state["industry_analysis"],
        state["competitor_analysis"],
        bundle,
        llm_client=services.pipeline.llm_client,
        search_client=services.pipeline.search_client,
        search_max_results=services.pipeline.config.search_max_results,
        llm_config=_llm_config(config, "valuation_analysis"),
    )
    return {"due_diligence": bundle, "valuation_analysis": result}


def _final(state: WorkflowState, config: dict[str, Any], services: WorkflowServices, runtime: dict[str, Any]) -> dict[str, Any]:
    result = run_final_report(
        state["project_input"],
        state["project_overview"],
        state["industry_analysis"],
        state["competitor_analysis"],
        state["due_diligence"],
        state["valuation_analysis"],
        llm_client=services.pipeline.llm_client,
        llm_config=_llm_config(config, "final_report"),
    )
    return {"final_report": result}


def get_node_registry() -> OrderedDict[str, NodeDefinition]:
    bp = FileField("bp_files", "BP 文件", (".pdf", ".pptx", ".docx"))
    team = FileField("team_files", "创始团队资料")
    financial = FileField("financial_files", "财务报表", (".xlsx", ".xls", ".pdf", ".docx"))
    business = FileField("business_plan_files", "商业计划书 / 业务规划书")
    tech = FileField("tech_ip_files", "技术与知识产权资料")
    legal = FileField("legal_files", "法律文件摘要")
    core = ("project_input", "project_overview", "industry_analysis")
    dd_components = (
        "team_due_diligence",
        "business_due_diligence",
        "financial_due_diligence",
        "tech_ip_due_diligence",
        "legal_due_diligence",
    )
    definitions = [
        NodeDefinition(
            "start",
            "开始",
            (),
            ("project_input",),
            _start,
            (bp,),
            (
                ConfigField("company_name", "公司名称", required=True),
                ConfigField("website", "官网"),
                ConfigField("funding_round", "融资轮次", "select", options=("种子轮", "天使轮", "A轮", "B轮", "C轮", "Pre-IPO")),
                ConfigField("funding_amount", "融资金额"),
                ConfigField("industry", "所属行业"),
                ConfigField("project_description", "项目描述", "textarea"),
            ),
        ),
        NodeDefinition("projectOverview", "项目基本概况", ("project_input",), ("project_overview",), _overview, checkpoint="report_review"),
        NodeDefinition("industryAnalysis", "行业深度分析", ("project_input", "project_overview"), ("industry_analysis",), _industry, checkpoint="report_review"),
        NodeDefinition("competitorDiscovery", "竞品发现", core, ("competitor_discovery",), _discovery, checkpoint="competitor_selection"),
        NodeDefinition(
            "competitorAnalysis",
            "竞品矩阵分析",
            core + ("competitor_discovery",),
            ("competitor_analysis",),
            _competitor,
            checkpoint="competitor_report_review",
        ),
        NodeDefinition(
            "deepDueDiligence",
            "深度尽调",
            core + ("competitor_analysis",),
            dd_components + ("due_diligence",),
            _deep_dd,
            (team, financial, business, tech, legal),
        ),
        NodeDefinition("teamDueDiligence", "团队尽调", core, ("team_due_diligence",), _team_dd, (team,)),
        NodeDefinition(
            "businessDueDiligence",
            "业务尽调",
            core + ("competitor_analysis",),
            ("business_due_diligence",),
            _business_dd,
            (business,),
        ),
        NodeDefinition("financialDueDiligence", "财务尽调", core, ("financial_due_diligence",), _financial_dd, (financial,)),
        NodeDefinition("techIpDueDiligence", "技术与知识产权尽调", core, ("tech_ip_due_diligence",), _tech_dd, (tech,)),
        NodeDefinition("legalDueDiligence", "法律法规尽调", core, ("legal_due_diligence",), _legal_dd, (legal,)),
        NodeDefinition(
            "valuationAnalysis",
            "估值分析",
            core + ("competitor_analysis",),
            ("due_diligence", "valuation_analysis"),
            _valuation,
        ),
        NodeDefinition(
            "finalReport",
            "综合研判与报告输出",
            core + ("competitor_analysis", "due_diligence", "valuation_analysis"),
            ("final_report",),
            _final,
        ),
    ]
    metadata: dict[str, tuple[str, tuple[LLMStepSpec, ...]]] = {
        "start": (
            "接收公司信息和 BP 文件，归一化为结构化项目输入。",
            (_step("start_normalization", "输入归一化", START_NORMALIZATION_PROMPT),),
        ),
        "projectOverview": (
            "检索并生成工商信息、里程碑、业务、产品、组织与创始团队概况。",
            (_step("project_overview", "项目概况生成", PROJECT_OVERVIEW_PROMPT),),
        ),
        "industryAnalysis": (
            "分析行业趋势、市场规模、竞争格局、政策、机会与壁垒。",
            (_step("industry_analysis", "行业分析生成", INDUSTRY_ANALYSIS_PROMPT),),
        ),
        "competitorDiscovery": (
            "通过公开检索生成候选竞品 longlist，等待人工选择。",
            (_step("competitor_discovery", "候选竞品发现", COMPETITOR_DISCOVERY_PROMPT),),
        ),
        "competitorAnalysis": (
            "逐家检索分析所选竞品，再统一生成矩阵、SWOT 与定位判断。",
            (
                _step("competitor_single", "单家竞品分析", COMPETITOR_SINGLE_PROMPT),
                _step("competitor_synthesis", "竞品统一汇总", COMPETITOR_SYNTHESIS_PROMPT),
            ),
        ),
        "deepDueDiligence": (
            "顺序执行团队、业务、财务、技术/IP、法律五项尽调并汇总风险。",
            (
                _step("team_due_diligence", "团队尽调", TEAM_DD_PROMPT),
                _step("business_due_diligence", "业务尽调", BUSINESS_DD_PROMPT),
                _step("financial_due_diligence", "财务尽调", FINANCIAL_DD_PROMPT),
                _step("tech_ip_due_diligence", "技术与知识产权尽调", TECH_IP_DD_PROMPT),
                _step("legal_due_diligence", "法律法规尽调", LEGAL_DD_PROMPT),
            ),
        ),
        "teamDueDiligence": (
            "分析创始团队履历、能力矩阵、股权稳定性和关键人风险。",
            (_step("team_due_diligence", "团队尽调", TEAM_DD_PROMPT),),
        ),
        "businessDueDiligence": (
            "分析商业模式、市场、增长模型、竞争格局和业务风险。",
            (_step("business_due_diligence", "业务尽调", BUSINESS_DD_PROMPT),),
        ),
        "financialDueDiligence": (
            "解析财务材料、计算关键比率并判断现金流和财务健康度。",
            (_step("financial_due_diligence", "财务尽调", FINANCIAL_DD_PROMPT),),
        ),
        "techIpDueDiligence": (
            "评审技术架构、研发团队、技术壁垒和知识产权风险。",
            (_step("tech_ip_due_diligence", "技术与知识产权尽调", TECH_IP_DD_PROMPT),),
        ),
        "legalDueDiligence": (
            "分析主体合规、股权结构、合同协议和法律风险。",
            (_step("legal_due_diligence", "法律法规尽调", LEGAL_DD_PROMPT),),
        ),
        "valuationAnalysis": (
            "基于项目、行业、竞品和已有尽调覆盖范围生成风险调整估值。",
            (_step("valuation_analysis", "估值分析", VALUATION_ANALYSIS_PROMPT),),
        ),
        "finalReport": (
            "汇总生成十二模块项目投研报告，并显著披露未执行尽调。",
            (_step("final_report", "综合研判与最终报告", FINAL_REPORT_PROMPT),),
        ),
    }
    definitions = [
        replace(
            definition,
            description=metadata[definition.type][0],
            llm_steps=metadata[definition.type][1],
        )
        for definition in definitions
    ]
    return OrderedDict((definition.type, definition) for definition in definitions)


__all__ = [
    "ConfigField",
    "FileField",
    "LLMStepSpec",
    "NodeDefinition",
    "WorkflowServices",
    "get_node_registry",
    "validate_node_config",
    "validate_workflow_node_configs",
]
