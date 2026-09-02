"""报告追问问答引擎：基于已生成报告 + LLM 能力进行流式回答。"""
import json
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from finsight.services.llm_clients import get_generator_a_client
from finsight.services.report_specs import clean_markdown_output

StreamCallback = Optional[Callable[[str, Dict[str, Any]], None]]


def parse_report_filename(report_filename: str) -> Dict[str, str]:
    stem = Path(report_filename).stem
    parts = stem.split("_")
    if len(parts) < 3:
        return {"stock_code": "", "stock_name": "", "report_type_slug": ""}
    return {
        "stock_code": parts[0],
        "stock_name": parts[1],
        "report_type_slug": "_".join(parts[2:]),
    }


def _emit_stream(callback: StreamCallback, event: str, **details: Any) -> None:
    if callback:
        callback(event, details)


def _build_question_messages(
    question: str,
    stock_code: str,
    stock_name: str,
    report_content: str,
    conversation_history: Optional[List[Dict[str, str]]] = None,
) -> List[Dict[str, str]]:
    conversation_history = conversation_history or []
    return [
        {
            "role": "system",
            "content": (
                "你是中文金融问答助手。"
                "回答时直接基于大模型联网搜索与已生成报告内容进行整合分析。"
                "不要使用 AkShare 结构化数据作为依据。"
                "必须优先给出清晰结论，并显式区分‘报告已有信息’与‘联网补充信息’。"
                "若联网信息不足或无法确认，请明确说明不确定性，但表达要自然、专业。"
                "涉及投资建议时保持审慎、合规，不得作出确定性收益承诺。"
            ),
        },
        {
            "role": "system",
            "content": (
                f"当前股票：{stock_name}（{stock_code}）。\n\n"
                f"当前可参考报告：\n{report_content[:12000]}\n\n"
                "请结合你的联网搜索能力回答用户问题，并尽量引用最新动态、行业信息、公司公告或新闻线索。"
            ),
        },
        *[
            {"role": item.get("role", "user"), "content": item.get("content", "").strip()}
            for item in conversation_history[-10:]
            if item.get("content", "").strip() and item.get("role") != "system"
        ],
        {"role": "user", "content": question},
    ]


def _safe_generate_answer(
    client: Any,
    messages: List[Dict[str, str]],
    stream_callback: StreamCallback = None,
) -> Dict[str, Any]:
    try:
        content = clean_markdown_output(
            client.generate(
                messages,
                temperature=0.3,
                max_tokens=1800,
                stream_callback=(
                    lambda chunk: _emit_stream(stream_callback, "answer_chunk", chunk=chunk)
                )
                if stream_callback
                else None,
            )
        )
        return {"ok": bool(content.strip()), "content": content, "error": "" if content.strip() else "模型返回空内容"}
    except Exception as exc:
        return {"ok": False, "content": "", "error": str(exc)}


def _report_only_answer(question: str, report_content: str) -> str:
    excerpt = report_content[:4000] if report_content else "当前无可用报告内容。"
    return (
        "当前无法完成联网增强问答，以下为基于现有报告内容的回退回答。\n\n"
        f"你的问题：{question}\n\n"
        f"可参考报告摘要/片段：\n{excerpt}\n\n"
        "建议：如需更准确回答，请稍后重试，或基于报告中的具体章节继续提问。"
    )


def answer_user_question(
    question: str,
    report_filename: str,
    report_content: str,
    conversation_history: Optional[List[Dict[str, str]]] = None,
    stream_callback: StreamCallback = None,
) -> Dict[str, Any]:
    meta = parse_report_filename(report_filename)
    stock_code = meta["stock_code"]
    stock_name = meta["stock_name"]
    if not stock_code:
        raise ValueError("无法从报告文件名解析股票代码")

    _emit_stream(stream_callback, "status", message="正在联网检索并生成回答")
    client = get_generator_a_client()
    primary = _safe_generate_answer(
        client,
        _build_question_messages(
            question=question,
            stock_code=stock_code,
            stock_name=stock_name,
            report_content=report_content,
            conversation_history=conversation_history,
        ),
        stream_callback=stream_callback,
    )

    fallback_mode = "none"
    answer = primary["content"]
    if not primary["ok"]:
        answer = _report_only_answer(question, report_content)
        fallback_mode = "report_only"
        _emit_stream(stream_callback, "answer_chunk", chunk=answer)

    _emit_stream(stream_callback, "complete", fallback_mode=fallback_mode)
    return {
        "answer": answer,
        "used_report": bool(report_content),
        "used_structured_data": False,
        "source": "llm_websearch_qa",
        "stock_code": stock_code,
        "stock_name": stock_name,
        "fallback_mode": fallback_mode,
        "fallback_reason": primary["error"],
    }
