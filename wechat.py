"""
小洋 —— 企业微信接入（次要渠道）

把企业微信当作小洋的一个"入口"：用户在企业微信发消息，小洋用同一套
人设 + 同一套记忆（按 wx:{user_id} 区分）回复。

回调消息采用企业微信的加密方案（AES），密钥全部走环境变量。
"""

import time
import xml.etree.ElementTree as ET

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import Response

from config import get_settings
from llm import DeepSeekClient
from memory import MemoryManager, get_memory_store
from wechat_crypto import WXBizMsgCrypt

router = APIRouter()


def _get_crypt(settings) -> WXBizMsgCrypt:
    if not settings.wechat_encoding_aes_key:
        raise ValueError("WECHAT_ENCODING_AES_KEY 未配置")
    return WXBizMsgCrypt(
        settings.wechat_token,
        settings.wechat_encoding_aes_key,
        settings.wechat_corp_id,
    )


@router.get("/wechat")
def wechat_verify(msg_signature: str, timestamp: str, nonce: str, echostr: str):
    """URL 验证：校验签名 + 解密 echostr 后原样返回。"""
    settings = get_settings()
    try:
        plain = _get_crypt(settings).decrypt_echostr(msg_signature, timestamp, nonce, echostr)
        return Response(content=plain, media_type="text/plain")
    except Exception as e:
        print(f"[微信验证失败] {e}")
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
        resp = httpx.post(
            f"https://qyapi.weixin.qq.com/cgi-bin/message/send?access_token={token}",
            json={
                "touser": user_id,
                "msgtype": "text",
                "agentid": settings.wechat_agent_id,
                "text": {"content": content},
            },
            timeout=10,
        )
        data = resp.json()
        print(f"[微信发送] touser={user_id} agentid={settings.wechat_agent_id} errcode={data.get('errcode')} errmsg={data.get('errmsg')}")
    except Exception as e:
        print(f"[微信发送失败] {e}")


@router.post("/wechat")
async def wechat_receive(request: Request):
    settings = get_settings()
    try:
        body = (await request.body()).decode("utf-8")
        root = ET.fromstring(body)

        # 加密模式：密文包在 <Encrypt> 里，需要先解密
        encrypt = root.findtext("Encrypt")
        if encrypt is not None:
            crypt = _get_crypt(settings)
            msg_signature = request.query_params.get("msg_signature", "")
            timestamp = request.query_params.get("timestamp", "")
            nonce = request.query_params.get("nonce", "")
            if not crypt.verify_signature(msg_signature, timestamp, nonce, encrypt):
                raise ValueError("签名校验失败")
            root = ET.fromstring(crypt.decrypt(encrypt))

        msg_type = root.findtext("MsgType") or ""
        user_id = root.findtext("FromUserName") or ""
        content = root.findtext("Content") or ""
        print(f"[微信收到] user={user_id} type={msg_type} msg={content[:40]}")
        if msg_type != "text" or not content or not user_id:
            return Response(content="success")

        llm = DeepSeekClient(settings)
        store = get_memory_store(settings)
        # 三个入口（App / 网页 / 企业微信）共用同一份记忆，都归到 settings.user_id
        mgr = MemoryManager(settings.user_id, store, llm, settings)
        msgs = mgr.messages_for_llm(content)
        msgs.append({"role": "user", "content": content})
        reply = llm.chat(msgs)
        mgr.record_turn(content, reply)
        _send_wx_message(settings, user_id, reply)
    except Exception as e:
        print(f"[微信错误] {e}")
    return Response(content="success")
