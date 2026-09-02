"""多 LLM 辩论式研报编排器。

流程：
1. 抓取 AkShare 结构化数据
2. Generator A / B 各写一版初稿（不同视角）
3. Judge 对两稿分别打分（5 维度 × 20 分）
4. 两个生成器参考对手稿件与评审反馈各自修订
5. Judge 终评，选出最终版本写入 result/

任一环节失败都有结构化数据回退方案，保证总能产出可用报告。
"""
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from finsight.config import config
from finsight.services.data_bundle import build_stock_data_bundle
from finsight.services.llm_clients import (
    get_generator_a_client,
    get_generator_b_client,
    get_judge_client,
)
from finsight.services.report_specs import (
    REPORT_TYPE_CONFIG,
    clean_markdown_output,
    get_report_filename,
    infer_sector,
    normalize_report_type,
    report_type_slug,
)

REPORT_META_DIR = config.REPORT_META_DIR
REPORT_META_DIR.mkdir(parents=True, exist_ok=True)

StatusCallback = Optional[Callable[[str, Dict[str, Any]], None]]
StreamCallback = Optional[Callable[[str, Dict[str, Any]], None]]

EXPECTED_OUTLINE = (
    "# 一、宏观经济与行业分析\n"
    "# 二、财务指标深度解析\n"
    "# 三、技术面与资金流向\n"
    "# 四、风险评估与投资建议"
)

# 多空对抗辩论的角色设定：
# adversarial 模式下 Generator A 扮演多头研究员，Generator B 扮演空头/风控研究员，
# Judge 作为中立仲裁人对双方稿件统一评分，避免结论偏向任何一方。
DEBATE_PERSPECTIVES: Dict[str, Dict[str, str]] = {
    "adversarial": {
        "a": (
            "多方（Bull）研究员视角：重点挖掘公司基本面亮点、成长催化剂、行业景气度与估值修复空间，"
            "论证看多逻辑；但不得回避重大风险，风险提示仍须客观完整。"
        ),
        "b": (
            "空方/风控（Bear）研究员视角：重点审查公司经营风险、估值泡沫、行业下行压力、财务质量与治理隐患，"
            "论证看空/审慎逻辑；但看空论点必须有数据支撑，不得为唱空而夸大或编造负面事实。"
        ),
    },
    "parallel": {
        "a": "偏重财务与估值",
        "b": "偏重行业、风险与催化因素",
    },
}


def _debate_mode() -> str:
    return config.DEBATE_MODE if config.DEBATE_MODE in DEBATE_PERSPECTIVES else "parallel"


def _debate_perspective(side: str) -> str:
    return DEBATE_PERSPECTIVES[_debate_mode()][side]


def _json_block(data: Dict[str, Any]) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2, default=str)


def _emit_status(callback: StatusCallback, status: str, **details: Any) -> None:
    if callback:
        callback(status, details)


def _emit_stream(callback: StreamCallback, event: str, **details: Any) -> None:
    if callback:
        callback(event, details)


def _truncate_text(value: Any, max_length: int = 2000) -> str:
    text = str(value or "")
    if len(text) <= max_length:
        return text
    return text[:max_length] + "\n...(truncated)"


def _extract_metric_groups(structured_data: Dict[str, Any]) -> Dict[str, Any]:
    spot = structured_data.get("spot", {})
    history_summary = structured_data.get("history", {}).get("summary", {})
    financial_latest = structured_data.get("financial", {}).get("latest", {})
    industry = structured_data.get("industry", {})
    web_search = structured_data.get("web_search", {})

    return {
        "market_metrics": {
            "最新价": spot.get("最新价"),
            "涨跌幅": spot.get("涨跌幅"),
            "换手率": spot.get("换手率"),
            "总市值": spot.get("总市值"),
            "流通市值": spot.get("流通市值"),
        },
        "valuation_metrics": {
            "市盈率-动态": spot.get("市盈率-动态") or industry.get("pe_dynamic"),
            "市净率": spot.get("市净率") or industry.get("pb"),
        },
        "price_trend_metrics": {
            "区间涨跌幅": history_summary.get("period_pct_change"),
            "区间最高价": history_summary.get("period_high"),
            "区间最低价": history_summary.get("period_low"),
            "近20日平均成交额": history_summary.get("avg_amount"),
            "近20日平均涨跌幅": history_summary.get("avg_pct_change"),
        },
        "financial_metrics": {
            key: financial_latest.get(key)
            for key in list(financial_latest.keys())[:16]
        },
        "industry_metrics": industry,
        "web_search_metrics": web_search.get("summary", {}),
    }


