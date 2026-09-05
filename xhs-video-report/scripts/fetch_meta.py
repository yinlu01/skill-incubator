#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
从小红书笔记页提取视频直链与元数据。

为什么不用 yt-dlp：对小红书成功率仅约 10%（移动优先 URL + 签名校验）。
改用 bsk 驱动用户已登录的真实 Chromium，登录态天然可用。

用法:
    python3 fetch_meta.py "<笔记URL>" [--out meta.json] [--wait 6]

输出 JSON:
    {
      "ok": true,
      "video": "https://...mp4",
      "title": "...", "desc": "...", "author": "...",
      "candidates": ["..."],   # 全部候选直链
      "diagnosis": "..."       # 失败时的诊断信息
    }
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time

BSK_CANDIDATES = [
    os.path.expanduser("~/.local/bin/bsk"),
    "/usr/local/bin/bsk",
    "bsk",
]


def find_bsk() -> str:
    for p in BSK_CANDIDATES:
        if os.path.exists(p):
            return p
        if p == "bsk":
            from shutil import which
            w = which("bsk")
            if w:
                return w
    sys.exit("找不到 bsk。请确认 browser-skill 已安装（~/.local/bin/bsk）")


# 多策略探测：video 标签 / 内嵌状态 / performance 网络记录
PROBE_JS = r"""
(() => {
  const out = {videos: [], title: '', desc: '', author: '', hints: []};
  const vids = document.querySelectorAll('video');
  out.hints.push(vids.length + ' 个 <video> 标签');

  // 策略 1：<video> / <source> 的 src（排除 blob: 伪协议）
  vids.forEach(v => {
    [v.src, v.currentSrc].forEach(s => {
      if (s && !s.startsWith('blob:')) out.videos.push(s);
      else if (s && s.startsWith('blob:')) out.hints.push('检测到 blob: URL（MSE 播放）');
    });
    v.querySelectorAll('source').forEach(s => {
      if (s.src && !s.startsWith('blob:')) out.videos.push(s.src);
    });
  });

  // 策略 2：页面内嵌 __INITIAL_STATE__ 里的媒体地址
  try {
    const raw = window.__INITIAL_STATE__ ? JSON.stringify(window.__INITIAL_STATE__) : '';
    const m = raw.match(/https?:[^"\\ ]+?\.(?:mp4|m3u8|flv)(?:\?[^"\\ ]*)?/g);
    if (m) { out.videos.push(...m); out.hints.push('从 __INITIAL_STATE__ 命中 ' + m.length + ' 条'); }
  } catch (e) {}

  // 策略 3：performance 资源记录里的媒体请求
  try {
    const ents = performance.getEntriesByType('resource').map(e => e.name);
    const hit = ents.filter(n => /\.(mp4|m3u8)(\?|$)/i.test(n));
    if (hit.length) { out.videos.push(...hit); out.hints.push('从网络记录命中 ' + hit.length + ' 条'); }
  } catch (e) {}

  // 元数据
  const pick = (sel) => { const e = document.querySelector(sel); return e ? e.innerText.trim() : ''; };
  out.title = pick('#detail-title') || pick('.title') || document.title || '';
  out.desc = pick('#detail-desc') || pick('.desc') || '';
  out.author = pick('.author-container .username') || pick('.author .name') || '';

  out.videos = [...new Set(out.videos.filter(Boolean))];
  return out;
})()
"""


def run(cmd: list[str], timeout: int = 60) -> tuple[int, str, str]:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.returncode, r.stdout, r.stderr
    except subprocess.TimeoutExpired:
        return -1, "", "timeout"


def start_session(bsk: str) -> str:
    code, out, err = run([bsk, "session", "start", "--json"])
    if code == 0:
        # 优先 JSON 解析
        try:
            data = json.loads(out)
            for k in ("session", "sessionId", "session_id", "id"):
                if k in data:
                    return str(data[k])
        except Exception:
            pass
        # 退化：从 stdout 抓 4 位 session id
        m = re.search(r"\b([a-z0-9]{4})\b", out)
        if m:
            return m.group(1)
    sys.exit(f"bsk session start 失败 (code={code})\nstdout: {out}\nstderr: {err}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("url")
    ap.add_argument("--out", default="/tmp/xhs_meta.json")
    ap.add_argument("--wait", type=int, default=6, help="页面加载等待秒数")
    args = ap.parse_args()

    bsk = find_bsk()
    sid = start_session(bsk)
    result = {"ok": False, "url": args.url, "video": "", "title": "",
              "desc": "", "author": "", "candidates": [], "diagnosis": ""}
    try:
        code, out, err = run([bsk, "navigate", args.url, "--session", sid], timeout=90)
        if code != 0:
            result["diagnosis"] = f"navigate 失败: {err or out}"
        else:
            time.sleep(args.wait)
            # 视频可能懒加载，滚一下再等
            run([bsk, "evaluate", "window.scrollTo(0,300)", "--session", sid], timeout=30)
            time.sleep(2)

            code, out, err = run(
                [bsk, "evaluate", PROBE_JS, "--session", sid, "--json"], timeout=60)
            if code != 0:
                result["diagnosis"] = f"evaluate 失败: {err or out}"
            else:
                try:
                    probe = json.loads(out)
                    if isinstance(probe, dict) and "videos" not in probe:
                        # bsk --json 实测（v0.1.10）把值包在 "value" 键里，兼容其他包裹
                        for k in ("value", "result", "data"):
                            if isinstance(probe.get(k), dict):
                                probe = probe[k]
                                break
                except Exception:
                    probe = None

                if not probe:
                    result["diagnosis"] = f"无法解析 evaluate 输出: {out[:400]}"
                else:
                    vids = probe.get("videos") or []
                    result["title"] = probe.get("title", "")
                    result["desc"] = (probe.get("desc", "") or "")[:2000]
                    result["author"] = probe.get("author", "")
                    result["candidates"] = vids
                    hints = probe.get("hints") or []

                    real = [v for v in vids if not v.startswith("blob:")]
                    if real:
                        # 优先 mp4 直链，其次 m3u8
                        mp4 = [v for v in real if ".mp4" in v]
                        m3u8 = [v for v in real if ".m3u8" in v]
                        result["video"] = mp4[0] if mp4 else (m3u8[0] if m3u8 else real[0])
                        result["ok"] = True
                    else:
                        result["diagnosis"] = (
                            "未拿到真实直链。" + " | ".join(hints) +
                            "。多半是 blob:/MSE 播放，需改用录屏兜底。"
                        )
    finally:
        run([bsk, "session", "stop", sid], timeout=30)

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
