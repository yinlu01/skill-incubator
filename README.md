# Skills

> **把个人方法论工程化为 AI Agent 可直接调用的能力资产** —— 从真实工作场景中提炼高频工作流，沉淀为经实测的 Skill，兼容 Agent Skills 开放标准，可被主流 Agent 一键安装调用。

**One-liner (EN)：** Production-ready Agent Skills distilled from real work — field-tested, standard-compliant, installable by any Agent Skills-compatible agent.

## 这不是什么 / 是什么

| | |
|---|---|
| ❌ 不是 | 提示词收藏夹、AI 使用心得、玩具 demo |
| ✅ 是 | 可执行的工作流资产：每个 Skill 定义触发条件、输入输出、硬性约定与质量判据 |
| ❌ 不是 | 写完就发布 |
| ✅ 是 | 必须用真实素材跑通全链路才收录（关键环节脚本交叉验证） |
| ❌ 不是 | 一次性对话产物 |
| ✅ 是 | 结构化、模板化、可直接交付的产出（HTML 报告 / 结构化纪要 / 知识卡片） |

**覆盖面**：10 个 Skill，跨金融分析、会议协同、知识沉淀、HR、AI 安全、学习闭环六类真实场景。

原简介：个人 AI Skill 孵化库。基于日常工作与学习场景画像分析，孵化高频、可复用的 skill，经真实场景实测后收录。

## Skill 目录

### 办公场景

| Skill | 用途 | 触发示例 |
|---|---|---|
| [meeting-minutes](meeting-minutes/) | 会议录音→结构化纪要（议题/决议/行动项/风险），可出分类公告摘要 | "帮我整理这段录音" |
| [daily-market-report](daily-market-report/) | 每日市场多维分析（A股/港股/商品/机构观点+风险提示） | "出个今日市场报告" |
| [obsidian-knowledge-card](obsidian-knowledge-card/) | 阅读材料→导读→双链→四问框架的结构化知识卡片 | "把这篇做成知识卡片" |
| [hr-recruitment](hr-recruitment/) | 面试结构设计、offer 起草、组织规划 | "设计一面面试题" |
| [ai-enterprise-security](ai-enterprise-security/) | 企业 AI 落地安全六维度框架与评审清单 | "出个安全评审清单" |

### 学习场景

| Skill | 用途 | 触发示例 |
|---|---|---|
| [feynman-flashcard](feynman-flashcard/) | 笔记反向生成费曼自测问答卡（概念/机制/应用/辨析四层，先答后看，间隔重复） | "考考我" |
| [weekly-learning-review](weekly-learning-review/) | 学习周报：聚合打卡/读书/卡片产出数据（固定本地数据源） | "出个学习周报" |
| [mba-case-analysis](mba-case-analysis/) | 运营管理案例分析框架路由（利特尔法则/瓶颈/EOQ/排队论/报童模型等），含公式手册与完整示范 | "帮我拆这个案例" |
| [xhs-video-report](xhs-video-report/) | 小红书科普视频→HTML 图文学习报告（登录态浏览器取直链→MLX 转录→抽关键帧→速览卡+深度笔记） | "帮我总结这个视频" |
| [bili-video-report](bili-video-report/) | B 站视频（科普/教程/多P课程）→HTML 图文学习报告（playurl 免 yt-dlp 抓取→带时间戳转录→时间戳×关键帧对齐→速览卡+时间轴导航） | "帮我总结这个 B 站视频" |

### 报告模板类资产

| 资产 | 用途 |
|---|---|
| [xhs-video-report/references/report-template.html](xhs-video-report/references/report-template.html) | 视频学习报告 HTML 模板（速览卡 / 深度区块 / 图注 / 行动清单 / 质量说明，含打印与移动端适配） |
| [bili-video-report/references/report-template.html](bili-video-report/references/report-template.html) | B 站版报告模板（额外含时间轴导航 / 多P分P索引 / 降级告知组件） |

## 安装

**方式一：skills CLI（推荐，跨 ~55 个 agent 通用）**

```bash
npx skills add yinlu01/skill-incubator          # 全部安装
npx skills add yinlu01/skill-incubator@xhs-video-report   # 单个安装
```

遵循 [agentskills.io](https://agentskills.io) 开放标准（由 Linux Foundation 旗下 AAIF 治理）：
任何含 `SKILL.md` 的公开仓库可被自动识别安装，无需提交审核。

**方式二：手动复制**

```bash
git clone https://github.com/yinlu01/skill-incubator.git
cp -R workbuddy-skills/<skill-name> ~/.workbuddy/skills/   # 用户级（所有项目可用）
# 或项目级：cp -R workbuddy-skills/<skill-name> <项目>/.workbuddy/skills/
```

重启 WorkBuddy 会话后生效。

## 孵化方法

1. **场景画像分析**：基于长期使用画像 + 记忆文件，识别高频重复工作流
2. **闭环规划**：按场景闭环（如学习：输入→加工→内化→复盘）找空白环节，避免重复建设
3. **写 skill**：SKILL.md 定义触发词、工作流、输出格式、硬性约定；复杂 skill 附 references/（公式手册、全程示范）
4. **真实实测**：用真实素材跑一遍，关键计算用脚本交叉验证
5. **收录发布**：实测通过后收录进本 repo

## 状态

- 2026-09-03：首批 8 个 skill（办公 5 + 学习 3）发布。feynman-flashcard 与 mba-case-analysis 经功能实测验证。
- 2026-09-05：第 9 个 skill [xhs-video-report](xhs-video-report/) 发布。全链路真实环境实测通过（小红书链接→HTML 报告），
  并交付首份真实报告（582 秒视频 / 3601 字转录 / 4 帧引用）。输出格式定为 **HTML**（非 Markdown），
  附可复用报告模板 `references/report-template.html`。
- 2026-09-05：第 10 个 skill [bili-video-report](bili-video-report/) 发布。基于第三方 bilibili-summary.skill
  评测结论重构：**抓取层**弃用 yt-dlp（实测 412）与 wbi 签名方案，改走公开 API + 浏览器 cookie + playurl 直下
  （20 分钟视频下载 5s，yt-dlp 需 18s 且不稳定）；**媒体层**复用 xhs 管线并新增带时间戳的 `segments.json`；
  **报告层**吸收第三方多P分组、知识图谱、降级告知优点，新增「时间戳×关键帧对齐」时间轴导航。
  首份真实报告实测：19分50秒视频 → 下载 5s + 转录 132s（约 9 倍实时）/ 6290 字 / 461 时间戳分段 / 18 帧引用 6 帧。