def _summarize_structured_data(structured_data: Dict[str, Any], report_type: str) -> Dict[str, Any]:
    stock = structured_data.get("stock", {})
    cache_info = structured_data.get("cache_info", {})
    metric_groups = _extract_metric_groups(structured_data)

    base_summary = {
        "stock": stock,
        "generated_at": structured_data.get("generated_at"),
        "source": structured_data.get("source", "akshare"),
        "cache_info": cache_info,
    }

    if report_type == "风险预测":
        focus = {
            "risk_focus": {
                "波动与区间走势": metric_groups["price_trend_metrics"],
                "估值风险": metric_groups["valuation_metrics"],
                "流动性与交易热度": {
                    "换手率": metric_groups["market_metrics"].get("换手率"),
                    "近20日平均成交额": metric_groups["price_trend_metrics"].get("近20日平均成交额"),
                },
                "财务稳健性": metric_groups["financial_metrics"],
            }
        }
    elif report_type == "前景分析":
        focus = {
            "growth_focus": {
                "市场表现": metric_groups["market_metrics"],
                "估值概览": metric_groups["valuation_metrics"],
                "趋势概览": metric_groups["price_trend_metrics"],
                "成长与盈利指标": metric_groups["financial_metrics"],
            }
        }
    elif report_type == "行业市场分析":
        focus = {
            "industry_focus": {
                "行业与估值快照": metric_groups["industry_metrics"],
                "市场表现": metric_groups["market_metrics"],
                "价格趋势": metric_groups["price_trend_metrics"],
            }
        }
    else:
        focus = {
            "analysis_focus": {
                "市场指标": metric_groups["market_metrics"],
                "估值指标": metric_groups["valuation_metrics"],
                "价格趋势": metric_groups["price_trend_metrics"],
                "财务摘要": metric_groups["financial_metrics"],
                "网页补充信息": metric_groups["web_search_metrics"],
            }
        }

    return {**base_summary, **focus}


def _build_report_spec(report_type: str) -> Dict[str, str]:
    cfg = REPORT_TYPE_CONFIG[report_type]
    rubric = {
        "data_grounding": "是否忠实使用 AkShare A 股结构化数据与当前接入接口结果，是否避免编造数据或无依据推断",
        "logic": "分析逻辑是否连贯，结论是否由数据、行业与风险信息支撑",
        "clarity": "报告结构是否清晰，是否遵循指定章节与专业表述",
        "risk": "风险揭示是否充分具体，是否覆盖核心不确定性",
        "compliance": "是否审慎、合规，避免确定性承诺与夸大表述",
    }
    return {
        "title": cfg["title"],
        "summary": cfg["summary"],
        "outline": cfg["outline"],
        "rubric": json.dumps(rubric, ensure_ascii=False, indent=2),
    }


