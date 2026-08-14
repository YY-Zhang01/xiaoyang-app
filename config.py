"""
小洋 —— 配置

所有配置一律从环境变量读取，绝不硬编码密钥。
本地开发可复制 .env.example 为 .env（uvicorn 不会自动加载，用 scripts/ 或 IDE 注入；
Vercel 上直接在该项目的 Settings → Environment Variables 里配置）。
"""

import os
from dataclasses import dataclass, field


def _env(name: str, default: str = "") -> str:
    return os.getenv(name, default)


def _env_bool(name: str, default: bool = False) -> bool:
    val = os.getenv(name)
    if val is None:
        return default
    return val.strip().lower() in ("1", "true", "yes", "on", "y")


def _env_int(name: str, default: int) -> int:
    val = os.getenv(name)
    if val is None or val.strip() == "":
        return default
    try:
        return int(val)
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    val = os.getenv(name)
    if val is None or val.strip() == "":
        return default
    try:
        return float(val)
    except ValueError:
        return default


@dataclass(frozen=True)
class Settings:
    # ---- DeepSeek（LLM）----
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-chat"
    deepseek_temperature: float = 0.8
    deepseek_max_tokens: int = 600

    # ---- 记忆 ----
    # memory_backend: "json"（本地开发） | "upstash"（Vercel 生产，冷启动不丢）
    memory_backend: str = "json"
    memory_json_path: str = "data/memory.json"
    upstash_redis_rest_url: str = ""
    upstash_redis_rest_token: str = ""
    # 完整保留的最近消息条数；超出部分会被压缩成长期记忆
    history_window: int = 20
    summarize_trigger: int = 32

    # ---- RAG 知识库 ----
    rag_enabled: bool = True
    # rag_backend: "bm25"（默认，serverless 可用，无模型下载）
    rag_backend: str = "bm25"
    knowledge_dir: str = "knowledge"
    rag_top_k: int = 3

    # ---- 企业微信 ----
    wechat_corp_id: str = ""
    wechat_agent_id: str = ""
    wechat_secret: str = ""
    wechat_token: str = ""

    # ---- 单用户默认标识（代码保留多用户口子，但当前产品只服务一个人）----
    user_id: str = "me"

    # ---- CORS（逗号分隔）----
    allowed_origins: str = "*"

    @property
    def allowed_origins_list(self) -> list[str]:
        if self.allowed_origins.strip() == "*":
            return ["*"]
        return [o.strip() for o in self.allowed_origins.split(",") if o.strip()]

    def validate(self) -> list[str]:
        """返回配置问题列表，空列表表示 OK。"""
        problems: list[str] = []
        if not self.deepseek_api_key:
            problems.append("DEEPSEEK_API_KEY 未设置（小洋无法调用模型）")
        if self.memory_backend == "upstash":
            if not self.upstash_redis_rest_url or not self.upstash_redis_rest_token:
                problems.append("MEMORY_BACKEND=upstash 但 UPSTASH_REDIS_REST_URL / TOKEN 未设置")
        if self.summarize_trigger <= self.history_window:
            problems.append("SUMMARIZE_TRIGGER 必须大于 HISTORY_WINDOW")
        return problems


_settings: Settings | None = None


def get_settings() -> Settings:
    """惰性单例：从环境变量构造一次，之后复用。"""
    global _settings
    if _settings is None:
        _settings = Settings(
            deepseek_api_key=_env("DEEPSEEK_API_KEY"),
            deepseek_base_url=_env("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
            deepseek_model=_env("DEEPSEEK_MODEL", "deepseek-chat"),
            deepseek_temperature=_env_float("DEEPSEEK_TEMPERATURE", 0.8),
            deepseek_max_tokens=_env_int("DEEPSEEK_MAX_TOKENS", 600),
            memory_backend=_env("MEMORY_BACKEND", "json").strip().lower(),
            memory_json_path=_env("MEMORY_JSON_PATH", "data/memory.json"),
            upstash_redis_rest_url=_env("UPSTASH_REDIS_REST_URL"),
            upstash_redis_rest_token=_env("UPSTASH_REDIS_REST_TOKEN"),
            history_window=_env_int("HISTORY_WINDOW", 20),
            summarize_trigger=_env_int("SUMMARIZE_TRIGGER", 32),
            rag_enabled=_env_bool("RAG_ENABLED", True),
            rag_backend=_env("RAG_BACKEND", "bm25").strip().lower(),
            knowledge_dir=_env("KNOWLEDGE_DIR", "knowledge"),
            rag_top_k=_env_int("RAG_TOP_K", 3),
            wechat_corp_id=_env("WECHAT_CORP_ID"),
            wechat_agent_id=_env("WECHAT_AGENT_ID"),
            wechat_secret=_env("WECHAT_SECRET"),
            wechat_token=_env("WECHAT_TOKEN", "xiaoyang666"),
            user_id=_env("USER_ID", "me"),
            allowed_origins=_env("ALLOWED_ORIGINS", "*"),
        )
    return _settings
