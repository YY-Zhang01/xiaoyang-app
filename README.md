# 小洋 · 后端

一个有长期记忆的个人 AI 伴侣。FastAPI + DeepSeek + Upstash，部署在 Vercel。

核心一句话：它不是聊天机器人，是记得你、知道你是谁的人。

## 它做了什么

- **记忆**：两层。最近的对话 + 从旧对话自动摘要出的长期记忆。存云端（Upstash），服务器重启不丢。
- **知识库**：翻你自己的笔记（Markdown），聊到相关话题时自动引用。纯 Python 的 BM25 检索，不下载大模型，serverless 上也能跑。
- **人设**：`prompt.py` 是可复用的模板；你的真实底细放 `persona_facts.py`（已 gitignore），两处分离，方便开源。
- **多入口**：手机 App、网页、企业微信，三个入口共用同一份记忆。

## 核心设计

### 记忆（重点）

| 层 | 存什么 | 说明 |
|---|---|---|
| 对话历史 | 最近 20 条完整消息 | 超了自动把旧的摘要掉 |
| 长期记忆 | 摘要出的事实，最多 300 条 | 每条带「分类」和「重要度」 |

- 摘要时让模型给每条打两个标：分类（个人/目标/健康/学习/情绪/其他）+ 重要度（1-5 分）。
- 聊天时**按当前话题**挑相关记忆塞进 prompt（关键词相关度 + 重要度），不是死板地只取最近几条。
- 容量满了按「重要度低、更旧」先删，重要的记得牢。
- 「重新开始」只清对话，不清长期记忆。

### 知识库（RAG）

用 sentence-transformers 现场下模型在 serverless 上会超时，所以换成纯 Python 的 BM25 词法检索：零依赖、毫秒级建索引，个人笔记这个规模够用。

### 安全

- 聊天接口要带 `X-API-Token`（App 用）或网页密码（网页版用），没带一律 401。
- 企业微信走它自己的加密校验（`wechat_crypto.py` 实现了官方加解密）。

## 目录

```
server.py        # 接口入口
config.py        # 配置，全走环境变量
prompt.py        # 人设模板（公开，无隐私）
persona_facts.py # 你的个人档案（gitignore，不上传）
llm.py           # 调 DeepSeek（流式 + 非流式 + 摘要）
memory.py        # 记忆层
rag.py           # 笔记检索（BM25）
wechat.py        # 企业微信
wechat_crypto.py # 企业微信加解密
chat_cli.py      # 命令行聊天
scripts/sync_knowledge.py  # 同步本地笔记
tests/           # pytest
static/          # 网页版（带密码门）
```

## 本地跑

```bash
pip install -r requirements.txt
copy .env.example .env            # 填 DEEPSEEK_API_KEY
python scripts/sync_knowledge.py  # 可选，让笔记检索生效
uvicorn server:app --reload
```

## 环境变量

关键几个，全量见 `.env.example`：

| 变量 | 说明 |
|---|---|
| `DEEPSEEK_API_KEY` | DeepSeek 密钥 |
| `MEMORY_BACKEND` | `json`（本地）/ `upstash`（生产） |
| `UPSTASH_REDIS_REST_URL` / `TOKEN` | 云端记忆存储 |
| `API_TOKEN` | App 访问钥匙 |
| `WEB_PASSWORD` | 网页版密码 |
| `WECHAT_CORP_ID` / `AGENT_ID` / `SECRET` / `TOKEN` / `ENCODING_AES_KEY` | 企业微信 |
| `MAX_MEMORIES_TOTAL` / `PER_CATEGORY` / `RETRIEVE_TOP_K` | 记忆容量参数 |

## API

除 `/health`、`/my-ip`、`/wechat` 外，其余接口都要带 `X-API-Token`。

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/chat` | 非流式对话 |
| POST | `/chat/stream` | SSE 流式（App 用） |
| POST | `/reset` | 重新开始（保留记忆） |
| GET / DELETE | `/memories` | 看 / 清长期记忆 |
| GET | `/my-ip` | 查当前出口 IP（企业微信白名单用） |
| GET | `/health` | 健康检查 |

## 部署到 Vercel

1. upstash.com 建个免费 Redis，拿 REST URL 和 Token。
2. `python scripts/sync_knowledge.py` 同步笔记（生成 `knowledge/`，随部署上传；已 gitignore）。
3. Vercel 建项目，配好环境变量（`MEMORY_BACKEND=upstash`）。
4. 部署。访问 `/health` 看到 `memory_backend: upstash` 就成。

## 企业微信的一个坑

企业微信有「企业可信 IP」白名单，Vercel 的出口 IP 会变。IP 变了企业微信就回不了消息，报 60020。处理：访问 `/my-ip` 拿当前 IP，加进白名单。

## 隐私

三个东西不要传公开仓库：`persona_facts.py`（个人档案）、`.env`（密钥）、`knowledge/`（笔记）。都已 gitignore。

## 测试

```bash
python -m pytest -q
```
