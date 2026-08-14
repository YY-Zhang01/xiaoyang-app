"""
小洋 —— 命令行对话

和 App 共享同一套人设 + 记忆（本地默认 data/memory.json），
你在终端聊过的内容，打开 App 她一样记得。
"""

from config import get_settings
from llm import DeepSeekClient, DeepSeekError
from memory import MemoryManager, get_memory_store


def main() -> None:
    settings = get_settings()
    llm = DeepSeekClient(settings)
    store = get_memory_store(settings)
    mgr = MemoryManager(settings.user_id, store, llm, settings)

    print("=" * 50)
    print("  小洋已上线。想说什么就说，输入 quit 退出")
    print("=" * 50)

    while True:
        try:
            user_input = input("\n你: ")
        except (EOFError, KeyboardInterrupt):
            print("\n\n小洋: 去吧，我在这等你回来。\n")
            break
        if user_input.lower() in ("quit", "exit", "q"):
            print("\n小洋: 去吧，我在这等你回来。\n")
            break
        if not user_input.strip():
            continue

        msgs = mgr.messages_for_llm(user_input)
        msgs.append({"role": "user", "content": user_input})
        try:
            reply = llm.chat(msgs)
        except DeepSeekError as e:
            print(f"\n小洋: 唔，出了点问题：{e}")
            continue
        mgr.record_turn(user_input, reply)
        print(f"\n小洋: {reply}")


if __name__ == "__main__":
    main()
