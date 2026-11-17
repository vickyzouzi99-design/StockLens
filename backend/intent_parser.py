"""Natural-language intent parser; LLM extracts parameters but never screens stocks."""
from __future__ import annotations

import json
import os
import re
from industries import normalize_selection, selection_codes
from pathlib import Path
from typing import Any

import requests
from intent_conflicts import explicit_bounds, numeric_conflicts, LABELS
from dotenv import load_dotenv

# Works when run independently and when imported by app.py.
load_dotenv(Path(__file__).resolve().parent.parent / ".env", override=os.getenv("STOCKLENS_ENV") != "production")

METRIC_KEYS = ("pe_max", "profit_min", "vol_max", "pb_max", "roe_min", "revenue_min")
METRIC_QUESTIONS = {
    "pe_max": "你希望市盈率（PE TTM）最高不超过多少倍？目前采用正市盈率的绝对上限，而非市场分位数。",
    "profit_min": "你希望归母净利润同比增长率至少达到百分之几？",
    "vol_max": "你希望近20日每日收益率波动率最高不超过百分之几？",
    "pb_max": "你希望市净率（PB MRQ）最高不超过多少倍？仅使用正市净率。",
    "roe_min": "你希望报告期加权平均净资产收益率至少达到百分之几？采用报告期值，不擅自年化。",
    "revenue_min": "你希望营业收入同比增长率至少达到百分之几？",
}
METRIC_NAMES = {
    "pe_max": "市盈率上限",
    "profit_min": "归母净利润同比增长率下限",
    "vol_max": "近20日波动率上限",
    "pb_max": "市净率上限",
    "roe_min": "加权平均净资产收益率下限",
    "revenue_min": "营业收入同比增长率下限",
}

