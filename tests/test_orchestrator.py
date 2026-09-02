"""辩论编排器单元测试（mock LLM 客户端与数据抓取）。"""
import pytest

from finsight.services import orchestrator
from finsight.services.report_specs import (
    infer_sector,
    normalize_report_type,
    report_type_slug,
)


def test_infer_sector():
    assert infer_sector("600519") == "主板"
    assert infer_sector("688981") == "科创板"
    assert infer_sector("300750") == "创业板"
    assert infer_sector("000858") == "深市主板"
    assert infer_sector("830799") == "北交所"


def test_report_type_slug():
    assert report_type_slug("股票分析报告") == "stock_analysis"
    assert report_type_slug("前景分析") == "prospect_analysis"
    assert report_type_slug("风险预测") == "risk_forecast"
    assert report_type_slug("行业市场分析") == "industry_market"


def test_normalize_report_type_fallback():
    assert normalize_report_type("不存在的类型") == "股票分析报告"


def test_parse_judge_result_valid_json():
    payload = (
        '{"total_score": 85, '
        '"dimension_scores": {"data_grounding": 18, "logic": 17, "clarity": 17, "risk": 16, "compliance": 17}, '
        '"strengths": ["结构完整"], "weaknesses": [], "revision_advice": []}'
    )
    result = orchestrator._parse_judge_result(payload)
    assert result["total_score"] == 85
    assert result["dimension_scores"]["data_grounding"] == 18


def test_parse_judge_result_wrapped_in_codeblock():
    payload = '```json\n{"total_score": 70, "dimension_scores": {"data_grounding": 14}}\n```'
    result = orchestrator._parse_judge_result(payload)
    # dimension_scores 缺失维度按 0 计，总分与维度和差异>8 时以维度和为准
    assert result["total_score"] == 14
    assert result["dimension_scores"]["logic"] == 0


def test_parse_judge_result_garbage():
    result = orchestrator._parse_judge_result("这不是JSON")
    assert result["total_score"] == 0
    assert result["weaknesses"]


def test_dimension_score_clamping():
    assert orchestrator._normalize_dimension_scores({"data_grounding": 99})["data_grounding"] == 20
    assert orchestrator._normalize_dimension_scores({"data_grounding": -5})["data_grounding"] == 0


class FakeClient:
    """模拟 OpenAI 兼容客户端。"""

    def __init__(self, response: str):
        self.response = response
        self.calls = 0

    def generate(self, messages, **kwargs):
        self.calls += 1
        if self.response is None:
            raise RuntimeError("mock failure")
        return self.response


def test_generate_debated_report_full_flow(monkeypatch, tmp_path):
    fake_report = (
        "# 贵州茅台(600519)分析报告\n\n"
        "# 一、宏观经济与行业分析\n内容。\n\n"
        "# 二、财务指标深度解析\n内容。\n\n"
        "# 三、技术面与资金流向\n内容。\n\n"
        "# 四、风险评估与投资建议\n内容。\n"
    )
    fake_judge_json = (
        '{"total_score": 80, '
        '"dimension_scores": {"data_grounding": 16, "logic": 16, "clarity": 16, "risk": 16, "compliance": 16}, '
        '"strengths": [], "weaknesses": [], "revision_advice": []}'
    )

    monkeypatch.setattr(
        orchestrator,
        "build_stock_data_bundle",
        lambda *a, **k: {"stock": {}, "generated_at": "2026-01-01 00:00:00", "cache_info": {}},
    )
    monkeypatch.setattr(orchestrator, "get_generator_a_client", lambda: FakeClient(fake_report))
    monkeypatch.setattr(orchestrator, "get_generator_b_client", lambda: FakeClient(fake_report))
    monkeypatch.setattr(orchestrator, "get_judge_client", lambda: FakeClient(fake_judge_json))
    # 输出目录重定向到临时目录
    monkeypatch.setattr(orchestrator, "REPORT_META_DIR", tmp_path)

    events = []
    result = orchestrator.generate_debated_report(
        stock_code="600519",
        stock_name="贵州茅台",
        report_type="股票分析报告",
        stream_callback=lambda event, details=None: events.append(event),
    )

    assert result["winner"] in ("generator_a", "generator_b")
    assert result["final_score"]["total_score"] == 80
    assert result["source"] == "akshare_multi_llm_debate"
    assert "report_chunk" in events and "complete" in events


def test_generate_debated_report_fallback(monkeypatch, tmp_path):
    """双生成器失败时应走结构化回退。"""

    monkeypatch.setattr(
        orchestrator,
        "build_stock_data_bundle",
        lambda *a, **k: {"stock": {}, "generated_at": "2026-01-01 00:00:00", "cache_info": {}},
    )
    monkeypatch.setattr(orchestrator, "get_generator_a_client", lambda: FakeClient(None))
    monkeypatch.setattr(orchestrator, "get_generator_b_client", lambda: FakeClient(None))
    monkeypatch.setattr(orchestrator, "get_judge_client", lambda: FakeClient(None))
    monkeypatch.setattr(orchestrator, "REPORT_META_DIR", tmp_path)

    result = orchestrator.generate_debated_report(
        stock_code="600519",
        stock_name="贵州茅台",
        report_type="股票分析报告",
    )

    assert result["winner"] == "structured_fallback"
    assert "回退报告" in result["report"]
