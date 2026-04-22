from __future__ import annotations

import re
from datetime import datetime

from app.models.question import Question
from app.models.topic import Topic

DEFAULT_FRAMEWORK_QUERY_TEMPLATES: dict[str, str] = {
    "financial": "{entity} annual report quarterly results revenue net income cash flow recent",
    "credit": "{entity} operating cash flow debt leverage refinancing recent",
    "valuation": "{entity} valuation PE market cap peer comparison recent",
    "business_model": "{entity} business model revenue model customer structure latest",
    "industry": "{entity} market share industry competition peer comparison recent",
    "moat": "{entity} competitive advantage moat market share customer retention recent",
    "risk": "{entity} risk negative issue pressure regulatory recent",
    "governance": "{entity} governance related party transaction internal control recent",
    "compliance": "{entity} regulatory compliance penalty license qualification recent",
    "adversarial": "{entity} bearish thesis downside risk counter evidence recent",
    "catalyst": "{entity} catalyst earnings product policy latest",
    "gap": "{entity} official filing investor relations annual report quarterly report",
    "general": "{entity} business performance latest analysis recent",
}

OBJECT_QUERY_OVERRIDES: dict[str, dict[str, str]] = {
    "listed_company": {
        "financial": "{entity} investor relations annual report quarterly results revenue margin cash flow",
        "valuation": "{entity} valuation PE market cap revenue growth peer comparison",
        "industry": "{entity} market share competitors industry position recent",
        "catalyst": "{entity} earnings release guidance buyback dividend product launch",
        "gap": "{entity} official filing annual report quarterly results investor presentation",
    },
    "private_company": {
        "financial": "{entity} revenue funding profitability business update latest",
        "business_model": "{entity} business model customers products ecosystem official",
        "industry": "{entity} industry report competitors market position latest",
        "governance": "{entity} ownership structure founder employee shareholding governance",
        "valuation": "{entity} funding valuation private company financing latest",
        "gap": "{entity} official website annual report business update financing news",
    },
    "industry_theme": {
        "financial": "{entity} industry data market size growth report latest",
        "business_model": "{entity} industry drivers demand supply policy technology latest",
        "industry": "{entity} industry association market size competition landscape report",
        "valuation": "{entity} key companies valuation sector comparison latest",
        "catalyst": "{entity} policy catalyst technology breakthrough price inflection latest",
        "gap": "{entity} official policy industry report market data latest",
    },
    "credit_issuer": {
        "financial": "{entity} annual report operating cash flow profit stability debt",
        "credit": "{entity} bond prospectus debt maturity refinancing rating report",
        "governance": "{entity} guarantee related party transaction litigation penalty",
        "risk": "{entity} default risk overdue debt guarantee litigation",
        "adversarial": "{entity} credit risk mitigation refinancing support rating outlook",
        "catalyst": "{entity} bond maturity refinancing rating change litigation latest",
        "gap": "{entity} prospectus annual report rating report bond announcement",
    },
    "macro_theme": {
        "financial": "{entity} macro data official statistics latest",
        "industry": "{entity} impact path sectors beneficiaries losers latest",
        "risk": "{entity} macro risk policy change market impact latest",
        "catalyst": "{entity} policy meeting central bank data release latest",
        "gap": "{entity} official data policy document latest",
    },
    "event": {
        "general": "{entity} event timeline official statement latest",
        "industry": "{entity} event impact beneficiaries losers market reaction latest",
        "risk": "{entity} event risk regulatory response litigation latest",
        "catalyst": "{entity} event next catalyst official update latest",
        "gap": "{entity} official statement filing announcement latest",
    },
    "concept_theme": {
        "industry": "{entity} concept theme supply chain beneficiaries latest",
        "valuation": "{entity} related stocks ETF valuation comparison latest",
        "risk": "{entity} crowded trade risk policy risk latest",
        "catalyst": "{entity} policy catalyst industry catalyst latest",
        "gap": "{entity} official data industry report related companies latest",
    },
    "fund_etf": {
        "financial": "{entity} ETF holdings performance expense ratio latest",
        "valuation": "{entity} ETF holdings valuation sector exposure latest",
        "risk": "{entity} ETF risk tracking error liquidity latest",
        "catalyst": "{entity} index rebalance policy catalyst latest",
        "gap": "{entity} ETF official holdings factsheet latest",
    },
    "commodity": {
        "financial": "{entity} price inventory supply demand latest",
        "industry": "{entity} supply demand production inventory report latest",
        "risk": "{entity} price risk policy inventory demand latest",
        "catalyst": "{entity} price catalyst supply disruption demand inflection latest",
        "gap": "{entity} official inventory production price data latest",
    },
}

