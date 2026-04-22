from __future__ import annotations

import json
import re

from app.agent.prompts.decompose_prompt import DECOMPOSE_PROMPT_TEMPLATE
from app.models.question import Question
from app.models.topic import Topic
from app.services.llm_service import call_llm

QuestionSpec = tuple[str, int, str] | tuple[str, int, str, str | None]

_PLATFORM_INTERNET_ENTITIES = {"拼多多", "阿里巴巴", "腾讯", "美团", "京东"}
_MANUFACTURING_NEW_ENERGY_ENTITIES = {"宁德时代", "比亚迪", "特斯拉"}
_SEMICONDUCTOR_ENTITIES = {"英伟达", "AMD", "博通"}
_BANK_ENTITIES = {"摩根大通", "美国银行"}
_ALLOWED_FRAMEWORK_TYPES = {
    "financial",
    "credit",
    "valuation",
    "business_model",
    "industry",
    "moat",
    "risk",
    "governance",
    "compliance",
    "adversarial",
    "catalyst",
    "gap",
    "general",
}
_FRAMEWORK_KEYWORDS = {
    "financial": ["财务", "收入", "营收", "利润", "毛利率", "净利率", "现金流", "资本开支"],
    "credit": ["偿债", "债务", "负债", "短债", "再融资", "授信", "流动性"],
    "valuation": ["估值", "PE", "PB", "EV", "倍数", "市值"],
    "business_model": ["商业模式", "收入模式", "单位经济", "客户结构", "盈利来源"],
    "industry": ["行业", "竞争", "市场份额", "同行", "格局", "客户"],
    "moat": ["壁垒", "护城河", "留存", "切换成本", "网络效应"],
    "risk": ["风险", "下行", "压力", "监管", "诉讼", "价格战"],
    "governance": ["治理", "内控", "关联交易", "股东", "实控人", "董事会"],
    "compliance": ["合规", "资质", "许可", "监管红线", "处罚"],
    "adversarial": ["反方", "证伪", "推翻", "削弱", "反证"],
    "catalyst": ["催化", "触发", "未来", "6到12个月", "事件"],
    "gap": ["缺少", "缺口", "还缺", "补齐", "哪些数据"],
}


def _entity(topic: Topic) -> str:
    return topic.entity or topic.topic


def _object_type(topic: Topic) -> str:
    object_type = getattr(topic, "research_object_type", "unknown")
    if object_type != "unknown":
        return object_type
    if topic.entity in {"华为", "字节跳动", "蚂蚁集团", "小红书"}:
        return "private_company"
    if topic.type == "company" and topic.listing_status == "listed":
        return "listed_company"
    if topic.type == "company" and topic.listing_status in {"private", "unlisted"}:
        return "private_company"
    if topic.type == "company":
        return "listed_company"
    if topic.type == "compliance":
        return "event"
    if topic.type == "theme":
        return "industry_theme"
    return "unknown"


def _industry_template(topic: Topic) -> str | None:
    entity = topic.entity or ""
    text = f"{topic.query} {topic.topic} {entity}"
    if entity in _SEMICONDUCTOR_ENTITIES or any(token in text for token in ["半导体", "芯片", "AI算力", "HBM", "先进封装"]):
        return "semiconductor"
    if entity in _PLATFORM_INTERNET_ENTITIES or any(token in text for token in ["电商", "平台", "互联网", "GMV", "广告"]):
        return "platform_internet"
    if entity in _BANK_ENTITIES or any(token in text for token in ["银行", "金融", "不良率", "息差"]):
        return "bank_financial"
    if any(token.lower() in text.lower() for token in ["saas", "software", "软件", "订阅", "ARR", "NRR"]):
        return "saas_software"
    if entity in _MANUFACTURING_NEW_ENERGY_ENTITIES or any(token in text for token in ["新能源", "制造", "电池", "汽车", "产能"]):
        return "manufacturing_new_energy"
    if any(token in text for token in ["贸易", "城投", "信用", "债", "违约"]):
        return "trade_credit"
    return None


