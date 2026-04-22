from __future__ import annotations

from app.agent.prompts.decompose_prompt import DECOMPOSE_PROMPT_TEMPLATE
from app.agent.prompts.define_prompt import DEFINE_PROMPT_TEMPLATE
from app.agent.prompts.extract_prompt import EXTRACT_PROMPT_TEMPLATE
from app.agent.prompts.reason_prompt import LOGIC_GAP_PROMPT_TEMPLATE, REASON_PROMPT_TEMPLATE
from app.agent.prompts.role_prompts import ROLE_CONTRACTS


def test_decompose_prompt_uses_real_research_role_not_module_identity() -> None:
    assert "你是一名专业的买方投研研究总监" in DECOMPOSE_PROMPT_TEMPLATE
    assert "Research Agent 的 Decompose 模块" not in DECOMPOSE_PROMPT_TEMPLATE
    assert "真实工作场景" in DECOMPOSE_PROMPT_TEMPLATE


def test_decompose_prompt_requires_framework_type_for_question_model_alignment() -> None:
    assert '"framework_type": "financial"' in DECOMPOSE_PROMPT_TEMPLATE
    assert '"search_query": "..."' in DECOMPOSE_PROMPT_TEMPLATE
    for framework_type in ["financial", "credit", "valuation", "industry", "adversarial", "gap"]:
        assert framework_type in DECOMPOSE_PROMPT_TEMPLATE


def test_core_prompts_use_real_professional_roles_not_module_identity() -> None:
    prompt_texts = [
        DEFINE_PROMPT_TEMPLATE,
        DECOMPOSE_PROMPT_TEMPLATE,
        EXTRACT_PROMPT_TEMPLATE,
        REASON_PROMPT_TEMPLATE,
        LOGIC_GAP_PROMPT_TEMPLATE,
        *(contract["role_prompt"] for contract in ROLE_CONTRACTS.values()),
    ]
    combined = "\n".join(prompt_texts)

    forbidden_fragments = [
        "你是 Research Agent",
        "Research Agent 的",
        "Define 模块",
        "Decompose 模块",
        "Extract 模块",
        "Reason 模块",
        "压力测试模块",
        "报告润色模块",
    ]
    for fragment in forbidden_fragments:
        assert fragment not in combined

    expected_roles = [
        "买方投研需求分析师",
        "专业的买方投研研究总监",
        "投研证据审阅员",
        "买方主研究员",
        "投研蓝军审稿人",
        "风控官",
        "投资经理",
    ]
    for role in expected_roles:
        assert role in combined
