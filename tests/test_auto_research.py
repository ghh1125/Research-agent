from __future__ import annotations

import unittest
from unittest.mock import patch

from app.agent.steps.auto_research import auto_research_loop
from app.models.judgment import ConfidenceBasis, EvidenceGap, Judgment, ResearchAction
from app.models.question import Question
from app.models.source import Source
from app.models.source import SourceTier
from app.models.topic import Topic


class AutoResearchLoopTest(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
