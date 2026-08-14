import tempfile
from pathlib import Path

from config import Settings
from memory import JsonFileMemoryStore, MemoryManager, MemoryState


class FakeLLM:
    """不联网的假 LLM，只用于验证记忆摘要流程。"""

    def summarize_to_facts(self, text: str) -> list[str]:
        return ["他最近在准备雅思", "他想去深圳找工作"]


def test_json_store_roundtrip():
    with tempfile.TemporaryDirectory() as d:
        store = JsonFileMemoryStore(str(Path(d) / "mem.json"))
        state = MemoryState(
            conversation=[{"role": "user", "content": "hi", "ts": 1}],
            memories=[{"content": "记得的事", "ts": 1}],
        )
        store.save("me", state)

        loaded = store.load("me")
        assert loaded.conversation[0]["content"] == "hi"
        assert loaded.memories[0]["content"] == "记得的事"

        store.clear_conversation("me")
        assert store.load("me").conversation == []
        assert len(store.load("me").memories) == 1  # 清对话不清记忆

        store.clear_memories("me")
        assert store.load("me").memories == []


def test_memory_manager_summarizes_when_long():
    settings = Settings(history_window=4, summarize_trigger=6)
    with tempfile.TemporaryDirectory() as d:
        store = JsonFileMemoryStore(str(Path(d) / "mem.json"))
        mgr = MemoryManager("me", store, FakeLLM(), settings)

        # 4 轮 = 8 条消息 > trigger(6)，触发摘要
        for i in range(4):
            mgr.record_turn(f"u{i}", f"a{i}")

        assert len(mgr.state.conversation) == settings.history_window  # 窗口被截断
        assert len(mgr.state.memories) >= 1
        assert "雅思" in mgr.system_prompt()  # 长期记忆进入了 system prompt


def test_reset_keeps_memories():
    settings = Settings(history_window=4, summarize_trigger=6)
    with tempfile.TemporaryDirectory() as d:
        store = JsonFileMemoryStore(str(Path(d) / "mem.json"))
        mgr = MemoryManager("me", store, FakeLLM(), settings)
        for i in range(4):
            mgr.record_turn(f"u{i}", f"a{i}")
        memories_before = len(mgr.state.memories)

        mgr.reset()
        assert mgr.state.conversation == []
        assert len(mgr.state.memories) == memories_before  # 记忆保留
