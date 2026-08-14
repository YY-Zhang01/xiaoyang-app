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


def test_echostr_flow():
    crypt = WXBizMsgCrypt(TOKEN, KEY, CORP_ID)
    echostr = crypt.encrypt("echo-ok")
    sig = crypt.signature("111", "222", echostr)
    assert crypt.decrypt_echostr(sig, "111", "222", echostr) == "echo-ok"