RISK_QUERY_TEMPLATES_BY_OBJECT = {
    "listed_company": ["{entity} risk downside regulatory cash flow pressure recent", "{entity} negative news margin pressure competition"],
    "private_company": ["{entity} financing pressure governance risk customer concentration", "{entity} policy risk product controversy latest"],
    "industry_theme": ["{entity} industry risk oversupply price war policy change", "{entity} bearish thesis demand weakness latest"],
    "credit_issuer": ["{entity} default risk overdue debt litigation guarantee", "{entity} rating downgrade refinancing pressure"],
    "macro_theme": ["{entity} macro downside risk policy reversal", "{entity} market risk adverse scenario latest"],
    "event": ["{entity} event downside regulatory litigation risk", "{entity} adverse impact latest"],
    "concept_theme": ["{entity} concept risk crowded trade policy change", "{entity} theme downside latest"],
    "fund_etf": ["{entity} ETF risk tracking error liquidity drawdown", "{entity} holdings risk latest"],
    "commodity": ["{entity} price downside inventory demand risk", "{entity} supply demand bearish latest"],
}

COUNTER_QUERY_TEMPLATES_BY_OBJECT = {
    "listed_company": ["{entity} earnings beat margin improvement cash flow positive", "{entity} growth acceleration guidance raised recent"],
    "private_company": ["{entity} funding growth product traction partnership latest", "{entity} business improvement market share latest"],
    "industry_theme": ["{entity} demand acceleration policy support technology breakthrough", "{entity} industry inflection positive evidence"],
    "credit_issuer": ["{entity} refinancing support rating stable debt repayment", "{entity} credit risk mitigation latest"],
    "macro_theme": ["{entity} positive scenario policy support data improvement", "{entity} counter evidence latest"],
    "event": ["{entity} clarification recovery positive response latest", "{entity} counter evidence event impact"],
    "concept_theme": ["{entity} policy support beneficiary evidence latest", "{entity} theme validation positive signal"],
    "fund_etf": ["{entity} ETF inflow holdings performance improvement", "{entity} index catalyst positive latest"],
    "commodity": ["{entity} price upside supply disruption demand recovery", "{entity} inventory decline positive latest"],
}

US_SYMBOL_ALIASES = {"PDD", "BABA", "JD", "BIDU", "NIO", "XPEV", "LI", "TSLA", "NVDA", "AAPL", "MSFT", "AMZN", "GOOG", "AMD", "AVGO", "JPM", "BAC"}
US_COMPANY_NAMES = {"拼多多", "阿里巴巴", "京东", "百度", "特斯拉", "英伟达", "苹果", "微软", "AMD", "博通", "摩根大通", "美国银行"}
ENGLISH_ENTITY_ALIASES = {
    "拼多多": "PDD Holdings",
    "阿里巴巴": "Alibaba",
    "京东": "JD.com",
    "百度": "Baidu",
    "特斯拉": "Tesla",
    "英伟达": "NVIDIA",
    "苹果": "Apple",
    "微软": "Microsoft",
    "腾讯": "Tencent",
    "美团": "Meituan",
}

