from __future__ import annotations

from src.nodes import competitor_analysis
from src.nodes.competitor_analysis import run_competitor_analysis
from src.schema import CompetitorCandidate, CompetitorDiscovery, IndustryAnalysis, ProjectInput, ProjectOverview


def test_prompt_uses_full_upstream_context_and_evidence_rules(fake_llm_client, fake_search_client) -> None:
    project_input = ProjectInput(
        company_name="目标公司",
        website="https://target.example.com",
        funding_round="A轮",
        industry="企业级人工智能",
        project_description="面向金融机构的知识库问答平台",
    )
    project_overview = ProjectOverview(
        company_registration_info="注册信息",
        development_milestones="发展历程",
        core_business="企业知识库问答",
        product_service_system="私有化部署的检索增强生成平台",
        use_cases_and_value="金融机构合规场景，降低知识检索成本",
        org_structure_and_operations="组织与运营",
    )
    industry_analysis = IndustryAnalysis(
        industry_definition="企业级生成式 AI",
        development_trends="从通用模型转向行业落地",
        market_size_and_drivers="合规需求和降本增效驱动",
        industry_chain_structure="模型、平台、应用",
        competitive_landscape="头部厂商集中，垂直场景仍分散",
        policy_environment="生成式 AI 与数据安全监管并行",
        opportunities_and_barriers="金融垂直场景有机会，但存在数据合规壁垒",
        opportunity_mapping_to_target="私有化交付能力匹配金融客户需求",
    )
    discovery = CompetitorDiscovery(
        candidates=[
            CompetitorCandidate(
                id="c1",
                name="竞品甲",
                website="https://competitor.example.com",
                product_or_service="企业知识助手",
                relationship="直接竞品",
                reason="客户群体与产品形态高度重合",
            )
        ],
        selected_ids=["c1"],
    )

    run_competitor_analysis(
        project_input,
        project_overview,
        industry_analysis,
        discovery,
        llm_client=fake_llm_client,
        search_client=fake_search_client,
        search_max_results=1,
    )

    prompt = fake_llm_client.prompts[-1]
    assert "企业知识库问答" in prompt
    assert "金融机构合规场景" in prompt
    assert "头部厂商集中，垂直场景仍分散" in prompt
    assert "数据合规壁垒" in prompt
    assert "竞品甲" in prompt
    assert "只分析用户最终确认的竞品" in prompt
    assert "事实、推断和资料不足" in prompt
    assert "对后续业务尽调和估值可比性的影响" in prompt


def test_capability_matrix_renders_as_markdown_table() -> None:
    rendered = competitor_analysis._render_capability_matrix(
        [
            {"dimension": "产品能力", "目标公司": "私有化|部署\n支持", "竞品甲": "SaaS 服务"},
            {"dimension": "商业模式", "目标公司": "订阅加实施", "竞品甲": "订阅制"},
        ]
    )

    assert "| 对比维度 | 目标公司 | 竞品甲 |" in rendered
    assert "| 产品能力 | 私有化\\|部署<br>支持 | SaaS 服务 |" in rendered
    assert "| 商业模式 | 订阅加实施 | 订阅制 |" in rendered


def test_prompt_keeps_every_selected_competitor_when_evidence_is_long(fake_llm_client) -> None:
    class LongEvidenceSearch:
        def search(self, query: str, *, category: str = "general", max_results: int = 5):
            return [
                {
                    "title": query,
                    "url": "https://example.com",
                    "content": ("长证据" * 4000) + "关键尾部证据",
                    "provider": "fake",
                }
            ]

    project_input = ProjectInput(company_name="目标公司", industry="企业服务")
    project_overview = ProjectOverview(
        company_registration_info="注册信息",
        development_milestones="发展历程",
        core_business="企业软件",
        product_service_system="管理平台",
        use_cases_and_value="提升运营效率",
        org_structure_and_operations="组织与运营",
    )
    industry_analysis = IndustryAnalysis(
        industry_definition="企业服务",
        development_trends="云化",
        market_size_and_drivers="数字化驱动",
        industry_chain_structure="软件与服务",
        competitive_landscape="竞争分散",
        policy_environment="合规经营",
        opportunities_and_barriers="客户迁移成本高",
        opportunity_mapping_to_target="垂直场景机会",
    )
    discovery = CompetitorDiscovery(
        candidates=[
            CompetitorCandidate(
                id="c1",
                name="竞品甲",
                product_or_service="产品甲",
                relationship="直接竞品",
                reason="同类产品",
            ),
            CompetitorCandidate(
                id="c2",
                name="竞品乙",
                product_or_service="产品乙",
                relationship="直接竞品",
                reason="同类客户",
            ),
        ],
        selected_ids=["c1", "c2"],
    )

    run_competitor_analysis(
        project_input,
        project_overview,
        industry_analysis,
        discovery,
        llm_client=fake_llm_client,
        search_client=LongEvidenceSearch(),
        search_max_results=1,
    )

    prompt = fake_llm_client.prompts[-1]
    assert "### 竞品甲" in prompt
    assert "### 竞品乙" in prompt
    assert "关键尾部证据" in prompt
