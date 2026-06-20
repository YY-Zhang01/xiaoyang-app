# 小洋

只属于张宇洋的 AI 伙伴。

## 项目结构

```
├── server.py          # FastAPI 后端（聊天 + 企业微信）
├── chat_cli.py        # 命令行聊天
├── static/            # 前端页面 + PWA
│   ├── index.html
│   ├── manifest.json
│   ├── sw.js
│   └── icon-*.png
├── vercel.json        # Vercel 部署配置
├── requirements.txt   # Python 依赖
└── .gitignore
```

## 本地运行

```bash
pip install -r requirements.txt
uvicorn server:app --reload
```

## 环境变量

| 变量 | 说明 |
|------|------|
| `DEEPSEEK_API_KEY` | DeepSeek API 密钥 |

## 部署

Vercel 一键部署，支持企业微信回调。
