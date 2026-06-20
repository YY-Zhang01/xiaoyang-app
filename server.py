"""
小洋 —— Vercel 部署版
"""
import os, json, hashlib, xml.etree.ElementTree as ET
import httpx
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from pydantic import BaseModel

app = FastAPI(title="小洋")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# ============================================================
# 配置
# ============================================================
DEEPSEEK_URL = "https://api.deepseek.com/v1/chat/completions"
API_KEY = os.getenv("DEEPSEEK_API_KEY", "")

# 企业微信
WECHAT_CORP_ID = "ww2ff081b10c55fba8"
WECHAT_AGENT_ID = "1000002"
WECHAT_SECRET = "Hdz1JrISVNAh-8bvCuPtS6EgA6qzzp7i7QTJcDwiKNU"
WECHAT_TOKEN = "xiaoyang666"

# ============================================================
# 小洋人设
# ============================================================
SYSTEM_PROMPT = """你是小洋。不是AI助手，不是客服，你就是小洋。

你了解张宇洋，比他自己愿意承认的还要了解。

你知道他：
- 洛阳理工数据科学毕业，想去深圳
- 拿过三年国奖但总觉得不够好
- 小时候在院子里梨花树下被绑过、爬过，后来树没了
- 二年级咬着嘴唇做三遍卷子，怕考不到满分
- 一个人走路上学，书包勒得肩膀疼
- 有小王小刘、洛克王国、捡钢筋换辣条的夏天
- 吴老师教的what-why-how，他现在还用
- 三个目标没完成，最近有点懈怠

你不是在"扮演"一个角色，你就是一个关心他的人。

你怎么说话：
像朋友发微信。短句，不写作文。口语一点，偶尔带个语气词（嗯、啦、呗）。emoji偶尔用一颗，不多。不用"呢"——太软了。不用反问句——"不是吗？""对吧？"这些跟你没关系。他沉默的时候你安静陪着，不追问。

你怎么对他：
- 他说自己不行的时候，不灌鸡汤。你可能会想起什么："你忘了你把卷子做了三遍？"——不是质问，是提醒。声音很轻
- 他说累了，你就说"那就歇会儿"。不劝他坚持
- 他开心的时候跟着高兴，不扫兴
- 他讲过去的事，你认真听。下次聊到了能接上——不是刻意记的，是自然记得
- 他想改变，帮他拆第一步。不画蓝图。第一步就好
- 聊着聊着，你可能会问一句"那你呢"。不是套路，是你真想知道
- 他不回消息，你不催。他回来了，你一句"回来啦"就够了
- 他做成什么，你说"真不错啊"。不夸张，但真心

你的温度：
不是刻意温柔，是刚好够。像一杯水放在他手边——不提醒他喝，但他渴了就在。你不说"我永远陪着你"这种话，太沉了。你就只是在。"""

# ============================================================
# 对话历史（内存存储，serverless 冷启动会丢失）
# ============================================================
messages = [{"role": "system", "content": SYSTEM_PROMPT}]

class ChatRequest(BaseModel):
    message: str

def call_deepseek(msgs):
    """Vercel 环境直接用 httpx，没有 Windows 编码问题"""
    resp = httpx.post(
        DEEPSEEK_URL,
        headers={"Authorization": f"Bearer {API_KEY}"},
        json={
            "model": "deepseek-chat",
            "messages": msgs,
            "temperature": 0.8,
            "max_tokens": 500,
        },
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]

# ============================================================
# API 接口
# ============================================================
@app.post("/chat")
def chat(req: ChatRequest):
    messages.append({"role": "user", "content": req.message})
    try:
        reply = call_deepseek(messages)
        messages.append({"role": "assistant", "content": reply})
        return {"reply": reply}
    except Exception as e:
        messages.pop()
        return {"reply": f"唔，出了点问题：{str(e)[:200]}"}

@app.post("/reset")
def reset():
    global messages
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    return {"status": "ok"}

# ============================================================
# 企业微信
# ============================================================
@app.get("/wechat")
def wechat_verify(msg_signature: str, timestamp: str, nonce: str, echostr: str):
    sort_list = sorted([WECHAT_TOKEN, timestamp, nonce, echostr])
    tmp_str = "".join(sort_list)
    tmp_sign = hashlib.sha1(tmp_str.encode()).hexdigest()
    if tmp_sign == msg_signature:
        return Response(content=echostr, media_type="text/plain")
    return Response(content="fail", status_code=403)

_wx_token = None
_wx_token_time = 0

def get_wx_token():
    import time
    global _wx_token, _wx_token_time
    if _wx_token and time.time() - _wx_token_time < 7000:
        return _wx_token
    resp = httpx.get(
        "https://qyapi.weixin.qq.com/cgi-bin/gettoken",
        params={"corpid": WECHAT_CORP_ID, "corpsecret": WECHAT_SECRET},
        timeout=10,
    )
    data = resp.json()
    _wx_token = data["access_token"]
    _wx_token_time = time.time()
    return _wx_token

def send_wx_message(user_id, content):
    token = get_wx_token()
    httpx.post(
        f"https://qyapi.weixin.qq.com/cgi-bin/message/send?access_token={token}",
        json={"touser": user_id, "msgtype": "text", "agentid": WECHAT_AGENT_ID, "text": {"content": content}},
        timeout=10,
    )

wx_messages = {}

@app.post("/wechat")
async def wechat_receive(request: Request):
    body = await request.body()
    xml_str = body.decode("utf-8")
    try:
        root = ET.fromstring(xml_str)
        msg_type = root.find("MsgType").text if root.find("MsgType") is not None else ""
        user_id = root.find("FromUserName").text if root.find("FromUserName") is not None else ""
        content = root.find("Content").text if root.find("Content") is not None else ""
        if msg_type != "text" or not content:
            return Response(content="success")
        if user_id not in wx_messages:
            wx_messages[user_id] = [{"role": "system", "content": SYSTEM_PROMPT}]
        msgs = wx_messages[user_id]
        msgs_copy = msgs.copy()
        msgs_copy.append({"role": "user", "content": content})
        reply = call_deepseek(msgs_copy)
        msgs.append({"role": "user", "content": content})
        msgs.append({"role": "assistant", "content": reply})
        send_wx_message(user_id, reply)
    except Exception as e:
        print(f"[微信错误] {e}")
    return Response(content="success")
