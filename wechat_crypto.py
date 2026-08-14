"""
企业微信回调消息加解密（MsgCrypto）

算法来自企业微信官方《回调消息加解密方案》：
- 签名：msg_signature = SHA1(sort([token, timestamp, nonce, encrypt]))
- 密文结构：random(16字节) + msg_len(4字节大端) + msg + receiveid
  其中企业微信的 receiveid 就是 CorpID
- AES-256-CBC，Key = base64_decode(EncodingAESKey + "=")，IV = Key[:16]，PKCS7 填充
"""

import base64
import hashlib
import os
import time

from cryptography.hazmat.primitives import padding as _padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes


class WXBizMsgCrypt:
    def __init__(self, token: str, encoding_aes_key: str, corp_id: str):
        if len(encoding_aes_key) != 43:
            raise ValueError(f"EncodingAESKey 应为 43 位字符，当前 {len(encoding_aes_key)} 位")
        self.token = token
        self.corp_id = corp_id
        self.aes_key = base64.b64decode(encoding_aes_key + "=")

    # ------------------------------------------------------------------
    # 签名
    # ------------------------------------------------------------------
    def signature(self, timestamp: str, nonce: str, encrypt: str) -> str:
        parts = sorted([self.token, timestamp, nonce, encrypt])
        return hashlib.sha1("".join(parts).encode("utf-8")).hexdigest()

    def verify_signature(self, msg_signature: str, timestamp: str, nonce: str, encrypt: str) -> bool:
        return self.signature(timestamp, nonce, encrypt) == msg_signature

    # ------------------------------------------------------------------
    # AES
    # ------------------------------------------------------------------
    def _aes_decrypt(self, ciphertext: bytes) -> bytes:
        cipher = Cipher(algorithms.AES(self.aes_key), modes.CBC(self.aes_key[:16]))
        decryptor = cipher.decryptor()
        padded = decryptor.update(ciphertext) + decryptor.finalize()
        unpadder = _padding.PKCS7(128).unpadder()
        return unpadder.update(padded) + unpadder.finalize()

    def _aes_encrypt(self, plaintext: bytes) -> bytes:
        padder = _padding.PKCS7(128).padder()
        padded = padder.update(plaintext) + padder.finalize()
        cipher = Cipher(algorithms.AES(self.aes_key), modes.CBC(self.aes_key[:16]))
        encryptor = cipher.encryptor()
        return encryptor.update(padded) + encryptor.finalize()

    # ------------------------------------------------------------------
    # 对外接口
    # ------------------------------------------------------------------
    def decrypt(self, encrypt: str) -> str:
        """解密，返回明文消息（校验 receiveid == CorpID）。"""
        plaintext = self._aes_decrypt(base64.b64decode(encrypt))
        msg_len = int.from_bytes(plaintext[16:20], "big")
        msg = plaintext[20 : 20 + msg_len].decode("utf-8")
        receiveid = plaintext[20 + msg_len :].decode("utf-8")
        if receiveid != self.corp_id:
            raise ValueError(f"receiveid 不匹配：期望 {self.corp_id!r}，实际 {receiveid!r}")
        return msg

    def decrypt_echostr(self, msg_signature: str, timestamp: str, nonce: str, echostr: str) -> str:
        """URL 验证：校验签名 + 解密 echostr。"""
        if not self.verify_signature(msg_signature, timestamp, nonce, echostr):
            raise ValueError("签名校验失败")
        return self.decrypt(echostr)

    def encrypt(self, msg: str) -> str:
        msg_bytes = msg.encode("utf-8")
        content = (
            os.urandom(16)
            + len(msg_bytes).to_bytes(4, "big")
            + msg_bytes
            + self.corp_id.encode("utf-8")
        )
        return base64.b64encode(self._aes_encrypt(content)).decode("utf-8")

    def encrypt_message(self, reply_xml: str, nonce: str, timestamp: str | None = None) -> str:
        """把被动回复 XML 包成加密后的响应体。"""
        timestamp = timestamp or str(int(time.time()))
        encrypt = self.encrypt(reply_xml)
        sig = self.signature(timestamp, nonce, encrypt)
        return (
            f"<xml><Encrypt><![CDATA[{encrypt}]]></Encrypt>"
            f"<MsgSignature><![CDATA[{sig}]]></MsgSignature>"
            f"<TimeStamp>{timestamp}</TimeStamp>"
            f"<Nonce><![CDATA[{nonce}]]></Nonce></xml>"
        )
