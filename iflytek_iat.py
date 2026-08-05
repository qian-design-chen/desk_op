"""讯飞语音听写 WebAPI 客户端。

轻量实现，只依赖 websocket-client。音频格式固定为 16kHz 单声道 16bit PCM。
"""

import base64
import hashlib
import hmac
import json
import time
from datetime import datetime, timezone
from urllib.parse import quote

import websocket

HOST = "iat-api.xfyun.cn"
PATH = "/v2/iat"


class IATError(Exception):
    """讯飞接口返回的业务错误。"""

    def __init__(self, code, message):
        super().__init__(f"讯飞接口错误 {code}: {message}")
        self.code = code
        self.message = message


def _build_url(api_key, api_secret):
    """按讯飞 WebAPI 鉴权规范生成带签名的 WebSocket 地址。"""
    date = datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S GMT")
    signature_origin = f"host: {HOST}\ndate: {date}\nGET {PATH} HTTP/1.1"
    signature = base64.b64encode(
        hmac.new(
            api_secret.encode("ascii"),
            signature_origin.encode("utf-8"),
            hashlib.sha256,
        ).digest()
    ).decode("ascii")
    authorization_origin = (
        f'api_key="{api_key}", algorithm="hmac-sha256", '
        f'headers="host date request-line", signature="{signature}"'
    )
    authorization = base64.b64encode(
        authorization_origin.encode("utf-8")
    ).decode("ascii")
    return (
        f"wss://{HOST}{PATH}?authorization={authorization}"
        f"&date={quote(date)}&host={HOST}"
    )


def _merge_result(result, current):
    """把 wpgs 模式的增量结果合并成当前文本。"""
    if result.get("pgs") == "rpl":
        current = ""
    for ws in result.get("ws", []):
        for cw in ws.get("cw", []):
            word = cw.get("w")
            if word:
                current += word
    return current


def recognize_pcm(
    pcm,
    app_id,
    api_key,
    api_secret,
    *,
    language="zh_cn",
    accent="mandarin",
    sample_rate=16000,
    punctuation=True,
    on_partial=None,
    read_timeout=40,
    frame_interval=0.04,
):
    """识别一段 PCM 音频，返回识别文本。"""
    url = _build_url(api_key, api_secret)
    ws = websocket.create_connection(url, timeout=20, enable_multithread=True)
    try:
        common = {"app_id": app_id}
        business = {
            "language": language,
            "domain": "iat",
            "accent": accent,
            "vad_eos": 8000,
            "dwa": "wpgs",
            "ptt": 1 if punctuation else 0,
        }
        chunk_size = 6400
        offset = 0
        first = True
        while True:
            if offset >= len(pcm):
                status = 2
                audio = b""
            else:
                status = 0 if first else 1
                audio = pcm[offset : offset + chunk_size]
                offset += chunk_size
            frame = {
                "data": {
                    "status": status,
                    "format": f"audio/L16;rate={sample_rate}",
                    "encoding": "raw",
                    "audio": base64.b64encode(audio).decode("ascii"),
                },
            }
            if first:
                frame["common"] = common
                frame["business"] = business
            ws.send(json.dumps(frame, ensure_ascii=False))
            first = False
            if status == 2:
                break
            if frame_interval:
                time.sleep(frame_interval)

        ws.settimeout(read_timeout)
        current = ""
        final = ""
        while True:
            try:
                raw = ws.recv()
            except websocket.WebSocketTimeoutException as exc:
                raise IATError(0, "识别超时，请重试") from exc
            if not raw:
                continue
            msg = json.loads(raw)
            code = msg.get("code", -1)
            if code != 0:
                raise IATError(code, msg.get("message", "unknown"))
            data = msg.get("data", {})
            result = data.get("result")
            if result:
                current = _merge_result(result, current)
                final = current
                if on_partial:
                    on_partial(final)
            if data.get("status") == 2:
                break
        return final.strip()
    finally:
        try:
            ws.close()
        except Exception:
            pass


def recognize_wav(path, *args, **kwargs):
    """读取 WAV 文件并识别（要求 16kHz 单声道 16bit）。"""
    import wave

    with wave.open(path, "rb") as wav:
        if (
            wav.getnchannels() != 1
            or wav.getframerate() != 16000
            or wav.getsampwidth() != 2
        ):
            raise ValueError(
                "测试音频必须是 16000Hz、单声道、16bit 的 WAV 文件"
            )
        pcm = wav.readframes(wav.getnframes())
    return recognize_pcm(pcm, *args, **kwargs)
