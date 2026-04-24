from __future__ import annotations

import unittest

from app.agent.steps.variable import normalize_variables
from app.models.evidence import Evidence


class VariableStepTest(unittest.TestCase):
    def test_structured_metric_routes_to_matching_variable_only(self) -> None:
        evidence = [
            Evidence(
                id="e1",
                topic_id="topic_001",
                question_id="q1",
                source_id="s1",
                content="经营活动现金流净额同比增长15%至120亿元。",
                evidence_type="data",
                metric_name="operating_cash_flow",
                metric_value=120,
                unit="亿元",
                period="FY2025",
                comparison_type="yoy",
            )
        ]

        variables = normalize_variables(evidence)
        names = {item.name for item in variables}

        self.assertIn("现金流质量", names)
        self.assertNotIn("收入增长", names)
        self.assertNotIn("盈利能力", names)

    def test_metric_name_is_required_for_variable_consumption(self) -> None:
        evidence = [
            Evidence(
                id="e1",
                topic_id="topic_001",
                question_id="q1",
                source_id="s1",
                content="公司营业收入同比增长17.04%，但没有结构化 metric_name。",
                evidence_type="data",
                metric_value=17.04,
                unit="%",
                period="FY2025",
            )
        ]

        self.assertEqual(normalize_variables(evidence), [])

    def test_long_summary_cannot_drive_variables_without_metric_name(self) -> None:
        evidence = [
            Evidence(
                id="e1",
                topic_id="topic_001",
                question_id="q1",
                source_id="s1",
                content=(
                    "电话会摘要称公司营业收入同比增长12%至2,600亿元，毛利率提升至38%，"
                    "经营现金流改善至120亿元，自由现金流改善，资本开支下降，云业务和国际业务均有增长动能。"
                ),
                evidence_type="data",
                evidence_score=0.95,
                quality_score=0.95,
            )
        ]

        self.assertEqual(normalize_variables(evidence), [])

    def test_metric_name_drives_one_variable_not_multiple_keyword_variables(self) -> None:
        evidence = [
            Evidence(
                id="e1",
                topic_id="topic_001",
                question_id="q1",
                source_id="s1",
                content="营业收入同比增长12%至2,600亿元，管理层称现金流质量有望继续改善。",
                evidence_type="data",
                metric_name="revenue",
                metric_value=2600,
                unit="亿元",
                period="FY2025",
                comparison_type="yoy",
            )
        ]

        variables = normalize_variables(evidence)

        self.assertEqual([item.name for item in variables], ["收入增长"])
        self.assertEqual(variables[0].evidence_ids, ["e1"])

    def test_blocked_or_contaminated_evidence_cannot_drive_variables(self) -> None:
        evidence = [
            Evidence(
                id="e1",
                topic_id="topic_001",
                question_id="q1",
                source_id="s1",
                content="Baidu revenue was RMB134598 million.",
                evidence_type="data",
                metric_name="revenue",
                metric_value=134598,
                unit="million",
                period="FY2025",
                cross_entity_contamination=True,
            ),
            Evidence(
                id="e2",
                topic_id="topic_001",
                question_id="q1",
                source_id="s1",
                content="Customer management revenue increased 1% year-over-year to RMB1",
                evidence_type="data",
                metric_name="customer_management_revenue",
                metric_value=1,
                unit="RMB",
                period="FY2025",
                is_truncated=True,
            ),
        ]

        self.assertEqual(normalize_variables(evidence), [])

    def test_supported_metrics_create_expected_variable_set(self) -> None:
        evidence = [
            Evidence(
                id="e1",
                topic_id="topic_001",
                question_id="q1",
                source_id="s1",
                content="Revenue grew 12% YoY.",
                evidence_type="data",
                metric_name="revenue_growth",
                metric_value=12,
                unit="%",
                period="FY2025",
            ),
            Evidence(
                id="e2",
                topic_id="topic_001",
                question_id="q1",
                source_id="s1",
                content="Gross margin improved to 38%.",
                evidence_type="data",
                metric_name="gross_margin",
                metric_value=38,
                unit="%",
                period="FY2025",
            ),
            Evidence(
                id="e3",
                topic_id="topic_001",
                question_id="q1",
                source_id="s1",
                content="Capital expenditures were RMB19,000 million.",
                evidence_type="data",
                metric_name="capital_expenditure",
                metric_value=19000,
                unit="million",
                period="FY2025",
            ),
            Evidence(
                id="e4",
                topic_id="topic_001",
                question_id="q1",
                source_id="s1",
                content="Market share was 18%.",
                evidence_type="data",
                metric_name="market_share",
                metric_value=18,
                unit="%",
                period="FY2025",
            ),
            Evidence(
                id="e5",
                topic_id="topic_001",
                question_id="q1",
                source_id="s1",
                content="PE was 18x.",
                evidence_type="data",
                metric_name="PE",
                metric_value=18,
                unit="x",
                period="FY2025",
            ),
        ]

        names = {item.name for item in normalize_variables(evidence)}

        self.assertEqual(names, {"收入增长", "盈利能力", "资本开支强度", "行业竞争", "估值锚点"})

    def test_direction_is_inferred_from_structured_metric_text_only(self) -> None:
        evidence = [
            Evidence(
                id="e1",
                topic_id="topic_001",
                question_id="q1",
                source_id="s1",
                content="Revenue grew 12% YoY but growth slowed from 20%.",
                evidence_type="data",
                metric_name="revenue_growth",
                metric_value=12,
                unit="%",
                period="FY2025",
            )
        ]

        variables = normalize_variables(evidence)

        self.assertEqual(variables[0].name, "收入增长")
        self.assertEqual(variables[0].direction, "mixed")
        self.assertTrue(variables[0].direction_notes)

    def test_variables_only_consume_registry_legal_evidence(self) -> None:
        evidence = [
            Evidence(
                id="e1",
                topic_id="topic_001",
                question_id="q1",
                source_id="s1",
                content="Revenue grew 12% YoY.",
                evidence_type="data",
                source_tier="official",
                metric_name="revenue_growth",
                metric_value=12,
                unit="%",
                period="FY2025",
                comparison_type="yoy",
            ),
            Evidence(
                id="e2",
                topic_id="topic_001",
                question_id="q1",
                source_id="s1",
                content="This broken narrative should not enter variables.",
                evidence_type="data",
                source_tier="official",
                metric_name="gross_margin",
                metric_value=38,
                unit="%",
                period="FY2025",
                can_enter_main_chain=False,
            ),
        ]

        variables = normalize_variables(evidence)

        self.assertEqual(len(variables), 1)
        self.assertEqual(variables[0].evidence_ids, ["e1"])
        self.assertEqual(variables[0].direction_label, "局部改善")


if __name__ == "__main__":
    unittest.main()
