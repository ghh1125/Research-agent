from __future__ import annotations

import re
from urllib.parse import urlparse

from pydantic import BaseModel, Field

from src.llm import RealLLMClient
from src.llm_config import LLMCallConfig, llm_context, render_prompt
from src.schema import CompetitorCandidate, CompetitorDiscovery, IndustryAnalysis, NodeMetaJudgment, ProjectInput, ProjectOverview, Source
from src.search import RealSearchClient, collect_evidence

_PROMPT = """\
你在为一级市场投资项目做"竞品发现"，目的是列出一份候选竞品 longlist，供投资人后续筛选确认。

目标公司：{company_name}
主营业务：{core_business}
核心产品/服务：{product_service}
所属行业：{industry}
行业竞争格局参考：{competitive_landscape}

公开检索结果（节选）：
{search_text}

任务：列出 5-10 家候选竞品，每家包含：
- name：公司名称
- website：官网（找不到留空）
- region：所属地区
- product_or_service：产品/服务简述
- relationship：与目标公司的竞争关系（直接竞品/潜在竞品/替代方案提供方等）
- reason：推荐纳入 longlist 的理由

候选竞品要包括：同赛道同产品形态公司、同客户群体的公司、可能构成替代方案的公司。
不要编造检索结果里完全没有依据的公司；如果某项信息找不到就留空或写"未公开"。
"""


class _CandidateLLM(BaseModel):
    name: str
    website: str | None = None
    region: str | None = None
    product_or_service: str
    relationship: str
    reason: str


class _CompetitorDiscoveryLLM(BaseModel):
    candidates: list[_CandidateLLM] = Field(default_factory=list, min_length=1, max_length=10)
    meta: NodeMetaJudgment = Field(default_factory=NodeMetaJudgment)


def run_competitor_discovery(
    project_input: ProjectInput,
    project_overview: ProjectOverview,
    industry_analysis: IndustryAnalysis,
    *,
    llm_client: RealLLMClient | None = None,
    search_client: RealSearchClient | None = None,
    search_max_results: int = 5,
    llm_config: LLMCallConfig | None = None,
) -> CompetitorDiscovery:
    """Node 3.1 — 竞品发现 (longlist, before user selection)."""

    search_client = search_client or RealSearchClient()
    queries = [
        f"{project_input.company_name} 竞品 竞争对手",
        f"{project_input.industry or ''} {project_overview.core_business} 同类公司",
        f"{project_input.industry or ''} 替代方案 产品",
    ]
    search_text, sources = collect_evidence(search_client, queries, category="competitor_discovery", max_results=search_max_results)

    client = llm_client or RealLLMClient()
    prompt_values = {
        "company_name": project_input.company_name,
        "core_business": project_overview.core_business,
        "product_service": project_overview.product_service_system,
        "industry": project_input.industry or "未提供",
        "competitive_landscape": industry_analysis.competitive_landscape,
        "search_text": search_text[:7000] or "(无检索结果)",
    }
    result = client.complete_json(
        render_prompt(_PROMPT, prompt_values, llm_config),
        _CompetitorDiscoveryLLM,
        context=llm_context(llm_config),
    )

    candidates = [
        CompetitorCandidate(
            id=f"cand-{idx}",
            name=c.name,
            website=c.website,
            region=c.region,
            product_or_service=c.product_or_service,
            relationship=c.relationship,
            reason=c.reason,
            source=_match_source(c.name, c.website, sources),
        )
        for idx, c in enumerate(result.candidates, start=1)
    ]
    meta = result.meta.to_meta(sources)
    return CompetitorDiscovery(candidates=candidates, selected_ids=[], meta=meta)


def _match_source(name: str, website: str | None, sources: list[Source]) -> Source | None:
    """Best-effort attribution: only return a source that actually mentions this candidate.
    Returns None (rather than a misleading unrelated source) when nothing matches."""

    for source in sources:
        if name in source.title or source.title in name:
            return source

    tokens = [t for t in re.split(r"[（）()，,、\s]+", name) if len(t) >= 2 and not (t.isascii() and len(t) < 3)]
    for source in sources:
        haystack = f"{source.title} {source.url or ''}"
        if any(token in haystack for token in tokens):
            return source

    if website:
        domain = urlparse(website if "://" in website else f"//{website}").netloc.replace("www.", "")
        if domain:
            for source in sources:
                if source.url and domain in source.url:
                    return source

    return None
