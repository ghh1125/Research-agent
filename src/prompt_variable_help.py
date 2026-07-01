from __future__ import annotations

from collections.abc import Iterable


VARIABLE_HELP: dict[str, tuple[str, str]] = {
    "raw_input": ("开始节点表单中的公司名称、官网、融资轮次、融资金额、行业和项目描述。", "开始节点用户输入"),
    "bp_text": ("从 BP 文件中解析出的完整文本；未上传 BP 时为空。", "开始节点上传的 BP 文件"),
    "company_name": ("本次投研项目的公司名称。", "开始节点用户输入"),
    "website": ("公司官网地址；未填写时为空。", "开始节点用户输入"),
    "industry": ("用户选择或填写的所属行业。", "开始节点用户输入"),
    "project_description": ("用户填写的项目描述。", "开始节点用户输入"),
    "funding_round": ("本次拟融资轮次。", "开始节点用户输入"),
    "funding_amount": ("本次拟融资金额；未填写时为空。", "开始节点用户输入"),
    "search_text": ("当前步骤通过外部搜索获得的证据文本，通常含标题、摘要和链接。", "当前节点外部检索"),
    "feedback_section": ("人工审核时填写的修改意见；首次生成时为空。", "当前节点人工审核"),
    "core_business": ("目标公司的主营业务摘要。", "项目基本概况"),
    "product_and_scene": ("目标公司的产品体系和主要业务落地场景。", "项目基本概况"),
    "product_service": ("目标公司的核心产品或服务体系。", "项目基本概况"),
    "product_service_system": ("目标公司的核心产品或服务体系。", "项目基本概况"),
    "use_cases_and_value": ("业务落地场景、客户价值和解决的问题。", "项目基本概况"),
    "founder_summary": ("创始人与核心团队背景摘要。", "项目基本概况"),
    "registration_info": ("公司主体、成立时间、注册资本等工商信息。", "项目基本概况"),
    "market_size_and_drivers": ("市场规模、增长驱动因素与关键假设。", "行业深度分析"),
    "competitive_landscape": ("行业竞争格局及主要参与者。", "行业深度分析"),
    "opportunities_and_barriers": ("行业机会、进入壁垒和主要约束。", "行业深度分析"),
    "opportunity_mapping_to_target": ("行业机会与目标公司能力、产品和场景的匹配关系。", "行业深度分析"),
    "policy_environment": ("与目标行业和公司相关的政策及监管环境。", "行业深度分析"),
    "industry_context": ("行业趋势、竞争格局、市场机会和政策环境摘要。", "行业深度分析"),
    "candidate_id": ("当前候选竞品的系统标识。", "竞品发现"),
    "candidate_name": ("当前待分析竞品的名称。", "竞品发现"),
    "candidate_website": ("当前待分析竞品的官网；未发现时为空。", "竞品发现"),
    "relationship": ("候选公司与目标公司的竞争关系类型。", "竞品发现"),
    "candidate_product": ("候选竞品的核心产品或服务摘要。", "竞品发现"),
    "candidate_reason": ("该公司被识别为竞品的理由。", "竞品发现"),
    "evidence_text": ("针对当前单家竞品逐项检索得到的完整证据文本。", "单家竞品外部检索"),
    "current_result": ("当前单家竞品已有的结构化分析结果；重新分析时使用。", "单家竞品分析"),
    "feedback": ("用户针对当前竞品报告填写的具体审核意见。", "竞品报告人工审核"),
    "individual_results_json": ("所有已选竞品逐家分析结果的完整 JSON。", "单家竞品分析"),
    "capability_matrix_json": ("目标公司与各竞品的能力矩阵数据。", "单家竞品分析汇总"),
    "current_summary": ("当前竞品统一汇总结果；按反馈重新汇总时使用。", "竞品矩阵分析"),
    "competitor_analysis_context": ("完整竞品矩阵报告，包括逐家分析、矩阵、SWOT 和定位判断。", "竞品矩阵分析"),
    "team_file_text": ("创始团队、核心成员、股权或组织材料的解析全文。", "团队尽调节点上传文件"),
    "business_file_text": ("商业计划书、业务规划和市场材料的解析全文。", "业务尽调节点上传文件"),
    "financial_file_text": ("损益表、资产负债表、现金流量表等财务材料的解析全文。", "财务尽调节点上传文件"),
    "tech_file_text": ("技术架构、研发、专利、软著和知识产权材料的解析全文。", "技术/IP 尽调节点上传文件"),
    "legal_file_text": ("股权结构、合同、诉讼和合规材料的解析全文。", "法律尽调节点上传文件"),
    "peer_findings": ("其他已完成专项尽调的关键发现，用于交叉核验。", "深度尽调其他专项输出"),
    "revenue": ("从财务材料中提取或计算的收入数据。", "财务文件解析与计算"),
    "cost": ("从财务材料中提取或计算的成本数据。", "财务文件解析与计算"),
    "gross_margin": ("从财务材料中提取或计算的毛利率。", "财务文件解析与计算"),
    "net_margin": ("从财务材料中提取或计算的净利率。", "财务文件解析与计算"),
    "ocf": ("从财务材料中提取的经营活动现金流。", "财务文件解析与计算"),
    "yoy": ("从财务材料中提取或计算的收入同比增速。", "财务文件解析与计算"),
    "computed_from": ("财务指标的计算口径、期间和原始字段说明。", "财务文件解析与计算"),
    "weighting_note": ("估值方法权重及采用该权重的说明。", "估值分析准备数据"),
    "industry_summary": ("行业趋势、规模、竞争和政策的压缩摘要。", "行业深度分析"),
    "due_diligence_coverage": ("已执行和未执行的专项尽调范围及资料缺口。", "深度尽调汇总"),
    "business_score": ("业务尽调给出的业务质量评分；未执行时为空。", "业务尽调"),
    "financial_health_summary": ("财务健康度结论和关键依据；未执行时为空。", "财务尽调"),
    "team_rating": ("团队能力评级及简要依据；未执行时为空。", "团队尽调"),
    "legal_risk_level": ("法律风险等级及关键依据；未执行时为空。", "法律尽调"),
    "overview_brief": ("项目基本概况的报告摘要。", "项目基本概况"),
    "industry_brief": ("行业深度分析的报告摘要。", "行业深度分析"),
    "valuation_brief": ("估值区间、方法、假设和敏感性结论摘要。", "估值分析"),
    "team_summary": ("团队尽调报告摘要；未执行时标注缺失。", "团队尽调"),
    "business_summary": ("业务尽调报告摘要；未执行时标注缺失。", "业务尽调"),
    "financial_summary": ("财务尽调报告摘要；未执行时标注缺失。", "财务尽调"),
    "tech_ip_summary": ("技术与知识产权尽调摘要；未执行时标注缺失。", "技术/IP 尽调"),
    "legal_summary": ("法律法规尽调摘要；未执行时标注缺失。", "法律尽调"),
    "risk_register": ("跨报告归并后的风险事项、证据、等级和应对建议。", "综合研判风险汇总"),
}


def variable_help(names: Iterable[str]) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    for name in names:
        description, source = VARIABLE_HELP[name]
        result.append(
            {
                "name": name,
                "placeholder": f"{{{name}}}",
                "description": description,
                "source": source,
            }
        )
    return result


__all__ = ["VARIABLE_HELP", "variable_help"]
