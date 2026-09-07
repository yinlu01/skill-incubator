---
name: podcast-report
description: "把播客单集（小宇宙 xiaoyuzhoufm.com 为主，通用音频直链亦可）转成 HTML 图文学习报告。当用户贴播客/小宇宙链接想「总结这期」「没时间听完」「把访谈存档」「这期讲了什么」时使用。流程：纯 HTTP 取元数据与音频直链（免登录免 cookie）→ 下载 → mlx-whisper 全量转录 → 长音频分块 → 双层 HTML 报告（速览卡 + 章节时间轴 + 深度笔记）→ 归档 Obsidian。"
agent_created: true
---

# 播客 → HTML 图文学习报告

## 核心认知

与前两个姊妹 skill 的分工：**xhs-video-report 打小红书，bili-video-report 打 B 站，
本 skill 打播客**。媒体管线（下载 → 转录 → 模板化 HTML → 归档）同源，但播客有三个本质差异：

1. **没有画面** → 不抽帧、不读图，产物少一个 `frames/`。省掉了视频类 skill 最费时的一步。
2. **时长是视频的 3–10 倍**（常见 1–2 小时，访谈类可达 4 小时）→ 转录文本动辄 5 万字，
   **必须分块阅读成稿**（`chunk.py`），否则会爆上下文且成稿质量下降。
3. **多一份素材：shownotes** → 节目方自述，常常自带章节时间戳、论文清单、延伸阅读。
   这是视频平台没有的，可直出章节时间轴，也是转录出错时的对照基准。

**输出物是 HTML，不是 Markdown。** 模板见 `references/report-template.html`。

## 抓取层：为什么不需要登录、不需要 cookie、不需要 yt-dlp

小宇宙把完整的 episode 对象内嵌在页面 `<script id="__NEXT_DATA__">` 里（Next.js SSR 注水数据），
其中 `enclosure.url` 就是**无鉴权**的音频直链（`media.xyzcdn.net/...m4a`）。
所以抓取层只有一步：桌面 UA + 一次 HTTP GET + 正则取 JSON。

```
GET https://www.xiaoyuzhoufm.com/episode/<eid>
  → __NEXT_DATA__.props.pageProps.episode
  → { title, duration, enclosure.url, shownotes, podcast{title,author}, pubDate }
```

实测（2026-09-07）：单行 curl 即可，音频 CDN 无 Referer 校验，浏览器直下无阻。
三个平台抓取难度对比：

| 平台 | 抓取层 |
|---|---|
| 小红书 | 必须 `xsec_token`，App 分享链接打不开，需登录态浏览器 |
| B 站 | 需 wbi 签名或 cookie，yt-dlp 常 412 |
| **小宇宙** | **纯 HTTP GET，无鉴权** |

**降级边界**：付费/私密单集的 `enclosure.url` 为空 —— 此时走报告模板的降级告知组件，
只基于 shownotes 与公开信息整理，不要编造口播内容。

## 前置依赖

- Python 3.10+（建议独立 venv）：`imageio-ffmpeg` + `mlx-whisper`，见文末「安装（外部用户）」
- **不需要** bsk / 浏览器 / cookie / yt-dlp
- 平台限制：转录后端 `mlx-whisper` 绑 Apple Silicon（macOS）。
  Linux/Windows 用户改 `media.py` 的转录部分为 `faster-whisper` 即可，其余流程不变。

环境体检：`$PY scripts/selfcheck.py`

## 工作流

```bash
PY=python3   # 你自己的 Python 3.10+ 解释器（已 pip install -r requirements.txt）
cd ~/.workbuddy/skills/podcast-report/scripts

# 1) 链接 → 元数据 + 音频直链（纯 HTTP，秒级）
$PY fetch_episode.py "<小宇宙链接>" --workdir /tmp/xyz_work
#    输入容错：完整 URL（带任意参数）/ 裸 eid / 混着文案的分享文本，都能解析

# 2) 下载 → 转码 → 全量转录（长播客耗时主要在这一步，建议后台跑）
$PY media.py --meta /tmp/xyz_work/meta.json --workdir /tmp/xyz_work
#    --model mlx-community/whisper-large-v3  换更大模型（更准、更慢）
#    --offline                               模型已缓存时强制离线，最稳
#    --skip-download                         音频已在本地时跳过

# 2.5) 长播客先分块，再逐块通读成稿
$PY chunk.py --workdir /tmp/xyz_work        # <30min 不切；30–90min 按 15min；>90min 按 20min
#    产物 chunks/chunk_NN.md（带 [HH:MM:SS - HH:MM:SS] 标题）+ manifest.json

# 3) 按 references/report-template.html 撰写，归档 Obsidian（见下）
```

