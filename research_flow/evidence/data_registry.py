from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from research_flow.evidence.knowledge_store import LocalKnowledgeStore
from research_flow.evidence.search import RealSearchClient, fetch_url_text
from research_flow.evidence.tools import DataToolProvider, default_tool_providers
from research_flow.schema import DataArtifact, Evidence, EvidenceBundle, ResearchGraphConfig, ResearchPlan, ResearchTask


@dataclass(frozen=True)
class DataToolSpec:
    name: str
    category: str
    description: str


CATEGORY_QUERIES: dict[str, str] = {
    "market_data": "{subject} {symbol} stock price valuation market data technical indicators",
    "financial_statements": "{subject} {symbol} annual report income statement cash flow balance sheet revenue gross margin",
    "filings": "{subject} {symbol} official filing annual report investor relations SEC HKEX cninfo",
    "news": "{subject} {symbol} recent news earnings product price competition policy",
    "macro": "{subject} industry macro policy interest rates FX cycle demand",
    "industry": "{subject} industry supply demand competition market share supply chain",
    "valuation": "{subject} {symbol} valuation PE EV EBITDA DCF comparable companies target price",
}


class DataToolRegistry:
    """Data tool registry with real provider calls and evidence deposit."""

    def __init__(
        self,
        knowledge_store: LocalKnowledgeStore,
        *,
        search_client: Any | None = None,
        llm_client: Any | None = None,
        config: ResearchGraphConfig | None = None,
        tool_providers: list[DataToolProvider] | None = None,
        progress_callback: Callable[[str], None] | None = None,
    ) -> None:
        self.knowledge_store = knowledge_store
        self.search_client = search_client or RealSearchClient()
        self.llm_client = llm_client
        self.config = config or ResearchGraphConfig()
        self.progress_callback = progress_callback
        if tool_providers is not None:
            self.tool_providers = tool_providers
        elif search_client is not None and not isinstance(search_client, RealSearchClient):
            self.tool_providers = []
        else:
            self.tool_providers = default_tool_providers()
        self.tools = [
            DataToolSpec("market_data.search", "market_data", "真实行情、价格、波动率、技术指标检索"),
            DataToolSpec("financial_statements.search", "financial_statements", "真实财报、利润表、现金流、资产负债表检索"),
            DataToolSpec("filings.search", "filings", "SEC/A 股/港交所/公司 IR 官方公告检索"),
            DataToolSpec("news.search", "news", "真实新闻、公告、事件和催化剂检索"),
            DataToolSpec("macro.search", "macro", "真实利率、汇率、政策、周期检索"),
            DataToolSpec("industry.search", "industry", "真实行业供需、竞争格局、产业链检索"),
            DataToolSpec("valuation.search", "valuation", "真实历史估值、可比公司、DCF 输入检索"),
            DataToolSpec("knowledge.local", "knowledge", "本地知识目录和用户材料检索"),
        ]

    def list_tools(self) -> list[dict[str, str]]:
        return [tool.__dict__.copy() for tool in self.tools]

    def collect(self, task: ResearchTask, plan: ResearchPlan) -> EvidenceBundle:
        artifacts: list[DataArtifact] = []
        errors: dict[str, str] = {}
        counts: dict[str, int] = {}
        for category in ["market_data", "financial_statements", "filings", "news", "macro", "industry", "valuation"]:
            if category not in plan.data_sources:
                continue
            try:
                self._emit(f"  - data[{category}] start")
                batch = self._native_category(task, plan, category)
                if batch:
                    providers = sorted({artifact.provider for artifact in batch})
                    self._emit(f"  - data[{category}] native providers={','.join(providers)} artifacts={len(batch)}")
                else:
                    self._emit(f"  - data[{category}] native empty; search fallback")
                    batch = self._search_category(task, category)
                    providers = sorted({artifact.provider for artifact in batch})
                    self._emit(f"  - data[{category}] search providers={','.join(providers) or 'none'} artifacts={len(batch)}")
                artifacts.extend(batch)
                counts[category] = len(batch)
            except Exception as exc:
                errors[category] = str(exc)
                counts[category] = 0
                self._emit(f"  - data[{category}] error={exc}")

        artifacts.extend(self._local_knowledge_artifacts(task))
        counts["knowledge"] = counts.get("knowledge", 0) + len([a for a in artifacts if a.category == "knowledge"])
        if self.config.require_search_results and not artifacts:
            raise RuntimeError(f"No evidence artifacts collected. Tool errors: {errors}")

        self._emit(f"  - evidence extraction start artifacts={len(artifacts)}")
        evidence = self._extract_evidence_with_llm(task, plan, artifacts)
        self._emit(f"  - evidence extraction done evidence={len(evidence)}")
        bundle = EvidenceBundle(artifacts=artifacts, evidence=evidence, tool_counts=counts, tool_errors=errors)
        for artifact in artifacts:
            self.knowledge_store.add_artifact(task, artifact)
        for item in evidence:
            self.knowledge_store.add_evidence(task, item)
        return bundle

    def _native_category(self, task: ResearchTask, plan: ResearchPlan, category: str) -> list[DataArtifact]:
        artifacts: list[DataArtifact] = []
        for provider in self.tool_providers:
            if provider.category != category:
                continue
            batch = provider.collect(task, plan)
            artifacts.extend(batch)
        return artifacts

    def _search_category(self, task: ResearchTask, category: str) -> list[DataArtifact]:
        subject = task.entity or (task.symbols[0] if task.symbols else task.raw_query)
        symbol = task.symbols[0] if task.symbols else subject
        query = CATEGORY_QUERIES[category].format(subject=subject, symbol=symbol)
        return self.search_query(task, category, query)

    def search_query(self, task: ResearchTask, category: str, query: str) -> list[DataArtifact]:
        symbol = task.symbols[0] if task.symbols else task.entity or task.raw_query
        self._emit(f"    search[{category}] query={query[:160]}")
        results = self.search_client.search(query, category=category, max_results=self.config.search_max_results)
        artifacts: list[DataArtifact] = []
        for idx, result in enumerate(results, start=1):
            url = result.get("url")
            content = result.get("content") or result.get("snippet") or ""
            if self.config.fetch_source_content and url and len(content) < 1000:
                try:
                    self._emit(f"    fetch[{category}] url={url} timeout={self.config.source_fetch_timeout_seconds}s")
                    fetched = fetch_url_text(url, timeout=self.config.source_fetch_timeout_seconds)
                    if fetched:
                        content = fetched
                        self._emit(f"    fetch[{category}] done chars={len(content)}")
                    else:
                        self._emit(f"    fetch[{category}] empty")
                except Exception as exc:
                    self._emit(f"    fetch[{category}] skipped error={type(exc).__name__}: {str(exc)[:160]}")
            artifacts.append(
                DataArtifact(
                    id=f"{category}_{idx}",
                    category=category,
                    title=result.get("title") or f"{category} source {idx}",
                    source_type=result.get("source_type") or category,
                    provider=result.get("provider") or "search",
                    url=url,
                    content=content,
                    metadata={"query": query, "market": task.market, "symbol": symbol},
                )
            )
        return artifacts

    def collect_followup(self, task: ResearchTask, plan: ResearchPlan, categories: list[str], queries: list[str]) -> EvidenceBundle:
        artifacts: list[DataArtifact] = []
        errors: dict[str, str] = {}
        counts: dict[str, int] = {}
        self._emit(f"  - followup collection start categories={','.join(categories)} queries={len(queries)}")
        for category in categories:
            if category not in CATEGORY_QUERIES:
                errors[category] = "unsupported followup category"
                counts[category] = 0
                self._emit(f"  - followup[{category}] skipped unsupported category")
                continue
            try:
                if queries:
                    batch: list[DataArtifact] = []
                    for query in queries:
                        batch.extend(self.search_query(task, category, query))
                else:
                    batch = self._native_category(task, plan, category) or self._search_category(task, category)
                artifacts.extend(batch)
                counts[category] = counts.get(category, 0) + len(batch)
                providers = sorted({artifact.provider for artifact in batch})
                self._emit(f"  - followup[{category}] providers={','.join(providers) or 'none'} artifacts={len(batch)}")
            except Exception as exc:
                errors[category] = str(exc)
                counts[category] = 0
                self._emit(f"  - followup[{category}] error={exc}")
        evidence = self._extract_evidence_with_llm(task, plan, artifacts)
        bundle = EvidenceBundle(artifacts=artifacts, evidence=evidence, tool_counts=counts, tool_errors=errors)
        for artifact in artifacts:
            self.knowledge_store.add_artifact(task, artifact)
        for item in evidence:
            self.knowledge_store.add_evidence(task, item)
        return bundle

    def _emit(self, message: str) -> None:
        if self.progress_callback is not None:
            self.progress_callback(message)

    def _local_knowledge_artifacts(self, task: ResearchTask) -> list[DataArtifact]:
        query = " ".join([task.entity or "", *task.symbols]).strip() or task.raw_query
        records = self.knowledge_store.search(query, limit=5)
        return [
            DataArtifact(
                id=f"knowledge_{idx}",
                category="knowledge",
                title=record.title,
                source_type="local_knowledge",
                provider="local_knowledge_store",
                content=record.content,
                metadata=record.metadata,
            )
            for idx, record in enumerate(records, start=1)
        ]

    def _extract_evidence_with_llm(self, task: ResearchTask, plan: ResearchPlan, artifacts: list[DataArtifact]) -> list[Evidence]:
        if not artifacts:
            return []
        if self.config.enable_llm and self.llm_client is not None:
            sanitized: list[Evidence] = []
            batches = list(self._artifact_batches(artifacts))
            for batch_index, batch in enumerate(batches, start=1):
                self._emit(f"  - evidence extraction batch {batch_index}/{len(batches)} artifacts={len(batch)}")
                prompt = f"""
你是严谨的投研证据抽取器。请从真实检索到的来源中抽取结构化证据。
要求：
- 只基于 artifacts 内容，不要编造。
- evidence.artifact_id 必须来自输入 artifact id。
- category 使用来源 category。
- 每条证据写清 claim、metric_name/metric_value/period/source_title/source_url/quality。
- 每个 artifact 最多抽取 1 条最关键证据；没有实质内容的 artifact 可以不抽。

任务：{task.model_dump_json()}
研究计划：{plan.model_dump_json()}
artifacts:
{self._artifact_context(batch)}
""".strip()
                extracted = self.llm_client.complete_json(
                    prompt,
                    EvidenceBundle,
                    role="quick",
                    context={"stage": "evidence_extraction", "quick_model": task.quick_model, "deep_model": task.deep_model},
                )
                sanitized.extend(self._sanitize_evidence(extracted.evidence, batch))
            sanitized = self._dedupe_evidence_ids(sanitized)
            if sanitized:
                return sanitized
            if not self.config.allow_heuristic_fallback:
                raise RuntimeError("LLM evidence extraction returned no valid evidence")
        if not self.config.allow_heuristic_fallback:
            raise RuntimeError("LLM evidence extraction is required but no LLM client is configured")
        return self._heuristic_evidence(artifacts)

    def _sanitize_evidence(self, evidence: list[Evidence], artifacts: list[DataArtifact]) -> list[Evidence]:
        artifacts_by_id = {artifact.id: artifact for artifact in artifacts}
        sanitized: list[Evidence] = []
        seen: set[str] = set()
        for item in evidence:
            artifact = artifacts_by_id.get(item.artifact_id)
            if artifact is None:
                continue
            source_url = item.source_url or artifact.url
            source_title = item.source_title or artifact.title
            quality = item.quality
            if artifact.metadata.get("official") and quality == "medium":
                quality = "high"
            item_id = item.id or f"e{len(sanitized) + 1}"
            if item_id in seen:
                item_id = f"e{len(sanitized) + 1}"
            seen.add(item_id)
            sanitized.append(
                item.model_copy(
                    update={
                        "id": item_id,
                        "category": artifact.category,
                        "source_url": source_url,
                        "source_title": source_title,
                        "quality": quality,
                    }
                )
            )
        return sanitized

    def _artifact_batches(self, artifacts: list[DataArtifact]):
        batch_size = max(1, self.config.evidence_extraction_batch_size)
        for start in range(0, len(artifacts), batch_size):
            yield artifacts[start : start + batch_size]

    def _artifact_context(self, artifacts: list[DataArtifact]) -> str:
        lines: list[str] = []
        max_chars = max(200, self.config.evidence_context_chars_per_artifact)
        for artifact in artifacts:
            lines.append(
                f"[{artifact.id}] category={artifact.category} title={artifact.title} url={artifact.url}\n"
                f"{artifact.content[:max_chars]}"
            )
        return "\n\n".join(lines)

    def _dedupe_evidence_ids(self, evidence: list[Evidence]) -> list[Evidence]:
        deduped: list[Evidence] = []
        seen: set[str] = set()
        for item in evidence:
            item_id = item.id
            if item_id in seen:
                item_id = f"e{len(deduped) + 1}"
            seen.add(item_id)
            deduped.append(item.model_copy(update={"id": item_id}))
        return deduped

    def _heuristic_evidence(self, artifacts: list[DataArtifact]) -> list[Evidence]:
        evidence: list[Evidence] = []
        for artifact in artifacts:
            if not artifact.content.strip():
                continue
            evidence.append(
                Evidence(
                    id=f"e{len(evidence) + 1}",
                    artifact_id=artifact.id,
                    category=artifact.category,
                    claim=artifact.content[:500],
                    source_title=artifact.title,
                    source_url=artifact.url,
                    quality="high" if artifact.metadata.get("official") else "medium",
                )
            )
        return evidence
