# workbuddy-skills

个人 WorkBuddy AI Skill 孵化库。基于日常工作与学习场景画像分析，孵化高频、可复用的 skill，经真实场景实测后收录。

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

## 安装

```bash
git clone https://github.com/yinlu01/workbuddy-skills.git
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
