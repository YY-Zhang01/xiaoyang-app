"""
小洋 —— 知识库检索（RAG）

目标：在 Vercel serverless 上"真正可用"。
原来的方案（sentence-transformers 现场下载几百 MB 模型）在 serverless 冷启动会超时，
所以这里默认改用 **纯 Python 的 BM25 词法检索**：零外部依赖、零模型下载、毫秒级构建。

对个人笔记这种规模（几十篇、几百块），BM25 + 中文字符 bigram 已经足够好用；
后续若想上语义检索，可在此扩展一个调用 hosted embedding API 的 backend。
"""

import math
import re
from dataclasses import dataclass
from pathlib import Path

from config import get_settings


# ============================================================
# 分词：CJK 按字符 bigram，拉丁词整体小写
# ============================================================
_CJK = re.compile(r"[\u4e00-\u9fff]")
_LATIN = re.compile(r"[a-z0-9]+")


def tokenize(text: str) -> list[str]:
    tokens: list[str] = []
    cjk_run: list[str] = []
    for ch in text:
        if _CJK.match(ch):
            cjk_run.append(ch)
        else:
            for i in range(len(cjk_run) - 1):
                tokens.append(cjk_run[i] + cjk_run[i + 1])
            cjk_run = []
    for i in range(len(cjk_run) - 1):
        tokens.append(cjk_run[i] + cjk_run[i + 1])
    for w in _LATIN.findall(text.lower()):
        tokens.append(w)
    return tokens


# ============================================================
# BM25
# ============================================================
@dataclass
class Chunk:
    text: str
    source: str


class BM25Index:
    def __init__(self, chunks: list[Chunk], k1: float = 1.5, b: float = 0.75):
        self.chunks = chunks
        self.k1 = k1
        self.b = b
        self.doc_tokens: list[list[str]] = [tokenize(c.text) for c in chunks]
        self.doc_len = [len(t) for t in self.doc_tokens]
        self.avgdl = (sum(self.doc_len) / len(chunks)) if chunks else 0.0
        self.df: dict[str, int] = {}
        for tokens in self.doc_tokens:
            for term in set(tokens):
                self.df[term] = self.df.get(term, 0) + 1
        self.n_docs = len(chunks)

    def search(self, query: str, k: int = 3) -> list[Chunk]:
        if not self.chunks:
            return []
        q_tokens = tokenize(query)
        scores: list[float] = []
        for tokens in self.doc_tokens:
            score = 0.0
            for term in q_tokens:
                tf = tokens.count(term)
                if tf == 0:
                    continue
                df = self.df.get(term, 0)
                idf = math.log((self.n_docs - df + 0.5) / (df + 0.5) + 1.0)
                denom = tf + self.k1 * (1 - self.b + self.b * len(tokens) / (self.avgdl or 1.0))
                score += idf * (tf * (self.k1 + 1)) / denom
            scores.append(score)
        ranked = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)
        out: list[Chunk] = []
        for i in ranked:
            if scores[i] <= 0:
                continue
            out.append(self.chunks[i])
            if len(out) >= k:
                break
        return out


# ============================================================
# 文档加载 & 切片
# ============================================================
def _split_text(text: str, chunk_size: int = 500, overlap: int = 80) -> list[str]:
    """按段落贪婪打包成 ~chunk_size 的块，块间有 overlap 字符重叠。"""
    text = text.strip()
    if not text:
        return []
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    chunks: list[str] = []
    buf = ""
    for p in paragraphs:
        if len(buf) + len(p) <= chunk_size:
            buf = f"{buf}\n{p}".strip()
        else:
            if buf:
                chunks.append(buf)
            if len(p) > chunk_size:
                start = 0
                while start < len(p):
                    seg = p[start : start + chunk_size]
                    chunks.append(seg.strip())
                    start += chunk_size - overlap
                buf = ""
            else:
                buf = p
    if buf:
        chunks.append(buf)
    return [c for c in chunks if c]


def load_chunks(knowledge_dir: str) -> list[Chunk]:
    """递归读取 knowledge_dir 下所有 .md，切片成 Chunk。"""
    base = Path(knowledge_dir)
    if not base.exists():
        return []
    chunks: list[Chunk] = []
    for md_file in sorted(base.rglob("*.md")):
        try:
            text = md_file.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        rel = md_file.relative_to(base).as_posix()
        for piece in _split_text(text):
            if len(piece) >= 10:
                chunks.append(Chunk(text=piece, source=rel))
    return chunks


# ============================================================
# 检索器（惰性建索引，每冷启动只重建一次，毫秒级）
# ============================================================
class Retriever:
    def __init__(self, knowledge_dir: str, backend: str = "bm25"):
        self.knowledge_dir = knowledge_dir
        self.backend = backend
        self._index: BM25Index | None = None

    def _ensure_index(self) -> BM25Index:
        if self._index is None:
            self._index = BM25Index(load_chunks(self.knowledge_dir))
        return self._index

    def retrieve(self, query: str, k: int = 3) -> list[Chunk]:
        return self._ensure_index().search(query, k=k)

    @property
    def is_ready(self) -> bool:
        return Path(self.knowledge_dir).exists() and bool(load_chunks(self.knowledge_dir))


def build_retriever(settings=None) -> Retriever | None:
    settings = settings or get_settings()
    if not settings.rag_enabled:
        return None
    return Retriever(settings.knowledge_dir, settings.rag_backend)


# ============================================================
# 命令行测试
# ============================================================
if __name__ == "__main__":
    import sys

    settings = get_settings()
    r = build_retriever(settings)
    if r is None or not r.is_ready:
        print(f"知识库不可用（RAG_ENABLED={settings.rag_enabled}, dir={settings.knowledge_dir}）")
        sys.exit(1)
    print("=" * 50)
    print("  小洋知识库检索（BM25）")
    print(f"  目录: {settings.knowledge_dir}")
    print("=" * 50)
    while True:
        q = input("\n❓ 你问: ").strip()
        if q.lower() in ("q", "quit", "exit"):
            break
        if not q:
            continue
        for i, c in enumerate(r.retrieve(q, k=settings.rag_top_k), 1):
            print(f"\n[片段{i} 来自 {c.source}]")
            print(c.text[:200])
        print("-" * 40)
