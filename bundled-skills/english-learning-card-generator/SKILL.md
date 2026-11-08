<!-- 配套技能卡 · 已脱敏副本 · 版权归各自作者 -->

---
name: english-learning-card-generator
display_name: "英语文本生成学习卡片"
display_name_en: "English Text Learning Card Generator"
description: "接收用户提供的英语课文，按自然段生成一套学习卡片图片（每段一张，超长段落自动拆为两张）。每张卡片包含该段英文原文、提炼出的关键词汇列表、整段中文翻译以及与词汇数量基本一致的词汇填空练习题；配色与字体字号适合中小学生阅读，并依据文本内容生成正面、得体的人物/场景插图。当用户需要把英语课文、阅读文章、教材段落转换为可打印、可分享的学习卡片图片时使用。"
description_zh: "把英语课文按自然段转换为一套图文并茂的学习卡片图片：英文原文 + 关键词汇 + 中文翻译 + 词汇填空练习，题目难度与课文对齐，适合中小学生阅读。"
description_en: "Turn English textbook passages into a set of learning-card images (one per paragraph): original text, key vocabulary, Chinese translation and matched fill-in-the-blank exercises, with student-friendly design and AI illustrations."
category: "Education"
version: "1.0.0"
author: "师研工坊"
agent_created: true
---

# 英语文本生成学习卡片

## Overview

本 skill 把一篇英语课文转换为**一套学习卡片图片**：按自然段切分，每段生成一张竖版卡片（1080px 宽），卡片固定包含四要素——英文原文、关键词汇、整段中文翻译、词汇填空练习；插图由 AI 依据段落内容生成。卡片由 HTML 模板渲染为 PNG，排版稳定可复现。

## 硬性规则（任何情况下不可违反）

1. **一张卡片四要素齐全**：英文原文、关键词汇列表、整段中文翻译、词汇填空练习，缺一不可。
2. **长段拆分**：自然段超过约 **110 个英文单词**，或预估内容会超出卡片高度时，拆为**两张卡片**分别呈现（标签注明 `Paragraph X (1/2)`、`(2/2)`），翻译与练习随内容同步拆分。
3. **练习题数量 ≈ 该卡关键词汇数量**（允许 ±1）；**每题句子不少于 10 个英文单词**；题目难度与课文难度相当（详见 references/content-guide.md）。
4. **插图人物必须依据文本内容合理、正面地生成**；**严禁丑化、矮化或贬低正面人物**（包括科学家、英雄人物、历史人物、师长、儿童等）；不出现暴力、恐怖、低俗元素。
5. **适合中小学生阅读**：配色、字体、字号按 references/design-guide.md 执行；正文最小字号 18px，深色文字配浅色底，整体构图居中、基本对称。
6. 插图中**不得出现任何文字**（所有文字由 HTML 模板渲染，避免 AI 生成乱码文字）。

## 交付物结构

```
<当前工作目录>/学习卡片/<课文标题>/
├── spec.json          # 卡片内容规格（可再编辑、可重渲染）
├── images/            # AI 生成的段落插图
├── html/card-01.html  # 每张卡片的 HTML（便于微调）
└── card-01.png ...    # 最终学习卡片图片（交付物）
```

## 工作流程

### Step 1 接收课文并切分自然段

- 依空行、缩进或段首序号切分自然段；逐段编号。
- 若用户给的是一整块无分段文本：按每 4-6 句切为一段（初中及以下取 4 句，高中取 5-6 句），并在交付说明中注明切分方式。
- 段落过短（< 25 词）时，可与相邻段合并为一张卡片，避免卡片内容空洞。

### Step 2 通读全文，校准难度

- 判断课文难度档：`primary`（小学）/ `junior`（初中）/ `senior`（高中），依据：词汇量级、句子平均长度、从句密度、话题。
- 该难度档决定：词汇提炼的选取范围、翻译用语、练习题的句式与词汇难度（标准见 references/content-guide.md）。

### Step 3 逐段生成卡片内容

对每个（或拆分后的每半个）段落，准备：

1. **英文原文** `en_text`：保持原文，不改动、不删减。
2. **关键词汇** `vocab`：3-6 个，每条含 `word`（词/短语）、`pos`（词性）、`meaning`（简明中文释义）。选取标准与禁选项见 content-guide。
3. **中文翻译** `zh_text`：整段忠实、自然的翻译。
4. **填空练习** `exercises` + `answers`：数量 ≈ 词汇数（±1）；每题 ≥ 10 个英文单词；空格统一用 `______`（6 个下划线）标记；答案顺序与题号一致。
5. 拆分判断：段落 > 110 词 → 按 55/45 左右在句子边界切成两卡，各自独立配词汇、翻译与练习。

