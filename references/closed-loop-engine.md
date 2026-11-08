# P4 闭环引擎（三脚本：改编/出题/回写）

> 自 SKILL.md 拆分（阶段9 技能审计）。SKILL.md 保留架构与铁律，实战细节看本文件。
>
> **📌 脚本命名约定（先读）**：本文出现的 `gen_error_variants.py`、`generate_practice_sheet.py`、
> `record_practice_result.py`、`docx_page_numbers.py` 均为**原私有工作环境的历史脚本，
> 不随本公开包分发** —— 它们是操作事实的可追溯记录（当时确实这么跑过），照抄会 "No such file"。
> 需要复现时，按文中描述的做法在 `scripts/` 下自行实现。
> 文中 `<RUNTIME_DIR>` / `<SCRIPTS_DIR>` / `<WORKSPACE>` 是占位符，指「你自己的运行目录 / 脚本目录 / 工作区」。


## P4 闭环引擎（三脚本，阶段1 实战验证）

三个脚本都在 `<SCRIPTS_DIR>/`，运行环境用 `<RUNTIME_DIR>/bin/python3`（python-docx可用；系统python缺lxml）。

### 1. 错题改编 `gen_error_variants.py`
无题薄弱点的出题兜底——从errors错题生成变式题：
- 数学：解析错题算式结构 → 模板题（绝对值混合/符号化简/乘方混合等4类，换随机数）
- 英语：按错误类型（拼写/三单/物主代词/be动词/连词）→ 模板填空变式
- 写入 questions（source='error_variant', source_error_id=原错题溯源）
- 校验方式：用自建数据跑一轮，记录变式题覆盖与掌握度升降结果。
- **🔴 变式题生成时answer字段常为空**（只写了解析）——后续需批量补答案：数学题用程序重算（见反例#8），英语题从解析语义提取（be动词/物主代词/三单/连词12道逐题核对全过）；补答案同时同步 question_items（item_no=1）

### 2. 出题引擎 `generate_practice_sheet.py`
> 🔴 **页码铁律（阶段1）**：本引擎及所有学生卷子脚本已接入 `<SCRIPTS_DIR>/docx_page_numbers.py` 共享页码工具（页脚"第 X 页 共 N 页"PAGE/NUMPAGES字段）。**任何新出的卷子必须带页码**——生成后验证：解压docx检查 `word/footer*.xml` 含 PAGE+NUMPAGES。

**批量改造旧脚本的两种import风格 + 一个docstring陷阱（36个脚本实操，阶段1）**：
- 风格A `from docx import Document`：在 `import os\nfrom docx import` 处插入 `import os, sys\nsys.path.insert(0, "<RUNTIME_DIR>/scripts")\nfrom docx_page_numbers import add_page_numbers\nfrom docx import`
- 风格B `import docx`（模块式）：在 `import docx` 处插入同前
- 调用点：`re.search(r"(\w+)\.save\(([^)]*)\)")` → 在 `X.save(...)` 前加 `add_page_numbers(X)`
- **🔴 陷阱：不要用 patch 匹配 `#!/usr/bin/env python3` 开头行来插入import**——带模块docstring的脚本（`"""..."""`在shebang后）会被模糊匹配误替换docstring的闭合引号，产生 SyntaxError: invalid character。正确锚点是真实的 `import os`/`from docx import` 行。批量改完必须全量 `ast.parse` 语法检查。

```bash
python3 generate_practice_sheet.py 数学 12 # 数学薄弱专项12题
python3 generate_practice_sheet.py 英语 15 "乘方" # 英语乘方过滤15题
```
- 按薄弱知识点选题（mastery_level=1, error_count降序）→ 生成docx练习卷+答案md → `<DATA_DIR>/`
- 写入exercise_answers + 更新usage_count + 设next_review_at=3天后（复习调度）
- 校验方式：用自建数据跑一轮，记录变式题覆盖与掌握度升降结果。

**🔴 SQL坑（本次踩过3次）**：直接 `ORDER BY m.error_count DESC LIMIT N` 会让错题最多的知识点（如正负数与数轴146题）霸占全部LIMIT名额，其他薄弱点一题都选不到。正确做法是**窗口函数均匀取样**：
```sql
SELECT ... FROM (
  SELECT q2.*, kb2.point_name,
         ROW_NUMBER() OVER (PARTITION BY q2.knowledge_point_id ORDER BY q2.usage_count ASC) AS rn
  FROM questions q2 JOIN knowledge_base kb2 ON q2.knowledge_point_id = kb2.id
  JOIN mastery m2 ON m2.knowledge_point_id = kb2.id
  WHERE kb2.subject = ? AND m2.mastery_level = 1
) q JOIN knowledge_base kb ON q.knowledge_point_id = kb.id
  JOIN mastery m ON m.knowledge_point_id = kb.id
WHERE q.rn <= 3 -- 每知识点最多3题，分散覆盖
ORDER BY m.error_count DESC
```
子查询内别名必须用 q2/m2/kb2，外层用 q/m/kb——混用会报 `no such column`。每知识点3题限制放SQL（rn<=3），Python侧不要再限，否则叠加成1题。

### 3. 结果回写 `record_practice_result.py`
```
python3 record_practice_result.py <sheet_id> "1:1 2:0 3:1 ..." # 1=对 0=错
```
- 每结果 → practice_log → 回写 mastery（practice_count+1, streak对+1/错清零）
- 等级规则：streak≥5且practice≥8→掌握(3)；practice≥3且streak≥2→巩固(2)；error_count≥3或streak<2→薄弱(1)
- 校验方式：用自建数据跑一轮，记录变式题覆盖与掌握度升降结果。
- 知识点关联：通过 `questions.question LIKE exercise_answers.question||'%'` 反查（exercise_answers存的是题目文本）

### 闭环使用场景
| 你说 | 系统做 |
|:---|:---|
| "给学生出一套数学薄弱题" | 出题引擎→薄弱点选题→docx卷 |
| "乘方专项15题" | kp_filter过滤出题 |
| "今天做了XX卷，记录结果" | 回写→掌握度更新 |
| "现在有哪些薄弱点？" | `SELECT kb.subject,kb.point_name,m.error_count FROM mastery m JOIN knowledge_base kb ON m.knowledge_point_id=kb.id WHERE m.mastery_level=1 ORDER BY m.error_count DESC` |
