#!/usr/bin/env python3
"""云上曲率 TTS 同步 HTTP 合成 Python 示例。

仅使用 Python 标准库，无需安装第三方依赖。

执行参数方式（优先级最高）：
    python3 speech_synthesis.py \
      --app-id your_app_id \
      --secret-key 'your_secret_key' \
      --text '您好，这是一个同步语音合成示例。' \
      --voice CHINESE_SC_ADS_BRAND \
      --format wav \
      --download output.wav

环境变量方式：
    export ILIVEDATA_APP_ID='your_app_id'
    export ILIVEDATA_SECRET_KEY='your_secret_key'
    python3 speech_synthesis.py --text '您好，这是一个合成示例。'

脚本初始化值方式：修改下方 INITIAL_APP_ID 和 INITIAL_SECRET_KEY。
凭证优先级：执行参数 > 环境变量 > 脚本内初始化值。

自签名 CA 推荐使用 --ca-file /path/to/company-ca.pem。
--insecure 会关闭证书验证，仅限临时联调，生产环境禁用。
运行 python3 speech_synthesis.py --help 查看全部参数。
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import json
import os
import ssl
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlencode, urlsplit
from urllib.request import Request, urlopen


DEFAULT_API_URL = "https://tts.ilivedata.com/api/v2/speech/synthesis"
DEFAULT_VOICE = "CHINESE_SC_ADS_BRAND"

# 可直接在此填写；执行参数和环境变量未设置时才使用这里的值。
INITIAL_APP_ID = 0
INITIAL_SECRET_KEY = ""


class TtsApiError(RuntimeError):
    pass


def utc_timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def create_signature(
    app_id: int,
    secret_key: str,
    timestamp: str,
    api_url: str,
    json_body: bytes,
) -> str:
    parsed = urlsplit(api_url)
    if parsed.scheme != "https" or not parsed.hostname:
        raise ValueError("API URL must be an absolute HTTPS URL")

    lines = ["POST", parsed.netloc.lower(), parsed.path or "/"]
    if parsed.query:
        lines.append(urlencode(sorted(parse_qsl(parsed.query, keep_blank_values=True))))
    lines.extend([
        hashlib.sha256(json_body).hexdigest(),
        f"X-AppId:{app_id}",
        f"X-TimeStamp:{timestamp}",
    ])
    digest = hmac.new(
        secret_key.encode("utf-8"),
        "\n".join(lines).encode("utf-8"),
        hashlib.sha256,
    ).digest()
    return base64.b64encode(digest).decode("ascii")


def create_ssl_context(ca_file: str | None, insecure: bool) -> ssl.SSLContext:
    if insecure:
        print("WARNING: TLS certificate verification is disabled", file=sys.stderr)
        return ssl._create_unverified_context()
    return ssl.create_default_context(cafile=ca_file)


def build_payload(args: argparse.Namespace) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "text": args.text,
        "language": args.language,
        "output": {"format": args.format},
    }
    voice = {
        key: value
        for key, value in {
            "name": args.voice,
            "audio": args.voice_audio,
            "emotion": args.emotion,
        }.items()
        if value is not None
    }
    if voice:
        payload["voice"] = voice
    if args.speed is not None:
        payload["output"]["speed"] = args.speed
    if args.loudness_lufs is not None:
        payload["output"]["loudnessLufs"] = args.loudness_lufs
    return payload


def request_synthesis(args: argparse.Namespace, ssl_context: ssl.SSLContext) -> dict[str, Any]:
    json_body = json.dumps(
        build_payload(args),
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    timestamp = utc_timestamp()
    signature = create_signature(args.app_id, args.secret_key, timestamp, args.url, json_body)
    request = Request(
        args.url,
        data=json_body,
        method="POST",
        headers={
            "Content-Type": "application/json;charset=UTF-8",
            "Accept": "application/json;charset=UTF-8",
            "X-AppId": str(args.app_id),
            "X-TimeStamp": timestamp,
            "Authorization": signature,
        },
    )
    try:
        with urlopen(request, timeout=args.timeout, context=ssl_context) as response:
            raw_body = response.read().decode("utf-8")
    except HTTPError as exc:
        raw_body = exc.read().decode("utf-8", errors="replace")
        raise TtsApiError(f"HTTP {exc.code}: {raw_body}") from exc
    except URLError as exc:
        raise TtsApiError(f"Request failed: {exc.reason}") from exc

    try:
        result = json.loads(raw_body)
    except json.JSONDecodeError as exc:
        raise TtsApiError(f"Response is not JSON: {raw_body}") from exc
    if result.get("errorCode") != 0:
        raise TtsApiError(
            f"Synthesis failed: code={result.get('errorCode')}, "
            f"message={result.get('errorMessage')}"
        )
    if not isinstance(result.get("data"), dict):
        raise TtsApiError(f"Response misses data: {result}")
    return result["data"]


def download_audio(url: str, output: str, timeout: float, ssl_context: ssl.SSLContext) -> None:
    output_path = Path(output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = tempfile.NamedTemporaryFile(
        prefix=f".{output_path.name}.",
        suffix=".part",
        dir=output_path.parent,
        delete=False,
    )
    part_path = Path(temporary.name)
    temporary.close()
    try:
        with urlopen(url, timeout=timeout, context=ssl_context) as response:
            with part_path.open("wb") as audio_file:
                while chunk := response.read(64 * 1024):
                    audio_file.write(chunk)
    except Exception:
        if part_path.exists():
            part_path.unlink()
        raise
    part_path.replace(output_path)
    print(f"Audio saved to {output_path}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="云上曲率 TTS 同步 HTTP 合成示例")
    parser.add_argument("--app-id", type=int)
    parser.add_argument("--secret-key")
    parser.add_argument("--text", required=True, help="待合成文本，长度 1 到 500")
    voice_group = parser.add_mutually_exclusive_group()
    voice_group.add_argument("--voice", help=f"音色名称，默认 {DEFAULT_VOICE}")
    voice_group.add_argument("--voice-audio", help="用于音色克隆的 WAV 音频 URL")
    parser.add_argument(
        "--emotion",
        choices=("ANGRY", "SAD", "HAPPY", "FEARFUL", "SURPRISED"),
    )
    parser.add_argument("--language", default="zh-CN")
    parser.add_argument("--format", choices=("pcm", "wav", "mp3"), default="wav")
    parser.add_argument("--speed", type=float)
    parser.add_argument("--loudness-lufs", type=float)
    parser.add_argument("--download", help="可选：把响应 URL 的音频下载到本地")
    parser.add_argument("--url", default=DEFAULT_API_URL)
    tls_group = parser.add_mutually_exclusive_group()
    tls_group.add_argument("--ca-file", help="用于校验证书的 CA PEM 文件")
    tls_group.add_argument("--insecure", action="store_true", help="关闭证书校验，仅限临时联调")
    parser.add_argument("--timeout", type=float, default=60.0)
    args = parser.parse_args()

    raw_app_id = args.app_id if args.app_id is not None else os.getenv("ILIVEDATA_APP_ID") or INITIAL_APP_ID
    try:
        args.app_id = int(raw_app_id)
    except (TypeError, ValueError):
        parser.error("appId 必须是整数")
    if args.secret_key is None:
        args.secret_key = os.getenv("ILIVEDATA_SECRET_KEY") or INITIAL_SECRET_KEY
    if args.app_id <= 0:
        parser.error("请通过执行参数、环境变量或脚本初始化值提供正整数 appId")
    if not args.secret_key:
        parser.error("请通过执行参数、环境变量或脚本初始化值提供 secretKey")
    args.text = args.text.strip()
    if not 1 <= len(args.text) <= 500:
        parser.error("--text 去除首尾空白后的长度必须在 1 到 500 之间")
    if args.voice is None and args.voice_audio is None:
        args.voice = DEFAULT_VOICE
    if args.speed is not None and not (args.speed <= 0 or 0.5 <= args.speed <= 2.0):
        parser.error("--speed 必须小于等于 0，或在 0.5 到 2.0 之间")
    if args.loudness_lufs is not None and not -30.0 <= args.loudness_lufs <= -6.0:
        parser.error("--loudness-lufs 必须在 -30.0 到 -6.0 之间")
    if args.timeout <= 0:
        parser.error("--timeout 必须大于 0")
    return args


def main() -> int:
    args = parse_args()
    try:
        ssl_context = create_ssl_context(args.ca_file, args.insecure)
        data = request_synthesis(args, ssl_context)
        print(json.dumps(data, ensure_ascii=False, indent=2))
        if args.download:
            url = data.get("url")
            if not url:
                raise TtsApiError("Response data misses audio URL")
            download_audio(str(url), args.download, args.timeout, ssl_context)
    except (TtsApiError, ValueError, OSError) as exc:
        print(f"FAILED: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("Interrupted", file=sys.stderr)
        return 130
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
