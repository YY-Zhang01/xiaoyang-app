"""
小洋 —— FastAPI 入口（Vercel 部署）

职责：只做"接线"，业务逻辑都在各模块里：
- config.py  配置（环境变量）
- prompt.py  人设
- llm.py     DeepSeek 客户端（含流式）
- memory.py  记忆层（对话历史 + 长期记忆，可持久化）
- rag.py     知识库检索（BM25，serverless 可用）
- wechat.py  企业微信接入

记忆状态不再放在模块级全局变量里（那会冷启动丢），而是每请求从 store 加载。
"""

import json
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import wechat as wechat_mod
from config import get_settings
from llm import DeepSeekClient, DeepSeekError
from memory import MemoryManager, get_memory_store
from rag import build_retriever

settings = get_settings()

# 模块级依赖都是"轻量无状态"的客户端；真正的记忆状态按请求从 store 加载
llm = DeepSeekClient(settings)
store = get_memory_store(settings)
retriever = build_retriever(settings)

app = FastAPI(title="小洋", description="只属于你的 AI 伙伴")
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins_list,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ChatRequest(BaseModel):
    message: str
    user_id: str | None = None


class UserRequest(BaseModel):
    user_id: str | None = None


def _uid(req_user_id: str | None) -> str:
    return req_user_id or settings.user_id


def _retrieve_context(query: str) -> tuple[str, list[str]]:
    """检索知识库，返回 (上下文字符串, 来源列表)。失败时静默降级为空。"""
    if retriever is None:
        return "", []
    try:
        chunks = retriever.retrieve(query, settings.rag_top_k)
    except Exception as e:
        print(f"[rag] 检索失败: {e}")
        return "", []
    if not chunks:
        return "", []
    ctx = "\n\n---\n\n".join(
        f"[参考{i + 1}：{c.source}]\n{c.text}" for i, c in enumerate(chunks)
    )
    return ctx, list({c.source for c in chunks})


def _build_llm_messages(mgr: MemoryManager, message: str, ctx: str) -> list[dict]:
    msgs = mgr.messages_for_llm()
    msgs.append({"role": "user", "content": message})
    if ctx:
        msgs.insert(
            -1,
            {
                "role": "system",
                "content": "以下是你的笔记中和当前话题相关的内容，如果相关就自然引用"
                "（不要生硬地说'根据笔记'）：\n\n" + ctx,
            },
        )
    return msgs


@app.get("/health")
def health():
    return {
        "status": "ok",
        "model": settings.deepseek_model,
        "memory_backend": settings.memory_backend,
        "rag": settings.rag_backend if (settings.rag_enabled and retriever) else "off",
        "config_problems": settings.validate(),
    }


@app.post("/chat")
def chat(req: ChatRequest):
    mgr = MemoryManager(_uid(req.user_id), store, llm, settings)
    ctx, sources = _retrieve_context(req.message)
    msgs = _build_llm_messages(mgr, req.message, ctx)
    try:
        reply = llm.chat(msgs)
    except DeepSeekError as e:
        return {"reply": f"唔，我卡了一下：{e}", "sources": []}
    mgr.record_turn(req.message, reply)
    return {"reply": reply, "sources": sources}


@app.post("/chat/stream")
def chat_stream(req: ChatRequest):
    """SSE 流式对话，供 Flutter App 使用。"""
    mgr = MemoryManager(_uid(req.user_id), store, llm, settings)
    ctx, sources = _retrieve_context(req.message)
    msgs = _build_llm_messages(mgr, req.message, ctx)

    def gen():
        acc: list[str] = []
        try:
            for delta in llm.stream(msgs):
                acc.append(delta)
                yield f"data: {json.dumps({'delta': delta}, ensure_ascii=False)}\n\n"
            reply = "".join(acc).strip()
            if reply:
                mgr.record_turn(req.message, reply)
            yield f"data: {json.dumps({'done': True, 'sources': sources}, ensure_ascii=False)}\n\n"
        except DeepSeekError as e:
            yield f"data: {json.dumps({'error': str(e)}, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/reset")
def reset(req: UserRequest):
    """重新开始：清空当前对话，但保留长期记忆（她仍然记得你）。"""
    mgr = MemoryManager(_uid(req.user_id), store, llm, settings)
    mgr.reset()
    return {"status": "ok"}


@app.get("/memories")
def get_memories(user_id: str | None = None):
    """看看小洋记住了什么（透明化）。"""
    mgr = MemoryManager(_uid(user_id), store, llm, settings)
    return {"memories": mgr.state.memories}


@app.delete("/memories")
def delete_memories(req: UserRequest):
    mgr = MemoryManager(_uid(req.user_id), store, llm, settings)
    mgr.reset_memories()
    return {"status": "ok"}


# 企业微信（次要渠道）
app.include_router(wechat_mod.router)

# 静态前端（Web PWA，次要渠道），必须最后挂载
_static_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
if os.path.isdir(_static_dir):
    app.mount("/", StaticFiles(directory=_static_dir, html=True), name="static")
