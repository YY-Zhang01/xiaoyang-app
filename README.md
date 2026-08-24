# 小洋 · 后端（个人 AI 伴侣）

工程目录：`xiaoyang-app/`
部署位置：Vercel serverless（域名 zyy-xiaoyang.xyz）

本文档以当前代码为准。

## 一、目录结构

```text
xiaoyang-app/
├── server.py        FastAPI 入口，只做接线
├── config.py        配置，全部走环境变量
├── prompt.py        人设模板（公开，不含隐私）
├── persona_facts.py 你的个人档案（gitignore，不上传）
├── llm.py           DeepSeek 客户端（流式 + 非流式 + 记忆摘要）
├── memory.py        记忆层（对话历史 + 长期记忆 + 相关度检索）
├── rag.py           笔记检索（BM25）
├── wechat.py        企业微信接入
├── wechat_crypto.py 企业微信加解密
├── chat_cli.py      命令行聊天
├── scripts/
│   ├── sync_knowledge.py   同步本地笔记到 knowledge/
│   └── check_upstash.py    Upstash 连通性自检
├── tests/           pytest
├── static/          网页版（带密码门）
├── knowledge/       笔记（gitignore，部署时上传）
└── requirements.txt 依赖
```

## 二、项目工作流程

```text
用户发消息（App / 网页 / 企业微信）
    │
    ▼
校验访问令牌（API_TOKEN / 网页密码 / 企业微信签名）
    │
    ▼
加载记忆（Upstash）
    ├── 读最近对话历史
    └── 读长期记忆
    │
    ▼
组装 system prompt
    ├── 人设（prompt.py 模板 + persona_facts.py 档案）
    └── 按当前话题挑相关记忆（关键词相关度 + 重要度）
    │
    ▼
RAG 检索笔记（BM25），命中则注入上下文
    │
    ▼
调 DeepSeek（流式返回给 App）
    │
    ▼
记录本轮对话；对话过长时摘要成长期记忆（分类 + 打分）
    │
    ▼
写回 Upstash
```

## 三、依赖

依赖文件：`requirements.txt`

```text
fastapi>=0.100.0
httpx>=0.24.0
uvicorn>=0.22.0
pydantic>=2.0.0
cryptography>=41.0.0
```

| 依赖 | 用途 |
|---|---|
| FastAPI、Uvicorn | 后端 API |
| httpx | 调 DeepSeek、Upstash、企业微信 |
| Pydantic | 请求校验 |
| cryptography | 企业微信消息加解密 |

运行环境：Vercel 自动用 Python 3.12 安装（serverless，无本地服务器）。

## 四、记忆系统

### 1. 两层记忆

| 层 | 存什么 | 说明 |
|---|---|---|
| 对话历史 | 最近 20 条完整消息 | 超过 32 条就把旧的摘要掉 |
| 长期记忆 | 摘要出的事实，最多 300 条 | 每条带分类 + 重要度 |

### 2. 摘要、分类、打分

对话超过阈值时，把溢出部分交给 DeepSeek 摘要，要求输出「分类|重要度|内容」格式：

- 分类：个人 / 目标 / 健康 / 学习 / 情绪 / 其他
- 重要度：1-5 分

### 3. 检索

聊天时按当前话题挑记忆注入 prompt：关键词相关度（复用 rag.py 的中文分词）+ 重要度，加权排序取前 8 条。没命中关键词就按重要度排，保证核心记忆在场。

### 4. 淘汰

容量满时按「重要度低、更旧」先删；每个分类有独立上限（50 条），防止某一类刷屏挤掉别的。

### 5. 存储

- 本地开发：`json`（data/memory.json）
- 生产：Upstash Redis REST，键 `xiaoyang:{user_id}:conversation` / `xiaoyang:{user_id}:memories`

## 五、企业微信

### 1. 加解密

企业微信回调消息是 AES 加密的，`wechat_crypto.py` 实现官方算法：

- 签名 `SHA1(sort(token, timestamp, nonce, encrypt))`
- AES-256-CBC，Key 来自 EncodingAESKey，IV=Key[:16]，PKCS7 32 字节块

### 2. 收发流程

1. 企业微信 POST 加密消息到 `/wechat`
2. 校验签名 → 解密 → 解析文本
3. 走同一套记忆 + DeepSeek 生成回复
4. 调 `message/send` 主动发回

### 3. IP 白名单坑

企业微信有「企业可信 IP」白名单，Vercel 出口 IP 会变。变了就报 60020 回不了消息。处理：访问 `/my-ip` 拿当前 IP，加进白名单。

## 六、运行与部署

本地运行：

```bash
pip install -r requirements.txt
copy .env.example .env
python scripts/sync_knowledge.py
uvicorn server:app --reload
```

部署到 Vercel：

```bash
npx vercel deploy --prod --yes --token <VERCEL_TOKEN>
```

环境变量见 `.env.example`。关键：`DEEPSEEK_API_KEY`、`MEMORY_BACKEND=upstash`、`UPSTASH_REDIS_REST_URL/TOKEN`、`API_TOKEN`、`WEB_PASSWORD`、`WECHAT_*`。

## 七、外部服务

| 服务 | 用途 |
|---|---|
| DeepSeek | 对话生成、记忆摘要 |
| Upstash Redis | 长期记忆和对话历史存储 |
| Vercel | 后端运行（serverless） |
| 企业微信 | 一个聊天入口 |

## 八、安全与隐私

- 聊天接口要带 `X-API-Token`（App 用）或网页密码（网页版用），否则 401。
- `persona_facts.py`（个人档案）、`.env`（密钥）、`knowledge/`（笔记）已 gitignore，不上传公开仓库。

## 九、测试

```bash
python -m pytest -q
```

覆盖：记忆读写、摘要与淘汰、相关度检索、企业微信加解密、BM25 检索与中文分词。