def _build_generation_messages(
    stock_code: str,
    stock_name: str,
    report_type: str,
    structured_data: Dict[str, Any],
    perspective: str,
) -> List[Dict[str, str]]:
    sector = infer_sector(stock_code)
    generated_at = structured_data.get("generated_at", "")
    compact_data = _summarize_structured_data(structured_data, report_type)
    return [
        {
            "role": "system",
            "content": (
                "你是一名专业的中文股票研究分析师。"
                "你必须严格基于提供的公司名称、股票代码、所属板块、可用市场数据、财务数据及行业背景信息写作。"
                "不得编造不存在的数据；若部分信息缺失，请以自然、克制、专业的研报语言处理。"
                "不要写生硬的括号说明、编者按或类似‘注：因数据接口限制，无法获取……’的突兀字眼。"
                "如需说明口径限制，应把限制自然融入正文分析。"
            ),
        },
        {
            "role": "user",
            "content": (
                "请基于给定的公司名称、股票代码、所属板块、可用市场数据、财务数据及行业背景信息，"
                "撰写一份正式、完整、偏卖方研报风格的中文个股分析报告。\n\n"
                "【报告标题格式】\n"
                f"# {stock_name}({stock_code})分析报告\n\n"
                f"**板块**: {sector}\n"
                f"**生成时间**: {generated_at}\n\n"
                "【报告结构】\n全文必须严格分为以下四个部分，并使用如下标题：\n\n"
                f"{EXPECTED_OUTLINE}\n\n"
                "【各部分写作要求】\n\n"
                "第一部分：宏观经济与行业分析\n"
                "- 结合当前宏观经济环境展开分析（GDP增速、通胀、货币政策、财政政策、利率、汇率、国际资本流动等）。\n"
                "- 分析宏观变量如何影响该股票所在行业和公司估值。\n"
                "- 结合公司真实所属行业，分析竞争格局、市场集中度、技术变革、政策影响、行业周期与景气度。\n"
                "- 必须保证公司、股票代码、行业属性一致，不得张冠李戴。\n\n"
                "第二部分：财务指标深度解析\n"
                "- 若有财务数据，重点分析盈利能力、成长能力、偿债能力、运营效率和现金流质量。\n"
                "- 同时分析公司治理质量（股权结构、信息披露透明度、管理层稳定性等）。\n"
                "- 若缺乏具体财务数据，必须明确说明，但仍可从框架角度提示应重点关注的指标和风险。\n"
                "- 不得捏造不存在的财务数据。\n\n"
                "第三部分：技术面与资金流向\n"
                "- 若有股价和成交数据，分析价格趋势、波动率、支撑压力位、量价关系与市场情绪。\n"
                "- 结合资金流向、换手率、投资者行为等行为金融特征分析。\n"
                "- 若缺乏技术数据，应明确说明技术面分析受限，并转从政策风险与市场情绪角度审慎分析。\n\n"
                "第四部分：风险评估与投资建议\n"
                "- 从市场、估值、财务、流动性、公司治理、政策、行业竞争等维度综合评估风险。\n"
                "- 给出明确的投资建议与仓位控制思路。\n"
                "- 必须强调风险控制和动态跟踪，不得给出绝对化、保证收益式表述。\n\n"
                "【语言风格要求】\n"
                "- 全文使用正式、专业、连续的中文自然段表述，每个部分写成完整分析段落。\n"
                "- 语言应具备研报风格，逻辑严谨，偏审慎、中性。\n\n"
                "【真实性与一致性要求】\n"
                "- 公司名称、股票代码、所属行业、板块、业务属性必须前后一致。\n"
                "- 禁止在没有数据支撑时虚构精确指标、具体价格、估值倍数或财务数字。\n"
                "- 若数据不足，必须明确写出“不足以支持进一步判断”或“需结合后续财报/公告验证”。\n\n"
                "【输出要求】\n"
                "- 直接输出最终报告正文（Markdown 格式），不要输出任何解释或引导语。\n\n"
                f"【补充信息】\n写作视角：{perspective}\n\n"
                f"【结构化数据摘要】\n{_json_block(compact_data)}\n\n"
                f"【结构化数据明细】\n{_truncate_text(_json_block(structured_data), 12000)}"
            ),
        },
    ]


def _build_judge_messages(
    stock_code: str,
    stock_name: str,
    report_type: str,
    structured_data: Dict[str, Any],
    report_text: str,
) -> List[Dict[str, str]]:
    compact_data = _summarize_structured_data(structured_data, report_type)
    return [
        {
            "role": "system",
            "content": (
                "你是金融研报评审员。请严格按评分标准输出 JSON，不要输出代码块。"
                "如果报告结构不符合要求、存在编造或结论过满，必须扣分。"
            ),
        },
        {
            "role": "user",
            "content": (
                f"请对以下 {stock_name}（{stock_code}）的{report_type}打分。\n"
                "评分维度满分均为 20 分，总分 100。输出必须是 JSON，字段如下：\n"
                "total_score, dimension_scores, strengths, weaknesses, revision_advice\n\n"
                "评分重点：\n"
                "1. 是否严格使用四个一级标题结构；\n"
                "2. 是否避免旧版摘要式、提纲式、多级编号式结构；\n"
                "3. 是否基于结构化数据写作且没有张冠李戴；\n"
                "4. 是否保持连续自然段、卖方研报风格和审慎合规表达。\n\n"
                f"目标章节结构：\n{EXPECTED_OUTLINE}\n\n"
                f"结构化数据摘要：\n{_json_block(compact_data)}\n\n"
                f"待评分报告：\n{report_text}"
            ),
        },
    ]


