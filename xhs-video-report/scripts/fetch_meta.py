#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
从小红书笔记页提取视频直链与元数据。

抓取策略（2026-09-07 升级，重要）：**纯 HTTP 优先，bsk 兜底**。
实测发现：带 xsec_token 的笔记 URL 用桌面 UA 一次 GET，页面内嵌的
`window.__INITIAL_STATE__` 里就有完整 note 对象，`video.media.masterUrl`
就是带签名的 mp4 直链（\u002F 编码需还原）——不需要浏览器、不需要登录态。
bsk 路径保留作为兜底（小红书改版 / 纯 HTTP 拿不到时）。

为什么不用 yt-dlp：对小红书成功率仅约 10%（移动优先 URL + 签名校验）。

用法:
    python3 fetch_meta.py "<笔记URL>" [--out meta.json] [--wait 6]

输出 JSON:
    {
      "ok": true,
      "video": "https://...mp4",
      "title": "...", "desc": "...", "author": "...",
      "candidates": ["..."],   # 全部候选直链
      "via": "http|bsk",       # 走的哪条路径
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
import urllib.request

BSK_CANDIDATES = [
    os.path.expanduser("~/.local/bin/bsk"),
    "/usr/local/bin/bsk",
    "bsk",
]

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")


def try_http_first(url: str) -> dict | None:
    """纯 HTTP 抓取：整页正则提取 masterUrl 直链。
    失败返回 result（ok=False，调用方回退 bsk）。"""
    result = {"ok": False, "url": url, "video": "", "title": "", "desc": "",
              "author": "", "candidates": [], "via": "http", "diagnosis": ""}
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": UA,
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "zh-CN,zh;q=0.9",
            "Accept-Encoding": "identity",
        })
        with urllib.request.urlopen(req, timeout=25) as r:
            html = r.read().decode("utf-8", errors="ignore")
    except Exception as e:
        result["diagnosis"] = f"纯 HTTP 获取页面失败: {type(e).__name__} {e}"
        return result

    if "__INITIAL_STATE__" not in html and "masterUrl" not in html:
        result["diagnosis"] = "页面像风控/验证页（无内嵌数据也无直链），回退 bsk"
        return result

    # 整页正则为主（masterUrl 可能不在 __INITIAL_STATE__ 的 feed 分支，
    # 而在页面其他 script 里——实测 walk(feed) 会漏，整页正则稳）
    vids: list[str] = []
    for m in re.finditer(r'"masterUrl":"(.*?)"', html):
        vids.append(m.group(1).replace("\\u002F", "/"))
    for m in re.finditer(r'"backupUrls":\[(.*?)\]', html):
        for u in re.findall(r'"(http[^"]+)"', m.group(1)):
            vids.append(u.replace("\\u002F", "/"))
    vids = [u for u in dict.fromkeys(vids) if ".mp4" in u or ".m3u8" in u]
    if not vids:
        result["diagnosis"] = "页面里没有视频直链（付费/图文笔记/已删除/需登录态？）"
        return result

    def meta_content(prop: str) -> str:
        m = re.search(
            r'<meta[^>]+(?:property|name)="' + prop + r'"[^>]+content="(.*?)"',
            html, re.S)
        if m:
            return m.group(1).replace("&amp;", "&")
        return ""

    def nickname() -> str:
        m = re.search(r'"nickname":"(.*?)"', html)
        return m.group(1) if m else ""

    title = meta_content("og:title").replace(" - 小红书", "").strip()
    result.update({
        "ok": True,
        "video": vids[0],
        "title": title or html_unescape_title(html),
        "desc": meta_content("description")[:2000],
        "author": nickname(),
        "candidates": vids,
    })
    return result


def html_unescape_title(html: str) -> str:
    import html as _h
    m = re.search(r"<title>(.*?)</title>", html, re.S)
    if not m:
        return ""
    return _h.unescape(m.group(1)).replace(" - 小红书", "").strip()


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
    ap.add_argument("--force-bsk", action="store_true",
                    help="跳过纯 HTTP，直接走浏览器路径")
    args = ap.parse_args()

    # ---- 路径 1：纯 HTTP（优先，快且不依赖浏览器）----
    if not args.force_bsk:
        result = try_http_first(args.url)
        if result and result.get("ok"):
            with open(args.out, "w", encoding="utf-8") as f:
                json.dump(result, f, ensure_ascii=False, indent=2)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return
        print(f"[info] 纯 HTTP 未命中：{(result or {}).get('diagnosis', '')}",
              file=sys.stderr)

    # ---- 路径 2：bsk 浏览器兜底 ----
    bsk = find_bsk()
    sid = start_session(bsk)
    result = {"ok": False, "url": args.url, "video": "", "title": "",
              "desc": "", "author": "", "candidates": [], "via": "bsk",
              "diagnosis": ""}
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
