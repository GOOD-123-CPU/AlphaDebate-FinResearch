"""研报生成路由：流式生成 / 任务队列生成 / 任务状态 / 报告读取 / 元数据。"""
import json
import logging
import threading
import time
import uuid
from collections import deque
from pathlib import Path

from flask import Blueprint, Response, jsonify, redirect, render_template, request, session, url_for

from finsight.extensions import db
from finsight.models import Task
from finsight.services.data_bundle import fetch_stock_history, fetch_stock_spot, search_stocks
from finsight.services.orchestrator import generate_debated_report
from finsight.services.report_specs import report_type_slug

logger = logging.getLogger(__name__)

report_bp = Blueprint("report", __name__)


def _login_required():
    return "user_id" in session


def _safe_filename(filename: str) -> bool:
    return bool(filename) and "../" not in filename and "\\" not in filename


def _result_dir() -> Path:
    return Path(__file__).resolve().parents[2] / "result"


@report_bp.route("/chat")
def chat():
    if not _login_required():
        return redirect(url_for("auth.login"))
    return render_template("chat.html")


@report_bp.route("/generate_report_stream")
def generate_report_stream():
    """SSE 流式生成研报（前端主入口）。"""
    if not _login_required():
        return jsonify({"error": "未登录"}), 401

    stock_code = request.args.get("stock_code", "").strip()
    company_name = request.args.get("company_name", "").strip()
    report_type = request.args.get("report_type", "").strip()
    force_refresh = request.args.get("force_refresh", "").strip().lower() in {"1", "true", "yes"}

    if not stock_code or not company_name or not report_type:
        return jsonify({"error": "参数不完整"}), 400

    def event_stream():
        try:
            yield f"data: {json.dumps({'event': 'status', 'message': '已启动流式生成'}, ensure_ascii=False)}\n\n"

            queue: deque = deque()
            done = {"value": False, "error": None, "result": None}

            def orchestrator_stream_callback(event: str, details: dict | None = None):
                payload = {"event": event}
                if details:
                    payload.update(details)
                queue.append(json.dumps(payload, ensure_ascii=False))

            def run():
                try:
                    done["result"] = generate_debated_report(
                        stock_code=stock_code,
                        stock_name=company_name,
                        report_type=report_type,
                        stream_callback=orchestrator_stream_callback,
                        force_refresh=force_refresh,
                    )
                except Exception as exc:  # noqa: BLE001
                    done["error"] = exc
                finally:
                    done["value"] = True

            threading.Thread(target=run, daemon=True).start()

            while not done["value"] or queue:
                while queue:
                    yield f"data: {queue.popleft()}\n\n"
                if not done["value"]:
                    time.sleep(0.03)

            if done["error"]:
                raise done["error"]

            generation_result = done["result"]
            final_payload = {
                "event": "result",
                "filename": generation_result["filename"],
                "report": generation_result.get("report", ""),
                "report_type": report_type,
                "report_slug": report_type_slug(report_type),
                "company_name": company_name,
                "stock_code": stock_code,
                "source": generation_result.get("source"),
                "winner": generation_result.get("winner"),
                "final_score": generation_result.get("final_score"),
                "used_cache": generation_result.get("used_cache", False),
                "cache_info": generation_result.get("cache_info", {}),
                "metadata_path": generation_result.get("metadata_path"),
                "structured_data_summary": generation_result.get("structured_data_summary", {}),
                "scoreboard": generation_result.get("scoreboard", {}),
                "fallback_info": generation_result.get("fallback_info", {}),
            }
            yield f"data: {json.dumps(final_payload, ensure_ascii=False)}\n\n"
        except Exception as exc:  # noqa: BLE001
            logger.error("流式生成研报失败: %s", exc)
            logger.exception(exc)
            yield f"data: {json.dumps({'event': 'error', 'error': str(exc)}, ensure_ascii=False)}\n\n"

    return Response(event_stream(), mimetype="text/event-stream")


