from __future__ import annotations

import unittest
from unittest.mock import patch

from app.agent.steps.auto_research import auto_research_loop, build_official_target_candidates, mark_official_target_sources
from app.models.judgment import ConfidenceBasis, EvidenceGap, Judgment, ResearchAction
from app.models.question import Question
from app.models.source import Source
from app.models.source import SourceTier
from app.models.topic import Topic


class AutoResearchLoopTest(unittest.TestCase):
    def test_builds_generic_official_target_candidates_without_company_whitelist(self) -> None:
        topic = Topic(
            id="topic_001",
            query="研究阿里巴巴财务质量",
            topic="阿里巴巴财务质量",
            goal="判断是否值得研究",
            type="company",
            entity="阿里巴巴",
            research_object_type="listed_company",
            listing_status="listed",
            market_type="US",
        )
        questions = [Question(id="q1", topic_id=topic.id, content="财务质量如何", priority=1, framework_type="financial")]
        action = ResearchAction(
            id="a1",
            priority="high",
            objective="补齐官方财务来源",
            reason="缺少官方源",
            required_data=["财报"],
            query_templates=["{entity} investor relations quarterly results"],
            source_targets=["official filings", "investor relations"],
        )

        candidates = build_official_target_candidates(topic, questions, action, start_index=1)

        self.assertGreaterEqual(len(candidates), 5)
        self.assertTrue(all(item.is_official_target_source for item in candidates))
        self.assertTrue(any("investor" in (item.url or "").lower() for item in candidates))
        self.assertTrue(any("sec.gov" in (item.url or "").lower() for item in candidates))
        self.assertTrue(all(item.target_reason for item in candidates))

    def test_marks_aggregator_results_as_rejected_official_targets(self) -> None:
        topic = Topic(
            id="topic_001",
            query="研究公司财务",
            topic="公司财务",
            goal="判断是否值得研究",
            type="company",
            entity="测试公司",
        )
        action = ResearchAction(
            id="a1",
            priority="high",
            objective="补齐官方财务来源",
            reason="缺少官方源",
            required_data=["财报"],
            query_templates=["{entity} 财报"],
            source_targets=["official filings", "investor relations"],
        )
        sources = [
            Source(
                id="s1",
                question_id="q1",
                title="测试公司 Annual Report Mirror",
                url="https://www.annualreports.com/Company/test",
                source_type="website",
                provider="fixture",
                source_origin_type="aggregator",
                tier=SourceTier.TIER2,
                content="测试公司 annual report mirror.",
            ),
            Source(
                id="s2",
                question_id="q1",
                title="测试公司 Investor Relations",
                url="https://investors.testcompany.com/results",
                source_type="company",
                provider="fixture",
                source_origin_type="company_ir",
                tier=SourceTier.TIER1,
                content="测试公司 Investor Relations quarterly results.",
            ),
        ]

        marked, stats = mark_official_target_sources(sources, topic, action)

        self.assertFalse(marked[0].is_official_target_source)
        self.assertEqual(marked[0].rejected_reason, "site_role_not_official")
        self.assertTrue(marked[1].is_official_target_source)
        self.assertEqual(stats["official_candidates"], 2)
        self.assertEqual(stats["targetable"], 1)
        self.assertEqual(stats["rejected"], 1)

    @patch("app.agent.steps.reason.call_llm", side_effect=RuntimeError("skip llm in unit test"))
    def test_low_confidence_with_action_triggers_one_round(self, reason_llm_mock) -> None:
        topic = Topic(
            id="topic_001",
            query="拼多多增长是否可持续",
            topic="拼多多高增长模式可持续性",
            goal="评估增长质量",
            type="company",
            entity="拼多多",
        )
        questions = [Question(id="q1", topic_id=topic.id, content="现金流和财报数据如何", priority=1)]
        judgment = Judgment(
            topic_id=topic.id,
            conclusion="当前证据不足以支撑明确结论",
            conclusion_evidence_ids=[],
            clusters=[],
            risk=[],
            unknown=["缺少官方来源"],
            evidence_gaps=[EvidenceGap(question_id="q1", text="子问题证据不足：现金流和财报数据如何", importance="high")],
            confidence="low",
            confidence_basis=ConfidenceBasis(
                source_count=0,
                source_diversity="low",
                conflict_level="none",
                evidence_gap_level="high",
                effective_evidence_count=0,
                has_official_source=False,
                official_evidence_count=0,
                weak_source_only=True,
            ),
            research_actions=[],
        )
        actions = [
            ResearchAction(
                id="a1",
                priority="high",
                objective="补齐现金流和财报数据",
                reason="缺少官方来源",
                required_data=["营收", "净利润", "经营现金流"],
                query_templates=["{entity} 财报 现金流"],
                source_targets=["official filings"],
                question_id="q1",
            )
        ]

        def fake_retrieve(topic, questions, action, existing_sources, start_index):
            return [
                Source(
                    id=f"s{start_index}",
                    question_id="q1",
                    flow_type="fact",
                    search_query="拼多多 财报 现金流",
                    title="PDD Holdings quarterly results",
                    url="https://investor.pddholdings.com/news",
                    source_type="company",
                    provider="fixture",
                    credibility_tier="tier1",
                    tier=SourceTier.TIER1,
                    source_score=0.92,
                    contains_entity=True,
                    is_recent=True,
                    content="拼多多财报显示，2025年营收保持增长，经营现金流改善，净利润仍需观察。",
                )
            ], ["拼多多 财报 现金流"]

        with patch(
            "app.services.llm_evidence_extractor.call_llm",
            return_value=(
                '{"evidences":[{"metric_name":"operating_cash_flow","metric_value":12,"unit":"亿元",'
                '"period":"FY2025","entity":"拼多多","quote":"2025年经营现金流改善至12亿元。",'
                '"extraction_confidence":0.9}]}'
            ),
        ):
            result = auto_research_loop(
                topic,
                questions,
                sources=[],
                evidence=[],
                variables=[],
                judgment=judgment,
                actions=actions,
                max_rounds=1,
                retrieve_fn=fake_retrieve,
            )

        self.assertTrue(result.trace)
        self.assertTrue(result.trace[0].triggered)
        self.assertTrue(result.trace[0].new_source_ids)
        self.assertTrue(result.trace[0].new_evidence_ids)
        self.assertEqual(result.trace[0].effectiveness_status, "effective")
        self.assertTrue(result.evidence)

    def test_loop_stops_safely_when_no_new_sources(self) -> None:
        topic = Topic(
            id="topic_001",
            query="研究公司",
            topic="公司研究",
            goal="判断研究价值",
            type="company",
            entity="测试公司",
        )
        questions = [Question(id="q1", topic_id=topic.id, content="财务质量如何", priority=1)]
        basis = ConfidenceBasis(
            source_count=0,
            source_diversity="low",
            conflict_level="none",
            evidence_gap_level="high",
            effective_evidence_count=0,
            has_official_source=False,
            official_evidence_count=0,
            weak_source_only=True,
        )
        judgment = Judgment(
            topic_id=topic.id,
            conclusion="当前证据不足以支撑明确结论",
            conclusion_evidence_ids=[],
            clusters=[],
            risk=[],
            unknown=["缺少证据"],
            evidence_gaps=[],
            confidence="low",
            confidence_basis=basis,
            research_actions=[],
        )
        actions = [
            ResearchAction(
                id="a1",
                priority="high",
                objective="补齐官方来源",
                reason="缺少证据",
                required_data=["财报"],
                query_templates=["{entity} 财报"],
                source_targets=["official filings"],
            )
        ]

        def empty_retrieve(topic, questions, action, existing_sources, start_index):
            return [], ["测试公司 财报"]

        result = auto_research_loop(
            topic,
            questions,
            [],
            [],
            [],
            judgment,
            actions,
            max_rounds=1,
            retrieve_fn=empty_retrieve,
        )

        self.assertTrue(result.trace[0].triggered)
        self.assertIn("未检索到新增可用来源", result.trace[0].stop_reason)
        self.assertEqual(result.evidence, [])
        self.assertEqual(result.actions[0].status, "skipped_no_official_target_source")
        self.assertIn("官方目标源", result.actions[0].status_reason or "")

    def test_loop_marks_ineffective_when_new_evidence_misses_target_gap(self) -> None:
        topic = Topic(
            id="topic_001",
            query="研究公司",
            topic="公司研究",
            goal="判断研究价值",
            type="company",
            entity="测试公司",
        )
        questions = [
            Question(id="q1", topic_id=topic.id, content="现金流如何", priority=1),
            Question(id="q2", topic_id=topic.id, content="行业竞争如何", priority=1),
        ]
        basis = ConfidenceBasis(
            source_count=0,
            source_diversity="low",
            conflict_level="none",
            evidence_gap_level="high",
            effective_evidence_count=0,
            has_official_source=False,
            official_evidence_count=0,
            weak_source_only=True,
        )
        judgment = Judgment(
            topic_id=topic.id,
            conclusion="当前证据不足以支撑明确结论",
            conclusion_evidence_ids=[],
            clusters=[],
            risk=[],
            unknown=["缺少证据"],
            evidence_gaps=[],
            confidence="low",
            confidence_basis=basis,
            research_actions=[],
        )
        actions = [
            ResearchAction(
                id="a1",
                priority="high",
                objective="补齐现金流证据",
                reason="缺少现金流证据",
                required_data=["现金流"],
                query_templates=["{entity} 现金流"],
                source_targets=["official filings"],
                question_id="q_missing",
            )
        ]

        def fake_retrieve(topic, questions, action, existing_sources, start_index):
            return [
                Source(
                    id=f"s{start_index}",
                    question_id="q2",
                    flow_type="fact",
                    search_query="测试公司 行业竞争",
                    title="行业竞争资料",
                    url="https://example.com/industry",
                    source_type="website",
                    provider="fixture",
                    source_score=0.8,
                    content="测试公司行业竞争格局仍在变化，市场份额需要继续观察。",
                )
            ], ["测试公司 行业竞争"]

        with patch(
            "app.services.llm_evidence_extractor.call_llm",
            return_value=(
                '{"evidences":[{"metric_name":"market_share","metric_value":18,"unit":"%",'
                '"period":"FY2025","entity":"测试公司","quote":"FY2025测试公司市场份额为18%。",'
                '"extraction_confidence":0.9}]}'
            ),
        ):
            result = auto_research_loop(
                topic,
                questions,
                [],
                [],
                [],
                judgment,
                actions,
                max_rounds=1,
                retrieve_fn=fake_retrieve,
            )

        self.assertEqual(result.trace[0].effectiveness_status, "ineffective")
        self.assertEqual(result.trace[0].covered_gap_question_ids, [])
        self.assertEqual(result.actions[0].status, "attempted_but_not_covering_gap")
        self.assertIn("未覆盖目标证据缺口", result.actions[0].status_reason or "")

    def test_loop_marks_low_quality_only_when_sources_extract_no_evidence(self) -> None:
        topic = Topic(
            id="topic_001",
            query="研究公司",
            topic="公司研究",
            goal="判断研究价值",
            type="company",
            entity="测试公司",
        )
        questions = [Question(id="q1", topic_id=topic.id, content="财务质量如何", priority=1)]
        basis = ConfidenceBasis(
            source_count=0,
            source_diversity="low",
            conflict_level="none",
            evidence_gap_level="high",
            effective_evidence_count=0,
            has_official_source=False,
            official_evidence_count=0,
            weak_source_only=True,
        )
        judgment = Judgment(
            topic_id=topic.id,
            conclusion="当前证据不足以支撑明确结论",
            conclusion_evidence_ids=[],
            clusters=[],
            risk=[],
            unknown=["缺少证据"],
            evidence_gaps=[],
            confidence="low",
            confidence_basis=basis,
            research_actions=[],
        )
        actions = [
            ResearchAction(
                id="a1",
                priority="high",
                objective="补齐财务质量",
                reason="缺少证据",
                required_data=["财报"],
                query_templates=["{entity} 财报"],
                source_targets=["professional finance media"],
            )
        ]

        def low_quality_retrieve(topic, questions, action, existing_sources, start_index):
            return [
                Source(
                    id=f"s{start_index}",
                    question_id="q1",
                    title="测试公司导航页",
                    url="https://example.com/nav",
                    source_type="website",
                    provider="fixture",
                    content="登录 注册 菜单 首页 联系电话 公司网址",
                )
            ], ["测试公司 财报"]

        result = auto_research_loop(
            topic,
            questions,
            [],
            [],
            [],
            judgment,
            actions,
            max_rounds=1,
            retrieve_fn=low_quality_retrieve,
        )

        self.assertEqual(result.actions[0].status, "attempted_low_quality_only")
        self.assertIn("低质量证据", result.actions[0].status_reason or "")

    @patch("app.agent.steps.reason.call_llm", side_effect=RuntimeError("skip llm in unit test"))
    def test_official_metric_additions_can_upgrade_confidence_after_auto_research(self, reason_llm_mock) -> None:
        topic = Topic(
            id="topic_900",
            query="我想投资阿里巴巴，是否值得进一步研究",
            topic="阿里巴巴研究价值",
            goal="判断是否值得继续研究",
            type="company",
            entity="阿里巴巴",
            research_object_type="listed_company",
        )
        questions = [
            Question(id="q1", topic_id=topic.id, content="财务质量如何", priority=1, framework_type="financial", coverage_level="covered"),
            Question(id="q2", topic_id=topic.id, content="估值锚点如何", priority=1, framework_type="valuation", coverage_level="partial"),
        ]
        judgment = Judgment(
            topic_id=topic.id,
            conclusion="当前证据不足以支撑明确结论",
            conclusion_evidence_ids=[],
            clusters=[],
            risk=[],
            unknown=["缺少官方来源"],
            evidence_gaps=[EvidenceGap(question_id="q1", text="缺少官方财务字段", importance="high")],
            confidence="low",
            confidence_basis=ConfidenceBasis(
                source_count=1,
                source_diversity="low",
                conflict_level="none",
                evidence_gap_level="high",
                effective_evidence_count=1,
                has_official_source=False,
                official_evidence_count=0,
                weak_source_only=True,
            ),
            research_actions=[],
        )
        actions = [
            ResearchAction(
                id="a1",
                priority="high",
                objective="补齐官方财务来源",
                reason="缺少官方财务字段",
                required_data=["营收", "经营现金流", "估值"],
                query_templates=["{entity} investor relations quarterly results"],
                source_targets=["official filings"],
                question_id="q1",
            )
        ]

        def fake_retrieve(topic, questions, action, existing_sources, start_index):
            return [
                Source(
                    id=f"s{start_index}",
                    question_id="q1",
                    flow_type="fact",
                    search_query="阿里巴巴 investor relations quarterly results",
                    title="Alibaba IR Results",
                    url="https://www.alibabagroup.com/results",
                    source_type="company",
                    provider="fixture",
                    source_origin_type="company_ir",
                    tier=SourceTier.TIER1,
                    source_score=0.95,
                    content="official content",
                )
            ], ["阿里巴巴 investor relations quarterly results"]

        with patch(
            "app.services.llm_evidence_extractor.call_llm",
            return_value=(
                '{"evidences":['
                '{"metric_name":"revenue","metric_value":996347,"unit":"million","period":"FY2025","entity":"Alibaba","quote":"Revenue was RMB996347 million in FY2025.","extraction_confidence":0.95},'
                '{"metric_name":"operating_cash_flow","metric_value":163509,"unit":"million","period":"FY2025","entity":"Alibaba","quote":"Operating cash flow was RMB163509 million in FY2025.","extraction_confidence":0.95},'
                '{"metric_name":"pe","metric_value":12,"unit":"x","period":"TTM","entity":"Alibaba","quote":"PE was 12x.","extraction_confidence":0.9}'
                ']}'
            ),
        ):
            result = auto_research_loop(
                topic,
                questions,
                sources=[],
                evidence=[],
                variables=[],
                judgment=judgment,
                actions=actions,
                max_rounds=1,
                retrieve_fn=fake_retrieve,
            )

        self.assertEqual(result.trace[0].effectiveness_status, "effective")
        self.assertEqual(result.judgment.confidence, "medium")

    @patch("app.agent.steps.reason.call_llm", side_effect=RuntimeError("skip llm in unit test"))
    def test_medium_confidence_with_high_priority_gap_still_triggers_one_round(self, reason_llm_mock) -> None:
        topic = Topic(
            id="topic_medium_gap",
            query="我想投资阿里巴巴，是否值得进一步研究",
            topic="阿里巴巴研究价值",
            goal="判断是否值得继续研究",
            type="company",
            entity="阿里巴巴",
            research_object_type="listed_company",
        )
        questions = [
            Question(id="q1", topic_id=topic.id, content="估值锚点如何", priority=1, framework_type="valuation", coverage_level="uncovered"),
            Question(id="q2", topic_id=topic.id, content="行业竞争如何", priority=1, framework_type="industry", coverage_level="partial"),
        ]
        judgment = Judgment(
            topic_id=topic.id,
            conclusion="当前证据支持继续标准研究，但估值和行业缺口仍然明显。",
            conclusion_evidence_ids=[],
            clusters=[],
            risk=[],
            unknown=["估值和行业竞争仍待补证"],
            evidence_gaps=[EvidenceGap(question_id="q1", text="缺少估值锚点和同行对比", importance="high")],
            confidence="medium",
            confidence_basis=ConfidenceBasis(
                source_count=2,
                source_diversity="medium",
                conflict_level="none",
                evidence_gap_level="high",
                effective_evidence_count=3,
                has_official_source=True,
                official_evidence_count=2,
            ),
            research_actions=[],
        )
        actions = [
            ResearchAction(
                id="a1",
                priority="high",
                objective="补齐估值锚点和同行对比",
                reason="高优先级估值缺口仍未覆盖",
                required_data=["PE", "PB", "同行估值", "市场份额"],
                query_templates=["{entity} valuation peer comparison market share"],
                source_targets=["recognized data providers", "professional finance media"],
                question_id="q1",
            )
        ]

        def fake_retrieve(topic, questions, action, existing_sources, start_index):
            return [
                Source(
                    id=f"s{start_index}",
                    question_id="q1",
                    flow_type="fact",
                    search_query="阿里巴巴 valuation peer comparison market share",
                    title="Alibaba peer comparison",
                    url="https://example.com/alibaba-peer-comparison",
                    source_type="report",
                    provider="fixture",
                    source_origin_type="professional_media",
                    tier=SourceTier.TIER2,
                    source_score=0.85,
                    content="PE was 12x and market share was 18%.",
                )
            ], ["阿里巴巴 valuation peer comparison market share"]

        with patch(
            "app.services.llm_evidence_extractor.call_llm",
            return_value=(
                '{"evidences":['
                '{"metric_name":"pe","metric_value":12,"unit":"x","period":"TTM","entity":"Alibaba","quote":"TTM PE was 12x.","extraction_confidence":0.9},'
                '{"metric_name":"market_share","metric_value":18,"unit":"%","period":"FY2025","entity":"Alibaba","quote":"FY2025 Market share was 18%.","extraction_confidence":0.9}'
                ']}'
            ),
        ):
            result = auto_research_loop(
                topic,
                questions,
                sources=[],
                evidence=[],
                variables=[],
                judgment=judgment,
                actions=actions,
                max_rounds=1,
                retrieve_fn=fake_retrieve,
            )

        self.assertTrue(result.trace)
        self.assertTrue(result.trace[0].triggered)
        self.assertEqual(result.trace[0].effectiveness_status, "effective")


if __name__ == "__main__":
    unittest.main()
