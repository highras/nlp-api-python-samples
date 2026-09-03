#!/usr/bin/env python3
"""云上曲率 TTS WebSocket 流式合成 Python 接入示例。

依赖安装：
    python3 -m pip install "websockets>=12,<18"

方式一：通过执行参数传入凭证（最高优先级）
    python3 speech_synthesis.py \
      --app-id your_app_id \
      --secret-key 'your_secret_key' \
      --text '您好，这是一个 WebSocket 流式语音合成示例。' \
      --voice CHINESE_SC_ADS_BRAND \
      --format mp3 \
      --output output.mp3

方式二：通过环境变量传入凭证
    export ILIVEDATA_APP_ID='your_app_id'
    export ILIVEDATA_SECRET_KEY='your_secret_key'
    python3 speech_synthesis.py --text '您好，这是一个合成示例。'

方式三：修改下方 INITIAL_APP_ID 和 INITIAL_SECRET_KEY 初始化值
    INITIAL_APP_ID = 0  # 将 0 替换为实际的 your_app_id（整数）
    INITIAL_SECRET_KEY = "your_secret_key"
    设置后运行：python3 speech_synthesis.py --text '您好，这是一个合成示例。'

凭证优先级：执行参数 > 环境变量 > 脚本内初始化值。

运行 python3 speech_synthesis.py --help 可查看全部参数。
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import hashlib
import hmac
import json
import os
import ssl
import struct
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, BinaryIO
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from urllib.request import Request, urlopen


DEFAULT_TOKEN_URL = "https://tts.ilivedata.com/api/v2/speech/synthesis/ws-token"

# 可直接在脚本内填写。执行参数和环境变量未设置时，才会使用这里的值。
INITIAL_APP_ID = 0
INITIAL_SECRET_KEY = ""


class TtsApiError(RuntimeError):
    """服务端返回的可读错误。"""


class AudioFileWriter:
    """按请求格式写入流式音频；WAV 分片会合并为一个 RIFF 容器。"""

    def __init__(self, output: BinaryIO, audio_format: str):
        self.output = output
        self.audio_format = audio_format
        self.wav_format_chunk: bytes | None = None
        self.wav_data_size = 0
        self.wav_data_size_offset: int | None = None

    def write(self, chunk: bytes) -> None:
        if self.audio_format != "wav":
            # PCM 是裸采样数据，MP3 是可连续解码的 MPEG 音频帧，均可顺序追加。
            self.output.write(chunk)
            return

        format_chunk, data_chunks = self._parse_wav(chunk)
        if self.wav_format_chunk is None:
            self._write_wav_header(format_chunk)
        elif format_chunk != self.wav_format_chunk:
            raise TtsApiError("WAV chunks have inconsistent fmt parameters")

        for data in data_chunks:
            self.output.write(data)
            self.wav_data_size += len(data)

    def finalize(self) -> None:
        if self.audio_format != "wav":
            return
        if self.wav_format_chunk is None or self.wav_data_size_offset is None:
            raise TtsApiError("No valid WAV audio chunk was received")
        if self.wav_data_size > 0xFFFFFFFF:
            raise TtsApiError("WAV audio data exceeds the RIFF 4 GiB size limit")

        if self.wav_data_size % 2:
            self.output.write(b"\x00")
        file_size = self.output.tell()
        riff_size = file_size - 8
        if riff_size > 0xFFFFFFFF:
            raise TtsApiError("WAV file exceeds the RIFF 4 GiB size limit")

        self.output.seek(4)
        self.output.write(struct.pack("<I", riff_size))
        self.output.seek(self.wav_data_size_offset)
        self.output.write(struct.pack("<I", self.wav_data_size))
        self.output.seek(file_size)

    def _write_wav_header(self, format_chunk: bytes) -> None:
        self.wav_format_chunk = format_chunk
        self.output.write(b"RIFF\x00\x00\x00\x00WAVE")
        self.output.write(b"fmt ")
        self.output.write(struct.pack("<I", len(format_chunk)))
        self.output.write(format_chunk)
        if len(format_chunk) % 2:
            self.output.write(b"\x00")
        self.output.write(b"data")
        self.wav_data_size_offset = self.output.tell()
        self.output.write(b"\x00\x00\x00\x00")

    @staticmethod
    def _parse_wav(chunk: bytes) -> tuple[bytes, list[bytes]]:
        if len(chunk) < 12 or chunk[:4] != b"RIFF" or chunk[8:12] != b"WAVE":
            raise TtsApiError("WAV audio chunk is not a RIFF/WAVE file")

        riff_end = struct.unpack_from("<I", chunk, 4)[0] + 8
        if riff_end > len(chunk):
            raise TtsApiError("WAV audio chunk is truncated")

        format_chunk: bytes | None = None
        data_chunks: list[bytes] = []
        offset = 12
        while offset + 8 <= riff_end:
            chunk_id = chunk[offset:offset + 4]
            chunk_size = struct.unpack_from("<I", chunk, offset + 4)[0]
            data_start = offset + 8
            data_end = data_start + chunk_size
            if data_end > riff_end:
                raise TtsApiError("WAV subchunk is truncated")
            if chunk_id == b"fmt " and format_chunk is None:
                format_chunk = chunk[data_start:data_end]
            elif chunk_id == b"data":
                data_chunks.append(chunk[data_start:data_end])
            offset = data_end + (chunk_size % 2)

        if format_chunk is None:
            raise TtsApiError("WAV audio chunk misses the fmt subchunk")
        if not data_chunks:
            raise TtsApiError("WAV audio chunk misses the data subchunk")
        return format_chunk, data_chunks


def utc_timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def create_signature(app_id: int, secret_key: str, timestamp: str, token_url: str) -> str:
    """按 GET 无请求体规则计算 HMAC-SHA256 + Base64 签名。"""
    parsed = urlsplit(token_url)
    if parsed.scheme != "https" or not parsed.hostname:
        raise ValueError("token URL must be an absolute HTTPS URL")

    host = parsed.netloc.lower()
    path = parsed.path or "/"
    lines = ["GET", host, path]
    if parsed.query:
        canonical_query = urlencode(sorted(parse_qsl(parsed.query, keep_blank_values=True)))
        lines.append(canonical_query)
    lines.extend([f"X-AppId:{app_id}", f"X-TimeStamp:{timestamp}"])
    string_to_sign = "\n".join(lines)

    digest = hmac.new(
        secret_key.encode("utf-8"),
        string_to_sign.encode("utf-8"),
        hashlib.sha256,
    ).digest()
    return base64.b64encode(digest).decode("ascii")


def create_ssl_context(ca_file: str | None, insecure: bool) -> ssl.SSLContext:
    if insecure:
        print("WARNING: TLS certificate verification is disabled", file=sys.stderr)
        return ssl._create_unverified_context()
    return ssl.create_default_context(cafile=ca_file)


def get_ws_token(
    app_id: int,
    secret_key: str,
    token_url: str,
    timeout: float,
    ssl_context: ssl.SSLContext,
) -> dict[str, Any]:
    timestamp = utc_timestamp()
    signature = create_signature(app_id, secret_key, timestamp, token_url)
    request = Request(
        token_url,
        method="GET",
        headers={
            "X-AppId": str(app_id),
            "X-TimeStamp": timestamp,
            "Authorization": signature,
            "Accept": "application/json",
        },
    )

    try:
        with urlopen(request, timeout=timeout, context=ssl_context) as response:
            body = response.read().decode("utf-8")
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise TtsApiError(f"Token request failed: HTTP {exc.code}, body={body}") from exc
    except URLError as exc:
        raise TtsApiError(f"Token request failed: {exc.reason}") from exc

    try:
        result = json.loads(body)
    except json.JSONDecodeError as exc:
        raise TtsApiError(f"Token response is not JSON: {body}") from exc

    if not result.get("token") or not result.get("wsUrl"):
        raise TtsApiError(f"Token response misses token/wsUrl: {result}")
    return result


def websocket_url(ws_url: str, token: str) -> str:
    parsed = urlsplit(ws_url)
    query = parse_qsl(parsed.query, keep_blank_values=True)
    query.append(("token", token))
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(query), parsed.fragment))


def build_payload(args: argparse.Namespace) -> dict[str, Any]:
    request: dict[str, Any] = {
        "appId": args.app_id,
        "text": args.text,
        "language": args.language,
        "output": {"format": args.format},
    }

    voice = {key: value for key, value in {
        "name": args.voice,
        "audio": args.voice_audio,
        "emotion": args.emotion,
    }.items() if value is not None}
    if voice:
        request["voice"] = voice

    if args.speed is not None:
        request["output"]["speed"] = args.speed
    if args.loudness_lufs is not None:
        request["output"]["loudnessLufs"] = args.loudness_lufs

    payload: dict[str, Any] = {"appId": args.app_id, "request": request}
    if args.session_id:
        payload["sessionId"] = args.session_id
    return payload


async def synthesize(args: argparse.Namespace, secret_key: str) -> None:
    try:
        import websockets
    except ImportError as exc:
        raise RuntimeError(
            "Missing dependency 'websockets'. Install it with: "
            "python3 -m pip install -r docs/client/requirements-websocket.txt"
        ) from exc

    ssl_context = create_ssl_context(args.ca_file, args.insecure)
    token_result = await asyncio.to_thread(
        get_ws_token,
        args.app_id,
        secret_key,
        args.token_url,
        args.http_timeout,
        ssl_context,
    )
    ws_url = websocket_url(str(token_result["wsUrl"]), str(token_result["token"]))
    payload = build_payload(args)
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = tempfile.NamedTemporaryFile(
        prefix=f".{output_path.name}.",
        suffix=".part",
        dir=output_path.parent,
        delete=False,
    )
    part_path = Path(temporary.name)
    temporary.close()

    task_id = ""
    chunks = 0
    total_bytes = 0
    completed = False

    print(f"Connecting to {token_result['wsUrl']}")
    try:
        connect_options: dict[str, Any] = {
            "open_timeout": args.connect_timeout,
            "max_size": 50 * 1024 * 1024,
        }
        if urlsplit(ws_url).scheme == "wss":
            connect_options["ssl"] = ssl_context
        async with websockets.connect(ws_url, **connect_options) as websocket:
            with part_path.open("wb") as audio_file:
                audio_writer = AudioFileWriter(audio_file, args.format)
                await websocket.send(json.dumps(payload, ensure_ascii=False))

                async for raw_message in websocket:
                    if not isinstance(raw_message, str):
                        raise TtsApiError("Unexpected binary WebSocket message")
                    try:
                        event = json.loads(raw_message)
                    except json.JSONDecodeError as exc:
                        raise TtsApiError(f"WebSocket message is not JSON: {raw_message}") from exc

                    event_type = event.get("event")
                    task_id = event.get("taskId") or task_id
                    if event_type == "init":
                        print(f"Task initialized: taskId={task_id}, sessionId={event.get('sessionId')}")
                    elif event_type == "audio":
                        try:
                            chunk = base64.b64decode(event.get("audioBase64", ""), validate=True)
                        except (ValueError, TypeError) as exc:
                            raise TtsApiError(f"Invalid audioBase64 in seq={event.get('seq')}") from exc
                        audio_writer.write(chunk)
                        chunks += 1
                        total_bytes += len(chunk)
                        print(
                            f"Audio chunk: seq={event.get('seq')}, bytes={len(chunk)}, "
                            f"durationMs={event.get('durationMs')}"
                        )
                    elif event_type == "done":
                        completed = True
                        print(f"Task completed: taskId={task_id}, remoteUrl={event.get('url')}")
                        break
                    elif event_type == "error":
                        raise TtsApiError(
                            f"Synthesis failed: code={event.get('errorCode')}, "
                            f"message={event.get('errorMessage')}"
                        )
                    else:
                        print(f"Ignored unknown event: {event_type}")
                if completed:
                    audio_writer.finalize()
    except Exception:
        if part_path.exists():
            part_path.unlink()
        raise

    if not completed:
        if part_path.exists():
            part_path.unlink()
        raise TtsApiError("WebSocket closed before the done event")

    part_path.replace(output_path)
    print(
        f"Saved {chunks} chunks ({total_bytes} received bytes, "
        f"{output_path.stat().st_size} file bytes) to {output_path}"
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="云上曲率 TTS WebSocket 流式合成 demo")
    parser.add_argument(
        "--app-id",
        type=int,
        help="appId；优先级高于 ILIVEDATA_APP_ID 和脚本内 INITIAL_APP_ID",
    )
    parser.add_argument(
        "--secret-key",
        help="secretKey；优先级高于 ILIVEDATA_SECRET_KEY 和脚本内 INITIAL_SECRET_KEY",
    )
    parser.add_argument("--text", required=True, help="待合成文本")
    voice_group = parser.add_mutually_exclusive_group()
    voice_group.add_argument("--voice", help="预置或已注册的音色名称")
    voice_group.add_argument("--voice-audio", help="用于音色克隆的音频 URL")
    parser.add_argument("--emotion", help="情感参数")
    parser.add_argument("--language", default="zh-CN", help="文本语种，默认 zh-CN")
    parser.add_argument("--format", choices=("pcm", "wav", "mp3"), default="wav")
    parser.add_argument("--output", default=None, help="本地输出文件，默认 output.<format>")
    parser.add_argument("--speed", type=float, help="语速倍率，范围 0.5 到 2.0")
    parser.add_argument("--loudness-lufs", type=float, help="目标响度，范围 -30.0 到 -6.0")
    parser.add_argument("--session-id", help="可选业务会话 ID")
    parser.add_argument("--token-url", default=DEFAULT_TOKEN_URL)
    tls_group = parser.add_mutually_exclusive_group()
    tls_group.add_argument("--ca-file", help="用于校验 HTTPS/WSS 服务证书的 CA PEM 文件")
    tls_group.add_argument(
        "--insecure",
        action="store_true",
        help="关闭 HTTPS/WSS 证书校验，仅限临时联调",
    )
    parser.add_argument("--http-timeout", type=float, default=10.0)
    parser.add_argument("--connect-timeout", type=float, default=10.0)
    args = parser.parse_args()

    raw_app_id = args.app_id
    if raw_app_id is None:
        raw_app_id = os.getenv("ILIVEDATA_APP_ID") or INITIAL_APP_ID
    try:
        args.app_id = int(raw_app_id)
    except (TypeError, ValueError):
        parser.error("appId 必须是整数")

    if args.secret_key is None:
        args.secret_key = os.getenv("ILIVEDATA_SECRET_KEY") or INITIAL_SECRET_KEY

    if args.app_id <= 0:
        parser.error(
            "请通过 --app-id、ILIVEDATA_APP_ID 或脚本内 INITIAL_APP_ID 提供正整数 appId"
        )
    if not args.secret_key:
        parser.error(
            "请通过 --secret-key、ILIVEDATA_SECRET_KEY 或脚本内 INITIAL_SECRET_KEY 提供 secretKey"
        )
    if not args.text.strip():
        parser.error("--text 去除首尾空白后不能为空")
    if args.speed is not None and not 0.5 <= args.speed <= 2.0:
        parser.error("--speed 必须在 0.5 到 2.0 之间")
    if args.loudness_lufs is not None and not -30.0 <= args.loudness_lufs <= -6.0:
        parser.error("--loudness-lufs 必须在 -30.0 到 -6.0 之间")
    if args.output is None:
        args.output = f"output.{args.format}"
    return args


def main() -> int:
    args = parse_args()

    try:
        asyncio.run(synthesize(args, args.secret_key))
    except (TtsApiError, RuntimeError, ValueError, OSError) as exc:
        print(f"FAILED: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("Interrupted", file=sys.stderr)
        return 130
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
