"""
小洋 —— 企业微信接入（次要渠道）

把企业微信当作小洋的一个"入口"：用户在企业微信发消息，小洋用同一套
人设 + 同一套记忆（按 wx:{user_id} 区分）回复。密钥全部走环境变量。
"""

import hashlib
import time
import xml.etree.ElementTree as ET

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import Response

from config import get_settings
from llm import DeepSeekClient
from memory import MemoryManager, get_memory_store

router = APIRouter()


def _verify(settings, msg_signature: str, timestamp: str, nonce: str, echostr: str) -> bool:
    sort_list = sorted([settings.wechat_token, timestamp, nonce, echostr])
    tmp_sign = hashlib.sha1("".join(sort_list).encode(), usedforsecurity=False).hexdigest()
    return tmp_sign == msg_signature


@router.get("/wechat")
def wechat_verify(msg_signature: str, timestamp: str, nonce: str, echostr: str):
    settings = get_settings()
    if _verify(settings, msg_signature, timestamp, nonce, echostr):
        return Response(content=echostr, media_type="text/plain")
    return Response(content="fail", status_code=403)


# ---- token 缓存（serverless 冷启动会重置，重新获取即可）----
_wx_token_cache: dict = {}


def _get_wx_token(settings) -> str:
    cached = _wx_token_cache.get("token")
    cached_time = _wx_token_cache.get("time", 0)
    if cached and time.time() - cached_time < 7000:
        return cached
    resp = httpx.get(
        "https://qyapi.weixin.qq.com/cgi-bin/gettoken",
        params={"corpid": settings.wechat_corp_id, "corpsecret": settings.wechat_secret},
        timeout=10,
    )
    resp.raise_for_status()
    token = resp.json()["access_token"]
    _wx_token_cache["token"] = token
    _wx_token_cache["time"] = time.time()
    return token


def _send_wx_message(settings, user_id: str, content: str) -> None:
    if not settings.wechat_corp_id or not settings.wechat_secret or not settings.wechat_agent_id:
        print("[微信] 未配置企业微信凭据，跳过发送")
        return
    try:
        token = _get_wx_token(settings)
        httpx.post(
            f"https://qyapi.weixin.qq.com/cgi-bin/message/send?access_token={token}",
            json={
                "touser": user_id,
                "msgtype": "text",
                "agentid": settings.wechat_agent_id,
                "text": {"content": content},
            },
            timeout=10,
        )
    except Exception as e:
        print(f"[微信发送失败] {e}")


@router.post("/wechat")
async def wechat_receive(request: Request):
    settings = get_settings()
    try:
        root = ET.fromstring((await request.body()).decode("utf-8"))
    except Exception as e:
        print(f"[微信] XML 解析失败: {e}")
        return Response(content="success")

    try:
        msg_type = root.findtext("MsgType") or ""
        user_id = root.findtext("FromUserName") or ""
        content = root.findtext("Content") or ""
        if msg_type != "text" or not content or not user_id:
            return Response(content="success")

        llm = DeepSeekClient(settings)
        store = get_memory_store(settings)
        mgr = MemoryManager(f"wx:{user_id}", store, llm, settings)
        msgs = mgr.messages_for_llm()
        msgs.append({"role": "user", "content": content})
        reply = llm.chat(msgs)
        mgr.record_turn(content, reply)
        _send_wx_message(settings, user_id, reply)
    except Exception as e:
        print(f"[微信错误] {e}")
    return Response(content="success")
