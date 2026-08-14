# 小洋 · 后端

只属于你的 AI 伙伴 —— 后端服务。FastAPI + DeepSeek，部署在 Vercel。

> 这是「小洋」产品化重构后的后端。核心命题：**小洋不是聊天机器人，是有长期记忆、知道你是谁的个人 AI 伴侣**。

## 它是什么

- **人设**：`prompt.py` 里的小洋，说话像朋友，不灌鸡汤（个人档案在 `persona_facts.py`，不提交）。
- **记忆**：两层记忆 —— 最近的对话窗口 + 由旧对话自动摘要出的「长期记忆」。存云端数据库，冷启动不丢。
- **知识库（RAG）**：检索你的笔记，让回复「记得你学过什么」。纯 Python BM25，serverless 可用、不下载大模型。
- **多入口**：Flutter App（主）、Web PWA、企业微信（次）。

## 架构

```
xiaoyang-app/
├── server.py       # FastAPI 入口，只做接线
├── config.py       # 配置（全部走环境变量）
├── prompt.py       # 小洋人设
├── llm.py          # DeepSeek 客户端（非流式 + 流式 + 记忆摘要）
├── memory.py       # 记忆层（对话历史 + 长期记忆 + 存储后端）
├── rag.py          # 知识库检索（BM25，零外部依赖）
├── wechat.py       # 企业微信接入
├── chat_cli.py     # 命令行对话（和 App 共享同一份记忆）
├── scripts/
│   └── sync_knowledge.py   # 把本地笔记同步进 knowledge/
├── tests/          # pytest
└── static/         # Web PWA（次要渠道）
```

### 数据流（一次对话）

```
消息进来
  → MemoryManager 从存储加载「记忆状态」
  → 组装 system prompt = 人设 + 长期记忆
  → RAG 检索笔记，注入相关上下文
  → 调 DeepSeek（流式返回增量给 App）
  → 记录本轮对话；对话过长时自动摘要成长期记忆
  → 写回存储
```

## 核心设计

### 记忆（"一直陪着你"的技术核心）

| 层 | 内容 | 生命周期 |
|----|------|----------|
| 对话历史 | 最近 N 条完整消息 | 超长后旧部分被摘要 |
| 长期记忆 | 自动摘要出的事实（偏好/计划/情绪） | 保留最近 60 条，跨「重新开始」仍在 |

- 存储后端可切换：`json`（本地开发，零配置）或 `upstash`（生产，冷启动不丢）。
- 「重新开始」只清对话，**不清长期记忆** —— 她仍然记得你。

### RAG（serverless 真正可用）

原方案用 sentence-transformers 现场下载几百 MB 模型，Vercel 冷启动会超时（实际是静默失效）。现在默认 **BM25 词法检索**：零外部依赖、零模型下载、毫秒级建索引，对个人笔记规模足够好用。

## 本地运行

```bash
# 1. 用已有的 venv 或新建
python -m venv .venv
.venv\Scripts\activate          # Windows

# 2. 装依赖（只有 4 个，很轻）
pip install -r requirements.txt

# 3. 配环境变量（复制样例）
copy .env.example .env
# 编辑 .env，填 DEEPSEEK_API_KEY

# 4. 同步笔记（可选，让 RAG 生效）
python scripts/sync_knowledge.py

# 5. 启动
uvicorn server:app --reload
# http://127.0.0.1:8000/docs 看接口文档
```

## 环境变量

见 [`.env.example`](.env.example)，关键几个：

| 变量 | 必填 | 说明 |
|------|------|------|
| `DEEPSEEK_API_KEY` | ✅ | DeepSeek 密钥 |
| `MEMORY_BACKEND` | 生产 ✅ | `json`（本地）或 `upstash`（生产） |
| `UPSTASH_REDIS_REST_URL` / `TOKEN` | 生产 ✅ | Upstash Redis REST 连接信息 |
| `WECHAT_CORP_ID` 等 | 可选 | 企业微信（次要渠道） |

## API

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/chat` | 非流式对话，返回 `{reply, sources}` |
| POST | `/chat/stream` | SSE 流式对话（Flutter 主用） |
| POST | `/reset` | 重新开始（保留长期记忆） |
| GET | `/memories` | 查看小洋的长期记忆 |
| DELETE | `/memories` | 清空长期记忆 |
| GET | `/health` | 健康检查 + 配置自检 |

## 部署到 Vercel

1. **创建 Upstash Redis**（免费额度够用）：upstash.com → Create Database → 拿到 REST URL 和 Token。
2. **同步笔记**：`python scripts/sync_knowledge.py`（生成 `knowledge/`，会随部署一起上传；该目录已 gitignore，属个人隐私）。
3. **推送代码**到 GitHub，在 Vercel import 这个仓库。
4. **配环境变量**（Vercel → Settings → Environment Variables）：
   - `DEEPSEEK_API_KEY`
   - `MEMORY_BACKEND=upstash`
   - `UPSTASH_REDIS_REST_URL`、`UPSTASH_REDIS_REST_TOKEN`
5. Deploy。`GET /health` 返回 `memory_backend: upstash` 即成功。

> 注意：笔记更新后需重新跑 `sync_knowledge.py` 并重新部署，RAG 才拿得到新内容。

## 测试

```bash
python -m pytest -q
```

覆盖：记忆存储读写、长对话自动摘要、重置保留记忆、BM25 检索与中文分词、长文本切片。
