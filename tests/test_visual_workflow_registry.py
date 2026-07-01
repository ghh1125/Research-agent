from __future__ import annotations

import pytest

from src.visual_workflow.registry import _llm_config, get_node_registry, validate_node_config


def test_registry_exposes_all_research_node_types() -> None:
    registry = get_node_registry()

    assert list(registry) == [
        "start",
        "projectOverview",
        "industryAnalysis",
        "competitorDiscovery",
        "competitorAnalysis",
        "deepDueDiligence",
        "teamDueDiligence",
        "businessDueDiligence",
        "financialDueDiligence",
        "techIpDueDiligence",
        "legalDueDiligence",
        "valuationAnalysis",
        "finalReport",
    ]


def test_unmodified_workflow_node_uses_catalog_default_model() -> None:
    config = _llm_config({}, "project_overview")

    assert config is not None
    assert config.model == "qwen3.7-plus"


def test_registry_describes_inputs_outputs_files_and_checkpoints() -> None:
    registry = get_node_registry()

    assert registry["start"].required_inputs == ()
    assert registry["start"].outputs == ("project_input",)
    assert [field.key for field in registry["start"].file_fields] == ["bp_files"]

    assert registry["competitorAnalysis"].required_inputs == (
        "project_input",
        "project_overview",
        "industry_analysis",
        "competitor_discovery",
    )
    assert registry["competitorAnalysis"].checkpoint == "competitor_report_review"

    aggregate = registry["deepDueDiligence"]
    assert aggregate.required_inputs == (
        "project_input",
        "project_overview",
        "industry_analysis",
        "competitor_analysis",
    )
    assert set(aggregate.outputs) == {
        "team_due_diligence",
        "business_due_diligence",
        "financial_due_diligence",
        "tech_ip_due_diligence",
        "legal_due_diligence",
        "due_diligence",
    }
    assert [field.key for field in aggregate.file_fields] == [
        "team_files",
        "financial_files",
        "business_plan_files",
        "tech_ip_files",
        "legal_files",
    ]

    assert [field.key for field in registry["financialDueDiligence"].file_fields] == ["financial_files"]
    assert registry["projectOverview"].checkpoint == "report_review"
    assert registry["industryAnalysis"].checkpoint == "report_review"
    assert registry["competitorDiscovery"].checkpoint == "competitor_selection"


def test_catalog_is_json_serializable_and_does_not_expose_runner() -> None:
    catalog = [definition.to_catalog_item() for definition in get_node_registry().values()]

    assert catalog[0]["type"] == "start"
    assert catalog[0]["description"]
    assert "runner" not in catalog[0]
    assert catalog[5]["fileFields"][0]["key"] == "team_files"
    assert catalog[0]["llmSteps"][0]["id"] == "start_normalization"
    assert catalog[0]["llmSteps"][0]["defaultModel"] == "qwen3.7-plus"
    assert "{raw_input}" in catalog[0]["llmSteps"][0]["defaultPrompt"]
    variable_help = catalog[0]["llmSteps"][0]["variableHelp"]
    assert variable_help[0] == {
        "name": "raw_input",
        "placeholder": "{raw_input}",
        "description": "开始节点表单中的公司名称、官网、融资轮次、融资金额、行业和项目描述。",
        "source": "开始节点用户输入",
    }
    assert variable_help[1]["name"] == "bp_text"
    assert variable_help[1]["source"] == "开始节点上传的 BP 文件"
    assert set(catalog[4]["llmSteps"][0]) >= {
        "id",
        "name",
        "defaultModel",
        "defaultPrompt",
        "variables",
        "variableHelp",
        "models",
    }
    assert [step["id"] for step in catalog[4]["llmSteps"]] == [
        "competitor_single",
        "competitor_synthesis",
    ]
    assert [step["id"] for step in catalog[5]["llmSteps"]] == [
        "team_due_diligence",
        "business_due_diligence",
        "financial_due_diligence",
        "tech_ip_due_diligence",
        "legal_due_diligence",
    ]
    for node in catalog:
        for step in node["llmSteps"]:
            assert [item["name"] for item in step["variableHelp"]] == step["variables"]
            assert all(item["description"] and item["source"] for item in step["variableHelp"])


def test_node_config_validation_rejects_unknown_prompt_variables_and_models() -> None:
    definition = get_node_registry()["projectOverview"]

    with pytest.raises(ValueError, match="项目概况生成.*未知模板变量"):
        validate_node_config(
            definition,
            {
                "llm_steps": {
                    "project_overview": {
                        "model": "qwen3.7-plus",
                        "prompt": "错误变量 {not_available}",
                    }
                }
            },
        )

    with pytest.raises(ValueError, match="不支持的模型"):
        validate_node_config(
            definition,
            {
                "llm_steps": {
                    "project_overview": {
                        "model": "qwen3.7-max",
                        "prompt": definition.llm_steps[0].default_prompt,
                    }
                }
            },
        )
