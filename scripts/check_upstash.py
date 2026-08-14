"""
小洋 —— Upstash 连通性自检

创建好 Upstash Redis 后，把 REST URL 和 Token 设进环境变量，跑这个脚本，
验证「小洋的永久记忆」能不能正常读写。部署到 Vercel 前先本地验一遍，最省心。

用法（PowerShell）：
    $env:UPSTASH_REDIS_REST_URL="https://xxxx.upstash.io"
    $env:UPSTASH_REDIS_REST_TOKEN="xxxx"
    python scripts/check_upstash.py

通过后，把同样的两个变量原样填进 Vercel 环境变量即可。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import get_settings
from memory import MemoryState, UpstashRedisMemoryStore


def main() -> int:
    settings = get_settings()
    if not settings.upstash_redis_rest_url or not settings.upstash_redis_rest_token:
        print("❌ 请先设置 UPSTASH_REDIS_REST_URL 和 UPSTASH_REDIS_REST_TOKEN")
        return 1

    store = UpstashRedisMemoryStore(
        settings.upstash_redis_rest_url, settings.upstash_redis_rest_token
    )
    probe_user = "__probe__"

    try:
        # 走完整的公开接口：写入 → 读回 → 清理
        state = MemoryState(
            conversation=[{"role": "user", "content": "连通性测试", "ts": 0}],
            memories=[{"content": "测试记忆", "ts": 0}],
        )
        store.save(probe_user, state)
        loaded = store.load(probe_user)
        ok = (
            len(loaded.conversation) == 1
            and loaded.conversation[0]["content"] == "连通性测试"
            and len(loaded.memories) == 1
        )
        store.clear_conversation(probe_user)
        store.clear_memories(probe_user)

        if not ok:
            print("⚠️  读写不一致，读回的数据不符合预期")
            return 1
        print("✅ Upstash 连接正常，小洋的永久记忆可以用了。")
        print(f"   地址: {settings.upstash_redis_rest_url}")
        return 0
    except Exception as e:
        print(f"❌ 连接失败：{e}")
        print("   检查：URL 是否带 https://、Token 是否完整、数据库是否处于运行状态。")
        return 1


if __name__ == "__main__":
    sys.exit(main())