产物：`audio.m4a` / `audio.wav` / `transcript.txt` / `segments.json` / `meta.json` / `chunks/`。

**性能基准（M4，124 分钟单集）**：元数据 1s → 下载 2s（约 60MB）→ 转录 **9.5 分钟**
（约 13× 实时）→ 53,124 字。经验：转录耗时 ≈ 音频时长 / 12，可据此预估等待时间。

## 报告撰写规范

1. **双层结构**：速览卡（30 秒判断值不值得听，敢下判断、给星级、给听法建议）+ 深度笔记。
2. **章节时间轴必写**：优先用 shownotes 里的 OUTLINE 时间戳；若没有，用 `segments.json`
   搜关键词定位真实时间戳。**时间不许编**。
3. **反直觉点 / 增量认知**是全片最值钱的一节，只写「听完才知道且违反常识」的，禁止复述内容。
4. **「与我何干」**必须引用用户真实项目（如 Agent 测评、AI 中台、大模型资源库），不能空谈。
5. **Shownotes 原文**整段保留在折叠区 —— 转录出错时有对照基准，且常含论文/资源清单。
6. **长播客成稿方法**：分块 → 逐块通读记要点 → 合并成稿。不要一次性把 5 万字塞进上下文。
7. Whisper 中文输出**通常没有标点**，属正常现象，不影响理解；引用原话时可适当补标点。

## 归档约定

- 目录：`~/Obsidian/AI技术/播客学习报告/`（与「视频学习报告」并列；可用环境变量
  `OBSIDIAN_PODCAST_REPORT_DIR` 覆盖，脚本与文档均不写死本机路径）
- 文件名：**`节目名 · 单集标题.html`**，中文，一眼能看出内容，不用英文短名
- 每份报告产出后**必须更新该目录的 `索引.md`**（含双链、时长、字数、一句话结论），
  否则归档等于没归档

## 已知坑（脚本已自愈，改动时勿删）

1. 代理环境下 `huggingface.co` 常 502 → 自动切 `hf-mirror.com`
2. HuggingFace Xet 后端会 401 → 自动 `HF_HUB_DISABLE_XET=1`
3. 模型已缓存时强制联网反而失败 → 检测到缓存自动 `HF_HUB_OFFLINE=1`，也可用 `--offline`
4. `mlx-whisper` 硬编码调用 `ffmpeg` 命令名 → 用 imageio 的二进制建同名软链到 `~/.local/bin`
5. 转录产物中文本无标点 → 用 `re.split` 按句切分无效，改用定长切分后再读

## 安装（外部用户）

```bash
git clone https://github.com/yinlu01/skill-incubator.git
cp -R workbuddy-skills/podcast-report ~/.workbuddy/skills/
# 或：npx skills add yinlu01/skill-incubator@podcast-report

python3 -m venv ~/.venv/podcast && source ~/.venv/podcast/bin/activate
pip install -r podcast-report/requirements.txt
```

首次转录会下载 Whisper 模型（约 1.6GB），之后全部离线可用。

## 隐私与安全

- **全程本地运行**：音频下载、转录、报告生成都在你的机器上完成，不上传任何第三方。
- **无凭据需求**：小宇宙抓取不需要登录态、不读写任何 cookie，因此也不存在凭据泄露面。
- **唯一外部请求**：小宇宙页面与其音频 CDN（取内容）、HuggingFace（首次下载模型）。
- 转录模型与音频文件缓存在本地临时目录，可随时清理。