def _build_revision_messages(
    stock_code: str,
    stock_name: str,
    report_type: str,
    structured_data: Dict[str, Any],
    own_report: str,
    peer_report: str,
    judge_feedback: Dict[str, Any],
    perspective: str = "",
) -> List[Dict[str, str]]:
    compact_data = _summarize_structured_data(structured_data, report_type)
    debate_hint = ""
    if _debate_mode() == "adversarial" and perspective:
        debate_hint = (
            f"\n6. 你在本次辩论中的立场是：{perspective}\n"
            "修订时请正面回应对手稿件中与你立场相冲突的论点：要么用数据反驳，要么审慎吸收；"
            "不得无依据地放弃立场，也不得无视有据的反驳。最终报告仍须整体连贯、立场自洽。\n"
        )
    return [
        {
            "role": "system",
            "content": "你是金融研报修订助手。请吸收对手优点、修复自身缺点，但不得编造任何未提供的数据。",
        },
        {
            "role": "user",
            "content": (
                f"请修订你的{report_type}。\n"
                f"目标标题：# {stock_name}({stock_code})分析报告\n"
                f"目标章节结构：\n{EXPECTED_OUTLINE}\n\n"
                f"结构化数据摘要：\n{_json_block(compact_data)}\n\n"
                f"你的原稿：\n{own_report}\n\n"
                f"对手稿件：\n{peer_report}\n\n"
                f"评审反馈：\n{_json_block(judge_feedback)}\n\n"
                "要求：\n"
                "1. 保留 Markdown 报告形式；\n"
                "2. 严格使用四个一级标题，不得恢复旧版摘要/提纲结构；\n"
                "3. 每个部分写成完整分析段落，不要写成清单；\n"
                "4. 不能引入结构化数据中不存在的事实；\n"
                "5. 如果某部分数据不足，请明确说明口径限制。"
                f"{debate_hint}"
            ),
        },
    ]


def _extract_json_object(text: str) -> str:
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return ""
    return text[start : end + 1]


def _normalize_dimension_scores(scores: Any) -> Dict[str, int]:
    expected_keys = ["data_grounding", "logic", "clarity", "risk", "compliance"]
    raw_scores = scores if isinstance(scores, dict) else {}
    normalized: Dict[str, int] = {}
    for key in expected_keys:
        value = raw_scores.get(key, 0)
        try:
            score = int(round(float(value)))
        except Exception:
            score = 0
        normalized[key] = max(0, min(20, score))
    return normalized


def _ensure_list(value: Any) -> List[str]:
    if isinstance(value, list):
        return [str(item) for item in value[:8]]
    if value:
        return [str(value)]
    return []


def _parse_judge_result(text: str) -> Dict[str, Any]:
    cleaned = clean_markdown_output(text)
    payload: Any = {}
    try:
        payload = json.loads(cleaned)
    except Exception:
        extracted = _extract_json_object(cleaned)
        if extracted:
            try:
                payload = json.loads(extracted)
            except Exception:
                payload = {}

    if not isinstance(payload, dict):
        payload = {}

    dimension_scores = _normalize_dimension_scores(payload.get("dimension_scores", {}))
    computed_total = sum(dimension_scores.values())
    total_score = payload.get("total_score", computed_total)
    try:
        total_score = int(round(float(total_score)))
    except Exception:
        total_score = computed_total
    total_score = max(0, min(100, total_score))
    if abs(total_score - computed_total) > 8:
        total_score = computed_total

    fallback_message = cleaned if cleaned else "评审模型未返回有效 JSON"
    return {
        "total_score": total_score,
        "dimension_scores": dimension_scores,
        "strengths": _ensure_list(payload.get("strengths")),
        "weaknesses": _ensure_list(payload.get("weaknesses")) or [fallback_message],
        "revision_advice": _ensure_list(payload.get("revision_advice")),
        "raw_text": cleaned,
    }