OFFICIAL_QUERY_TEMPLATES_BY_MARKET = {
    "US": [
        "{entity} site:sec.gov 10-K annual report",
        "{entity} investor relations earnings results",
        "{entity} IR quarterly results press release",
    ],
    "A_share": [
        "{entity} site:cninfo.com.cn 年度报告",
        "{entity} site:sse.com.cn 披露",
        "{entity} 巨潮资讯 年报 季报",
    ],
    "HK": [
        "{entity} site:hkexnews.hk annual report",
        "{entity} HKEX disclosure results",
        "{entity} investor relations annual results",
    ],
}

PROFESSIONAL_QUERY_TEMPLATES = [
    "{entity} revenue gross margin net income {year}",
    "{entity} earnings results fiscal year",
    "{entity} annual report financial highlights",
]

FRAMEWORK_LAYERED_QUERY_TEMPLATES = {
    "financial": ["{entity} operating cash flow capex free cash flow"],
    "credit": ["{entity} operating cash flow capex debt maturity leverage"],
    "industry": ["{entity} market share competitor comparison"],
    "valuation": ["{entity} PE PB EV EBITDA valuation multiple"],
    "governance": ["{entity} board directors shareholder structure"],
    "compliance": ["{entity} regulatory penalty compliance investigation"],
    "risk": ["{entity} risk regulatory lawsuit investigation"],
    "adversarial": ["{entity} risk regulatory lawsuit investigation"],
}


def _entity(topic: Topic) -> str:
    return topic.entity or topic.topic


def _object_type(topic: Topic) -> str:
    object_type = getattr(topic, "research_object_type", "unknown")
    if object_type != "unknown":
        return object_type
    if topic.type == "company" and getattr(topic, "listing_status", "unknown") == "listed":
        return "listed_company"
    if topic.type == "company" and getattr(topic, "listing_status", "unknown") in {"private", "unlisted"}:
        return "private_company"
    if topic.type == "theme":
        return "industry_theme"
    return "listed_company" if topic.type == "company" else "industry_theme"


def _market_type(topic: Topic) -> str:
    market_type = getattr(topic, "market_type", "other")
    if market_type != "other":
        return market_type
    if is_us_stock(topic):
        return "US"
    entity = _entity(topic)
    if entity in {"宁德时代", "比亚迪", "贵州茅台"}:
        return "A_share"
    if entity in {"腾讯", "美团", "小米"}:
        return "HK"
    return market_type


def build_directed_search_queries(entity: str, market_type: str) -> list[str]:
    """Build official site-directed queries. These are best-effort, not main recall queries."""

    queries: list[str] = []
    for template in OFFICIAL_QUERY_TEMPLATES_BY_MARKET.get(market_type, []):
        query = template.format(entity=entity, year=datetime.now().year).strip()
        if query and query not in queries:
            queries.append(query)
    return queries


def build_main_search_queries(entity: str, framework: str) -> list[str]:
    """Build high-recall queries for the main retrieval path."""

    current_year = datetime.now().year
    queries: list[str] = []
    template_groups = [
        PROFESSIONAL_QUERY_TEMPLATES,
        FRAMEWORK_LAYERED_QUERY_TEMPLATES.get(framework, []),
    ]
    for templates in template_groups:
        for template in templates:
            query = template.format(entity=entity, year=current_year).strip()
            if query and query not in queries:
                queries.append(query)
    return queries


def build_layered_search_queries(entity: str, market_type: str, framework: str) -> list[str]:
    """Build source-governed queries: high-recall main queries first, official directed queries last."""

    queries: list[str] = []
    for query in [*build_main_search_queries(entity, framework), *build_directed_search_queries(entity, market_type)]:
        if query and query not in queries:
            queries.append(query)
    return queries


def split_directed_queries(queries: list[str]) -> tuple[list[str], list[str]]:
    """Separate site-directed queries from main queries so they cannot starve broad retrieval."""

    main: list[str] = []
    directed: list[str] = []
    for query in queries:
        if "site:" in query.lower():
            directed.append(query)
        else:
            main.append(query)
    return main, directed


