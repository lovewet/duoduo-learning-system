<!-- 配套技能卡 · 已脱敏副本 · 版权归各自作者 -->

---
name: study-methods-lookup
display_name: 学科学习方法速查
display_name_en: Study Methods Lookup
description: 青橙科教8学科16学段2000+学习方法与解题技巧结构化检索，覆盖小学/初中/高中数学、物理、化学、生物科学、语文、英语、历史、地理，含步骤与易错提示
description_zh: 青橙科教8学科16学段2000+学习方法与解题技巧结构化检索，覆盖小学/初中/高中数学、物理、化学、生物科学、语文、英语、历史、地理，含步骤与易错提示
description_en: Qingcheng Education's 2000+ structured study methods and problem-solving techniques across 8 subjects and 16 grade levels (math, physics, chemistry, science, Chinese, English, history, geography), with steps and pitfall tips
category: education
version: 1.1.0
author: 青橙科教
---

# 学科学习方法速查

> 青橙科教自研的学科学习方法与解题技巧库，覆盖小学/初中/高中 8 学科 16 学段方法库，共 2000+ 条学习方法，按「学科-学段」结构化组织，含解题步骤与易错提示。

## 技能说明

当用户需要以下场景时，按以下步骤执行：

1. 查询某学科某学段的学习方法与解题技巧
2. 查找某个知识点/题型对应的解题方法（如"化学式书写"、"一元二次方程"）
3. 需要某模块的学习策略、易错点、操作步骤
4. 为讲题/答疑提供解题方法参考
5. 为学生辅导提供分学科的学习方法建议
6. 为备课/出题补充对应题型的解题技巧

## 核心能力

| 能力 | 说明 |
|---|---|
| 多维度检索 | 按学科、学段、模块、关键词精准检索学习方法 |
| 方法详情 | 每条方法含名称、适用场景、操作步骤、易错提示 |
| 8学科16学段全覆盖 | 小/初/高中数学、物理、化学、科学、语文、英语、历史、地理 |
| 结构化组织 | 按学科方法库→模块→方法分层，检索高效 |

## 方法库索引

数据存放于 `references/`（每个学科学段一个 gz 压缩方法库），通过 `@references/_index.json` 索引定位：

| 学段 | 学科方法库文件 |
|------|---------------|
| 小学 | 小学数学-cz.json.gz、小学科学-cz.json.gz |
| 初中 | 初中数学/物理/化学/生物/科学/语文/英语/历史/地理/道德与法治 -cz.json.gz |
| 高中 | 高中数学/物理/化学/生物/语文/英语/历史/地理 -gz.json.gz |

## 执行步骤

### 第一步：确定用户需求

判断用户需求属于以下哪类：

1. **按学科方法库查询** — 用户想了解某学科某学段的全部学习模块与解题方法
2. **按关键词检索方法** — 用户想查找某个知识点/题型对应的解题方法（最常用）
3. **获取方法详情** — 用户想了解某个方法的具体步骤与易错点
4. **按模块浏览** — 用户想看看某学科某学段的某个知识模块有哪些方法

### 第二步：调用检索脚本

使用 Bash 工具调用 `scripts/methods_query.py`，根据需求选择对应子命令：

#### 1. 列出所有学科方法库
```bash
python3 scripts/methods_query.py subjects
```

#### 2. 搜索学习方法（按关键词，最常用）
```bash
python3 scripts/methods_query.py search --keyword "化学式" --subject "初中化学"
python3 scripts/methods_query.py search --keyword "一元二次方程"
python3 scripts/methods_query.py search --subject "高中物理" --module "力学"
```

参数说明：
- `--keyword`：搜索关键词（会匹配方法名称、适用场景、步骤、提示）
- `--subject`：限定学科（如"初中化学""高中数学"），不填则全库搜索
- `--module`：限定模块名（如"力学"）
- `--limit`：返回条数（默认 10）
- `--detail`：显示完整详情（步骤 + 易错提示）

#### 3. 获取某个方法的完整详情
```bash
python3 scripts/methods_query.py get --id 初中化学-cz-001 --detail
```

#### 4. 浏览某学科某学段的全部模块
```bash
python3 scripts/methods_query.py modules --subject "高中数学"
```

### 第三步：结果加工与输出

检索到方法后：
1. 从 `steps`（操作步骤）与 `tips`（易错提示）中提炼要点
2. **结合用户具体问题做"教研化"加工**——把通用方法与用户的具体题目/场景结合，给出针对性讲解
3. 讲解时给出清晰的步骤引导，并提醒典型易错点
4. 若检索不到直接匹配的方法，扩大关键词范围或换成上位概念再查（如"化学式"查不到就查"化学用语"）

### 数据来源与维护

- 方法库数据来自青橙科教方法库中心（ima 知识库批量提取）
- 本技能 references/ 为打包发布副本；维护时同步更新方法库中心
- 新增学科/学段方法库：在 references/ 新增 gz 压缩文件，并更新 `_index.json`