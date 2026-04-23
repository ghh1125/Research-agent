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

    def test_cash_flow_quality_requires_cash_flow_metric_whitelist(self) -> None:
        evidence = [
            Evidence(
                id="e1",
                topic_id="topic_001",
                question_id="q1",
                source_id="s1",
                content=(
                    "电话会摘要显示管理层认为业务经营改善，平台生态保持增长，"
                    "公司将继续投入云业务并提升经营效率，现金流质量有望优化。"
                ),
                evidence_type="claim",
                stance="neutral",
                evidence_score=0.9,
                quality_score=0.9,
            ),
            Evidence(
                id="e2",
                topic_id="topic_001",
                question_id="q1",
                source_id="s1",
                content="营业收入同比增长12%至2,600亿元，管理层称现金流质量有望继续改善。",
                evidence_type="data",
                stance="neutral",
                evidence_score=0.9,
                quality_score=0.9,
                metric_name="revenue",
                metric_value=2600,
                unit="亿元",
                period="FY2025",
                comparison_type="yoy",
            ),
        ]

        variables = normalize_variables(evidence)

        self.assertFalse(any(item.name == "现金流质量" for item in variables))
        self.assertIn("收入增长", {item.name for item in variables})

    def test_valuation_anchor_requires_valuation_metric(self) -> None:
        evidence = [
            Evidence(
                id="e1",
                topic_id="topic_001",
                question_id="q1",
                source_id="s1",
                content="公司收入同比增长12%至2,600亿元，毛利率提升至38%，市场讨论PE估值修复。",
                evidence_type="data",
                stance="neutral",
                evidence_score=0.9,
                quality_score=0.9,
                metric_name="revenue",
                metric_value=2600,
                unit="亿元",
                period="FY2025",
                comparison_type="yoy",
            )
        ]

        variables = normalize_variables(evidence)

        self.assertFalse(any(item.name == "估值锚点" for item in variables))

    def test_long_summary_cannot_drive_more_than_two_variables(self) -> None:
        evidence = [
            Evidence(
                id="e1",
                topic_id="topic_001",
                question_id="q1",
                source_id="s1",
                content=(
                    "公司营业收入同比增长12%至2,600亿元，毛利率提升至38%，经营现金流改善，资本开支下降，"
                    "市场份额提升至25%，客户结构优化，PE估值修复至18倍，ROE改善至15%，管理层表示长期竞争力增强。"
                    "该段为电话会和新闻摘要合并内容，不是单一字段或完整表格行。"
                ),
                evidence_type="data",
                stance="neutral",
                evidence_score=0.95,
                quality_score=0.95,
            )
        ]

        variables = normalize_variables(evidence)
        usage_count = sum("e1" in item.evidence_ids for item in variables)

        self.assertLessEqual(usage_count, 2)

    def test_structured_metric_routes_to_matching_variable_only(self) -> None:
        evidence = [
            Evidence(
                id="e1",
                topic_id="topic_001",
                question_id="q1",
                source_id="s1",
                content="经营活动现金流净额同比增长15%至120亿元。",
                evidence_type="data",
                stance="neutral",
                evidence_score=0.9,
                quality_score=0.9,
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

    def test_long_mixed_data_summary_cannot_drive_strict_variables_without_metric_name(self) -> None:
        evidence = [
            Evidence(
                id="e1",
                topic_id="topic_001",
                question_id="q1",
                source_id="s1",
                content=(
                    "电话会摘要称公司营业收入同比增长12%至2,600亿元，毛利率提升至38%，"
                    "经营现金流改善至120亿元，自由现金流改善，资本开支下降，云业务、广告业务、"
                    "本地生活和国际业务均有增长动能，同时管理层强调长期目标和风险控制。"
                ),
                evidence_type="data",
                stance="neutral",
                evidence_score=0.95,
                quality_score=0.95,
            )
        ]

        variables = normalize_variables(evidence)

        self.assertFalse(any(item.name in {"收入增长", "盈利能力", "现金流质量", "估值锚点"} for item in variables))

    def test_short_single_metric_sentence_can_drive_strict_variable(self) -> None:
        evidence = [
            Evidence(
                id="e1",
                topic_id="topic_001",
                question_id="q1",
                source_id="s1",
                content="自由现金流同比下降56%至152亿元。",
                evidence_type="data",
                stance="neutral",
                evidence_score=0.9,
                quality_score=0.9,
            )
        ]

        variables = normalize_variables(evidence)

        self.assertIn("现金流质量", {item.name for item in variables})

    def test_trustworthy_official_fallback_creates_cloud_and_capex_variables(self) -> None:
        evidence = [
            Evidence(
                id="e1",
                topic_id="topic_001",
                question_id="q1",
                source_id="s1",
                source_tier="official",
                content="Cloud revenue grew 35% YoY in Q3 FY2026.",
                evidence_type="data",
                stance="neutral",
                evidence_score=0.7,
                quality_score=0.7,
                quality_notes=["semi_structured_official_metric"],
                period="FY2026Q3",
                comparison_type="yoy",
            ),
            Evidence(
                id="e2",
                topic_id="topic_001",
                question_id="q1",
                source_id="s1",
                source_tier="official",
                content="Capital expenditures were RMB19,000 million in Q3 FY2026.",
                evidence_type="data",
                stance="neutral",
                evidence_score=0.9,
                quality_score=0.9,
                quality_notes=["complete_official_metric"],
                period="FY2026Q3",
            ),
        ]

        variables = normalize_variables(evidence)
        names = {item.name for item in variables}

        self.assertIn("云业务增长", names)
        self.assertIn("资本开支强度", names)

    def test_untrusted_short_fallback_without_metric_name_cannot_drive_strict_variable(self) -> None:
        evidence = [
            Evidence(
                id="e1",
                topic_id="topic_001",
                question_id="q1",
                source_id="s1",
                source_tier="content",
                content="Cloud revenue grew 35% YoY in Q3 FY2026.",
                evidence_type="data",
                stance="neutral",
                evidence_score=0.9,
                quality_score=0.9,
                period="FY2026Q3",
                comparison_type="yoy",
            )
        ]

        variables = normalize_variables(evidence)

        self.assertFalse(any(item.name == "云业务增长" for item in variables))

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