def _listed_company_template(topic: Topic) -> list[QuestionSpec]:
    entity = _entity(topic)
    industry = _industry_template(topic)
    if industry == "semiconductor":
        return [
            (f"{entity}的收入增长和利润率是否由真实需求、产品代际和供给约束共同支撑", 1, "financial"),
            (f"{entity}在AI算力、HBM、先进封装或关键客户中的竞争位置是否稳固", 1, "industry"),
            (f"{entity}的毛利率、经营现金流和资本开支是否显示高质量增长", 1, "financial"),
            (f"{entity}的估值是否已经充分反映增长预期，与核心同行相比是否仍有研究空间", 2, "valuation"),
            (f"{entity}面临哪些技术替代、客户集中、出口管制或供应链约束风险", 2, "risk"),
            (f"{entity}最强反方逻辑是什么，哪些证据会削弱继续研究价值", 2, "adversarial"),
            (f"{entity}未来6到12个月有哪些财报、产品或产业链催化剂值得跟踪", 3, "catalyst"),
            (f"{entity}还缺少哪些官方披露、同行对比和估值数据才能进入深度研究", 3, "gap"),
        ]
    if industry == "platform_internet":
        return [
            (f"{entity}收入和利润增长来自用户规模、商家供给、货币化率还是补贴拉动", 1, "financial"),
            (f"{entity}营销费用率、履约成本、利润率和现金流是否支持增长质量", 1, "credit"),
            (f"{entity}平台双边网络、用户留存和商家生态是否形成可持续壁垒", 1, "moat"),
            (f"{entity}与主要同行相比，在流量、GMV、广告、云或本地生活等业务上的相对位置如何", 2, "industry"),
            (f"{entity}价格竞争、监管、数据合规和平台治理会如何影响业务模式", 2, "risk"),
            (f"{entity}最强反方逻辑是什么，哪些证据会推翻高增长或壁垒判断", 2, "adversarial"),
            (f"{entity}未来财报、用户指标、业务分部或监管事件中有哪些关键催化剂", 3, "catalyst"),
            (f"{entity}还缺少哪些分部、用户、订单、GMV、同行和估值数据", 3, "gap"),
        ]
    if industry == "bank_financial":
        return [
            (f"{entity}净息差、手续费收入和利润增长是否显示经营质量改善", 1, "financial"),
            (f"{entity}不良率、拨备覆盖率和资本充足率是否能支撑信用周期压力", 1, "credit"),
            (f"{entity}存款成本、贷款结构和风险资产暴露相对同行处于什么位置", 1, "industry"),
            (f"{entity}估值与ROE、资产质量和资本回报是否匹配", 2, "valuation"),
            (f"{entity}面临哪些利率周期、地产敞口、监管资本或信用损失风险", 2, "risk"),
            (f"{entity}最强反方逻辑是什么，哪些证据说明风险被低估", 2, "adversarial"),
            (f"{entity}未来财报、资本动作、监管或宏观利率变化有哪些催化剂", 3, "catalyst"),
            (f"{entity}还缺少哪些资产质量、资本和同行对比数据", 3, "gap"),
        ]
    if industry == "saas_software":
        return [
            (f"{entity}ARR、订阅收入、续约率和客户扩张是否支持高质量增长", 1, "financial"),
            (f"{entity}NRR、CAC、LTV、销售效率和 Rule of 40 是否显示商业模式健康", 1, "business_model"),
            (f"{entity}产品粘性、生态集成、客户留存和切换成本是否构成护城河", 1, "moat"),
            (f"{entity}利润转折、现金流和研发投入是否支持持续投入", 2, "financial"),
            (f"{entity}与同类软件或云服务公司相比，增长、利润率和估值处于什么位置", 2, "valuation"),
            (f"{entity}面临哪些客户预算收缩、竞争替代、AI重构或获客成本风险", 2, "risk"),
            (f"{entity}最强反方逻辑是什么，哪些证据会削弱产品粘性或增长质量", 2, "adversarial"),
            (f"{entity}还缺少哪些订阅指标、客户留存、同行估值和现金流数据", 3, "gap"),
        ]
    if industry == "trade_credit":
        return [
            (f"{entity}经营现金流、自由现金流、短债和债务到期结构是否支持偿债", 1, "credit"),
            (f"{entity}贸易业务的收入质量、毛利率、应收账款和存货周转是否健康", 1, "financial"),
            (f"{entity}担保链条、关联交易、资金占用和实控人风险是否突出", 1, "governance"),
            (f"{entity}再融资渠道、授信稳定性和外部支持能力如何", 1, "credit"),
            (f"{entity}行业价格、客户集中和上下游信用风险如何传导到违约概率", 2, "risk"),
            (f"{entity}哪些证据表明信用风险可能被高估或已经缓解", 2, "adversarial"),
            (f"{entity}未来债务到期、评级变化、诉讼处罚或再融资事件有哪些催化剂", 3, "catalyst"),
            (f"{entity}还缺少哪些债务明细、现金流、担保和评级报告信息", 3, "gap"),
        ]
    if industry == "manufacturing_new_energy":
        return [
            (f"{entity}收入、毛利率和产能利用率是否体现制造业经营质量", 1, "financial"),
            (f"{entity}经营现金流、资本开支和负债结构是否支持持续扩张", 1, "credit"),
            (f"{entity}技术路线、客户结构、市场份额和同行竞争位置如何", 1, "industry"),
            (f"{entity}成本曲线、库存、应收和价格周期是否会影响利润韧性", 2, "financial"),
            (f"{entity}原材料价格、价格战、海外政策和贸易壁垒会如何影响利润", 2, "risk"),
            (f"{entity}最强反方逻辑是什么，哪些证据会削弱技术或成本优势", 2, "adversarial"),
            (f"{entity}未来订单、产能、价格或政策变化中有哪些催化剂", 3, "catalyst"),
            (f"{entity}还缺少哪些三表、订单、产能、同行和估值数据", 3, "gap"),
        ]
    return [
        (f"{entity}财务质量如何：收入增长、利润率、现金流和资产负债是否健康", 1, "financial"),
        (f"{entity}商业模式和盈利来源是否清晰，可持续性如何", 1, "business_model"),
        (f"{entity}行业竞争格局和相对位置如何，同行对比是否支持继续研究", 1, "industry"),
        (f"{entity}估值、增长和盈利质量之间是否匹配", 2, "valuation"),
        (f"{entity}管理层、资本配置、股东结构、关联交易和内控是否健康", 2, "governance"),
        (f"{entity}品牌、技术、渠道、规模或网络效应等护城河是否稳固", 2, "moat"),
        (f"{entity}最强反方逻辑是什么，哪些风险会削弱继续研究价值", 2, "adversarial"),
        (f"{entity}还缺少哪些关键数据才能进入下一阶段研究", 3, "gap"),
    ]


