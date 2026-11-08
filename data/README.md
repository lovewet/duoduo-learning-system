# 数据目录（本包不含任何数据）

本仓库**不分发**任何学生数据。使用时把你自己的 SQLite 库放在本目录：

```
data/error_db.sqlite
```

四库表结构与字段定义见：

- `references/four-library-design.md` — 知识点库 / 错题库 / 题库 / 掌握度画像设计
- `references/error_record.schema.json` — 错题记录的 JSON Schema
- `references/schema-change-procedure.md` — 改表流程
- `references/db-audit-playbook.md` — 数据体检手册

`*.sqlite` / `*.csv` 等已被 `.gitignore` 排除，不会被误提交。
