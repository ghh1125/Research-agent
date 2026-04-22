from __future__ import annotations

import unittest

from app.agent.steps.action import generate_research_actions
from app.models.judgment import ConfidenceBasis, EvidenceGap, Judgment


class ActionStepTest(unittest.TestCase):
    def test_action_generation_returns_structured_tasks(self) -> None:
        judgment = Judgment(
            topic_id="topic_001",
            conclusion="当前证据不足以支撑明确结论",
            conclusion_evidence_ids=[],
            clusters=[],
            risk=[],
            unknown=["缺少官方财报"],
            evidence_gaps=[
                EvidenceGap(question_id="q1", text="子问题证据不足：现金流和财报数据缺失", importance="high")
            ],
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

        actions = generate_research_actions(judgment)

        self.assertTrue(actions)
        self.assertEqual(actions[0].priority, "high")
        self.assertTrue(actions[0].objective)
        self.assertTrue(actions[0].required_data)
        self.assertTrue(actions[0].question)
        self.assertTrue(actions[0].search_query)
        self.assertTrue(actions[0].query_templates)
        self.assertTrue(actions[0].target_sources)
        self.assertTrue(actions[0].source_targets)
        self.assertTrue(any("capital" in query.lower() or "资本开支" in query for query in actions[0].query_templates))


if __name__ == "__main__":
    unittest.main()
