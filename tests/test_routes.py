"""路由冒烟测试（不依赖真实 LLM / AkShare）。

运行：pytest tests/ -v
"""
import pytest

from finsight import create_app
from finsight.extensions import db


@pytest.fixture()
def app(tmp_path, monkeypatch):
    # 隔离数据库到临时目录
    monkeypatch.setenv("SECRET_KEY", "test-secret")
    app = create_app()
    app.config["TESTING"] = True
    yield app


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def logged_in_client(app, client):
    with app.app_context():
        from werkzeug.security import generate_password_hash

        from finsight.models import User

        if not User.query.filter_by(username="tester").first():
            db.session.add(User(username="tester", password=generate_password_hash("test1234")))
            db.session.commit()

    resp = client.post(
        "/login",
        data={"username": "tester", "password": "test1234"},
        follow_redirects=False,
    )
    assert resp.status_code in (200, 302)
    return client


def test_login_page(client):
    resp = client.get("/login")
    assert resp.status_code == 200


def test_register_and_login(client):
    import uuid

    username = f"user_{uuid.uuid4().hex[:8]}"
    resp = client.post(
        "/register",
        data={"username": username, "password": "pass123", "confirmPassword": "pass123"},
        follow_redirects=False,
    )
    assert resp.status_code == 302

    resp = client.post(
        "/login",
        data={"username": username, "password": "pass123"},
        follow_redirects=False,
    )
    assert resp.status_code == 302


def test_chat_requires_login(client):
    resp = client.get("/chat", follow_redirects=False)
    assert resp.status_code == 302


def test_generate_stream_requires_login(client):
    resp = client.get("/generate_report_stream?stock_code=600519&company_name=贵州茅台&report_type=股票分析报告")
    assert resp.status_code == 401


def test_read_report_rejects_traversal(logged_in_client):
    resp = logged_in_client.get("/read_report/..%2f..%2fetc/passwd")
    assert resp.status_code in (400, 404)


def test_report_status_unknown_task(logged_in_client):
    resp = logged_in_client.get("/report_status/nonexistent-id")
    assert resp.status_code == 404


# ---------- 深度升级新增路由测试 ----------

def test_report_list_empty(logged_in_client):
    resp = logged_in_client.get("/report_list")
    assert resp.status_code == 200
    data = resp.get_json()
    assert "reports" in data


def test_report_list_requires_login(client):
    resp = client.get("/report_list")
    assert resp.status_code == 401


def test_search_stocks_requires_login(client):
    resp = client.get("/search_stocks?keyword=600519")
    assert resp.status_code == 401


def test_search_stocks_empty_keyword(logged_in_client):
    resp = logged_in_client.get("/search_stocks?keyword=")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["results"] == []


def test_stock_chart_data_requires_params(logged_in_client):
    resp = logged_in_client.get("/stock_chart_data")
    assert resp.status_code == 400


def test_stock_quote_requires_params(logged_in_client):
    resp = logged_in_client.get("/stock_quote")
    assert resp.status_code == 400


def test_debate_mode_config_default():
    from finsight.config import config

    assert config.DEBATE_MODE in {"adversarial", "parallel"}
    assert isinstance(config.LLM_STREAM, bool)


def test_debate_perspectives_defined():
    from finsight.services.orchestrator import DEBATE_PERSPECTIVES, _debate_mode, _debate_perspective

    assert set(DEBATE_PERSPECTIVES.keys()) == {"adversarial", "parallel"}
    assert _debate_mode() in {"adversarial", "parallel"}
    assert _debate_perspective("a")
    assert _debate_perspective("b")


def test_llm_client_stream_flag():
    from finsight.services.llm_clients import OpenAICompatClient

    client = OpenAICompatClient("http://example.invalid/v1", "key", "model", stream_enabled=False)
    assert client.stream_enabled is False


def test_with_disclaimer_appends_footer():
    from finsight.services.orchestrator import _with_disclaimer

    report = "# 测试报告\n\n正文内容"
    result = _with_disclaimer(report)
    assert "免责声明" in result
    assert result.startswith("# 测试报告")


def test_with_disclaimer_no_duplicate():
    from finsight.services.orchestrator import _with_disclaimer

    report = "# 报告\n\n**免责声明**：本报告由人工智能生成，仅供参考。"
    result = _with_disclaimer(report)
    assert result.count("免责声明") == 1
