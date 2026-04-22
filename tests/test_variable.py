from __future__ import annotations

import unittest

from app.agent.steps.variable import normalize_variables
from app.models.evidence import Evidence


class VariableStepTest(unittest.TestCase):
    def test_normalize_variables_groups_evidence_into_research_variables(self) -> None:
        evidence = [
            Evidence(
                id="e1",
                topic_id="topic_001",
                question_id="q1",
                source_id="s1",
                content="公司营业收入同比增长17.04%",
                evidence_type="data",
                stance="counter",
            ),
            Evidence(
                id="e2",
                topic_id="topic_001",
                question_id="q2",
                source_id="s2",
                flow_type="risk",
                content="行业价格竞争加剧，产能快速扩张",
                evidence_type="risk_signal",
                stance="support",
            ),
            Evidence(
                id="e3",
                topic_id="topic_001",
                question_id="q3",
                source_id="s3",
                content="经营活动现金流120亿元，同比增长15%，现金转换率改善",
                evidence_type="data",
                stance="counter",
            ),
            Evidence(
                id="e4",
                topic_id="topic_001",
                question_id="q4",
                source_id="s4",
                content="公司市场份额35%，同行排名第一，价格竞争格局仍然激烈",
                evidence_type="data",
                stance="neutral",
            ),
        ]

        variables = normalize_variables(evidence)
        names = {item.name for item in variables}
        all_evidence_ids = {evidence_id for item in variables for evidence_id in item.evidence_ids}

        self.assertIn("收入增长", names)
        self.assertIn("现金流质量", names)
        self.assertIn("行业竞争", names)
        self.assertTrue(all_evidence_ids.issubset({"e1", "e2", "e3", "e4"}))
        self.assertTrue(any(item.direction == "improving" for item in variables))

    def test_variable_marks_growth_slowdown_as_mixed(self) -> None:
        evidence = [
            Evidence(
                id="e1",
                topic_id="topic_001",
                question_id="q1",
                source_id="s1",
                content="公司营业收入同比增长17.04%，但增速从80%降至20%，增长放缓。",
                evidence_type="data",
                stance="neutral",
            )
        ]

        variables = normalize_variables(evidence)
        revenue = next(item for item in variables if item.name == "收入增长")

        self.assertEqual(revenue.direction, "mixed")
        self.assertTrue(revenue.direction_notes)

    def test_financial_variables_ignore_weak_slogan_text(self) -> None:
        evidence = [
            Evidence(
                id="e1",
                topic_id="topic_001",
                question_id="q1",
                source_id="s1",
                content="公司坚持创新驱动发展，持续创造价值并保持稳健增长。",
                evidence_type="claim",
                stance="neutral",
                evidence_score=0.8,
                quality_score=0.8,
            ),
            Evidence(
                id="e2",
                topic_id="topic_001",
                question_id="q1",
                source_id="s1",
                content="营业收入 84 净利润 67 毛利率 2",
                evidence_type="data",
                stance="neutral",
                is_truncated=True,
                evidence_score=0.8,
                quality_score=0.8,
            ),
        ]

        variables = normalize_variables(evidence)

        self.assertFalse(any(item.category == "financial" for item in variables))

    def test_governance_penalty_forces_deteriorating_direction(self) -> None:
        evidence = [
            Evidence(
                id="e1",
                topic_id="topic_001",
                question_id="q1",
                source_id="s1",
                content="公司因反垄断违规收到监管罚款，并面临进一步 investigation。",
                evidence_type="risk_signal",
                stance="neutral",
                evidence_score=0.8,
                quality_score=0.8,
            )
        ]

        variables = normalize_variables(evidence)
        governance = next(item for item in variables if item.name == "治理合规")

        self.assertEqual(governance.direction, "deteriorating")
        self.assertTrue(any("规则层负向信号" in note for note in governance.direction_notes))

    def test_governance_conflicting_signals_are_mixed(self) -> None:
        evidence = [
            Evidence(
                id="e1",
                topic_id="topic_001",
                question_id="q1",
                source_id="s1",
                content="公司获得监管批准，但历史诉讼仍在推进。",
                evidence_type="claim",
                stance="neutral",
                evidence_score=0.8,
                quality_score=0.8,
            )
        ]

        variables = normalize_variables(evidence)
        governance = next(item for item in variables if item.name == "治理合规")

        self.assertEqual(governance.direction, "mixed")


if __name__ == "__main__":
    unittest.main()
