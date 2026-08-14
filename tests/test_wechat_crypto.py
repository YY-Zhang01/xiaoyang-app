import base64
import os

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from wechat_crypto import WXBizMsgCrypt

# 43 个字符的测试 EncodingAESKey（对应 32 字节全零 AES 密钥）
KEY = "A" * 43
TOKEN = "xiaoyang666"
CORP_ID = "ww_test_corp"


def test_encrypt_decrypt_roundtrip():
    crypt = WXBizMsgCrypt(TOKEN, KEY, CORP_ID)
    msg = "<xml><MsgType><![CDATA[text]]></MsgType><Content><![CDATA[你好]]></Content></xml>"
    encrypted = crypt.encrypt(msg)
    assert crypt.decrypt(encrypted) == msg


def test_signature_verify():
    crypt = WXBizMsgCrypt(TOKEN, KEY, CORP_ID)
    encrypted = crypt.encrypt("hello")
    sig = crypt.signature("1234567890", "nonce", encrypted)
    assert crypt.verify_signature(sig, "1234567890", "nonce", encrypted) is True
    assert crypt.verify_signature("wrong", "1234567890", "nonce", encrypted) is False


def test_corp_id_mismatch_rejected():
    crypt = WXBizMsgCrypt(TOKEN, KEY, CORP_ID)
    encrypted = crypt.encrypt("hello")
    other = WXBizMsgCrypt(TOKEN, KEY, "ww_other_corp")
    try:
        other.decrypt(encrypted)
        assert False, "应当因 receiveid 不匹配而抛异常"
    except ValueError:
        pass


def test_32_byte_block_padding():
    """回归测试：企业微信用 32 字节块填充，且消息长到 pad>16 时也必须能解密。"""
    crypt = WXBizMsgCrypt(TOKEN, KEY, CORP_ID)
    msg = "你好世界" * 10  # 40 字节，容易让 pad 超过 16
    content = os.urandom(16) + len(msg.encode()).to_bytes(4, "big") + msg.encode() + CORP_ID.encode()
    # 按企业微信规范做 32 字节块 PKCS7 填充
    pad = 32 - (len(content) % 32)
    if pad == 0:
        pad = 32
    padded = content + bytes([pad]) * pad
    cipher = Cipher(algorithms.AES(crypt.aes_key), modes.CBC(crypt.aes_key[:16]))
    encryptor = cipher.encryptor()
    ciphertext = encryptor.update(padded) + encryptor.finalize()
    encrypted = base64.b64encode(ciphertext).decode()
    assert crypt.decrypt(encrypted) == msg


def test_echostr_flow():
    crypt = WXBizMsgCrypt(TOKEN, KEY, CORP_ID)
    echostr = crypt.encrypt("echo-ok")
    sig = crypt.signature("111", "222", echostr)
    assert crypt.decrypt_echostr(sig, "111", "222", echostr) == "echo-ok"
