# error_db.sqlite 加字段/改结构标准流程

> ## ⚠️ 环境说明（先读这段）
>
> 本文引用的 `duoduo_error_tracker.py`（入库主入口）、`skill_lint.py`（技能层校验）、
> `backfill_orig.py`（历史回填）、`classify_photo.py`、`ingest_card_answers_0909.py`、
> `migrate_to_sqlite.py` 都是**原私有工作环境的历史脚本，不随本公开包分发**。
> 文中提到它们是**操作事实的可追溯记录**（当时确实这么跑过），**不是给使用者的可执行命令** ——
> 照抄会得到 "No such file"。需要复现时，按文中描述的做法自行实现即可。
>
> 第 7 步「跑 skill_lint 确认技能没被改坏」在本包内**无法执行** ——
> 包内替代做法：改完跑 `python scripts/selftest_ingest.py` + `python scripts/verify_all.py`，
> 并人工 diff `SKILL.md` 与 `references/skills-registry.yaml` 是否一致。
>
> 文中 `<RUNTIME_DIR>` / `<SCRIPTS_DIR>` / `<WORKSPACE>` 是**占位符**，指「你自己的运行目录 / 脚本目录 / 工作区」，不是真实路径。

> 阶段9 实测（errors 表新增 `question_full` / `student_steps`）总结；同日二次实践补「列建了但一直是 NULL」「从自由文本列回填」两节。改任何表结构前读此文件。

## 为什么不能只 `ALTER TABLE` 就完事

`errors` 表**有多个写入者**：只加列不改写入点 → 新列永远为 NULL，看起来"功能已上线"其实一行数据都没录进去。

加字段时必须同步的写入点（阶段9 全库扫描结果，`grep -rn "INSERT INTO errors" <RUNTIME_DIR>/scripts`）：

| 写入点 | 用途 | 是否需改 |
|:--|:--|:--|
| `duoduo_error_tracker.py`（`add_error()` + `cmd_add` CLI） | 手工/批改入库**主入口** | ✅ 必改（含 `KNOWN_FIELDS` 白名单，`update_error` 也走它） |
| `classify_photo.py`（Kimi 提示词 + INSERT） | 照片流水线自动入库 | ✅ 必改（提示词要新字段 + INSERT 列 + 兜底值） |
| `migrate_to_sqlite.py` / `kimi_*.py` / `update_errors_2026*.py` / `ingest_card_answers_0909.py` | 历史一次性迁移脚本 | ❌ 已跑完，不再改（改了也无意义）；但**新写脚本要照最新列** |

## 🔴 新列上线后的必做审计：覆盖度盘点（阶段9 实测发现「列建了从未写过」）

新列建好、写入点也改了，**仍不等于有数据**——要按列统计非空数才知道真实覆盖：

```python
import sqlite3
c = sqlite3.connect('<DATA_DIR>/db/error_db.sqlite')
for t in ('errors','questions','question_items','exercise_answers'):
    cols = [r[1] for r in c.execute(f"PRAGMA table_info({t})")]
    n = c.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
    filled = {col: c.execute(f"SELECT COUNT(*) FROM {t} WHERE {col} IS NOT NULL AND TRIM({col})<>''").fetchone()[0] for col in cols}
    print(t, n, {k:v for k,v in filled.items() if v})
```

实测（阶段9，N条错题）：`question_full`（原题）**0 / 513 非空**——列建了、写入点也改了，但实际一条数据没进（图片流水线长期只往 `error_desc` 自由文本写摘要）；`student_steps` 仅 7。
**教训：任何「新增结构化列」上线后必须跑一次覆盖度盘点，不能看到 `ALTER` 成功就认为功能可用。**

### 数据源辨别（别把题库当学生作答）

| 表 | 存的是 | 能当「学生原作答」？ |
|:--|:--|:--|
| `errors` | 错因摘要 + （少量）原题/原作答 | ✅ 唯一来源 |
| `questions`(约 700) / `exercise_answers`(约 480) / `question_items`(约 1k) | 出题题库、历史练习卷答案、小题答案+解析 | ❌ **老师标准答案**，当学生的用＝直接泄题 |

## 从自由文本列回填结构列（阶段9 实测可行）

当结构化列长期为空、而信息其实一直写在自由文本列（如 `error_desc`）里时，**不必重拍卷面**：写一个幂等回填脚本把能确定识别的字段抽出来写回结构列。
范式（实例：`duoduo-practice-generation/scripts/backfill_orig.py`，`question_full` 0→107、`student_steps` 7→45）：

