# 校验 · 数据入库 · 踩坑清单

> 讲义流水线文档的第 9~12 章，独立成文。
> 上游：`lecture-pipeline.md`（§0~§7）、`answer-sheet.md`（§8）

## 9. 出厂校验（`scripts/verify_lecture.py`）

### 9.1 六类检查

| 类 | 查什么 |
|---|---|
| 符号 | 双重转义 `&amp;gt;` / `&amp;lt;` / `&amp;amp;` |
| 选项 | 数量 3 或 4、无重复、无空、**两次作答选项一致** |
| 答案 | 索引不越界、解析非空 |
| 题目 | 题干非空 |
| 结构 | div 配平、标签配对、无死链、无重复 id |
| 措辞 | 无「0 分三连」「每次都弱」等评判性表述 |

### 9.2 写法教训（校验工具本身要准）

1. **两段式判分让选项渲染两遍** → 不能报"8 个选项"，应"取前一半并校验两段一致"
2. **FILL/JUDGE 的自评按钮也用了 `.ot` 类** → 必须**按容器区分**：
   - `<div class="opts">` = 选择题
   - `<div class="opts row2">` = 自评按钮

**校验工具误报比不校验更糟** —— 会让人忽略真实问题。

---


## 10. 数据入库（讲义做完必须回写）

### 10.1 四库联动

| 表 | 写什么 |
|---|---|
| `errors` | 每道新错题（含 error_pattern / student_steps） |
| `knowledge_base` | 缺的知识点先补，再回填 `knowledge_point_id` |
| `questions` | 讲义里的练习题（含答案与解析） |
| `task_cards` | 7 天 × 3 科的任务卡 |
| `mastery` | 有错题的知识点重建画像（mastery_level=0, interval=1） |

### 10.2 注意事项

- **先查重**：`date + subject + error_desc`
- **只导确保正确的题**：算不出确定答案的宁可不入库（别污染）
- **CSV 要同步**：`errors/questions/task_cards/knowledge_base/mastery` 五张，UTF-8-BOM
- **NAS 主库对 SMB 只读**：本地改完导出增量 `.sql` 放到 NAS，等容器内执行

---


## 11. 踩坑清单（19 条，按血泪程度排）

1. **`ENDDAY` 一个 day 只能 1 个**（多个会提前关 body）
2. **题干/选项的转义规则不同**（题干写 `&lt;`，选项写裸 `<`）
3. **ASCII `|` 会破坏字段** → 绝对值用全角 `｜`
4. **多行 HTML 只能放 LEC 块**（放题目行只保留第一行，且不报错）
5. **SVG 里的文字只转义一次**（传 `y > 0` 给 esc，不要传 `y &gt; 0`）
6. **自己出的题必须先算**（本项目出现 5 次"答案解析不一致"）
7. **PDF 里的图会丢**（"如图"的题必须自己重画）
8. **PDF 里的 `÷` 和 `+` 极易看错**（用答案反推验算）
9. **Python 脚本里写中文长句，ASCII 双引号会截断字符串** → 长内容先 Write 到文件再读
10. **head 替换边界算错会残留旧版**（症状：div 深度≠0 + 重复 id）
11. **重写时容易漏掉旧图解**（v5 重写后 5 张图只剩 1 张）
12. **校验脚本的误报比不校验更糟**（两段式判分、自评按钮都会骗过简单正则）
13. **框图含答案，不能进作答纸**
14. **题号必须网页与作答纸同源**（都用 `.qno`，不要各自编号）
15. **`w:sz` 是半磅不是 twips** —— `SZ_BODY / 2.0` 才得 pt；写成 `/ 20.0` 会**少算 10 倍**，
    分页与利用率全错（表现为"利用率 8%"这种离谱数字）
16. **估算行数不能只数 `<br>`** —— 英语阅读原文没有 `<br>`，实际折 8~19 行。
    用 `est_lines()` 按视觉宽度算（中日韩 1.0、英文 0.55，每行 42 字宽）
17. **选项不能一律算 1 行或 N 行** —— 4 个 18 字选项合计 72 字照样折行。
    用 `opt_rows()` 按宽度贪心装箱
18. **「每天强制一页」是会失效的假设** —— 全部 63 题进纸后单天 920~1683pt ≫ 757pt。
    假设失效就换算法（`paginate()` 按真实页高切分），**别靠调参数糊过去**；
    日志里出现「利用率 >100% 却仍打印 → 1 页」就是算法与假设脱节的信号
19. **校验脚本别写死版本号** —— `verify_answer_key.py` 曾写死 `v10.html`，
    网页升到 v13 后拿旧网页对新答案册，报 5 条假差异。用 `glob` 自动取最新版

---


## 12. 复用清单（下次做新一期讲义时照着做）

```
□ 1. 转 PDF → raw_text.txt，提取「薄弱知识点表」
□ 2. 提取每道错题的「变式练习 + 参考答案 + 详解」（extract_bank.py）
□ 3. 逐题验算，写「错在第几步」（error_pattern）
□ 4. 按 0 分优先排序，排 7 天（三科并行，数学占一半）
□ 5. 每天按「八件套」写 DSL（先说清楚 → 表 → 易错 → 演示 → 视频 → 题）
□ 6. 程序框图题每题生成一张 SVG（纯流程结构，**无演算区面板**）
□ 7. 渲染 → 合并 head/day1-7/tail → 跑 patch_head.py 同步页头
□ 8. 跑 verify_lecture.py，必须 0 问题
□ 9. 出作答纸 docx + html（**全部题目进纸**，零答案零框图，题号一致）
□ 10. 出答案册 → 跑 verify_answer_key.py，必须 63/63 通过
□ 11. 打印 → 手写 → 拍照/扫描 → 按纸批改 → 填《批改记录》
□ 12. 入库（errors / kb / questions / task_cards / mastery）+ 同步 CSV
```

---

**相关文件**
- `scripts/lecture_dsl.py` — DSL 渲染器
- `scripts/dsl_source.py` — DSL 解析（唯一真值）+ 版式参数集中定义
- `scripts/verify_lecture.py` — 出厂校验
- `scripts/make_answer_docx.py` / `make_answer_html.py` — 作答纸（Word / HTML，同源）
- `scripts/make_answer_key.py` — 答案册
- `scripts/verify_answer_key.py` — 答案册 vs 网页交叉校验
- `scripts/patch_head.py` — 同步 print.css / print.js.html 进已构建的页头
- `scripts/strip_scratch_area.py` — 删除框图「演算区」面板
- `scripts/extract_bank.py` — 从学情分析 raw_text 挖变式题库
- `assets/print.css` / `assets/print.js.html` — 网页端作答纸打印
- `assets/figs/q1~q5.svg` — 程序框图模板