def _private_company_template(topic: Topic) -> list[QuestionSpec]:
    entity = _entity(topic)
    return [
        (f"{entity}商业模式、收入模式、客户结构和单位经济是否成立", 1, "business_model"),
        (f"{entity}无法直接交易股票时，现实研究路径应转向经营质量、产业链机会和潜在资本市场动作", 1, "general"),
        (f"{entity}增长来源、持续性、获客效率和产品粘性如何", 1, "financial"),
        (f"{entity}所在赛道空间、竞争格局和进入壁垒如何", 1, "industry"),
        (f"{entity}融资、现金消耗、客户集中、政策和技术风险是什么", 1, "risk"),
        (f"{entity}创始团队、股权结构、员工持股和治理透明度如何", 2, "governance"),
        (f"{entity}最强反方逻辑是什么，哪些信息会削弱继续研究价值", 2, "adversarial"),
        (f"{entity}还缺少哪些官方披露、融资、经营和可比公司信息", 3, "gap"),
    ]


def _industry_theme_template(topic: Topic) -> list[QuestionSpec]:
    subject = topic.entity or "该主题"
    return [
        (f"{subject}的市场空间、增速和所处阶段如何", 1, "industry"),
        (f"{subject}相关样本的财务、现金流和经营指标是否已经出现共性变化", 1, "financial"),
        (f"{subject}由哪些政策、技术、需求或供给因素驱动", 1, "business_model"),
        (f"{subject}产业链中哪些公司、环节或资产最受益，哪些会受损", 1, "industry"),
        (f"{subject}竞争格局、进入壁垒和龙头相对优势如何", 1, "moat"),
        (f"{subject}面临哪些政策变化、供给过剩、价格战或技术替代风险", 2, "risk"),
        (f"{subject}最强反方逻辑是什么，哪些因素会推翻主题判断", 2, "adversarial"),
        (f"{subject}还缺少哪些行业数据、官方政策和关键公司证据", 3, "gap"),
    ]


