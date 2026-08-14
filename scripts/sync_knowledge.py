"""
小洋 —— 笔记同步脚本

把本地笔记目录同步到 knowledge/（部署时随仓库带上，供 serverless 检索用）。
knowledge/ 已被 .gitignore 忽略（个人隐私），部署时由 Vercel CLI 直接打包上传。

用法：
    python scripts/sync_knowledge.py [源目录...]
    不传参数时读环境变量 NOTE_SOURCE_DIRS（分号或逗号分隔）；
    再没有则回退到默认位置 docs/ 和 learning/。
"""

import os
import shutil
import sys
from pathlib import Path

# Windows 终端 UTF-8 兼容（避免 emoji 在 GBK 控制台报错）
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


def parse_dirs() -> list[Path]:
    if len(sys.argv) > 1:
        return [Path(a) for a in sys.argv[1:]]
    raw = os.getenv("NOTE_SOURCE_DIRS", "")
    if raw:
        return [Path(p.strip()) for p in raw.replace(";", ",").split(",") if p.strip()]
    candidates = [Path("E:/ReshapingMyself"), Path.home() / "ReshapingMyself"]
    root = next((c for c in candidates if c.exists()), None)
    if root is None:
        print("找不到笔记根目录，请显式传入源目录或设置 NOTE_SOURCE_DIRS")
        sys.exit(1)
    return [root / "docs", root / "learning"]


def main() -> None:
    here = Path(__file__).resolve().parent.parent
    dest = here / "knowledge"
    srcs = parse_dirs()

    # 清空后重新同步，保证删除的笔记也一并移除
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True, exist_ok=True)

    count = 0
    for src in srcs:
        if not src.exists():
            print(f"⚠️  跳过不存在的目录: {src}")
            continue
        for md in src.rglob("*.md"):
            target = dest / src.name / md.relative_to(src)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(md, target)
            count += 1

    print(f"✅ 已同步 {count} 篇笔记到 {dest}")


if __name__ == "__main__":
    main()