def _fallback_score(report_text: str, reason: str) -> Dict[str, Any]:
    base_score = 60 if report_text.strip() else 0
    return {
        "total_score": base_score,
        "dimension_scores": {
            "data_grounding": 12 if report_text.strip() else 0,
            "logic": 12 if report_text.strip() else 0,
            "clarity": 12 if report_text.strip() else 0,
            "risk": 12 if report_text.strip() else 0,
            "compliance": 12 if report_text.strip() else 0,
        },
        "strengths": [],
        "weaknesses": [reason],
        "revision_advice": ["建议补充人工复核或重试模型生成"],
        "raw_text": reason,
    }


def _safe_generate(client: Any, messages: List[Dict[str, str]], fallback_text: str = "", **kwargs: Any) -> Dict[str, Any]:
    try:
        content = clean_markdown_output(client.generate(messages, **kwargs))
        return {"ok": bool(content.strip()), "content": content, "error": "" if content.strip() else "模型返回空内容"}
    except Exception as exc:
        return {"ok": False, "content": fallback_text, "error": str(exc)}


def _safe_judge(client: Any, messages: List[Dict[str, str]], report_text: str, **kwargs: Any) -> Dict[str, Any]:
    try:
        judged = client.generate(messages, **kwargs)
        return _parse_judge_result(judged)
    except Exception as exc:
        return _fallback_score(report_text, f"评审失败: {exc}")


def _fallback_stream_sections(
    stock_code: str,
    stock_name: str,
    report_type: str,
    structured_data: Dict[str, Any],
) -> List[str]:
    summary = _summarize_structured_data(structured_data, report_type)
    report_spec = _build_report_spec(report_type)
    return [
        f"# {stock_name}（{stock_code}）{report_spec['title']}\n\n",
        "## 1. 报告说明\n当前多模型生成链路不可用，以下内容为基于 AkShare 结构化数据自动整理的回退报告。\n\n",
        f"## 2. 结构化数据摘要\n```json\n{_json_block(summary)}\n```\n\n",
        "## 3. 核心观察\n- 已优先保留行情、估值、财务和行业快照等结构化信息。\n"
        "- 当前版本不包含完整的多模型辩论润色，因此结论性表达被主动收敛。\n"
        "- 若需要更完整报告，请稍后重试生成任务。\n\n",
        "## 4. 风险提示\n- 若 AkShare 某些字段缺失，则本报告对应部分也可能为空。\n"
        "- 本回退报告仅供参考，不构成个性化投资建议。\n",
    ]


REPORT_DISCLAIMER = (
    "\n\n---\n\n"
    "**免责声明**：本报告由人工智能基于公开市场数据自动生成，仅供技术研究与学习参考，"
    "可能存在错误、遗漏或过时信息，不构成任何证券投资建议。市场有风险，投资需谨慎，"
    "请自行核实相关数据与结论后审慎决策。\n"
)


def _write_debug_metadata(report_filename: str, payload: Dict[str, Any]) -> str:
    metadata_path = REPORT_META_DIR / f"{Path(report_filename).stem}.json"
    metadata_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    return str(metadata_path)


def _with_disclaimer(report_text: str) -> str:
    """为最终报告统一追加免责声明（合规要求，见 DISCLAIMER.md）。"""
    text = (report_text or "").rstrip()
    if "免责声明" in text[-200:]:
        return text
    return text + REPORT_DISCLAIMER


