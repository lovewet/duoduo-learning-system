<!-- 配套技能卡 · 已脱敏副本 · 版权归各自作者 -->

---
name: exercise-assistant
display_name: K12 Exercise Assistant 解题答疑
display_name_en: K12 Exercise Assistant
version: 1.1.2
status: active
layer: L2-domain
scope: k12-exercise-qa
category: Education
trigger: |
  解题 / 答疑 / 这道题 / 怎么解 / 帮我讲 / 错题 / 订正 / 改错 / 为什么选
description: |
  K12 全学段（小学 1~6 / 初中 7~9 / 高中 10~12）9 学科（语数英物化生史地政）解题答疑。
  输入：题目文本（图片见 V2）。输出：5 段结构化讲解（审题→思路→解答→检查→举一反三）。
  模型能力约束：K12 教材范围内的概念、定理、例题；不替考、不越级（不答超纲竞赛题）。
description_zh: K12 全学段 9 学科解题答疑：输入题目（文字/图片），输出审题→思路→解答→检查→举一反三五段结构化分步讲解。
description_en: "K12 exercise Q&A across 9 subjects and all grade bands - takes a question (text or image) and produces a 5-phase structured explanation (Probe, Strategy, Run, Check, Transfer)."
author: 米拉之落
prerequisites: []
companion_skills: review-notebook (D9-D24 错因体系), k12l (教学模式旁支)
references:
  - references/学科分层与知识点索引.md
  - references/答疑工作流与提示词模板.md
  - references/接口契约与数据格式.md
  - references/学段差异化策略.md
  - references/实现路径与里程碑.md
evals:
  - evals/盲评回归题集.md
  - evals/trigger_cases.json
---

# ExerciseAssistant · K12 全学段解题答疑 Skill

> 能力落本地：5 段结构化讲解 + 三级渐进披露。
> 红线：不替代、超纲不答、规范书写、培养思路。

## § 0 一句话与边界

K12 教材范围内，对一道题给出 **审题→思路→解答→检查→举一反三** 五段结构化讲解。
拒绝：大学/竞赛/考研题；压轴"秒杀技巧"；替考；家庭矛盾（→how2talk）；错因归类与同类练习（→review-notebook）。

## § 1 目的

「学生问一道题」做成 Agent 可稳定调用的 Skill：9 学科 × 3 学段 × 17 题型全路由；24 题盲评 ≥80%；知识点可追溯；本地 LLM 可跑。

## § 2 输入

核心字段：`question.text` + `grade.{band,level}` + `subject` + `question_type`（17 类）；可选 `context.{difficulty,student_level,purpose}`、`request.thinking_level`（NONE..MAX，高难题默认 MEDIUM）。
V2 图片：`question.attachments[].{type:'image', intent, data_url|local_path}`，intent 8 类，路由见 engine/ocr_router.py。

完整字段契约、校验规则与示例 → `references/接口契约与数据格式.md`。

## § 3 工作流（5 步）

1. **意图识别**：判定学段×学科×题型三元组（keywords + 反问补全）
2. **路由加载**：按三元组注入学科 prompt（分层索引摘要 + 答疑工作流全文模板）
3. **5 段生成**：LLM 按 PROBE/STRATEGY/RUN/CHECK/TRANSFER 骨架生成结构化 JSON
4. **自检重试**：5 段非空 + 公式闭合 + 答句有；缺段重生成（≤2 次）；越界拒绝
5. **家长护栏**（仅 purpose=parental_explain）：追加"家长如何引导"，不替答

学科特化与学段差异化（低段口吻化具象 / 高段定理与分类讨论）→ `references/学段差异化策略.md`。

## § 4 输出

结构化 JSON：`phases[5]`（PROBE.highlights / STRATEGY.knowledge_points+alternatives / RUN.{formula_tex, step_latex, answer_line} / CHECK.verification / TRANSFER.{variant_problem, transfer_hint}）+ `knowledge_points_used`（KP ID）+ `difficulty_realized` + `self_eval` + `guardians` + `rendering.{human_readable, markdown}`。

`guardians.out_of_scope_code`：OUT_OF_SCOPE_{GRADE, SUBJECT, OLYMPIAD} / EXAM_REPLACE_REFUSE / FORMAT_INVALID / LLM_LOW_CONFIDENCE（未知学科走顶层 error.code）。

完整 schema 与错误码用户提示 → `references/接口契约与数据格式.md`。人类可读输出：5 段标题 + 内容，公式 KaTeX 渲染。

## § 5 评估

5 维 rubric（正确性/规范性/启发性/检查性/举一反三，各 0–2 分）× 24 题盲评（9 学科、学段 1/3/5/7/10/12、越界题 2 道必拒）→ `evals/盲评回归题集.md`。
门槛：非越界 ≥80%；越界识别 100%；关键通过率 ≥95%/≥70%；结构完整 ≥90%。真机：M7b R2 93.64%；M6 12 图 99.57%。

## § 6 题型

17 类（single_choice … comprehensive，完整枚举与定义 → 接口契约）。

## § 7 边界（companion skills）

review-notebook=错因归类+同类练习；k12l=通用批改；how2talk=情绪/亲子沟通；handwriting-coach=评书写；reading-growth-architect=选书。本 Skill 只做"题目→5 段讲解"。

## § 8 路径 / § 9 反馈 / § 11 证据

- 路径：`references/实现路径与里程碑.md`（M0–M7 落地，M8 发布中）
- 反馈埋点：题目 hash + grade×subject×question_type + LLM 版本 + 5 段得分；≥30 题/学科 → KP 频率合并 `assets/subject_taxonomy.json` → prompt 微调

## § 10 版本

1.0.0 (design, 阶段7) 首版设计 → 1.1.0 (阶段7) V2 图片 OCR + 266 测试 → 1.1.1 (阶段8) M7b 真机 R2 93.64% + M6 真机 12 图 99.57% → 1.1.2 M8 发布收口（本版本）。明细见 CHANGELOG.md。
