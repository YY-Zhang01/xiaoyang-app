"""
小洋 —— 记忆层（"一直陪着你"的技术核心）

两层记忆：
1. 对话历史（conversation）  —— 最近的完整对话窗口
2. 长期记忆（memories）      —— 由旧对话自动摘要出的、小洋"记得"的事

存储后端（MemoryStore）两种实现：
- JsonFileMemoryStore    —— 本地开发，写一个 JSON 文件，零配置
- UpstashRedisMemoryStore —— Vercel 生产，走 Upstash Redis REST，冷启动不丢

MemoryManager 负责：加载/保存、组装 system prompt、记录一轮对话、超长时自动摘要。
"""

import json
import os
import threading
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path

import httpx

from config import get_settings
from prompt import SYSTEM_PROMPT


# ============================================================
# 数据结构
# ============================================================
@dataclass
class MemoryState:
    conversation: list[dict] = field(default_factory=list)  # {role, content, ts}
    memories: list[dict] = field(default_factory=list)      # {content, ts}


# ============================================================
# 存储后端
# ============================================================
class MemoryStore(ABC):
    @abstractmethod
    def load(self, user_id: str) -> MemoryState: ...

    @abstractmethod
    def save(self, user_id: str, state: MemoryState) -> None: ...

    @abstractmethod
    def clear_conversation(self, user_id: str) -> None: ...

    @abstractmethod
    def clear_memories(self, user_id: str) -> None: ...


class JsonFileMemoryStore(MemoryStore):
    """本地开发用。注意：Vercel serverless 文件系统只读，生产请用 Upstash。"""

    def __init__(self, path: str):
        self.path = Path(path)
        self._lock = threading.Lock()

    def _read_all(self) -> dict:
        if not self.path.exists():
            return {}
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}

    def _write_all(self, data: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, self.path)

    def load(self, user_id: str) -> MemoryState:
        with self._lock:
            u = self._read_all().get(user_id, {})
        return MemoryState(
            conversation=list(u.get("conversation", [])),
            memories=list(u.get("memories", [])),
        )

    def save(self, user_id: str, state: MemoryState) -> None:
        with self._lock:
            data = self._read_all()
            data[user_id] = {
                "conversation": state.conversation,
                "memories": state.memories,
            }
            self._write_all(data)

    def clear_conversation(self, user_id: str) -> None:
        with self._lock:
            data = self._read_all()
            if user_id in data:
                data[user_id]["conversation"] = []
                self._write_all(data)

    def clear_memories(self, user_id: str) -> None:
        with self._lock:
            data = self._read_all()
            if user_id in data:
                data[user_id]["memories"] = []
                self._write_all(data)


class UpstashRedisMemoryStore(MemoryStore):
    """Upstash Redis REST 后端，serverless 友好、冷启动不丢。"""

    def __init__(self, rest_url: str, token: str):
        self.rest_url = rest_url.rstrip("/")
        self.token = token

    def _cmd(self, command: list) -> dict:
        resp = httpx.post(
            self.rest_url,
            headers={"Authorization": f"Bearer {self.token}"},
            json=command,
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json()

    def _key(self, user_id: str, kind: str) -> str:
        return f"xiaoyang:{user_id}:{kind}"

    def _load_json(self, key: str) -> list:
        try:
            result = self._cmd(["GET", key]).get("result")
        except httpx.HTTPError:
            return []
        if result is None:
            return []
        try:
            return json.loads(result)
        except (json.JSONDecodeError, TypeError):
            return []

    def _save_json(self, key: str, value: list) -> None:
        self._cmd(["SET", key, json.dumps(value, ensure_ascii=False)])

    def load(self, user_id: str) -> MemoryState:
        return MemoryState(
            conversation=self._load_json(self._key(user_id, "conversation")),
            memories=self._load_json(self._key(user_id, "memories")),
        )

    def save(self, user_id: str, state: MemoryState) -> None:
        self._save_json(self._key(user_id, "conversation"), state.conversation)
        self._save_json(self._key(user_id, "memories"), state.memories)

    def clear_conversation(self, user_id: str) -> None:
        self._cmd(["DEL", self._key(user_id, "conversation")])

    def clear_memories(self, user_id: str) -> None:
        self._cmd(["DEL", self._key(user_id, "memories")])


def get_memory_store(settings=None) -> MemoryStore:
    settings = settings or get_settings()
    backend = settings.memory_backend
    if backend == "upstash":
        return UpstashRedisMemoryStore(
            settings.upstash_redis_rest_url, settings.upstash_redis_rest_token
        )
    # 默认 json；未知值回退到 json
    return JsonFileMemoryStore(settings.memory_json_path)


# ============================================================
# 记忆管理器
# ============================================================
class MemoryManager:
    def __init__(self, user_id: str, store: MemoryStore, llm, settings=None):
        self.user_id = user_id
        self.store = store
        self.llm = llm
        self.settings = settings or get_settings()
        self.state = store.load(user_id)

    # ------------------------------------------------------------------
    def system_prompt(self) -> str:
        """人设 + 长期记忆。记忆是"自然记得"，不是逐条背诵。"""
        parts = [SYSTEM_PROMPT]
        if self.state.memories:
            recent = self.state.memories[-20:]
            lines = "\n".join(f"- {m['content']}" for m in recent)
            parts.append(
                "你记得的关于他的事（长期记忆，自然融入对话，不要逐条复述，也不要强调'我记得'）：\n"
                + lines
            )
        return "\n\n".join(parts)

    def messages_for_llm(self) -> list[dict]:
        """返回准备送给 LLM 的消息（含 system，不含本轮用户消息）。"""
        msgs = [{"role": "system", "content": self.system_prompt()}]
        for m in self.state.conversation:
            msgs.append({"role": m["role"], "content": m["content"]})
        return msgs

    # ------------------------------------------------------------------
    def record_turn(self, user_text: str, reply_text: str) -> None:
        now = time.time()
        self.state.conversation.append({"role": "user", "content": user_text, "ts": now})
        self.state.conversation.append(
            {"role": "assistant", "content": reply_text, "ts": now}
        )
        self._maybe_summarize()
        self._persist()

    def _maybe_summarize(self) -> None:
        conv = self.state.conversation
        if len(conv) <= self.settings.summarize_trigger:
            return
        keep = self.settings.history_window
        overflow = conv[:-keep]
        try:
            text = "\n".join(f"{m['role']}: {m['content']}" for m in overflow)
            facts = self.llm.summarize_to_facts(text)
            now = time.time()
            for f in facts:
                self.state.memories.append({"content": f, "ts": now})
        except Exception:
            pass  # 摘要失败不致命，照常截断窗口
        # 去重 + 限量（只留最近 60 条长期记忆）
        seen: set[str] = set()
        deduped: list[dict] = []
        for m in self.state.memories:
            if m["content"] not in seen:
                seen.add(m["content"])
                deduped.append(m)
        self.state.memories = deduped[-60:]
        self.state.conversation = conv[-keep:]

    def reset(self) -> None:
        self.state.conversation = []
        self._persist()

    def reset_memories(self) -> None:
        self.state.memories = []
        self._persist()

    def _persist(self) -> None:
        try:
            self.store.save(self.user_id, self.state)
        except Exception as e:  # 存储失败不打断对话，但要留痕
            print(f"[memory] 保存失败（{type(e).__name__}）: {e}")