def _credit_issuer_template(topic: Topic) -> list[QuestionSpec]:
    subject = _entity(topic)
    return [
        (f"{subject}现金流、债务结构和短期偿债能力是否健康", 1, "credit"),
        (f"{subject}盈利质量、经营稳定性和主业现金回款是否可持续", 1, "financial"),
        (f"{subject}再融资渠道、债务到期分布和外部支持能力如何", 1, "credit"),
        (f"{subject}实控人、担保链条、关联交易、表外风险和合规事项如何", 1, "governance"),
        (f"{subject}违约触发点和下行传导链条是什么", 2, "risk"),
        (f"{subject}哪些证据表明信用风险可能被高估或已有缓解", 2, "adversarial"),
        (f"{subject}未来到期、评级、再融资和司法事项中有哪些催化剂", 3, "catalyst"),
        (f"{subject}还缺少哪些债务、现金流、评级和公告信息", 3, "gap"),
    ]


def _macro_event_template(topic: Topic) -> list[QuestionSpec]:
    subject = _entity(topic)
    return [
        (f"{subject}的核心驱动因素是什么，当前处于什么阶段", 1, "general"),
        (f"{subject}通过哪些路径影响行业、公司、资产价格或信用风险", 1, "industry"),
        (f"{subject}最关键的跟踪变量是什么，哪些数据最能验证方向", 1, "financial"),
        (f"{subject}受益对象和受损对象分别是谁，影响程度如何", 2, "industry"),
        (f"{subject}有哪些政策、市场或执行风险会削弱当前判断", 2, "risk"),
        (f"{subject}最强反方逻辑是什么，哪些证据会改变方向判断", 2, "adversarial"),
        (f"{subject}未来6到12个月有哪些催化剂或触发条件", 3, "catalyst"),
        (f"{subject}还缺少哪些官方数据、政策文件和市场验证信号", 3, "gap"),
    ]


def _concept_asset_template(topic: Topic) -> list[QuestionSpec]:
    subject = _entity(topic)
    return [
        (f"{subject}对应的核心资产、产业链环节或标的范围是什么", 1, "industry"),
        (f"{subject}当前驱动因素是基本面、政策、资金面还是事件催化", 1, "business_model"),
        (f"{subject}相关标的的盈利、估值或供需逻辑是否有真实支撑", 1, "valuation"),
        (f"{subject}哪些受益标的、ETF或资源品最值得建立跟踪", 2, "industry"),
        (f"{subject}面临哪些拥挤交易、价格波动、政策变化或供需逆转风险", 2, "risk"),
        (f"{subject}最强反方逻辑是什么，哪些信号会推翻主题判断", 2, "adversarial"),
        (f"{subject}未来有哪些政策、价格、财报或资金流催化剂", 3, "catalyst"),
        (f"{subject}还缺少哪些官方数据、价格数据和可比资产信息", 3, "gap"),
    ]


