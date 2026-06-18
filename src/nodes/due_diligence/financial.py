from __future__ import annotations

import re

from pydantic import BaseModel, Field

from src.files import parse_files, truncate
from src.llm import RealLLMClient
from src.report import render_meta_section
from src.schema import FinancialDueDiligence, FinancialRatios, IndustryAnalysis, NodeMetaJudgment, ProjectInput, ProjectOverview

_KEYWORDS: dict[str, list[str]] = {
    "revenue": ["营业收入", "营业总收入", "营收"],
    "cost": ["营业成本", "营业总成本"],
    "net_profit": ["净利润", "归属于母公司所有者的净利润"],
    "operating_cash_flow": ["经营活动产生的现金流量净额", "经营活动现金流量净额"],
}

_PROMPT = """\
你在做一级市场投资项目的"财务尽调"。财务比率已经由程序确定性计算完成，你只负责解释，不要自己重新算数或编造新的数字。

已计算的财务比率（程序计算，非 LLM 生成）：
- 营业收入序列：{revenue}
- 营业成本序列：{cost}
- 毛利率（最新期）：{gross_margin}
- 净利率（最新期）：{net_margin}
- 经营活动现金流净额（最新期）：{ocf}
- 营收同比增速：{yoy}
- 数据来源说明：{computed_from}

公司：{company_name}　融资轮次：{funding_round}　融资金额：{funding_amount}
公司主营业务（参考）：{core_business}

行业市场规模与增长驱动（来自行业深度分析节点，供你判断毛利率/增速是否符合行业惯常水平）：
{market_size_and_drivers}

用户上传的财务文件解析文本（节选，可能为空，仅供你理解业务背景，不要从这里二次提取数字）：
{financial_file_text}

任务：
1. revenue_structure：收入结构解读（基于上面给出的营业收入序列和业务背景）
2. cost_structure：成本结构解读
3. unit_economics：经济模型/单位经济性解读
4. cash_flow_health：现金流健康度解读
5. financial_health_summary：财务健康度总结
6. risk_notes：财务风险提示列表（例如"数据未覆盖完整报告期""毛利率低于行业惯常水平"等，可结合行业市场规模与增长驱动判断）

如果上面的比率字段是 None/空，必须在 missing_info 里说明"未能从上传文件中提取到对应财务数据"，不要假设具体数值。
"""


class _FinancialLLM(BaseModel):
    revenue_structure: str
    cost_structure: str
    unit_economics: str
    cash_flow_health: str
    financial_health_summary: str
    risk_notes: list[str] = Field(default_factory=list)
    meta: NodeMetaJudgment = Field(default_factory=NodeMetaJudgment)


def _number(token: str) -> float | None:
    cleaned = token.replace(",", "").replace("，", "").strip()
    try:
        return float(cleaned)
    except ValueError:
        return None


def _extract_from_sheets(sheets: dict[str, list[list[str]]]) -> dict[str, list[float]]:
    found: dict[str, list[float]] = {}
    for rows in sheets.values():
        for row in rows:
            if not row:
                continue
            label_cell = row[0]
            for key, keywords in _KEYWORDS.items():
                if key in found:
                    continue
                if any(kw in label_cell for kw in keywords):
                    values = [v for v in (_number(c) for c in row[1:]) if v is not None]
                    if values:
                        found[key] = values
    return found


def _extract_from_text(text: str) -> dict[str, list[float]]:
    found: dict[str, list[float]] = {}
    for key, keywords in _KEYWORDS.items():
        for kw in keywords:
            pattern = re.compile(rf"{re.escape(kw)}[^0-9\-]{{0,10}}([\-0-9.,]+)")
            matches = pattern.findall(text)
            values = [v for v in (_number(m) for m in matches) if v is not None]
            if values:
                found[key] = values
                break
    return found


