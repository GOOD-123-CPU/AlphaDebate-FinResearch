"""应用配置中心。

所有配置通过环境变量读取（支持 .env 文件），仓库中绝不包含真实密钥。
"""
import os
import secrets
from pathlib import Path

from dotenv import load_dotenv

# 加载项目根目录下的 .env（存在才加载）
BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


def _env(key: str, default: str = "") -> str:
    return (os.getenv(key) or default).strip()


class Config:
    """Flask 与业务配置。"""

    # ---------- Flask 基础 ----------
    SECRET_KEY = _env("SECRET_KEY") or secrets.token_hex(32)
    SQLALCHEMY_DATABASE_URI = "sqlite:///" + str(BASE_DIR / "instance" / "database.db")
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # ---------- 目录 ----------
    BASE_DIR = BASE_DIR
    RESULT_DIR = BASE_DIR / "result"
    CACHE_DIR = BASE_DIR / "cache"
    REPORT_META_DIR = RESULT_DIR / "metadata"

    # ---------- LLM（OpenAI 兼容接口，任意服务商可替换） ----------
    LLM_API_URL = _env("LLM_API_URL", "https://api.deepseek.com/v1/chat/completions")
    LLM_API_KEY = _env("LLM_API_KEY")
    LLM_API_KEY_FALLBACK = _env("LLM_API_KEY_FALLBACK")
    LLM_MODEL = _env("LLM_MODEL", "deepseek-v3")
    GENERATOR_A_MODEL = _env("GENERATOR_A_MODEL") or _env("LLM_MODEL", "deepseek-v3")
    GENERATOR_B_MODEL = _env("GENERATOR_B_MODEL") or _env("LLM_MODEL", "deepseek-v3")
    JUDGE_MODEL = _env("JUDGE_MODEL") or _env("LLM_MODEL", "deepseek-v3")

    # ---------- 数据抓取 ----------
    CACHE_TTL_MINUTES = int(_env("CACHE_TTL_MINUTES", "30") or 30)

    # ---------- 辩论引擎 ----------
    # adversarial: 多空对抗模式（Generator A 看多方 vs Generator B 看空/风控方，Judge 中立仲裁）
    # parallel:    平行视角模式（两个生成器写不同侧重的同向报告，原始行为）
    DEBATE_MODE = _env("DEBATE_MODE", "adversarial")
    # 是否启用真流式（OpenAI stream=true 逐 token 推送；服务商不支持时自动回退非流式）
    LLM_STREAM = _env("LLM_STREAM", "true").lower() in {"1", "true", "yes"}

    # ---------- 可选：RAG / MetaGPT 插件引擎 ----------
    ZHIPUAI_API_KEY = _env("ZHIPUAI_API_KEY")
    BOCHA_API_KEY = _env("BOCHA_API_KEY")
    DASHSCOPE_API_KEY = _env("DASHSCOPE_API_KEY")
    VLLM_API_BASE = _env("VLLM_API_BASE", "http://127.0.0.1:8731/v1")
    VLLM_API_KEY = _env("VLLM_API_KEY")
    VLLM_MODEL = _env("VLLM_MODEL", "Qwen/Qwen3-14B")


config = Config()
