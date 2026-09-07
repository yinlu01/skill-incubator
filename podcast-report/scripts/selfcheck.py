#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
环境体检：跑播客报告全链路之前先确认依赖齐不齐。

用法:
    python3 scripts/selfcheck.py
"""
from __future__ import annotations

import os
import shutil
import sys
import urllib.error
import urllib.request

OK, WARN, BAD = "✅", "⚠️ ", "❌"


def check_python() -> None:
    v = sys.version_info
    flag = OK if v >= (3, 10) else BAD
    print(f"{flag} Python {v.major}.{v.minor}.{v.micro}  ({sys.executable})")


def check_module(name: str, hint: str) -> None:
    try:
        __import__(name)
        print(f"{OK} {name}")
    except ImportError:
        print(f"{BAD} {name} 未安装 —— {hint}")


def check_ffmpeg() -> None:
    if shutil.which("ffmpeg"):
        print(f"{OK} ffmpeg（PATH）")
        return
    try:
        import imageio_ffmpeg
        exe = imageio_ffmpeg.get_ffmpeg_exe()
        link = os.path.expanduser("~/.local/bin/ffmpeg")
        if os.path.exists(link):
            print(f"{OK} ffmpeg（imageio + 软链 {link}）")
        else:
            print(f"{WARN} ffmpeg 不在 PATH，但有 imageio 二进制 {exe}；"
                  f"运行 media.py 时会自动建软链")
    except ImportError:
        print(f"{BAD} ffmpeg 不可用 —— pip install imageio-ffmpeg")


def check_mlx() -> None:
    try:
        import mlx.core  # noqa: F401
        print(f"{OK} mlx（Apple Silicon 加速可用）")
    except ImportError:
        print(f"{BAD} mlx 不可用 —— 本 skill 的转录后端依赖 Apple Silicon。"
              f"非 macOS 用户请改用 faster-whisper 替换 media.py 的转录部分。")


def check_model_cache() -> None:
    root = os.environ.get("HF_HOME") or os.path.expanduser("~/.cache/huggingface")
    base = os.path.join(root, "hub")
    if not os.path.isdir(base):
        print(f"{WARN} 尚无 HF 缓存目录 {base}（首次转录需联网下载模型，约 1.6GB）")
        return
    found = [d for d in os.listdir(base) if d.startswith("models--mlx-community--whisper")]
    if found:
        for d in sorted(found):
            print(f"{OK} 已缓存模型 {d.replace('models--', '').replace('--', '/')}")
    else:
        print(f"{WARN} 未发现 whisper 模型缓存（首次运行 media.py 会联网下载）")


def check_network() -> None:
    for name, url in [("小宇宙", "https://www.xiaoyuzhoufm.com"),
                      ("音频 CDN", "https://media.xyzcdn.net")]:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=12) as r:
                print(f"{OK} {name} 可达（HTTP {r.status}）")
        except urllib.error.HTTPError as e:
            # CDN 根路径返回 403 属正常（不允许列目录），说明链路是通的
            print(f"{OK} {name} 可达（HTTP {e.code}，根路径受限属正常）")
        except Exception as e:
            print(f"{BAD} {name} 不可达：{type(e).__name__} {e}")


def main() -> None:
    print("=== podcast-report 环境体检 ===\n")
    check_python()
    check_module("imageio_ffmpeg", "pip install imageio-ffmpeg")
    check_module("mlx_whisper", "pip install mlx-whisper（仅 Apple Silicon）")
    check_ffmpeg()
    check_mlx()
    check_model_cache()
    check_network()
    print("\n提示：若转录时遇到 HuggingFace 502，代理环境下设 "
          "HF_ENDPOINT=https://hf-mirror.com，或给 media.py 加 --offline。")


if __name__ == "__main__":
    main()
