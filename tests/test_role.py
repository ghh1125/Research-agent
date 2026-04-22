from __future__ import annotations

import os
import unittest

from app.agent.steps.investment import apply_investment_layer
from app.agent.steps.reason import reason_and_generate
from app.agent.steps.role import synthesize_role_outputs
from app.agent.steps.variable import normalize_variables
from app.config import get_settings
from app.models.evidence import Evidence
from app.models.question import Question
from app.models.source import Source
from app.models.topic import Topic


class RoleStepTest(unittest.TestCase):
    def setUp(self) -> None:
        os.environ["DASHSCOPE_API_KEY"] = ""
        os.environ["OPENAI_API_KEY"] = ""
        get_settings.cache_clear()

    def tearDown(self) -> None:
        os.environ.pop("DASHSCOPE_API_KEY", None)
        os.environ.pop("OPENAI_API_KEY", None)
        get_settings.cache_clear()

    def test_synthesize_role_outputs_returns_five_explicit_roles(self) -> None:
        topic = Topic(
            id="topic_001",
            query="研究宁德时代是否值得进一步研究",
            topic="宁德时代研究价值",
            goal="判断是否值得继续深挖",
            type="company",
            entity="宁德时代",
        )
        questions = [Question(id="q1", topic_id=topic.id, content="财务质量如何", priority=1, covered=True)]
        sources = [
            Source(id="s1", question_id="q1", flow_type="fact", title="Fact", source_type="website", provider="fixture", content="营业收入同比增长"),
            Source(id="s2", question_id="q1", flow_type="risk", title="Risk", source_type="website", provider="fixture", content="价格竞争加剧"),
            Source(id="s3", question_id="q1", flow_type="counter", title="Counter", source_type="website", provider="fixture", content="现金流改善"),
        ]
        evidence = [
            Evidence(id="e1", topic_id=topic.id, question_id="q1", source_id="s1", flow_type="fact", content="营业收入同比增长17.04%", evidence_type="data"),
            Evidence(id="e2", topic_id=topic.id, question_id="q1", source_id="s2", flow_type="risk", content="行业价格竞争加剧", evidence_type="risk_signal", stance="support"),
            Evidence(id="e3", topic_id=topic.id, question_id="q1", source_id="s3", flow_type="counter", content="经营活动现金流改善并转正", evidence_type="data", stance="counter"),
        ]
        variables = normalize_variables(evidence)
        judgment = reason_and_generate(topic, evidence, questions, variables)
        judgment = apply_investment_layer(topic, questions, evidence, judgment, variables)

        roles = synthesize_role_outputs(topic, sources, evidence, variables, judgment)
        role_ids = {role.role_id for role in roles}

        self.assertEqual(len(roles), 5)
        self.assertEqual(
            role_ids,
            {"fact_researcher", "risk_officer", "counter_analyst", "synthesis_analyst", "investment_manager"},
        )
        self.assertTrue(any(role.cognitive_bias == "contrarian" and "e3" in role.evidence_ids for role in roles))
        self.assertTrue(all(role.output_summary for role in roles))
        self.assertTrue(all(role.role_description for role in roles))
        self.assertTrue(all(role.role_prompt for role in roles))
        self.assertTrue(all(role.operating_rules for role in roles))
        self.assertTrue(all(role.forbidden_actions for role in roles))
        self.assertTrue(all(role.success_criteria for role in roles))
        self.assertTrue(any(role.framework_types for role in roles))
        self.assertTrue(any(role.pressure_test_ids for role in roles))
        self.assertTrue(
            any(
                role.pressure_test_ids and any(test_id in role.output_summary for test_id in role.pressure_test_ids)
                for role in roles
            )
        )


if __name__ == "__main__":
    unittest.main()