def _framework_template(question: Question, topic: Topic) -> str:
    object_type = _object_type(topic)
    object_templates = OBJECT_QUERY_OVERRIDES.get(object_type, {})
    return object_templates.get(
        question.framework_type,
        DEFAULT_FRAMEWORK_QUERY_TEMPLATES.get(question.framework_type, DEFAULT_FRAMEWORK_QUERY_TEMPLATES["general"]),
    )


def _question_semantic_query(question: Question, topic: Topic) -> str:
    entity = _entity(topic)
    text = question.content
    keyword_candidates = re.findall(r"[\u4e00-\u9fffA-Za-z0-9%]{2,}", text)
    stopwords = {
        "哪些",
        "是否",
        "如何",
        "什么",
        "以及",
        "当前",
        "目前",
        "需要",
        "判断",
        "决定",
        "研究",
        "证据",
        "补证",
        "围绕",
        "用户",
        "最强",
        "未来",
    }
    keywords = [item for item in keyword_candidates if item not in stopwords and item != entity]
    query_terms = keywords[:7]
    object_type = _object_type(topic)
    if question.framework_type in {"financial", "credit"}:
        query_terms.extend(["latest", "annual report", "quarterly results"])
    elif question.framework_type == "valuation" and object_type == "listed_company":
        query_terms.extend(["valuation", "peer comparison", "recent"])
    elif question.framework_type == "industry":
        query_terms.extend(["industry report", "recent"])
    elif question.framework_type == "catalyst":
        query_terms.extend(["latest", "catalyst"])
    elif question.framework_type == "gap":
        query_terms.extend(["official", "latest"])
    else:
        query_terms.append("recent")
    return " ".join([entity, *query_terms]).strip()


def build_fact_queries(question: Question, topic: Topic) -> list[str]:
    entity = _entity(topic)
    market_type = _market_type(topic)
    object_type = _object_type(topic)
    layered_queries = (
        build_layered_search_queries(entity, market_type, question.framework_type)
        if object_type == "listed_company" or market_type in {"US", "A_share", "HK"}
        else []
    )
    framework_query = _framework_template(question, topic).format(entity=entity)
    semantic_query = _question_semantic_query(question, topic)
    queries: list[str] = []
    explicit_search_query = (question.search_query or "").strip()
    semantic_queries = [] if explicit_search_query else [semantic_query]
    for query in [explicit_search_query, *layered_queries, framework_query, *semantic_queries]:
        if query and query not in queries:
            queries.append(query)
    return queries


def build_risk_queries(topic: Topic) -> list[str]:
    entity = _entity(topic)
    templates = RISK_QUERY_TEMPLATES_BY_OBJECT.get(_object_type(topic), RISK_QUERY_TEMPLATES_BY_OBJECT["industry_theme"])
    return [template.format(entity=entity) for template in templates]


def build_counter_queries(topic: Topic) -> list[str]:
    entity = _entity(topic)
    templates = COUNTER_QUERY_TEMPLATES_BY_OBJECT.get(_object_type(topic), COUNTER_QUERY_TEMPLATES_BY_OBJECT["industry_theme"])
    return [template.format(entity=entity) for template in templates]


def build_english_queries(topic: Topic) -> list[str]:
    entity = ENGLISH_ENTITY_ALIASES.get(_entity(topic), _entity(topic))
    if _object_type(topic) != "listed_company":
        return []
    return [
        f"{entity} investor relations annual report revenue net income",
        f"{entity} quarterly results earnings release cash flow",
    ]


def is_us_stock(topic: Topic) -> bool:
    if getattr(topic, "market_type", None) == "US":
        return True
    if topic.entity and (topic.entity.upper() in US_SYMBOL_ALIASES or topic.entity in US_COMPANY_NAMES):
        return True
    symbol = getattr(topic, "symbol", None)
    if symbol:
        return not any(exchange_suffix in symbol for exchange_suffix in [".SZ", ".SH", ".HK"])
    return False
