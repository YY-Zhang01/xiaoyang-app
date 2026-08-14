from rag import BM25Index, Chunk, _split_text, tokenize


def test_tokenize_cjk_bigram():
    tokens = tokenize("雅思备考规划")
    assert "雅思" in tokens
    assert "备考" in tokens


def test_tokenize_latin_words():
    tokens = tokenize("Flutter deepseek-chat")
    assert "flutter" in tokens
    assert "deepseek" in tokens
    assert "chat" in tokens


def test_bm25_retrieves_relevant_chunk():
    chunks = [
        Chunk("雅思8周冲刺规划，每天背单词、练口语", "learning/ielts.md"),
        Chunk("毕业设计用了图数据库做知识图谱", "docs/bishi.md"),
        Chunk("SSL 证书配置与 Flutter 网络请求", "docs/ssl.md"),
    ]
    idx = BM25Index(chunks)
    res = idx.search("雅思备考有什么计划", k=1)
    assert res and res[0].source == "learning/ielts.md"


def test_bm25_no_match_returns_empty():
    idx = BM25Index([Chunk("知识图谱设计", "a.md")])
    assert idx.search("zzzzzzzz 不存在的内容", k=3) == []


def test_split_long_text_bounded():
    text = "段落一。" * 200  # 800 字单段
    pieces = _split_text(text, chunk_size=500, overlap=80)
    assert all(len(p) <= 500 for p in pieces)
    assert len(pieces) >= 2
