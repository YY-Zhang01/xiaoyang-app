"""
小洋 —— DeepSeek 客户端

提供：
- chat():      非流式对话（Web / 企业微信 / CLI 用）
- stream():    流式对话（Flutter App 用，SSE 增量返回）
- summarize_to_facts(): 把一段对话压缩成长期记忆事实（记忆层用）

只依赖 httpx + stdlib，不引入额外 SDK。
"""

import json
from typing import Iterator

import httpx

from config import get_settings


class DeepSeekError(Exception):
    """调用 DeepSeek 失败时抛出，message 面向用户友好。"""


class DeepSeekClient:
    def __init__(self, settings=None):
        self.settings = settings or get_settings()

    # ------------------------------------------------------------------
    @property
    def _endpoint(self) -> str:
        base = self.settings.deepseek_base_url.rstrip("/")
        return f"{base}/chat/completions"

    @property
    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.settings.deepseek_api_key}",
            "Content-Type": "application/json",
        }

    def _payload(
        self,
        messages: list[dict],
        *,
        stream: bool = False,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> dict:
        return {
            "model": self.settings.deepseek_model,
            "messages": messages,
            "temperature": self.settings.deepseek_temperature if temperature is None else temperature,
            "max_tokens": self.settings.deepseek_max_tokens if max_tokens is None else max_tokens,
            "stream": stream,
        }

    def _ensure_key(self) -> None:
        if not self.settings.deepseek_api_key:
            raise DeepSeekError(
                "DEEPSEEK_API_KEY 未配置，小洋暂时没法开口。请到 Vercel 环境变量里补上。"
            )

    # ------------------------------------------------------------------
    def chat(
        self,
        messages: list[dict],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> str:
        """非流式对话，返回完整回复文本。"""
        self._ensure_key()
        try:
            resp = httpx.post(
                self._endpoint,
                headers=self._headers,
                json=self._payload(
                    messages, temperature=temperature, max_tokens=max_tokens
                ),
                timeout=httpx.Timeout(60.0, connect=10.0),
            )
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"]
        except httpx.HTTPStatusError as e:
            raise DeepSeekError(f"DeepSeek 接口返回 {e.response.status_code}，稍后再试") from e
        except (httpx.HTTPError, KeyError, IndexError, json.JSONDecodeError) as e:
            raise DeepSeekError(f"和 DeepSeek 的连接出了点问题：{type(e).__name__}") from e

    # ------------------------------------------------------------------
    def stream(
        self,
        messages: list[dict],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> Iterator[str]:
        """流式对话，逐个产出文本增量（已拼接好，直接可展示）。"""
        self._ensure_key()
        try:
            with httpx.stream(
                "POST",
                self._endpoint,
                headers=self._headers,
                json=self._payload(
                    messages, stream=True, temperature=temperature, max_tokens=max_tokens
                ),
                timeout=httpx.Timeout(120.0, connect=10.0),
            ) as resp:
                resp.raise_for_status()
                for line in resp.iter_lines():
                    line = line.strip()
                    if not line:
                        continue
                    if line.startswith("data:"):
                        line = line[5:].strip()
                    if line == "[DONE]":
                        break
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    delta = (
                        obj.get("choices", [{}])[0]
                        .get("delta", {})
                        .get("content")
                    )
                    if delta:
                        yield delta
        except httpx.HTTPStatusError as e:
            raise DeepSeekError(f"DeepSeek 接口返回 {e.response.status_code}，稍后再试") from e
        except httpx.HTTPError as e:
            raise DeepSeekError(f"和 DeepSeek 的连接出了点问题：{type(e).__name__}") from e

    # ------------------------------------------------------------------
    def summarize_to_facts(self, conversation_text: str) -> list[str]:
        """把一段对话压缩成小洋该长期记住的事实（每条一句话）。"""
        system = (
            "你是小洋的记忆整理器。把对话里关于用户的重要事实、偏好、计划、情绪，"
            "压缩成一条条第三人称的长期记忆。要求：每条一句话、客观、只写值得以后想起的，"
            "最多 8 条。只输出事实本身，每行一条，不要编号、不要引号、不要任何解释。"
        )
        try:
            out = self.chat(
                [
                    {"role": "system", "content": system},
                    {"role": "user", "content": conversation_text},
                ],
                temperature=0.3,
                max_tokens=400,
            )
        except DeepSeekError:
            return []
        facts: list[str] = []
        for line in out.splitlines():
            cleaned = line.strip().lstrip("-•*0123456789.、 ").strip()
            if cleaned:
                facts.append(cleaned)
        return facts[:8]
