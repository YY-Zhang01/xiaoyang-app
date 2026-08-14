import tempfile
from pathlib import Path

from config import Settings
from memory import JsonFileMemoryStore, MemoryManager, MemoryState


class FakeLLM:
    """不联网的假 LLM，只用于验证记忆摘要流程。"""

    def summarize_to_facts(self, text: str) -> list[dict]:
        return [
            {"category": "学习", "importance": 5, "content": "他最近在准备雅思"},
            {"category": "目标", "importance": 4, "content": "他想去深圳找工作"},
        ]


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


def test_retrieve_relevant_by_keyword():
    settings = Settings()
    with tempfile.TemporaryDirectory() as d:
        store = JsonFileMemoryStore(str(Path(d) / "mem.json"))
        mgr = MemoryManager("me", store, FakeLLM(), settings)
        mgr.state.memories = [
            {"content": "他喜欢喝美式咖啡", "category": "个人", "importance": 3, "ts": 1},
            {"content": "他最近在准备雅思", "category": "学习", "importance": 5, "ts": 2},
            {"content": "他想去深圳找工作", "category": "目标", "importance": 4, "ts": 3},
        ]
        # 问"雅思"，相关记忆应该排第一
        rel = mgr.retrieve_relevant("雅思备考进展如何", k=3)
        assert rel[0]["content"] == "他最近在准备雅思"


def test_retain_evicts_low_importance():
    settings = Settings(max_memories_total=2, max_memories_per_category=10)
    with tempfile.TemporaryDirectory() as d:
        store = JsonFileMemoryStore(str(Path(d) / "mem.json"))
        mgr = MemoryManager("me", store, FakeLLM(), settings)
        mgr.state.memories = [
            {"content": "重要的事", "category": "个人", "importance": 5, "ts": 1},
            {"content": "琐碎的事", "category": "个人", "importance": 1, "ts": 2},
            {"content": "一般的事", "category": "个人", "importance": 3, "ts": 3},
        ]
        mgr._retain()
        contents = {m["content"] for m in mgr.state.memories}
        assert "重要的事" in contents
        assert "一般的事" in contents
        assert "琐碎的事" not in contents  # 重要度最低被挤掉