def compute_financial_ratios(parsed_files: list) -> FinancialRatios:
    """Deterministic figure extraction + ratio computation. No LLM involved in the arithmetic."""

    figures: dict[str, list[float]] = {}
    sources_used: list[str] = []
    for item in parsed_files:
        if item.sheets:
            extracted = _extract_from_sheets(item.sheets)
            if extracted:
                sources_used.append(f"{item.path} (表格)")
            for key, values in extracted.items():
                figures.setdefault(key, values)
        elif item.text:
            extracted = _extract_from_text(item.text)
            if extracted:
                sources_used.append(f"{item.path} (文本关键词匹配)")
            for key, values in extracted.items():
                figures.setdefault(key, values)

    ratios = FinancialRatios()
    revenue = figures.get("revenue", [])
    cost = figures.get("cost", [])
    net_profit = figures.get("net_profit", [])
    ocf = figures.get("operating_cash_flow", [])

    if revenue:
        ratios.revenue = {f"period_{i + 1}": v for i, v in enumerate(revenue)}
    if cost:
        ratios.cost = {f"period_{i + 1}": v for i, v in enumerate(cost)}
    if revenue and cost and revenue[-1]:
        ratios.gross_margin_pct = round((revenue[-1] - cost[-1]) / revenue[-1] * 100, 2)
    if revenue and net_profit and revenue[-1]:
        ratios.net_margin_pct = round(net_profit[-1] / revenue[-1] * 100, 2)
    if ocf:
        ratios.operating_cash_flow = ocf[-1]
    if len(revenue) >= 2 and revenue[-2]:
        ratios.revenue_yoy_growth_pct = round((revenue[-1] - revenue[-2]) / revenue[-2] * 100, 2)
    ratios.computed_from = "; ".join(sources_used) or "未提取到结构化财务数据"
    return ratios


def run_financial_due_diligence(
    project_input: ProjectInput,
    project_overview: ProjectOverview,
    industry_analysis: IndustryAnalysis,
    *,
    financial_files: list[str] | None = None,
    llm_client: RealLLMClient | None = None,
) -> FinancialDueDiligence:
    """Node 4 sub-report — 财务尽调. Ratios are computed deterministically in Python; the LLM only interprets."""

    parsed = parse_files(financial_files or [])
    ratios = compute_financial_ratios(parsed)
    financial_file_text = truncate("\n\n".join(p.text for p in parsed if p.text and not p.sheets), 4000)

    client = llm_client or RealLLMClient()
    result = client.complete_json(
        _PROMPT.format(
            revenue=ratios.revenue or "无数据",
            cost=ratios.cost or "无数据",
            gross_margin=ratios.gross_margin_pct,
            net_margin=ratios.net_margin_pct,
            ocf=ratios.operating_cash_flow,
            yoy=ratios.revenue_yoy_growth_pct,
            computed_from=ratios.computed_from,
            company_name=project_input.company_name,
            funding_round=project_input.funding_round or "未提供",
            funding_amount=project_input.funding_amount or "未提供",
            core_business=project_overview.core_business,
            market_size_and_drivers=industry_analysis.market_size_and_drivers,
            financial_file_text=financial_file_text or "(无补充文本)",
        ),
        _FinancialLLM,
    )

    meta = result.meta.to_meta([])
    risk_lines = "\n".join(f"- {r}" for r in result.risk_notes) or "- 无明显风险提示"
    markdown = f"""# 财务尽调报告

## 1. 收入结构
{result.revenue_structure}

## 2. 成本结构
{result.cost_structure}

## 3. 经济模型
{result.unit_economics}

## 4. 现金流健康度
{result.cash_flow_health}

## 5. 财务健康度总结
{result.financial_health_summary}

## 6. 关键比率（程序计算）
- 毛利率：{ratios.gross_margin_pct}
- 净利率：{ratios.net_margin_pct}
- 经营活动现金流净额：{ratios.operating_cash_flow}
- 营收同比增速：{ratios.revenue_yoy_growth_pct}

## 7. 风险提示
{risk_lines}
""" + render_meta_section(meta)

    return FinancialDueDiligence(
        revenue_structure=result.revenue_structure,
        cost_structure=result.cost_structure,
        unit_economics=result.unit_economics,
        cash_flow_health=result.cash_flow_health,
        financial_health_summary=result.financial_health_summary,
        ratios=ratios,
        risk_notes=result.risk_notes,
        markdown=markdown,
        meta=meta,
    )
