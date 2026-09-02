"""报告追问路由：流式问答 / 普通问答。"""
import json
import logging
import threading
import time
from collections import deque
from pathlib import Path

from flask import Blueprint, Response, jsonify, request, session

from finsight.services.qa_engine import answer_user_question

logger = logging.getLogger(__name__)

qa_bp = Blueprint("qa", __name__)


def _login_required():
    return "user_id" in session


def _result_dir() -> Path:
    return Path(__file__).resolve().parents[2] / "result"


def _load_report_content(report_filename: str) -> str:
    if not report_filename or "../" in report_filename or "\\" in report_filename:
        raise ValueError("无效的文件名")
    report_path = _result_dir() / report_filename
    if not report_path.exists():
        raise FileNotFoundError("报告不存在")
    return report_path.read_text(encoding="utf-8")


@qa_bp.route("/ask_question", methods=["POST"])
def ask_question_route():
    if not _login_required():
        return jsonify({"error": "未登录"}), 401

    data = request.get_json(silent=True) or {}
    question = (data.get("question") or "").strip()
    report_filename = (data.get("report_filename") or "").strip()
    conversation_history = data.get("conversation_history") or []

    if not question or not report_filename:
        return jsonify({"error": "参数不完整"}), 400

    try:
        report_content = _load_report_content(report_filename)
        answer = answer_user_question(
            question=question,
            report_filename=report_filename,
            report_content=report_content,
            conversation_history=conversation_history,
        )
        return jsonify(answer)
    except FileNotFoundError as exc:
        return jsonify({"error": str(exc)}), 404
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:  # noqa: BLE001
        logger.error("问答失败: %s", exc)
        logger.exception(exc)
        return jsonify({"error": str(exc)}), 500


@qa_bp.route("/ask_question_stream")
def ask_question_stream_route():
    if not _login_required():
        return jsonify({"error": "未登录"}), 401

    question = request.args.get("question", "").strip()
    report_filename = request.args.get("report_filename", "").strip()
    conversation_history_raw = request.args.get("conversation_history", "[]")

    try:
        conversation_history = json.loads(conversation_history_raw) if conversation_history_raw else []
    except Exception:  # noqa: BLE001
        conversation_history = []

    if not question or not report_filename:
        return jsonify({"error": "参数不完整"}), 400

    try:
        report_content = _load_report_content(report_filename)
    except FileNotFoundError:
        return jsonify({"error": "报告不存在"}), 404
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    def event_stream():
        try:
            yield f"data: {json.dumps({'event': 'status', 'message': '已启动问答流式输出'}, ensure_ascii=False)}\n\n"

            queue: deque = deque()
            done = {"value": False, "result": None, "error": None}

            def qa_stream_callback(event: str, details: dict | None = None):
                payload = {"event": event}
                if details:
                    payload.update(details)
                queue.append(json.dumps(payload, ensure_ascii=False))

            def worker():
                try:
                    done["result"] = answer_user_question(
                        question=question,
                        report_filename=report_filename,
                        report_content=report_content,
                        conversation_history=conversation_history,
                        stream_callback=qa_stream_callback,
                    )
                except Exception as exc:  # noqa: BLE001
                    done["error"] = exc
                finally:
                    done["value"] = True

            threading.Thread(target=worker, daemon=True).start()

            while not done["value"] or queue:
                while queue:
                    yield f"data: {queue.popleft()}\n\n"
                if not done["value"]:
                    time.sleep(0.03)

            if done["error"]:
                raise done["error"]

            yield f"data: {json.dumps({'event': 'result', **(done['result'] or {})}, ensure_ascii=False)}\n\n"
        except Exception as exc:  # noqa: BLE001
            logger.error("问答流式输出失败: %s", exc)
            logger.exception(exc)
            yield f"data: {json.dumps({'event': 'error', 'error': str(exc)}, ensure_ascii=False)}\n\n"

    return Response(event_stream(), mimetype="text/event-stream")
