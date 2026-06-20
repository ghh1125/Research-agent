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
    for report in (team, business, financial, tech_ip, legal):
        evidence_index.extend(report.meta.sources)

    return DueDiligenceBundle(
        team=team,
        business=business,
        financial=financial,
        tech_ip=tech_ip,
        legal=legal,
        risk_register=risk_register,
        evidence_index=evidence_index,
    )


def _team_severity(capability_rating: str) -> str:
    return {"强": "低", "中": "中", "弱": "高"}.get(capability_rating, "中")


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
