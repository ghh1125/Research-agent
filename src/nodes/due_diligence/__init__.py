from __future__ import annotations

from src.nodes.due_diligence.business import run_business_due_diligence
from src.nodes.due_diligence.financial import run_financial_due_diligence
from src.nodes.due_diligence.legal import run_legal_due_diligence
from src.nodes.due_diligence.team import run_team_due_diligence
from src.nodes.due_diligence.tech_ip import run_tech_ip_due_diligence
from src.schema import (
    BusinessDueDiligence,
    DueDiligenceBundle,
    FinancialDueDiligence,
    LegalDueDiligence,
    RiskRegisterItem,
    Source,
    TeamDueDiligence,
    TechIPDueDiligence,
)

_SEVERITY_ORDER = {"高": 0, "中": 1, "低": 2}


def summarize_team(team: TeamDueDiligence) -> str:
    return f"[团队尽调] 能力评估={team.capability_rating}；关键人风险：{team.key_person_risk}"


def summarize_business(business: BusinessDueDiligence) -> str:
    return f"[业务尽调] 评分={business.business_score}；风险：{'；'.join(r.description for r in business.risk_notes) or '无'}"


def summarize_financial(financial: FinancialDueDiligence) -> str:
    return f"[财务尽调] 健康度：{financial.financial_health_summary}；风险：{'；'.join(r.description for r in financial.risk_notes) or '无'}"


def summarize_tech_ip(tech_ip: TechIPDueDiligence) -> str:
    return f"[技术与知识产权尽调] 核心壁垒：{tech_ip.core_tech_barrier}；风险：{'；'.join(r.description for r in tech_ip.risk_notes) or '无'}"


def summarize_legal(legal: LegalDueDiligence) -> str:
    return f"[法律尽调] 风险等级={legal.legal_risk_level}；风险：{'；'.join(legal.risk_notes) or '无'}"


def build_due_diligence_bundle(
    team,
    business,
    financial,
    tech_ip,
    legal,
) -> DueDiligenceBundle:
    """Node 4 aggregation — combine the 5 due-diligence sub-reports into one bundle with risk_register and evidence_index."""

    risk_register: list[RiskRegisterItem] = []
    risk_register.append(RiskRegisterItem(category="团队", description=team.key_person_risk, severity=_team_severity(team.capability_rating)))
    for note in business.risk_notes:
        risk_register.append(RiskRegisterItem(category="业务", description=note.description, severity=note.severity))
    for note in financial.risk_notes:
        risk_register.append(RiskRegisterItem(category="财务", description=note.description, severity=note.severity))
    for note in tech_ip.risk_notes:
        risk_register.append(RiskRegisterItem(category="技术与知识产权", description=note.description, severity=note.severity))
    for note in legal.risk_notes:
        risk_register.append(RiskRegisterItem(category="法律", description=note, severity=legal.legal_risk_level))
    risk_register.sort(key=lambda item: _SEVERITY_ORDER.get(item.severity, 1))

    evidence_index: list[Source] = []
    seen_sources: set[tuple[str, str | None]] = set()
    for report in (team, business, financial, tech_ip, legal):
        for source in report.meta.sources:
            key = (source.title, source.url)
            if key in seen_sources:
                continue
            seen_sources.add(key)
            evidence_index.append(source)

    markdown = _render_bundle_markdown(team, business, financial, tech_ip, legal, risk_register, evidence_index)

    return DueDiligenceBundle(
        team=team,
        business=business,
        financial=financial,
        tech_ip=tech_ip,
        legal=legal,
        risk_register=risk_register,
        evidence_index=evidence_index,
        markdown=markdown,
    )


def _team_severity(capability_rating: str) -> str:
    return {"强": "低", "中": "中", "弱": "高"}.get(capability_rating, "中")


def _render_bundle_markdown(team, business, financial, tech_ip, legal, risk_register: list[RiskRegisterItem], evidence_index: list[Source]) -> str:
    """Deterministic汇总 render — no LLM call, purely re-presents data already produced by the 5
    sub-reports so the 深度尽调 aggregation step is a visible report, not just an internal data structure."""

    severity_counts = {"高": 0, "中": 0, "低": 0}
    for item in risk_register:
        severity_counts[item.severity] = severity_counts.get(item.severity, 0) + 1

    risk_lines = "\n".join(f"- [{item.severity}] [{item.category}] {item.description}" for item in risk_register) or "- 无"
    evidence_lines = "\n".join(f"- {s.title}{f'（{s.provider}）' if s.provider else ''}{f' {s.url}' if s.url else ''}" for s in evidence_index) or "- 无"

    return f"""# 深度尽调汇总报告

## 1. 各维度结论速览
- {summarize_team(team)}
- {summarize_business(business)}
- {summarize_financial(financial)}
- {summarize_tech_ip(tech_ip)}
- {summarize_legal(legal)}

## 2. 风险统计
- 高风险：{severity_counts['高']} 项
- 中风险：{severity_counts['中']} 项
- 低风险：{severity_counts['低']} 项

## 3. 风险清单（按严重度排序）
{risk_lines}

## 4. 证据来源汇总（去重后，共 {len(evidence_index)} 条）
{evidence_lines}
"""


__all__ = [
    "run_team_due_diligence",
    "run_business_due_diligence",
    "run_financial_due_diligence",
    "run_tech_ip_due_diligence",
    "run_legal_due_diligence",
    "build_due_diligence_bundle",
    "summarize_team",
    "summarize_business",
    "summarize_financial",
    "summarize_tech_ip",
    "summarize_legal",
]
