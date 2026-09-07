#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
小宇宙（xiaoyuzhoufm.com）单集元数据 + 音频直链抓取。

为什么可以这么简单（重要，别凭直觉加复杂度）：
    小宇宙把完整的 episode 对象内嵌在页面 `<script id="__NEXT_DATA__">` 里
    （Next.js 的 SSR 注水数据），其中 `enclosure.url` 就是**无鉴权**的音频直链。
    所以：不需要登录、不需要 cookie、不需要浏览器自动化、不需要 yt-dlp。
    一次纯 HTTP GET 就够 —— 这是本 skill 相对 xhs / bili 两个姊妹 skill 的最大优势。

    实测（2026-09-07）：桌面 UA + 单次 GET 即可，音频 CDN 为 media.xyzcdn.net，
    curl 直下无 Referer 校验。

用法:
    python3 fetch_episode.py "<单集链接或 eid>" --workdir /tmp/xyz_work
    python3 fetch_episode.py "https://www.xiaoyuzhoufm.com/episode/6a8eadd61352af56ff3c6017"

输入容错:
    完整 URL（可带任意查询参数）/ 裸 eid（24 位 hex）/ 一段混着文案的分享文本，都能解析。

产物:
    <workdir>/meta.json   —— media.py 的输入
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.request

BASE = "https://www.xiaoyuzhoufm.com"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")


def extract_eid(text: str) -> str:
    """从各种形态的输入里提取单集 eid。"""
    # 1) 规范路径 /episode/<eid>
    m = re.search(r"/episode/([0-9a-zA-Z]{16,})", text)
    if m:
        return m.group(1)
    # 2) 裸 24 位 hex（小宇宙 eid 形态）
    m = re.search(r"\b([0-9a-fA-F]{24})\b", text)
    if m:
        return m.group(1)
    # 3) 任意 16 位以上 alnum token（兜底）
    m = re.search(r"\b([0-9a-zA-Z]{16,})\b", text)
    if m:
        return m.group(1)
    return ""


def fetch_html(eid: str) -> str:
    url = f"{BASE}/episode/{eid}"
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": UA,
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "zh-CN,zh;q=0.9",
            "Accept-Encoding": "identity",  # 避免 gzip，省掉解压依赖
        },
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", errors="ignore")


def parse_next_data(html: str) -> dict:
    m = re.search(
        r'<script[^>]+id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.S)
    if not m:
        raise RuntimeError(
            "页面里找不到 __NEXT_DATA__ —— 小宇宙可能改版了，"
            "或该单集需要登录（付费/私密）。请改用浏览器人工确认。")
    return json.loads(m.group(1))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("target", help="单集链接、eid，或含链接的一段文本")
    ap.add_argument("--workdir", default="/tmp/xyz_work")
    args = ap.parse_args()

    eid = extract_eid(args.target)
    if not eid:
        sys.exit(f"无法从输入中解析出单集 eid：{args.target[:120]}")

    print(f"[1/2] 抓取单集页 eid={eid}", flush=True)
    html = fetch_html(eid)
    data = parse_next_data(html)
    ep = (data.get("props", {}).get("pageProps", {}) or {}).get("episode") or {}
    if not ep:
        sys.exit("__NEXT_DATA__ 里没有 episode 对象 —— 链接可能已失效或单集已下架。")

    pod = ep.get("podcast") or {}
    enc = ep.get("enclosure") or {}
    audio = enc.get("url") or (ep.get("media") or {}).get("sourceUrl") or ""

    meta = {
        "ok": bool(audio),
        "eid": eid,
        "url": f"{BASE}/episode/{eid}",
        "title": ep.get("title") or "",
        "podcast_title": pod.get("title") or "",
        "author": pod.get("author") or "",
        "podcast_brief": pod.get("brief") or "",
        "duration_sec": float(ep.get("duration") or 0),
        "audio_url": audio,
        "pub_date": ep.get("pubDate") or "",
        "description": ep.get("description") or "",
        "shownotes": ep.get("shownotes") or "",
        "play_count": ep.get("playCount") or 0,
        "is_private": bool(ep.get("isPrivateMedia")),
        "pay_type": ep.get("payType") or "",
        "links": ep.get("links") or [],
    }

    os.makedirs(args.workdir, exist_ok=True)
    out = os.path.join(args.workdir, "meta.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    mm = int(meta["duration_sec"] // 60)
    ss = int(meta["duration_sec"] % 60)
    print(f"[2/2] 元数据落盘 -> {out}")
    print(f"  节目  {meta['podcast_title']}（{meta['author']}）")
    print(f"  标题  {meta['title']}")
    print(f"  时长  {mm} 分 {ss} 秒")
    print(f"  音频  {'已获取' if audio else '未获取（付费/私密单集，需降级）'}"
          f" {audio[:80]}")
    if meta["shownotes"]:
        print(f"  Shownotes  {len(meta['shownotes'])} 字"
              f"{'（含 OUTLINE 章节，可用于时间轴）' if 'OUTLINE' in meta['shownotes'] else ''}")
    if not audio:
        print("\n⚠️  拿不到音频直链：多为付费/私密单集。请走报告模板的降级告知组件。")


if __name__ == "__main__":
    main()
