"""问答引擎单元测试（mock LLM 客户端）。"""
import pytest

from finsight.services import qa_engine


class FakeClient:
    def __init__(self, response):
        self.response = response

    def generate(self, messages, **kwargs):
        if self.response is None:
            raise RuntimeError("mock failure")
        return self.response


def test_parse_report_filename():
    meta = qa_engine.parse_report_filename("600519.SS_贵州茅台_stock_analysis.md")
    assert meta["stock_code"] == "600519.SS"
    assert meta["stock_name"] == "贵州茅台"
    assert meta["report_type_slug"] == "stock_analysis"


def test_parse_report_filename_invalid():
    meta = qa_engine.parse_report_filename("badname.md")
    assert meta["stock_code"] == ""


def test_answer_success(monkeypatch):
    monkeypatch.setattr(qa_engine, "get_generator_a_client", lambda: FakeClient("回答内容"))
    result = qa_engine.answer_user_question(
        question="公司基本面如何？",
        report_filename="600519.SS_贵州茅台_stock_analysis.md",
        report_content="报告内容……",
    )
    assert result["answer"] == "回答内容"
    assert result["fallback_mode"] == "none"


def test_answer_fallback_to_report(monkeypatch):
    monkeypatch.setattr(qa_engine, "get_generator_a_client", lambda: FakeClient(None))
    result = qa_engine.answer_user_question(
        question="公司基本面如何？",
        report_filename="600519.SS_贵州茅台_stock_analysis.md",
        report_content="报告内容……",
    )
    assert result["fallback_mode"] == "report_only"
    assert "回退回答" in result["answer"]


def test_answer_requires_valid_filename():
    with pytest.raises(ValueError):
        qa_engine.answer_user_question(
            question="q",
            report_filename="badname.md",
            report_content="",
        )