写作细则（选词标准、题目编写、拆分方法、难度校准）**必须**阅读 `references/content-guide.md`。

### Step 4 生成段落插图

- 对每张卡片，用 **ImageGen** 工具（如未加载，先 ToolSearch 检索 `ImageGen`，再经 DeferExecuteTool 调用）生成一张插图，保存到 `images/` 目录（如 `para-01.png`）。
- 提示词模板（按段落内容填空）：
  `儿童教育风格扁平插画：{依据段落内容描述的场景/人物}，明亮温暖的配色，构图简洁居中，背景干净，画面中不出现任何文字`
- 人物描绘规则（硬性）：依据文本内容合理呈现；正面人物（科学家、英雄、师长、学生等）必须得体、庄重、积极；严禁丑化、矮化、贬低；不确定如何呈现时改用场景/物品插画（如书本、田野、校园）。
- 生成失败或无需插图时，卡片自动降级为 emoji 装饰（spec 中给 `emoji` 字段），**不得阻塞整批任务**。
- 建议尺寸 1024×1024 或 1440×720；模板会按 `object-fit: cover` 居中裁切。

### Step 5 写 spec.json 并渲染

1. 按下方 schema 写 `spec.json`（UTF-8）。
2. 运行渲染脚本（自动完成：填模板 → 生成 HTML → 无头浏览器截图 → 裁切 → 输出 PNG；若缺 Pillow 会自动安装）：

```bash
<python> "<skill目录>/scripts/generate_cards.py" "<spec.json路径>" "<输出根目录>"
```

- `<python>` 用会话中的托管 Python（如 `<HOME>/.workbuddy/binaries/python/versions/3.13.12/python.exe`）。
- 脚本依次输出每个 PNG 的路径；结束打印 `DONE`。
- 全部完成后用 present_files 批量展示所有 PNG。

### Step 6 检查与交付

- 逐张确认：四要素齐全、无文字溢出、插图与内容匹配且人物呈现得体、构图对称。
- 发现溢出或拥挤 → 回到 Step 3 拆分或精简，重跑 Step 5（重渲染很快，直接覆盖）。
- 交付时简要说明：共几张卡片、每张对应哪一段、词汇数与练习数的对应关系。

## spec.json Schema

```json
{
  "source_title": "Unit 3 Reading",          // 必填，页眉标题
  "brand": "师研工坊 · 英语学习卡片",          // 可选，页脚署名
  "grade_hint": "初中",                       // 可选，显示在页脚
  "cards": [
    {
      "para_label": "Paragraph 1",           // 必填；拆分卡写 "Paragraph 3 (1/2)"
      "image": "images/para-01.png",         // 可选，相对 spec 所在目录；无则用 emoji
      "emoji": "🌾",                          // 可选，无图时的装饰
      "en_text": "English paragraph text ...",
      "vocab": [
        {"word": "hybrid", "pos": "n./adj.", "meaning": "杂交的；混合的"}
      ],
      "zh_text": "整段中文翻译……",
      "exercises": [
        "Scientists around the world are studying hybrid rice because it can grow well in ______ fields."
      ],
      "answers": ["hybrid"],
      "word_bank": true                       // 可选，默认 true（显示词库条）
    }
  ]
}
```

## 故障排除

- **脚本找不到浏览器**：脚本按 Edge→Chrome 常见路径自动探测；都失败时设置环境变量 `CARD_BROWSER` 指向 msedge.exe/chrome.exe 后重跑。
- **PNG 空白或字体异常**：确认 HTML 头部 `<meta charset="UTF-8">` 未被改动；重跑脚本。
- **内容溢出被裁切**：该段内容超长，回 Step 3 拆分为两张卡。
- **Pillow 安装失败**：手动在托管 Python 对应 venv 中 `pip install pillow`；仍失败则脚本输出未裁切整图，可先交付并在说明中注明。

## Resources

- `assets/card-template.html`：卡片版式模板（脚本自动填充，含占位符；修改版式时同步阅读 design-guide 并保持占位符不变）。
- `scripts/generate_cards.py`：一键渲染脚本（spec.json → HTML + PNG）。
- `references/content-guide.md`：词汇提炼、翻译、填空题编写、长段拆分、插图人物规则的详细标准。
- `references/design-guide.md`：配色、字体字号、构图对称性的视觉规范。
