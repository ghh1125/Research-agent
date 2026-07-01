from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from src.files import parse_files, truncate
from src.llm import RealLLMClient
from src.llm_config import LLMCallConfig, llm_context, render_prompt
from src.schema import FileManifestEntry, NodeMeta, ProjectInput

_NORMALIZE_PROMPT = """\
你在做一级市场投资项目的信息接收和归一化。

用户原始输入：
{raw_input}

BP/补充文件解析出的文本（可能为空，截断展示）：
{bp_text}

任务：
1. 把公司名称、官网、融资轮次、融资金额、所属行业、项目描述归一化为标准字段；用户已直接提供的字段不要改变语义，只做格式规范化。
2. 如果用户没有提供某个字段，但 BP 文本里能找到，就从 BP 文本里补全，并在 missing_fields 留空；如果哪都找不到，把字段名加入 missing_fields。
3. 给出一句话的 data_quality_check，说明这次输入信息的完整度和主要缺口。
4. 不要编造没有依据的事实。
"""


class _NormalizedFields(BaseModel):
    company_name: str
    website: str | None = None
    funding_round: str | None = None
    funding_amount: str | None = None
    industry: str | None = None
    project_description: str = ""
    missing_fields: list[str] = Field(default_factory=list)
    data_quality_check: str = ""


_FILE_CATEGORY_BY_SUFFIX = {
    ".pdf": "bp_or_document",
    ".ppt": "bp_or_document",
    ".pptx": "bp_or_document",
    ".doc": "bp_or_document",
    ".docx": "bp_or_document",
    ".xls": "financial_statement",
    ".xlsx": "financial_statement",
}


def run_start(
    *,
    company_name: str | None = None,
    website: str | None = None,
    bp_files: list[str] | None = None,
    funding_round: str | None = None,
    funding_amount: str | None = None,
    industry: str | None = None,
    project_description: str | None = None,
    llm_client: RealLLMClient | None = None,
    llm_config: LLMCallConfig | None = None,
) -> ProjectInput:
    """Node 0 — 开始: receive raw user input + BP files, normalize into ProjectInput."""

    bp_files = bp_files or []
    parsed = parse_files(bp_files)
    manifest: list[FileManifestEntry] = []
    bp_texts: list[str] = []
    for item in parsed:
        from pathlib import Path

        category = _FILE_CATEGORY_BY_SUFFIX.get(Path(item.path).suffix.lower(), "other")
        manifest.append(FileManifestEntry(path=item.path, kind=item.kind, category=category, chars_extracted=len(item.text), error=item.error))
        if item.text:
            bp_texts.append(item.text)
    bp_parsed_content = truncate("\n\n".join(bp_texts), max_chars=12000)

    raw_input = {
        "company_name": company_name,
        "website": website,
        "funding_round": funding_round,
        "funding_amount": funding_amount,
        "industry": industry,
        "project_description": project_description,
    }
    client = llm_client or RealLLMClient()
    prompt_values = {
        "raw_input": raw_input,
        "bp_text": truncate(bp_parsed_content, 4000) or "(无)",
    }
    normalized = client.complete_json(
        render_prompt(_NORMALIZE_PROMPT, prompt_values, llm_config),
        _NormalizedFields,
        context=llm_context(llm_config),
    )

    meta = NodeMeta(
        missing_info=normalized.missing_fields,
        confidence="high" if not normalized.missing_fields else "medium",
    )
    return ProjectInput(
        company_name=normalized.company_name or company_name or "未知公司",
        website=normalized.website or website,
        funding_round=normalized.funding_round or funding_round,  # type: ignore[arg-type]
        funding_amount=normalized.funding_amount or funding_amount,
        industry=normalized.industry or industry,
        project_description=normalized.project_description or project_description or "",
        bp_parsed_content=bp_parsed_content,
        file_manifest=manifest,
        missing_fields=normalized.missing_fields,
        data_quality_check=normalized.data_quality_check,
        meta=meta,
    )
