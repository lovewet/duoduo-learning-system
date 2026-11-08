# 统一结构化诊断规范（diagnosis-schema v1.0）

> 设计目标（项目约定）：**「以前的和以后的所有的诊断都要结构化」**。
> 本文件是硬规范。任何批改 / 学情分析 / 试卷诊断 / 作文诊断 / 练习复盘 / 周报，
> **先产出符合本 schema 的 JSON 并入库，再写给人看的 Markdown 报告**。
> 自由文本报告只能作为结构化数据的「渲染结果」，不得再作为唯一事实源。

---

## 一、为什么要结构化

历史问题：诊断散在十几个 `.md` 报告里，出题脚本、复习排程、视频匹配、进度台账
都读不到；每次都要重新读一遍人话报告再手工摘重点，且容易摘错（阶段31
就发生过「凭局部印象补写作文内容」「误判 9(1) 默写失分」两次订正）。

结构化之后，**下游全部自动消费同一份数据**：

```
diagnosis JSON
   ├→ errors / error_category_mapping / mastery （错题库）
   ├→ diagnosis_items.assessment_focus （§6 出题考核侧重）
   ├→ diagnosis_items.video_needed + core_terms （§8 B 站视频检索 topic）
   ├→ 近期学习计划 / 进度台账 （§7 排期权重）
   └→ Markdown 报告 （给人看，渲染产物）
```

---

## 二、顶层必填字段

| 字段 | 类型 | 说明 |
|:--|:--|:--|
| `schema_version` | string | 固定 `"1.0"` |
| `diagnosis_id` | string | 全局唯一，建议 `DIAG-<YYYYMMDD>-<TYPE>` |
| `diagnosis_type` | enum | `exam_booklet_analysis` / `handwritten_paper_grading` / `essay_diagnosis` / `practice_review` / `oral_check` / `weekly_report` |
| `retrospective` | bool | 历史诊断回填置 `true`，并在 `limitations` 写明是反推的 |
| `learner` / `grade` / `exam_date` | string | 学习者、学段、日期 |
| `exam` | object | 考试名、学校、难度、官方等级；无考试时用 `null` |
| `source_pdfs` / `source_files` | array | 原始材料清单 |
| `read_channel` | object | 读取通道与择优记录（见 grading-analysis-playbook.md） |
| `subjects` | object | 每科官方结论 + 薄弱知识点表（含 `my_rate` / `class_rate` / `gap_vs_class`） |
| `items` | array | 逐题诊断，字段见下 |
| `cross_findings` | array | 跨学科根因，带 `weight`（0~1，合计 1） |
| `assessment_focus` | array | 由 `cross_findings` 派生，直接驱动出题考核 |
| `limitations` | array<string> | 缺什么、什么不确定、什么没编造 |
| `generated_at` | ISO datetime | 生成时间 |

## 三、`items[]` 逐题必填字段

| 字段 | 类型 | 规则 |
|:--|:--|:--|
| `item_id` / `subject` / `paper_qno` | string | 身份键，不用报告里的「我的错题 N」（会重排） |
| `score` / `full` | number\|null | **官方给多少写多少，不给就 null，禁止折算/编造** |
| `class_rate` | number\|null | 0~1 小数，与 `my_rate` 分开存 |
| `title` / `question_brief` | string | 题目摘要，数学公式须 OCR 补全后视觉复核 |
| `knowledge_points` | array<string> | 可多个，第一个作为主知识点 |
| `error_type` | enum | 沿用 `errors` 表既有枚举；**英语一律 `grammar`**（用户硬偏好） |
| `error_subtype` / `category_id` / `category_name` | string | 按 `three-subject-error-categories.md`：数学 M1–M4 / 英语 E1–E5 / 语文 Y1–Y3 |
| `root_cause` | string | 「错在第几步」的具体动作，不许写「粗心」「不会」 |
| `evidence` | array<string> | **只写可核实事实**：官方得分、班级得分率、OCR 复核结论、历史错题记录；禁止写臆测的学生错答 |
| `correct_action` | string | 下次要做的具体动作（可观测） |
| `severity` | enum | `🔴` / `🟡` / `🟢`；禁用中文「中/高」或英文 high/medium |
| `exam_focus` | array<string> | 直接进 §6 出题考核侧重 |
| `video_needed` | bool | `false` 的题不检索视频，避免攒无用课 |
| `core_terms` / `method_terms` / `question_features` | array<string> | 供 §8 视频引擎构造检索词 |
| `teach_instead` | string | 无对口课时的讲解方案 |

## 四、证据纪律（最容易出错的三条）

1. **学校错题本的【错题订正】栏常常是空白的**（供学生手写），PDF 里没有学生答案。
   此时不得臆测「他大概写成了 X」。诊断依据只能是：官方得分/满分、班级得分率、
   官方薄弱知识点表、以及**同场**已 OCR 的手写答题卡。
2. **官方没给总分与标准答案就不写**。报告里可以写「本次不估分」，不能折算出分数。
3. **数学公式从 PDF 文本层常被吞掉字母**（A/B/P/Q、分数、上标）。必须走
   夸克 `general-ocr` 或原图补，且补完要回原图复核；补不准的符号在 `limitations` 标明。

## 五、存储与写入顺序

```
① 生成 <姓名>_<类型>_<YYYYMMDD>.json → <REPORT_DIR>/诊断/
② 备份 error_db.sqlite（带时间戳）
③ 写 diagnoses（一次诊断一行）
④ 写 diagnosis_items（逐题一行，error_id 关联 errors）
⑤ 写 errors + error_category_mapping + mastery 联动
⑥ 写 Markdown 报告（渲染 JSON，不另起事实源）
```

数据库表：`diagnoses` / `diagnosis_items`（`bili_video_engine.py` 同批建立，
`UNIQUE(diagnosis_id, item_id)` 保证幂等重跑）。

**历史回填**：把过去的自由文本报告转成结构化时，`retrospective=true`，
`evidence` 写明「由 errors 表反推」，并把已作废的记录（如 1441）排除出 active 诊断项。
阶段31 已完成第一次回填：`DIAG-YYYYMMDD-HANDWRITTEN-YUWEN`（语文手写卷，1441–1452）。

## 六、与出题考核的联动（硬规则）

`assessment_focus[].weight` 直接作为 §6 出题流水线中该考点的**出题权重下限**：

- 权重 ≥ 0.25 的根因，每次组卷**必须**至少出 2 道针对性题；
- 权重 0.10–0.25 的，每次组卷至少 1 道；
- 「分类讨论/多解」类题，答案页必须写全解集，只答一解判半对；
- 「题干限定条件」类题，把限定条件放在题干中部或末尾，并要求作答时写出核对了哪几条；
- 「新定义」类题，必须用**全新定义**（不复用原题），检验方法迁移而非记答案。

## 七、交付前自检

- [ ] JSON 能被 `json.load` 解析，必填字段齐全
- [ ] 所有 `score/full/class_rate` 与官方报告逐项对得上（抽查 3 条）
- [ ] `evidence` 里没有「可能/大概/应该」等推测措辞
- [ ] `severity` 全是 emoji 三档
- [ ] `retrospective` 标记正确，历史回填写了 limitations
- [ ] `diagnosis_items.error_id` 全部能在 `errors` 查到
- [ ] Markdown 报告里的每个数字都能在 JSON 里找到出处
- [ ] `assessment_focus` 已同步给 §6 出题配置