def _build_question_specs(topic: Topic) -> list[QuestionSpec]:
    object_type = _object_type(topic)
    if object_type == "listed_company":
        return _listed_company_template(topic)
    if object_type == "private_company":
        return _private_company_template(topic)
    if object_type == "credit_issuer":
        return _credit_issuer_template(topic)
    if object_type in {"industry_theme"}:
        return _industry_theme_template(topic)
    if object_type in {"macro_theme", "event"} or topic.type == "compliance":
        return _macro_event_template(topic)
    if object_type in {"concept_theme", "fund_etf", "commodity"}:
        return _concept_asset_template(topic)
    return _industry_theme_template(topic)


def _extend_hypothesis_questions(topic: Topic, prompts: list[QuestionSpec]) -> list[QuestionSpec]:
    if not topic.hypothesis:
        return prompts
    entity = _entity(topic)
    hypothesis_prompt = (
        f"围绕用户假设“{topic.hypothesis}”，{entity}最关键的可验证变量和证伪条件是什么",
        2,
        "adversarial",
    )
    merged = [*prompts, hypothesis_prompt]
    deduped: list[QuestionSpec] = []
    seen: set[str] = set()
    for content, priority, framework_type in merged:
        normalized = content.strip()
        if normalized in seen:
            continue
        seen.add(normalized)
        deduped.append((normalized, priority, framework_type))
        if len(deduped) >= 8:
            break
    return deduped


def _fallback_question_specs(topic: Topic) -> list[QuestionSpec]:
    prompts = _extend_hypothesis_questions(topic, _build_question_specs(topic))
    return prompts


def _questions_from_specs(topic: Topic, prompts: list[QuestionSpec]) -> list[Question]:
    questions: list[Question] = []
    for index, spec in enumerate(prompts, start=1):
        content, priority, framework_type = spec[:3]
        explicit_search_query = spec[3] if len(spec) > 3 else None
        questions.append(
            Question(
                id=f"q{index}",
                topic_id=topic.id,
                search_query=(explicit_search_query or _fallback_search_query(topic, content, framework_type)).strip(),
                content=content,
                priority=priority,
                framework_type=framework_type,
            )
        )
    return questions


def _fallback_search_query(topic: Topic, content: str, framework_type: str) -> str:
    entity = _entity(topic)
    framework_terms = {
        "financial": "revenue gross margin net income operating cash flow annual report",
        "credit": "operating cash flow debt maturity capex free cash flow",
        "valuation": "PE PB EV EBITDA market cap peer comparison",
        "business_model": "business model revenue model customer structure",
        "industry": "market share competitor comparison industry position",
        "moat": "competitive advantage market share customer retention",
        "risk": "risk regulatory lawsuit investigation margin pressure",
        "governance": "governance board shareholder related party internal control",
        "compliance": "regulatory penalty compliance license investigation",
        "adversarial": "risk downside bearish thesis counter evidence",
        "catalyst": "earnings guidance product policy catalyst",
        "gap": "annual report investor relations financial results",
    }.get(framework_type, "business performance financial results analysis")
    keyword_candidates = re.findall(r"[\u4e00-\u9fffA-Za-z0-9%]{2,}", content)
    stopwords = {"是否", "如何", "哪些", "什么", "研究", "证据", "判断", "未来", "当前", "最强", entity}
    keywords = [item for item in keyword_candidates if item not in stopwords][:3]
    return " ".join([entity, *keywords, framework_terms]).strip()


def _extract_json_payload(raw: str) -> object | None:
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    match = re.search(r"\{.*\}", cleaned, flags=re.DOTALL)
    if not match:
        return None
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        return None


