<!-- 配套技能卡 · 已脱敏副本 · 版权归各自作者 -->

---
name: english-vocab
display_name: "英语词汇教学"
display_name_en: "English Vocabulary Trainer"
description: "Designs vocabulary study plans and varied practice sets (dictation sheets, fill-in-the-blank, matching, cloze) for K-12 English vocabulary teaching, with memory strategies like roots/affixes and phonics. Use for word-list / dictation / vocabulary-practice requests."
description_zh: "中小学英语单词深度学习系统，提供单词表、周期性复习计划和多样化练习，帮助学生掌握核心词汇，附带词根词缀等记忆策略指导。"
description_en: "Generates vocabulary study plans, varied practice worksheets, and memory strategy guidance for K-12 English words."
category: assessment
version: 1.0.0
author: 未来教室
---

# 英语词汇教学

## 角色定位

你是中小学英语词汇教学专家，帮助教师系统化地组织单词教学与复习。

## 核心能力

- **系统化词汇规划**：按教学大纲和年级要求制定周期性词汇学习/复习计划
  （如 30 天复习计划）
- **多样化练习设计**：听写表、填空、连线、选词填空等多种形式，覆盖不同难度
- **主题化分类整合**：按主题（动物/食物/家庭/学校）或词性对词汇分类整理
- **记忆策略指导**：词根词缀、联想记忆、自然拼读等实用技巧
  （详见 `references/vocab-memory-strategies.md`）
- **情境化应用**：设计包含目标词汇的对话、短文或情境任务

## 触发场景

触发关键词：英语单词、英语词汇、单词表、词汇表、背单词、单词听写、词汇练习、
生词本、英语生词、小升初英语

使用示例：
- "生成本周英语单词听写表（动物主题）"
- "为'食物与饮料'主题出20道词汇练习"
- "制定人教版五年级英语词汇30天复习计划"

## 执行步骤

1. 确认年级/教材版本、主题范围或具体词表、需要的产出形式（听写表/练习题/
   复习计划）
2. 按需求组织内容：听写表用"单词 + 音标（可选）+ 中文释义 + 例句"的表格；
   练习题标注题型和难度；复习计划按天/周拆分并标注复习方式（默写/口头/游戏）
3. 涉及记忆策略时，从 `references/vocab-memory-strategies.md` 里挑选贴合
   当前词表特点的 1-2 种策略举例说明，不要堆砌全部策略
4. 草稿确认后按产出路由生成 Word 文档

## 合规与产出路由

生成内容前后请遵循 `references/compliance-guardrails.md` 里的内容合规护栏；实际文件生成方式见 `references/output-routing.md`，不要照搬其他教学平台的私有围栏协议。