1. 先 `--dry-run --show 30` 抽样眼看，确认抽取规则不把正解/错因残句当原题；改任何正则后重跑抽样。
2. **只填空列**，且已有值先过质量闸门（脏值清空重算）——这样脚本**幂等**，可反复跑。
3. **必须 `--backup`**：备份落 `db_backups/error_db_<ts>_pre_orig_backfill.sqlite`。
4. **质量闸门宁缺勿错**：题面必须长度 3–90、含数字+运算符、不以运算符结尾、不含 `=`，且不命中脏值正则（`应[=为＝]` / `^时` / `^若` / `①` / `第N题` / `学生` / `错误` / `不会` / `写成` / `写了` / 结尾`得`）。**宁可写「原卷面未回传」也不印半截式子**。
5. **抽出值与同表其它列做交叉校验**：抽出的「学生原文」若与 `correct_answer` **等值**（去空格、统一减号后比较；**只等值、不做子串**）则该条是正解 → 丢弃。
6. 回填只改结构列，**原自由文本列一字不动**（保持溯源）。

## 六步流程

```bash
DB=<DATA_DIR>/db/error_db.sqlite

# 1. 备份（用户铁律：结构变更前必备份）
cp "$DB" "<RUNTIME_DIR>/backups/error_db.sqlite.bak-$(date +%Y%m%d_%H%M%S)"

# 2. 探列名 + 加列（幂等：已存在则跳过）
<RUNTIME_DIR>/tool_venv/bin/python -c "
import sqlite3
c=sqlite3.connect('$DB')
cols=[r[1] for r in c.execute('PRAGMA table_info(errors)')]
if 'question_full' not in cols:
    c.execute('ALTER TABLE errors ADD COLUMN question_full TEXT'); c.commit()
print([r[1] for r in c.execute('PRAGMA table_info(errors)')][-5:])"
```

3. 改**全部**在用的写入点（见上表）
4. 冒烟测试（下节）
5. **覆盖度盘点**（见上节）+ 需要时回填
6. 门控/技能文档同步（`duoduo-learning-database` 七张表 + `duoduo-error-analyzer` CP-1 + 相关技能门控）
7. 跑 `scripts/skill_lint.py` 确认技能层没被改坏

## 冒烟测试（写 → 读回 → 删除）

**禁止**直接跑真实流水线验证（浪费 API/OCR 额度、会往错题库塞垃圾）。造一条带唯一 source 的测试记录：

```bash
<RUNTIME_DIR>/tool_venv/bin/python scripts/duoduo_error_tracker.py add \
  --date 2026-09-10 --subject 测试 --chapter 冒烟 --kp "字段冒烟测试" \
  --desc "测试" --answer "x=1" --type careless --source "smoketest-$(date +%Y%m%d)" \
  --question-full "<整题全文>" --student-steps "<完整作答过程>"

# 读回确认内容完整（不是只看 id）→ 按 source 精确删除 → 打印剩余条数确认库干净
<RUNTIME_DIR>/tool_venv/bin/python -c "
import sqlite3
c=sqlite3.connect('$DB'); c.row_factory=sqlite3.Row
r=c.execute(\"SELECT id,question_full,student_steps FROM errors WHERE source='smoketest-YYYYMMDD'\").fetchone()
print('Q=',r['question_full']); print('S=',r['student_steps'])
c.execute('DELETE FROM errors WHERE source=?',('smoketest-YYYYMMDD',)); c.commit()
print('remaining:', c.execute('SELECT COUNT(*) FROM errors').fetchone()[0])"
```

要点：**用 `source` 做删除锚点**（唯一、不会误删真实数据）；`errors.id` 会自增跳号（冒烟用过 #540 后即删），这是正常的，不要试图回收 id。

## 字段长度约定

- `error_desc` / `correct_answer`：≤500，只放**错因摘要**，不是题面
- `question_full` / `student_steps`：≤8000，放**全文**（整题 / 完整作答过程）。截断在脚本里做（`.strip()[:8000] or None`），DB 层 TEXT 不限长
- 空 vs NULL 语义：字段有内容但学生确实没作答 → 写 `（空白未答）`，**不留 NULL**（NULL 表示"没采集"，两者下游行为不同）

## 历史欠账处理

新列上线后旧记录必为 NULL（阶段9 时 N条）。策略分两步：
1. **能回填的立刻回填**：信息本来就在自由文本列里的（题面/作答常写在 `error_desc`），用上面「从自由文本列回填结构列」范式一次性回填（实测 N条里能安全抽出原题 107、作答 45）——**不要因为「不追求 100%」就干脆不做**。
2. **抽不出来的不造假**：其余 400+ 条只有错因摘要，原作答**除重拍卷面否则永久拿不回来**；向用户**如实报缺口**（别再说「每道都有原题和作答」），并只在题目再次被触及时顺手重录。