def _coerce_priority(value: object) -> int:
    try:
        priority = int(value)
    except (TypeError, ValueError):
        return 2
    return min(max(priority, 1), 3)


def _infer_framework_type(content: str) -> str:
    lowered = content.lower()
    for framework_type, keywords in _FRAMEWORK_KEYWORDS.items():
        if any(keyword.lower() in lowered for keyword in keywords):
            return framework_type
    return "general"


def _coerce_framework_type(value: object, content: str) -> str:
    framework_type = str(value or "").strip()
    if framework_type in _ALLOWED_FRAMEWORK_TYPES:
        return framework_type
    return _infer_framework_type(content)


def _is_actionable_question(content: str, topic: Topic) -> bool:
    normalized = content.strip()
    if len(normalized) < 8 or len(normalized) > 120:
        return False
    if normalized == topic.query or normalized == topic.topic:
        return False
    generic_patterns = [
        r"^研究.+是否",
        r"^分析.+是否",
        r"^探讨.+是否",
        r"有哪些证据支持该假设",
        r"有哪些证据可以反驳",
    ]
    return not any(re.search(pattern, normalized) for pattern in generic_patterns)


def _parse_llm_questions(raw: str, topic: Topic) -> list[Question] | None:
    payload = _extract_json_payload(raw)
    if payload is None:
        return None
    raw_questions = payload.get("questions") if isinstance(payload, dict) else payload
    if not isinstance(raw_questions, list):
        return None

    question_specs: list[QuestionSpec] = []
    seen: set[str] = set()
    for item in raw_questions:
        if not isinstance(item, dict):
            continue
        content = str(item.get("content") or "").strip()
        if not _is_actionable_question(content, topic):
            continue
        if content in seen:
            continue
        seen.add(content)
        search_query = str(item.get("search_query") or "").strip() or _fallback_search_query(
            topic,
            content,
            _coerce_framework_type(item.get("framework_type"), content),
        )
        framework_type = _coerce_framework_type(item.get("framework_type"), content)
        question_specs.append(
            (
                content,
                _coerce_priority(item.get("priority")),
                framework_type,
                search_query,
            )
        )
        if len(question_specs) >= 8:
            break

    if len(question_specs) < 5:
        return None
    framework_types = {spec[2] for spec in question_specs}
    if not framework_types.intersection({"financial", "credit", "industry", "business_model", "compliance"}):
        return None
    if "adversarial" not in framework_types:
        question_specs.append(
            (
                f"{_entity(topic)}最强反方逻辑是什么，哪些证据会削弱继续研究价值",
                2,
                "adversarial",
                _fallback_search_query(topic, "最强反方逻辑和风险证据", "adversarial"),
            )
        )
    if "gap" not in framework_types and len(question_specs) < 8:
        question_specs.append(
            (
                f"{_entity(topic)}还缺少哪些关键数据才能决定是否进入下一阶段研究",
                3,
                "gap",
                _fallback_search_query(topic, "关键数据缺口和官方披露", "gap"),
            )
        )

    return _questions_from_specs(topic, question_specs[:8])


def _llm_decompose(topic: Topic) -> list[Question] | None:
    prompt = DECOMPOSE_PROMPT_TEMPLATE.format(
        topic=topic.topic,
        entity=topic.entity or "",
        topic_type=topic.type,
        goal=topic.goal,
        hypothesis=topic.hypothesis or "null",
    )
    raw = call_llm(prompt, temperature=0.1)
    return _parse_llm_questions(raw, topic)


def _fallback_decompose(topic: Topic) -> list[Question]:
    return _questions_from_specs(topic, _fallback_question_specs(topic))


def decompose_problem(topic: Topic) -> list[Question]:
    """Break a topic into object-aware, analyst-style sub-questions with LLM-first generation."""

    try:
        llm_questions = _llm_decompose(topic)
        if llm_questions:
            return llm_questions
    except RuntimeError:
        pass
    return _fallback_decompose(topic)