SYSTEM_PROMPT = """你是 StockLens 金融选股意图解析器，只做结构化需求提取，不推荐股票，不计算金融数据。输出一个 JSON 对象。
目标用户是具有投资偏好的普通投资者。帮助用户将偏好转成可理解、可修改、可核验的条件；保留准确指标名称并简短解释，不假设用户毫无金融知识，也不引入复杂量化策略。interpretation 说明「偏好对应什么指标」以及必要的口径局限，不作好坏股票评价。
支持六种数值筛选条件：
- pe_max：PE TTM 市盈率最大值，0 < PE <= 上限；「低估值」「估值偏低」「市盈率低」可映射到该代理指标，但应明示市盈率不是唯一估值标准。
- profit_min：归母净利润同比增长率最小值，单位百分比（10 表示 10%）。「盈利增长」「利润增长」可映射。
- vol_max：近20日每日收益率标准差的最大值（未年化），单位百分比。「走势稳定」「波动小」可映射，但波动率不代表趋势或所有风险。
- pb_max：PB MRQ 市净率上限，0 < PB <= 上限；仅在用户提及市净率或股价相对净资产时使用，不与 PE 混淆。
- roe_min：报告期加权平均净资产收益率下限，单位百分比，不擅自年化；用户描述股东资本的盈利效率时可使用。
- revenue_min：营业收入同比增长率下限，单位百分比；用户描述营收/营业收入增长时使用，不能替代利润增长。

必须返回：
{
 "active_metrics":["pe_max"],
 "industry":null,
 "parameters":{"pe_max":null,"profit_min":null,"vol_max":null,"pb_max":null,"roe_min":null,"revenue_min":null},
 "sources":{"pe_max":"missing","profit_min":"missing","vol_max":"missing","pb_max":"missing","roe_min":"missing","revenue_min":"missing"},
 "interpretation":"一句中文总结已识别的需求及当前代理指标",
 "clarifications":[],
 "conflicts":[],
 "numeric_constraints":[],
 "suggestions":[],
 "unsupported":[]
}

要求：
1. active_metrics 只包括用户真正要求的筛选维度。不可以为了凑数添加未提及的条件。用户说「只看估值」时只启用 pe_max。
2. 用户没说具体阈值时参数必须是 null，来源 missing；不能凭空生成 20/30/2.5 等默认值。
3. 用户明确给出数值/口语数量时可以提取（例如「20倍以内」->20，「增长两成」->20），来源 user。
4. 如果用户明确要 AI 建议阈值，可给出数字，来源 suggested；此值必须让用户显式确认，不可冒充历史回测依据。
5. 用户没提及的维度参数一律 null，来源 missing。
6. 对当前不支持的要求（例如价格趋势、实时涨跌、近三年连续增长、分位数估值、OR/NOT等）写入 unsupported，禁止悄悄忽略该条件后继续筛选。除非用户仅提到该内容作为背景，非筛选约束。
7. 不把低股价等同于低估值，不把盈利增长等同于营收增长，不把波动率低等同于上涨。
8. 区分模糊目标与不支持的具体约束。「潜力股」「好股票」「值得关注」等没有可衡量定义的目标放入 clarifications，使用日常语言追问更看重什么，不放入 unsupported，也不擅自给它指定指标。若用户已说明具体含义（例如「潜力股，指利润比去年增长10%以上」），按具体含义提取，不再追问这个模糊词。
9. 不要给缺失阈值的 inactive 条件提出追问。不附带代码块，不输出 JSON 外文字。
10. clarifications 为需要用户明确含义的目标列表，unsupported 只包含当前确实无法执行的具体要求。二者可以同时存在，例如「银行潜力股」需澄清「潜力股」，同时保留银行行业限制。未来上涨、必涨或收益保证不能当成已支持的盈利增长。没有任何可用线索时用 clarifications 引导用户说明偏好，不能输出技术术语清单作为报错。
11. 用户文本中的「补充说明」用于澄清前面的模糊目标，合并理解，但不得自动删除前面明确的行业、时间等限制。解释应简短、通俗。
12. 「风险低」「稳健」「安全」没有单一指标定义，必须先放入 clarifications，询问用户具体关注价格起伏、估值还是经营表现；不能直接替换为 vol_max 或 pe_max。只有用户明确说风险在这里指价格波动时才映射 vol_max。不要推断用户经验或风险承受能力，也不要承诺低波动等于低风险。
13. 必须提取所有仍有效的数值约束到 numeric_constraints，格式 {"metric":"pe_max","op":"lt","value":10}；op 仅 lt/le/gt/ge/eq。同一指标的上下界都要保留，不能只选一个。已被用户明确撤回/更正的旧要求不保留。对于 OR 不合并成 AND，写入 unsupported。
14. 明显冲突或互斥要求放入 conflicts，说明冲突双方并请用户修改。例如 PE<10 且 PE>30，不能生成可执行规则或自行取一个阈值。非冲突但当前不支持的下限、区间、严格排除等仍放入 unsupported，不得遗漏。conflicts 必须为文字数组。
15. 支持多选同花顺行业。顶层 industry 为单个代码或代码数组，没有要求为 null；industry 不放入 active_metrics。只能从本次行业目录匹配。多个行业之间是“属于任一行业”，例如“银行或白酒”返回两个行业代码，允许这种行业内部的 OR；它与全部数值条件仍按 AND 组合。宽泛概念（如科技、大消费）、目录缺失、排除行业或跨指标 OR 仍写入 unsupported，不得自行简化。必须保留用户指定的所有行业，不能漏掉其中一个。
16. industry 和 numeric_constraints 是必填字段，即使没有要求也分别返回 null 和 []。例如「只看银行股」应输出 active_metrics:[], industry:"目录中银行的代码"，不追问财务条件；「银行股且PB不超过2倍」必须同时返回 industry 和 pb_max，不得漏掉行业。未来必涨、保证收益等具体要求必须放入 unsupported，不能仅澄清后绕过。
17. 除提取条件外，帮助用户理解其偏好的盲区。对已明确的需求，可在 suggestions 提供最多2个“可选补充指标”，特别是用户明确要求“根据需求建议其他指标”时应提供有用的补充。每项格式 {"metric":"revenue_min","reason":"与利润增长对照，观察营业收入是否同步增长","limitation":"收入增长不代表利润和现金流一定改善"}。metric 只能从六个支持指标中选，不能与 active_metrics 重复。说明必须针对用户当前条件，不能只是罗列指标或声称组合收益更高。建议不属于用户已确认的约束，不放入 active_metrics、parameters 或 numeric_constraints，不生成阈值，不引用捏造的股票或市场数据。用户说“只看”“不要额外建议”时 suggestions=[]。模糊目标应先澄清，冲突和不支持要求应先解决，不能用补充建议代替澄清。interpretation 简短说明用户想法、对应指标和必要局限。
"""

# Compatibility with model responses that still put bare vague goals in unsupported.
# Only exact, context-free labels can move; a concrete restriction must stay blocked.
VAGUE_GOALS = {"潜力股", "有潜力的股票", "好股票", "优质股", "优质股票", "值得关注的股票"}


