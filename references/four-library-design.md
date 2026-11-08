# 学生学习数据库四库联动设计细节（阶段1 v2 定稿）

> 触发：用户"数据库要分类建立 要有出题的题库还要有错题库 错误知识点框架 要有知识点库 相互之间要有联系链接 不能完全独立"+"不光是现有的 我在其他地方还有很多题库知识点的数据"
>
> **📌 脚本命名约定（先读）**：本文出现的 `parse_docx_questions.py`、`sync_cloud_kb.py`
> 均为**原私有工作环境的历史脚本，不随本公开包分发** —— 它们是操作事实的可追溯记录，
> 照抄会 "No such file"。需要复现时，按文中描述的做法在 `scripts/` 下自行实现。
> 文中 `<RUNTIME_DIR>` / `<SCRIPTS_DIR>` 是占位符，指「你自己的运行目录 / 脚本目录」。


## 核心痛点（典型场景）

- 错题表里的知识点是自由文本，与结构化的知识点清单**对不上**，无法按知识点聚合与出题
- 数据散落在多个位置（SQLite 库、笔记、文档、云端知识库），口径不一
- 大量现成题目埋在 docx / PDF 里没有结构化，无法复用、改编、查重

**因此四库必须用 `knowledge_point_id` 贯穿**，而不是各自独立建表。

---

## 表结构 SQL（定稿）

```sql
CREATE TABLE knowledge_base (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    subject TEXT NOT NULL, edition TEXT NOT NULL, grade TEXT NOT NULL,
    unit TEXT NOT NULL, unit_num TEXT, point_name TEXT NOT NULL,
    point_type TEXT DEFAULT 'grammar', -- grammar/vocab/sentence/writing/concept
    detail TEXT, parent_id INTEGER REFERENCES knowledge_base(id),
    source TEXT, -- import_kp/100page/errors_mapping
    created_at TEXT DEFAULT (datetime('now','localtime'))
);
CREATE UNIQUE INDEX idx_kb_unique ON knowledge_base(subject, grade, unit, point_name);

CREATE TABLE knowledge_detail (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    knowledge_point_id INTEGER NOT NULL REFERENCES knowledge_base(id),
    unit TEXT NOT NULL, category TEXT NOT NULL, -- 词汇与短语/重点句式/重点语法/重点知识/写作背默
    sub_type TEXT, content TEXT NOT NULL, seq INTEGER,
    source TEXT DEFAULT '100page_docx',
    created_at TEXT DEFAULT (datetime('now','localtime'))
);
CREATE INDEX idx_kd_unit ON knowledge_detail(unit, category);

-- errors: 现有表保留 + ALTER ADD knowledge_point_id REFERENCES knowledge_base(id) + error_pattern

CREATE TABLE questions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    knowledge_point_id INTEGER NOT NULL REFERENCES knowledge_base(id),
    subject TEXT NOT NULL, grade TEXT NOT NULL, q_type TEXT NOT NULL,
    difficulty INTEGER DEFAULT 3, question TEXT NOT NULL, answer TEXT NOT NULL,
    solution TEXT, source TEXT, source_file TEXT,
    source_error_id INTEGER REFERENCES errors(id), -- 错题改编溯源
    usage_count INTEGER DEFAULT 0, correct_rate REAL,
    created_at TEXT DEFAULT (datetime('now','localtime'))
);
CREATE INDEX idx_q_kp ON questions(knowledge_point_id);

CREATE TABLE mastery (
    knowledge_point_id INTEGER PRIMARY KEY REFERENCES knowledge_base(id),
    error_count INTEGER DEFAULT 0, error_types TEXT, severity_avg REAL,
    last_error_at TEXT, practice_count INTEGER DEFAULT 0,
    correct_streak INTEGER DEFAULT 0, mastery_level INTEGER DEFAULT 0,
    next_review_at TEXT, updated_at TEXT DEFAULT (datetime('now','localtime'))
);

CREATE TABLE practice_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sheet_id TEXT, knowledge_point_id INTEGER REFERENCES knowledge_base(id),
    question_id INTEGER REFERENCES questions(id), error_id INTEGER REFERENCES errors(id),
    result INTEGER NOT NULL, practiced_at TEXT DEFAULT (datetime('now','localtime'))
);
CREATE INDEX idx_pl_kp ON practice_log(knowledge_point_id);

CREATE TABLE kp_mapping_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    error_id INTEGER, kb_id INTEGER,
    match_method TEXT, -- exact/auto_similar/manual
    confidence REAL, mapped_at TEXT
);
```

## mastery_level 计算规则（回写时自动更新）

| 条件 | 等级 |
|:-----|:----:|
| error_count=0 | 0 未知 |
| error_count≥3 或 correct_streak<2 | 1 薄弱 |
| practice≥3 且 correct_streak≥2 | 2 巩固 |
| correct_streak≥5 且 practice≥8 | 3 掌握 |

## 多源导入管道细节

```
数据源 → parser → normalize → dedup → load → 挂knowledge_point_id(自动匹配+人工抽检)
```

- **docx批量导入**（`parse_docx_questions.py`）：识别题干行/选项行/答案行（"答案: B"）/解析行；知识点识别=文件名校验（"有理数专项"→知识点）+题目关键词匹配；question内容MD5去重；未识别知识点进 pending_kp 清单
- **云端KB**（`sync_cloud_kb.py`）：读云端笔记与知识库（通过各自 API）→同一归一化管道；与本地按(subject,unit,point_name)合并
- **质量规则**：唯一约束合并重复源；题目MD5去重；未识别知识点人工确认；每批batch_id可回滚

## 已确认决策（阶段1 用户拍板）

1. 表名设计者定最优 → knowledge_base/knowledge_detail/errors(保留)/questions/mastery/practice_log
2. 错题382知识点映射=自动相似匹配（confidence阈值）+人工抽检
3. 100页详解按单元存 knowledge_detail 子表
4. 错题改编出题：薄弱点无现成题时由错题生成变式题

## 实施顺序

P0建表+94条迁移 → P1错题382知识点自动匹配+抽检 → P2 100页详解按单元入库 → P3 docx批量导入题库 → P4闭环 → P5云端

## 方案文档位置

- 完整方案: `<DATA_DIR>/学生学习数据库系统设计方案_v1.md`（v2内容）
- 100页docx已提取: `<DATA_DIR>/七年级上期英语核心知识/`（全文txt 199KB + 按单元切分JSON 221KB，10/10单元：Starter Unit1-3 + Unit1-7）
