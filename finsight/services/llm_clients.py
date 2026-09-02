"""LLM 客户端（OpenAI 兼容 chat/completions 协议）。

- 密钥全部来自环境变量 / finsight.config，源码中不含任何真实 Key。
- 支持主备双 Key：主 Key 遇 401 时自动切换备 Key。
- 兼容 DeepSeek / Qwen / GLM / Kimi / 本地 vLLM 等任意 OpenAI 兼容服务。
- 支持真流式（stream=true）：逐 token 通过 stream_callback 推送，
  服务商不支持流式时自动回退为整段响应模拟分块。
"""
import json
from typing import Callable, Dict, List, Optional
from urllib import error, request

from finsight.config import config

STREAM_CHUNK_SIZE = 8
STREAM_TIMEOUT = 300


class OpenAICompatClient:
    """最小依赖的 OpenAI 兼容客户端（仅用标准库）。"""

    def __init__(
        self,
        api_url: str,
        api_key: str,
        model: str,
        fallback_api_key: str = "",
        stream_enabled: bool = True,
    ):
        self.api_url = api_url
        self.api_key = api_key
        self.fallback_api_key = fallback_api_key
        self.model = model
        self.stream_enabled = stream_enabled

    # ------------------------------------------------------------------
    def _build_request(self, payload: dict, api_key: str) -> request.Request:
        return request.Request(
            self.api_url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "Accept": "text/event-stream" if payload.get("stream") else "application/json",
            },
            method="POST",
        )

    def _open_with_key_fallback(self, payload: dict) -> str:
        """依次尝试主备 Key 发起请求，返回 SSE/JSON 原始文本。"""
        candidate_keys = [key for key in [self.api_key, self.fallback_api_key] if key]
        if not candidate_keys:
            raise RuntimeError(
                "未配置 LLM_API_KEY。请在项目根目录创建 .env 文件并设置有效的模型 API Key"
                "（参考 .env.example）。"
            )

        last_error: Optional[Exception] = None
        raw = ""
        for index, candidate_key in enumerate(candidate_keys):
            req = self._build_request(payload, candidate_key)
            try:
                opener = request.build_opener(request.ProxyHandler({}))
                with opener.open(req, timeout=STREAM_TIMEOUT) as resp:
                    raw = resp.read().decode("utf-8")
                self.api_key = candidate_key
                break
            except error.HTTPError as exc:
                detail = exc.read().decode("utf-8", errors="ignore")
                if exc.code == 401 and index < len(candidate_keys) - 1:
                    last_error = RuntimeError(f"LLM HTTP {exc.code}: {detail}")
                    continue
                raise RuntimeError(f"LLM HTTP {exc.code}: {detail}") from exc
            except Exception as exc:
                last_error = exc
                if index < len(candidate_keys) - 1:
                    continue
                raise RuntimeError(f"LLM request failed: {exc}") from exc
        else:
            raise RuntimeError(f"LLM request failed: {last_error}")
        return raw

    # ------------------------------------------------------------------
    def generate(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.4,
        max_tokens: int = 4096,
        stream_callback: Optional[Callable[[str], None]] = None,
    ) -> str:
        use_stream = bool(stream_callback and self.stream_enabled)
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": use_stream,
        }

        raw = self._open_with_key_fallback(payload)

        if use_stream:
            content = self._consume_sse(raw, stream_callback)
            if content is not None:
                return content
            # 服务商不支持流式（返回了普通 JSON）→ 回退模拟分块
        else:
            content = self._parse_json_response(raw)
            if content is not None:
                self._emit_simulated(content, stream_callback)
                return content

        raise RuntimeError("LLM response format error: empty content")

    # ------------------------------------------------------------------
    def _parse_json_response(self, raw: str) -> Optional[str]:
        try:
            data = json.loads(raw)
            content = data["choices"][0]["message"]["content"].strip()
            return content or None
        except Exception:
            return None

    def _consume_sse(self, raw: str, stream_callback: Callable[[str], None]) -> Optional[str]:
        """解析 SSE 响应；若响应实际是普通 JSON 则返回 None（调用方回退）。"""
        stripped = raw.lstrip()
        if stripped.startswith("{"):
            # 不是 SSE，是普通 JSON 响应
            content = self._parse_json_response(raw)
            if content:
                self._emit_simulated(content, stream_callback)
                return content
            return None

        parts: List[str] = []
        for line in raw.splitlines():
            line = line.strip()
            if not line.startswith("data:"):
                continue
            data_str = line[len("data:"):].strip()
            if not data_str or data_str == "[DONE]":
                continue
            try:
                chunk = json.loads(data_str)
                delta = chunk.get("choices", [{}])[0].get("delta", {})
                token = delta.get("content") or ""
                if token:
                    parts.append(token)
                    try:
                        stream_callback(token)
                    except Exception:  # 回调异常不影响生成
                        pass
            except Exception:
                continue

        content = "".join(parts).strip()
        return content or None

    def _emit_simulated(self, content: str, stream_callback: Optional[Callable[[str], None]]) -> None:
        if stream_callback and content:
            for idx in range(0, len(content), STREAM_CHUNK_SIZE):
                stream_callback(content[idx : idx + STREAM_CHUNK_SIZE])


def get_llm_config() -> Dict[str, str]:
    return {
        "api_url": config.LLM_API_URL,
        "api_key": config.LLM_API_KEY,
        "fallback_api_key": config.LLM_API_KEY_FALLBACK,
        "default_model": config.LLM_MODEL,
        "generator_a_model": config.GENERATOR_A_MODEL,
        "generator_b_model": config.GENERATOR_B_MODEL,
        "judge_model": config.JUDGE_MODEL,
        "stream_enabled": config.LLM_STREAM,
    }


def _make_client(model_attr: str):
    cfg = get_llm_config()
    return OpenAICompatClient(
        cfg["api_url"],
        cfg["api_key"],
        cfg[model_attr],
        cfg["fallback_api_key"],
        stream_enabled=cfg["stream_enabled"],
    )


def get_generator_a_client() -> OpenAICompatClient:
    return _make_client("generator_a_model")


def get_generator_b_client() -> OpenAICompatClient:
    return _make_client("generator_b_model")


def get_judge_client() -> OpenAICompatClient:
    return _make_client("judge_model")