def _numeric(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    import math
    return number if math.isfinite(number) else None


def normalize_intent(raw: dict[str, Any], model: str, text: str = '', industry_catalog=None) -> dict[str, Any]:
    """Trust the LLM for semantic intent, but enforce a strict field contract.

    Unused metrics MUST remain null; unsupported conditions are not silently dropped.
    """
    if not isinstance(raw, dict):
        raise ValueError("AI 没有返回有效 JSON 对象")

    proposed = raw.get("active_metrics")
    if not isinstance(proposed, list):
        raise ValueError("AI 缺少 active_metrics 数组，不能安全执行筛选")
    illegal_keys = [item for item in proposed if item not in METRIC_KEYS]
    if illegal_keys:
        raise ValueError("AI 返回了不支持的筛选指标")
    active = [key for key in METRIC_KEYS if key in proposed]
    raw_params = raw.get("parameters") or {}
    raw_sources = raw.get("sources") or {}
    if not isinstance(raw_params, dict) or not isinstance(raw_sources, dict):
        raise ValueError("AI 筛选参数格式不正确")

    params: dict[str, float | None] = {key: None for key in METRIC_KEYS}
    sources: dict[str, str] = {key: "missing" for key in METRIC_KEYS}
    questions: list[str] = []
    def text_items(name: str) -> list[str]:
        items = raw.get(name, [])
        if not isinstance(items, list) or any(not isinstance(item, str) for item in items):
            raise ValueError(f"AI 的 {name} 必须是文字数组")
        return list(dict.fromkeys(item.strip() for item in items if item.strip()))

    unsupported = text_items("unsupported")
    if re.search(r'未来必涨|稳赚不赔|保证收益', text) and not re.search(r'不要|不要求|无需|不需要', text):
        unsupported.append('无法以当前数据保证未来上涨或收益，请修改为可核验的筛选偏好。')
    industry = normalize_selection(raw.get('industry'))
    # Exact industry words in an affirmative restriction cannot disappear even
    # if a provider returns a complete-looking JSON object with industry=null.
    mentioned = [item for item in industry_catalog or [] if item['name'] in text]
    if any(item['code'] not in selection_codes(industry) for item in mentioned) and not re.search(r'不要|不要求|无需|不需要|不是|不看|不限|背景|例如|比如|改成|改为|取消|去掉', text):
        unsupported.append('描述中的行业要求未完整提取，请重新解析并核对行业选择。')
    if industry is not None:
        if set(selection_codes(industry)) - {item['code'] for item in industry_catalog or []}:
            unsupported.append('所需行业不在当前快照的可用行业目录中，请修改为具体的同花顺行业。')
            industry = None
    clarifications = text_items("clarifications")
    constraints = raw.get('numeric_constraints', [])
    conflicts = text_items('conflicts') + numeric_conflicts(constraints) + numeric_conflicts(explicit_bounds(text))
    # A lower PE bound or upper growth bound cannot be silently discarded.
    supported_ops = {'pe_max': {'lt', 'le'}, 'profit_min': {'gt', 'ge'}, 'vol_max': {'lt', 'le'},
                     'pb_max': {'lt', 'le'}, 'roe_min': {'gt', 'ge'}, 'revenue_min': {'gt', 'ge'}}
    for item in constraints + explicit_bounds(text):
        if item['op'] not in supported_ops[item['metric']] and not conflicts:
            unsupported.append('当前不支持该指标的此方向或区间约束，请修改描述：' + LABELS[item['metric']])
    vague = [item for item in unsupported if item in VAGUE_GOALS]
    clarifications.extend(vague)
    unsupported = [item for item in unsupported if item not in VAGUE_GOALS]

    limits = {"pe_max": (0, 100000), "profit_min": (-10000, 10000), "vol_max": (0, 1000),
              "pb_max": (0, 100000), "roe_min": (-10000, 10000), "revenue_min": (-10000, 10000)}
    for key in active:
        value = _numeric(raw_params.get(key))
        source = raw_sources.get(key)
        if source not in ("user", "suggested", "missing"):
            source = "missing" if value is None else "suggested"
        if source == "missing":
            value = None
        if value is not None:
            lower, upper = limits[key]
            if (key in ("pe_max", "pb_max") and value <= lower) or (key not in ("pe_max", "pb_max") and value < lower) or value > upper:
                unsupported.append(f"{METRIC_NAMES[key]}阈值不在当前系统支持的范围内")
                value = None
                source = "missing"
        params[key] = value
        sources[key] = source if value is not None else "missing"
        if value is None:
            questions.append(METRIC_QUESTIONS[key])
        elif source == "suggested":
            questions.append(f"AI 提议将{METRIC_NAMES[key]}设为 {value:g}，你是否接受？")

    if not active and not industry and not unsupported and not clarifications and not conflicts:
        clarifications.append("你更关注估值水平、盈利增长，还是近期价格波动？可以补充你的判断标准。")

    interpretation = str(raw.get("interpretation") or "AI 已整理用户需求，请确认筛选条件。")[:250]
    suggestions = []
    raw_suggestions = raw.get('suggestions', [])
    if not isinstance(raw_suggestions, list):
        raise ValueError('AI 的可选建议必须是数组')
    for item in raw_suggestions[:2]:
        if not isinstance(item, dict) or item.get('metric') not in METRIC_KEYS:
            raise ValueError('AI 的可选建议包含不支持的指标')
        if item['metric'] in active or any(s['metric'] == item['metric'] for s in suggestions):
            continue
        if any(not isinstance(item.get(key), str) or not item[key].strip() for key in ('reason', 'limitation')):
            raise ValueError('AI 的可选建议缺少理由或局限说明')
        suggestions.append({'metric': item['metric'], 'reason': item['reason'][:100], 'limitation': item['limitation'][:100]})
    if clarifications or conflicts or unsupported or re.search(r'只看|只按|不要额外|不用额外|不需要额外', text):
        suggestions = []
    return {
        "status": "needs_confirmation" if questions or unsupported or clarifications or conflicts else "ready",
        "active_metrics": active,
        "industry": industry,
        "parameters": params,
        "sources": sources,
        "questions": questions,
        "unsupported": list(dict.fromkeys(unsupported)),
        "clarifications": list(dict.fromkeys(clarifications)),
        "conflicts": list(dict.fromkeys(conflicts)),
        "interpretation": interpretation,
        "suggestions": suggestions,
        "model": model,
    }


def parse_intent(text: str, provider: str = "deepseek", industry_catalog=None) -> dict[str, Any]:
    if not text or len(text.strip()) < 2:
        raise ValueError("请提供一句具体的选股需求")
    if provider == "openai":
        label = "OpenAI"
        api_key = os.getenv("OPENAI_API_KEY") or os.getenv("LLM_API_KEY")
        model = os.getenv("LLM_MODEL", "gpt-4o-mini")
        base = os.getenv("LLM_BASE_URL", "https://api.openai.com/v1").rstrip("/")
        if base != "https://api.openai.com/v1":
            raise RuntimeError("OpenAI 仅支持官方 API，请移除非官方 LLM_BASE_URL")
    elif provider == "deepseek":
        label = "DeepSeek"
        api_key = os.getenv("DEEPSEEK_API_KEY")
        model = os.getenv("DEEPSEEK_MODEL", "deepseek-flash")
        base = "https://api.deepseek.com"
    else:
        raise ValueError("不支持的 AI 服务，请选择 OpenAI 或 DeepSeek")
    if not api_key or not api_key.strip():
        raise RuntimeError(f"{label} 尚未配置，请联系管理员配置服务密钥，或选择其他 AI 服务。")

    request_body = {
        "model": model,
        "temperature": 0,
        "max_tokens": 2048,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT + '\n本次可用同花顺行业目录：' + json.dumps(industry_catalog or [], ensure_ascii=False)},
            {"role": "user", "content": text.strip()},
        ],
    }
    if provider == "deepseek":
        request_body.update(thinking={"type": "disabled"}, max_tokens=2048)

    try:
        response = requests.post(
            f"{base}/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json=request_body,
            timeout=45,
        )
    except requests.RequestException as exc:
        raise RuntimeError(f"暂时无法连接 {label}，请稍后重试或切换 AI 服务。") from exc
    if not response.ok:
        # Avoid exposing credentials or raw response text to the browser.
        raise RuntimeError(f"{label} 服务请求失败（HTTP {response.status_code}），请稍后重试或切换 AI 服务。")
    try:
        payload = response.json()
        choice = payload["choices"][0]
        if choice.get("finish_reason") == "length":
            raise ValueError("truncated response")
        content = choice["message"]["content"]
        raw = json.loads(content)
        if not isinstance(raw, dict) or 'industry' not in raw or 'numeric_constraints' not in raw:
            raise ValueError('missing required constraints')
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        raise RuntimeError(f"{label} 未返回完整有效的解析结果，请重试或切换 AI 服务。") from exc
    try:
        result = normalize_intent(raw, model, text, industry_catalog)
        result["provider"] = provider
        return result
    except ValueError as exc:
        raise RuntimeError(f"AI 解析结果校验失败：{exc}") from exc