@report_bp.route("/generate_report", methods=["POST"])
def generate_report_route():
    """非流式生成（任务队列模式）。"""
    if not _login_required():
        return jsonify({"error": "未登录"}), 401

    data = request.get_json(silent=True) or {}
    stock_code = (data.get("stock_code") or "").strip()
    company_name = (data.get("company_name") or "").strip()
    report_type = (data.get("report_type") or "").strip()
    force_refresh = bool(data.get("force_refresh"))

    if not stock_code or not company_name or not report_type:
        return jsonify({"error": "参数不完整"}), 400

    task_id = str(uuid.uuid4())
    new_task = Task(id=task_id, status="处理中")
    db.session.add(new_task)
    db.session.commit()

    def update_task_status(status: str, details: dict | None = None):
        with db.session.no_autoflush:
            task = db.session.get(Task, task_id)
            if task:
                task.status = status
                if details:
                    task.result = json.dumps({"progress": details}, ensure_ascii=False)
                db.session.commit()

    def worker():
        try:
            generation_result = generate_debated_report(
                stock_code=stock_code,
                stock_name=company_name,
                report_type=report_type,
                status_callback=update_task_status,
                force_refresh=force_refresh,
            )
            response_data = {
                "filename": generation_result["filename"],
                "path": generation_result["report_path"],
                "report_type": report_type,
                "report_slug": report_type_slug(report_type),
                "company_name": company_name,
                "stock_code": stock_code,
                "source": generation_result.get("source"),
                "winner": generation_result.get("winner"),
                "final_score": generation_result.get("final_score"),
                "used_cache": generation_result.get("used_cache", False),
                "cache_info": generation_result.get("cache_info", {}),
                "metadata_path": generation_result.get("metadata_path"),
                "structured_data_summary": generation_result.get("structured_data_summary", {}),
                "scoreboard": generation_result.get("scoreboard", {}),
                "fallback_info": generation_result.get("fallback_info", {}),
            }
            with db.session.no_autoflush:
                task = db.session.get(Task, task_id)
                if task:
                    task.status = "完成"
                    task.result = json.dumps(response_data, ensure_ascii=False)
                    db.session.commit()
        except Exception as exc:  # noqa: BLE001
            logger.error("生成研报失败: %s", exc)
            logger.exception(exc)
            with db.session.no_autoflush:
                task = db.session.get(Task, task_id)
                if task:
                    task.status = "失败"
                    task.result = json.dumps({"error": str(exc)}, ensure_ascii=False)
                    db.session.commit()

    threading.Thread(target=worker, daemon=True).start()
    return jsonify({"task_id": task_id})


@report_bp.route("/report_status/<task_id>")
def report_status(task_id):
    if not _login_required():
        return jsonify({"error": "未登录"}), 401

    task = db.session.get(Task, task_id)
    if not task:
        return jsonify({"error": "任务不存在"}), 404

    payload = {"task_id": task.id, "status": task.status}
    if task.result:
        try:
            payload["result"] = json.loads(task.result)
        except json.JSONDecodeError:
            payload["result"] = task.result
    return jsonify(payload)


@report_bp.route("/read_report/<path:filename>")
def read_report(filename):
    if not _login_required():
        return jsonify({"error": "未登录"}), 401
    if not _safe_filename(filename):
        return jsonify({"error": "无效的文件名"}), 400

    report_path = _result_dir() / filename
    if not report_path.exists():
        return jsonify({"error": "报告不存在"}), 404

    try:
        markdown_content = report_path.read_text(encoding="utf-8")
        return jsonify({
            "filename": filename,
            "content": markdown_content,
            "created_at": time.ctime(report_path.stat().st_ctime),
        })
    except Exception as exc:  # noqa: BLE001
        logger.error("读取报告文件失败: %s", exc)
        return jsonify({"error": f"读取报告失败: {exc}"}), 500


@report_bp.route("/search_stocks")
def search_stocks_route():
    """全市场 A 股代码/名称模糊搜索（沪+深+北）。"""
    if not _login_required():
        return jsonify({"error": "未登录"}), 401
    keyword = request.args.get("keyword", "").strip()
    limit = min(int(request.args.get("limit", 20) or 20), 50)
    try:
        result = search_stocks(keyword, limit=limit)
        return jsonify(result)
    except Exception as exc:  # noqa: BLE001
        logger.error("股票搜索失败: %s", exc)
        return jsonify({"error": f"搜索失败: {exc}"}), 500