def generate_debated_report(
    stock_code: str,
    stock_name: str,
    report_type: str,
    status_callback: StatusCallback = None,
    stream_callback: StreamCallback = None,
    force_refresh: bool = False,
) -> Dict[str, Any]:
    """主入口：生成一份辩论式研报并写入 result/ 目录。"""
    report_type = normalize_report_type(report_type)

    _emit_status(status_callback, "抓取数据中", step="fetch_data", force_refresh=force_refresh)
    structured_data = build_stock_data_bundle(stock_code, stock_name, force_refresh=force_refresh)
    cache_info = structured_data.get("cache_info", {})
    _emit_stream(stream_callback, "status", message="已完成结构化数据抓取", step="fetch_data", cache_info=cache_info)

    generator_a = get_generator_a_client()
    generator_b = get_generator_b_client()
    judge = get_judge_client()

    # ---------- 第一轮：双稿生成 ----------
    _emit_status(status_callback, "生成初稿中", step="draft_generation")
    _emit_stream(stream_callback, "status", message="正在生成初稿", step="draft_generation")
    draft_a_v1_result = _safe_generate(
        generator_a,
        _build_generation_messages(stock_code, stock_name, report_type, structured_data, _debate_perspective("a")),
        temperature=0.35,
        max_tokens=5000,
        stream_callback=lambda chunk: _emit_stream(stream_callback, "draft_chunk", source="generator_a_v1", chunk=chunk),
    )
    draft_b_v1_result = _safe_generate(
        generator_b,
        _build_generation_messages(stock_code, stock_name, report_type, structured_data, _debate_perspective("b")),
        temperature=0.35,
        max_tokens=5000,
        stream_callback=lambda chunk: _emit_stream(stream_callback, "draft_chunk", source="generator_b_v1", chunk=chunk),
    )
    draft_a_v1 = draft_a_v1_result["content"]
    draft_b_v1 = draft_b_v1_result["content"]

    # ---------- 双稿均失败 → 结构化回退 ----------
    if not draft_a_v1 and not draft_b_v1:
        fallback_sections = _fallback_stream_sections(stock_code, stock_name, report_type, structured_data)
        for section in fallback_sections:
            _emit_stream(stream_callback, "report_chunk", source="structured_fallback", chunk=section)
        final_report = "".join(fallback_sections)
        report_path = config.RESULT_DIR / get_report_filename(stock_code, stock_name, report_type)
        report_path.write_text(_with_disclaimer(final_report), encoding="utf-8")
        report_filename = report_path.name
        fallback_info = {
            "draft_a_v1_error": draft_a_v1_result["error"],
            "draft_b_v1_error": draft_b_v1_result["error"],
            "report_mode": "structured_fallback",
        }
        debug_payload = {
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "stock_code": stock_code,
            "stock_name": stock_name,
            "report_type": report_type,
            "winner": "structured_fallback",
            "cache_info": cache_info,
            "fallback_info": fallback_info,
            "structured_data_summary": _summarize_structured_data(structured_data, report_type),
            "drafts": {},
            "scores": {},
        }
        metadata_path = _write_debug_metadata(report_filename, debug_payload)
        _emit_status(status_callback, "写入结果中", step="persist_result", winner="structured_fallback")
        _emit_stream(stream_callback, "complete", winner="structured_fallback", filename=report_filename, report_mode="structured_fallback")
        return {
            "sector": infer_sector(stock_code),
            "report_type": report_type,
            "report": final_report,
            "filename": report_filename,
            "analysis_date": structured_data["generated_at"],
            "source": "akshare_structured_fallback",
            "used_cache": bool(cache_info.get("used_cache")),
            "cache_info": cache_info,
            "report_path": str(report_path),
            "metadata_path": metadata_path,
            "winner": "structured_fallback",
            "final_score": _fallback_score(final_report, "双生成模型均失败"),
            "scoreboard": {},
            "fallback_info": fallback_info,
            "structured_data": structured_data,
            "structured_data_summary": _summarize_structured_data(structured_data, report_type),
            "report_slug": report_type_slug(report_type),
        }

    if not draft_a_v1:
        draft_a_v1 = draft_b_v1
    if not draft_b_v1:
        draft_b_v1 = draft_a_v1

    # ---------- 第一轮评审 ----------
    _emit_status(status_callback, "评审中", step="judge_round_1")
    _emit_stream(stream_callback, "status", message="初稿已生成，正在评审", step="judge_round_1")
    score_a_v1 = _safe_judge(
        judge,
        _build_judge_messages(stock_code, stock_name, report_type, structured_data, draft_a_v1),
        draft_a_v1,
        temperature=0.1,
        max_tokens=1800,
    )
    score_b_v1 = _safe_judge(
        judge,
        _build_judge_messages(stock_code, stock_name, report_type, structured_data, draft_b_v1),
        draft_b_v1,
        temperature=0.1,
        max_tokens=1800,
    )

    # ---------- 第二轮：辩论修订 ----------
    _emit_status(status_callback, "辩论修订中", step="revision_round")
    _emit_stream(stream_callback, "status", message="正在进行修订与二次生成", step="revision_round")
    draft_a_v2_result = _safe_generate(
        generator_a,
        _build_revision_messages(
            stock_code, stock_name, report_type, structured_data,
            draft_a_v1, draft_b_v1, score_a_v1, perspective=_debate_perspective("a"),
        ),
        fallback_text=draft_a_v1,
        temperature=0.35,
        max_tokens=5000,
        stream_callback=lambda chunk: _emit_stream(stream_callback, "draft_chunk", source="generator_a_v2", chunk=chunk),
    )
    draft_b_v2_result = _safe_generate(
        generator_b,
        _build_revision_messages(
            stock_code, stock_name, report_type, structured_data,
            draft_b_v1, draft_a_v1, score_b_v1, perspective=_debate_perspective("b"),
        ),
        fallback_text=draft_b_v1,
        temperature=0.35,
        max_tokens=5000,
        stream_callback=lambda chunk: _emit_stream(stream_callback, "draft_chunk", source="generator_b_v2", chunk=chunk),
    )
    draft_a_v2 = draft_a_v2_result["content"] or draft_a_v1
    draft_b_v2 = draft_b_v2_result["content"] or draft_b_v1

    # ---------- 最终评审与选优 ----------
    _emit_status(status_callback, "最终评分中", step="judge_round_2")
    _emit_stream(stream_callback, "status", message="修订完成，正在选择最终版本", step="judge_round_2")
    score_a_v2 = _safe_judge(
        judge,
        _build_judge_messages(stock_code, stock_name, report_type, structured_data, draft_a_v2),
        draft_a_v2,
        temperature=0.1,
        max_tokens=1800,
    )
    score_b_v2 = _safe_judge(
        judge,
        _build_judge_messages(stock_code, stock_name, report_type, structured_data, draft_b_v2),
        draft_b_v2,
        temperature=0.1,
        max_tokens=1800,
    )

    final_report = draft_a_v2
    winner = "generator_a"
    final_score = score_a_v2
    if score_b_v2.get("total_score", 0) > score_a_v2.get("total_score", 0):
        final_report = draft_b_v2
        winner = "generator_b"
        final_score = score_b_v2

    config.RESULT_DIR.mkdir(exist_ok=True)
    report_path = config.RESULT_DIR / get_report_filename(stock_code, stock_name, report_type)
    report_path.write_text(_with_disclaimer(final_report), encoding="utf-8")
    report_filename = report_path.name
    _emit_stream(stream_callback, "report_chunk", source=winner, chunk=final_report)

    fallback_info = {
        "draft_a_v1_error": draft_a_v1_result["error"],
        "draft_b_v1_error": draft_b_v1_result["error"],
        "draft_a_v2_error": draft_a_v2_result["error"],
        "draft_b_v2_error": draft_b_v2_result["error"],
    }
    debug_payload = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "stock_code": stock_code,
        "stock_name": stock_name,
        "report_type": report_type,
        "debate_mode": _debate_mode(),
        "winner": winner,
        "cache_info": cache_info,
        "fallback_info": fallback_info,
        "structured_data_summary": _summarize_structured_data(structured_data, report_type),
        "drafts": {
            "draft_a_v1": draft_a_v1,
            "draft_b_v1": draft_b_v1,
            "draft_a_v2": draft_a_v2,
            "draft_b_v2": draft_b_v2,
        },
        "scores": {
            "draft_a_v1": score_a_v1,
            "draft_b_v1": score_b_v1,
            "draft_a_v2": score_a_v2,
            "draft_b_v2": score_b_v2,
        },
    }
    metadata_path = _write_debug_metadata(report_filename, debug_payload)

    _emit_status(status_callback, "写入结果中", step="persist_result", winner=winner)
    _emit_stream(stream_callback, "complete", winner=winner, filename=report_filename, report_mode="full_report")

    return {
        "sector": infer_sector(stock_code),
        "report_type": report_type,
        "debate_mode": _debate_mode(),
        "report": final_report,
        "filename": report_filename,
        "analysis_date": structured_data["generated_at"],
        "source": "akshare_multi_llm_debate",
        "used_cache": bool(cache_info.get("used_cache")),
        "cache_info": cache_info,
        "report_path": str(report_path),
        "metadata_path": metadata_path,
        "winner": winner,
        "final_score": final_score,
        "scoreboard": {
            "draft_a_v1": score_a_v1,
            "draft_b_v1": score_b_v1,
            "draft_a_v2": score_a_v2,
            "draft_b_v2": score_b_v2,
        },
        "fallback_info": fallback_info,
        "structured_data": structured_data,
        "structured_data_summary": _summarize_structured_data(structured_data, report_type),
        "report_slug": report_type_slug(report_type),
    }
