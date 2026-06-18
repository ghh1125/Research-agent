from __future__ import annotations

from pydantic import BaseModel, Field

from src.files import parse_files, truncate
from src.llm import RealLLMClient
from src.report import render_meta_section
from src.schema import IndustryAnalysis, LegalDueDiligence, NodeMetaJudgment, ProjectInput, ProjectOverview, RiskLevel

_PROMPT = """\
你在做一级市场投资项目的"法律法规尽调"。

公司：{company_name}　所属行业：{industry}
公司基本信息（参考）：{registration_info}

行业政策环境（来自行业深度分析节点，供你判断公司是否处于强监管行业，合规要求是否更高）：
{policy_environment}

用户上传的法律文件摘要解析文本（节选，可能为空，可能包含股权结构、核心合同、未决诉讼信息）：
{legal_file_text}

其他尽调维度已完成的初步发现（供你判断跨领域风险，例如财务尽调发现的现金流/收入问题是否构成合规或对外负债风险，不要照抄，只在结论里体现交叉影响）：
{peer_findings}

任务：
1. entity_compliance：公司主体合规分析（结合行业政策环境判断合规要求高低；如果资料中提到未决诉讼或争议，作为合规风险的一部分在这里说明，没有就写"资料不足"）
2. equity_structure_analysis：股权结构分析
3. contracts_and_agreements：核心/重要合同与协议分析
4. risk_notes：法律风险提示列表（如果财务/团队/业务尽调的发现会带来合规或纠纷风险，在这里体现）
5. legal_risk_level：法律风险等级，只能是"低"/"中"/"高"

没有依据的内容写"资料不足"，不要编造合同条款或诉讼细节。
"""


class _LegalLLM(BaseModel):
    entity_compliance: str
    equity_structure_analysis: str
    contracts_and_agreements: str
    risk_notes: list[str] = Field(default_factory=list)
    legal_risk_level: RiskLevel
    meta: NodeMetaJudgment = Field(default_factory=NodeMetaJudgment)


def run_legal_due_diligence(
    project_input: ProjectInput,
    project_overview: ProjectOverview,
    industry_analysis: IndustryAnalysis,
    *,
    legal_files: list[str] | None = None,
    llm_client: RealLLMClient | None = None,
    peer_findings: str | None = None,
) -> LegalDueDiligence:
    """Node 4 sub-report — 法律法规尽调. peer_findings typically carries 团队/业务/财务尽调 preliminary
    findings so legal risk judgment accounts for cross-domain signals (e.g. cash flow risk -> compliance risk)."""

    parsed = parse_files(legal_files or [])
    legal_file_text = truncate("\n\n".join(p.text for p in parsed if p.text), 8000)

    client = llm_client or RealLLMClient()
    result = client.complete_json(
        _PROMPT.format(
            company_name=project_input.company_name,
            industry=project_input.industry or "未提供",
            registration_info=project_overview.company_registration_info,
            policy_environment=industry_analysis.policy_environment,
            legal_file_text=legal_file_text or "(用户未上传法律文件)",
            peer_findings=peer_findings or "(暂无其他尽调维度的初步发现)",
        ),
        _LegalLLM,
    )

    meta = result.meta.to_meta([])
    risk_lines = "\n".join(f"- {r}" for r in result.risk_notes) or "- 无明显风险提示"
    markdown = f"""# 法律法规尽调报告

## 1. 公司主体合规分析
{result.entity_compliance}

## 2. 股权结构分析
{result.equity_structure_analysis}

## 3. 合同与协议
{result.contracts_and_agreements}

## 4. 风险提示
{risk_lines}

## 5. 法律风险等级
{result.legal_risk_level}
""" + render_meta_section(meta)

    return LegalDueDiligence(
        entity_compliance=result.entity_compliance,
        equity_structure_analysis=result.equity_structure_analysis,
        contracts_and_agreements=result.contracts_and_agreements,
        risk_notes=result.risk_notes,
        legal_risk_level=result.legal_risk_level,
        markdown=markdown,
        meta=meta,
    )