@report_bp.route("/stock_quote")
def stock_quote_route():
    """实时行情快照（供搜索选中后回显价格/涨跌幅）。"""
    if not _login_required():
        return jsonify({"error": "未登录"}), 401
    stock_code = request.args.get("stock_code", "").strip()
    if not stock_code:
        return jsonify({"error": "参数不完整"}), 400
    try:
        spot = fetch_stock_spot(stock_code)
        return jsonify({"success": True, "spot": spot})
    except Exception as exc:  # noqa: BLE001
        logger.error("获取行情失败(%s): %s", stock_code, exc)
        return jsonify({"success": False, "error": f"获取行情失败: {exc}"}), 502


@report_bp.route("/stock_chart_data")
def stock_chart_data_route():
    """近 30 个交易日的 K 线/收盘价数据（供 ECharts 行情图渲染）。"""
    if not _login_required():
        return jsonify({"error": "未登录"}), 401
    stock_code = request.args.get("stock_code", "").strip()
    if not stock_code:
        return jsonify({"error": "参数不完整"}), 400
    try:
        history = fetch_stock_history(stock_code, days=60)
        records = history.get("records", [])[-30:]
        dates = [str(r.get("日期", "")) for r in records]
        kline = [[r.get("开盘"), r.get("收盘"), r.get("最低"), r.get("最高")] for r in records]
        volumes = [r.get("成交量") for r in records]
        closes = [r.get("收盘") for r in records]
        return jsonify({
            "success": True,
            "stock_code": stock_code,
            "dates": dates,
            "kline": kline,
            "volumes": volumes,
            "closes": closes,
            "summary": history.get("summary", {}),
        })
    except Exception as exc:  # noqa: BLE001
        logger.error("获取图表数据失败(%s): %s", stock_code, exc)
        return jsonify({"success": False, "error": f"获取图表数据失败: {exc}"}), 502


@report_bp.route("/report_list")
def report_list_route():
    """历史报告中心：列出 result/ 目录下全部已生成报告及其评分。"""
    if not _login_required():
        return jsonify({"error": "未登录"}), 401

    result_dir = _result_dir()
    if not result_dir.exists():
        return jsonify({"reports": []})

    reports = []
    for md_path in sorted(result_dir.glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True):
        if not _safe_filename(md_path.name):
            continue
        item = {
            "filename": md_path.name,
            "size": md_path.stat().st_size,
            "created_at": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(md_path.stat().st_mtime)),
        }
        # 尝试读取配套元数据里的评分与胜者
        meta_path = result_dir / "metadata" / f"{md_path.stem}.json"
        if meta_path.exists():
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
                item["stock_code"] = meta.get("stock_code", "")
                item["stock_name"] = meta.get("stock_name", "")
                item["report_type"] = meta.get("report_type", "")
                item["winner"] = meta.get("winner", "")
                item["debate_mode"] = meta.get("debate_mode", "")
                scores = meta.get("scores", {})
                final_key = "draft_a_v2" if meta.get("winner") == "generator_a" else "draft_b_v2"
                final_score = scores.get(final_key, {})
                if meta.get("winner") == "structured_fallback":
                    final_score = {}
                item["total_score"] = final_score.get("total_score")
            except Exception:  # noqa: BLE001
                pass
        reports.append(item)

    return jsonify({"reports": reports[:100]})


@report_bp.route("/report_metadata/<path:filename>")
def report_metadata(filename):
    if not _login_required():
        return jsonify({"error": "未登录"}), 401
    if not _safe_filename(filename):
        return jsonify({"error": "无效的文件名"}), 400

    metadata_filename = f"{Path(filename).stem}.json"
    metadata_path = _result_dir() / "metadata" / metadata_filename
    if not metadata_path.exists():
        return jsonify({"error": "报告元数据不存在"}), 404

    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        return jsonify({
            "filename": filename,
            "metadata_filename": metadata_filename,
            "metadata": metadata,
        })
    except Exception as exc:  # noqa: BLE001
        logger.error("读取报告元数据失败: %s", exc)
        return jsonify({"error": f"读取报告元数据失败: {exc}"}), 500
