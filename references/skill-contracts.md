# 配套技能调用契约（28 项）

> 注册表 `skills-registry.yaml` 只回答「调谁」，本文件回答「**具体给什么、拿回什么、
> 缺了怎么办**」。20 个学习类技能的具体内容已随包放在 `bundled-skills/`，
> 6 个第三方通用文档解析工具请自行安装（本包不分发他人技能全文）。

> 机器可读版本：`skill-contracts.json`；可执行解析与兜底：`scripts/skill_contracts.py`。

## 通用调用协议

```json
{
  "skill": "<name>",
  "trigger": "<命中的触发词>",
  "inputs": { ... },        // 见下表「输入」列，缺字段先报缺，不猜
  "expect": [ ... ],        // 见「输出」列，返回必须可校验
  "on_missing": "<fallback>"
}
```

**编排顺序**：命中多条按 `priority` 升序，第一条为主，其余作补充；
主技能失败时走 `fallback`，并在交付物里写明「该能力由兜底实现提供」，不假装调过外部技能。

## 契约总表

| # | 技能 | 层 | 触发词 | 输入 | 输出 | 优先级 | 具体内容 | 缺失兜底 |
|:--|:--|:--|:--|:--|:--|--:|:--|:--|
| 1 | `duoduo-learning-system` | orchestrator | 学生/错题/作答纸/答案册 | 学情分析PDF/练习册照片/错题原题 | 网页讲义/作答纸docx/html/答案册docx/html | 1 | 外部依赖 | — |
| 2 | `mingbian-error-attribution` | content | 错因/归因/为什么错/错在第几步 | 原题/学生错解过程/班级正确率 | 证据链/主次错因/A/B/C分层再练题组 | 2 | `bundled-skills/` 已含 | skill_contracts.attribute_error()：13 值 error_t |
| 3 | `mingbian-tiered-variation` | content | 变式题/分层命题/专项题组/培优补差题 | 知识点/或一道母题 | A通道多题型题组 / B通道基础-提升-拓展三层变式/附答案与命题意图 | 3 | `bundled-skills/` 已含 | skill_contracts.tiered_variation()：A/B/C 三档变式生 |
| 4 | `mingbian-paper-blueprint` | content | 出卷/组卷/命题/双向细目表 | 教材版本/年级/范围 | 双向细目表/试卷/答案 | 2 | `bundled-skills/` 已含 | skill_contracts.paper_blueprint()：组卷细目表结构 |
| 5 | `study-methods-lookup` | content | 学习方法/解题技巧/怎么记/怎么学 | 学科/学段/题型或知识点 | 结构化方法卡/步骤/易错提示 | 4 | `bundled-skills/` 已含 | skill_contracts.method_lookup()：方法索引与命中规则 |
| 6 | `junior-school-portal` | content | 知识点讲解/概念辨析/复习方法/备考建议 | 学科/知识点 | 知识梳理/方法建议 | 4 | `bundled-skills/` 已含 | skill_contracts.concept_glossary()：初中概念口径校验 |
| 7 | `study-guide-html` | content | 复习讲义/学科复习系列/做一册/批量出册 | 学科/章节或专题/册次计划 | 单文件HTML复习讲义系列 | 5 | `bundled-skills/` 已含 | scripts/lecture_dsl.py + assets/print.css |
| 8 | `socrates-math-coach` | content | 数学实验/交互动图/几何画板/动点最值 | 数学问题 | 交互式推演可视化 | 6 | `bundled-skills/` 已含 | assets/figs/*.svg 程序框图示例 + 手工讲解，不生成交互页 |
| 9 | `muma-learning-expert` | content | 物理/化学/自主学习平台 | 学科 | 讲解/探究/理解检验 | 6 | `bundled-skills/` 已含 | references/learning-science.md / icap-framewor |
| 10 | `local-ocr` | tool | 扫描件识别/OCR/拍照试卷/老卷子 | 图片或扫描PDF | 逐行文本 + 可选坐标与置信度 | 2 | `bundled-skills/` 已含 | scripts/quark_ocr.py（需自备凭证）或纯文本输入 |
| 11 | `exercise-assistant` | content | 五段讲解/思路怎么讲/举一反三/这题讲清楚 | 题目/学段/学科 | PROBE/STRATEGY/RUN/CHECK/TRANSFER 五段结构 | 5 | `bundled-skills/` 已含 | scripts/duoduo_query.py + make_answer_* 系列 |
| 12 | `homework-explain-card` | content | 我怎么跟他讲/家长讲题/别直接给答案/辅导作业怎么开口 | 题目/年级/孩子卡在哪 | 3 个启发问句 + 讲法步骤 + 单独放在最后的答案区 | 7 | `bundled-skills/` 已含 | skill_contracts.explain_card()：3 个启发问句 + 答案后置 |
| 13 | `class-analysis-junior` | content | 学情分析/3-2-1建议/阶段总结怎么写/这阶段学得怎么样 | 成绩或得分明细/知识点掌握表 | 3 项立即行动 / 2 项中期调整 / 1 项长期机制 | 7 | `bundled-skills/` 已含 | scripts/metrics.py + duoduo_query.py stats |
| 14 | `grade9-chinese-error-diagnosis-core` | content | 语文错题/语文错因/阅读不会/作文偏题 | 语文题目/学生作答/口述思路 | 考点定位/采分点拆解/A–G 主因次因 | 3 | `bundled-skills/` 已含 | references/three-subject-error-categories.md 语 |
| 15 | `chinese-essay-grading-assistant` | content | 作文批改/改作文/作文评语/作文打分 | 作文文本或图片/学段/批改重点 | 分项打分/逐段批注/病句错别字修正 | 4 | `bundled-skills/` 已含 | references/learning-science.md + 只批改不代写原则 |
| 16 | `english-tutor` | content | 英语批改/英语作文/完形填空/阅读理解 | 英语题目/学生作答/练习类型 | 批改意见/讲解/知识点归纳 | 3 | `bundled-skills/` 已含 | references/three-subject-error-categories.md 英 |
| 17 | `english-vocab` | content | 背单词/词汇/拼写错/单词表 | 单词范围/学段 | 单词表/周期复习计划/练习 | 5 | `bundled-skills/` 已含 | scripts/duoduo_query.py search + export_csv.py |
| 18 | `edu-reading-diagnose` | content | 阅读丢分/阅读理解不会/阅读错因/伴读 | 阅读题/学生答案 | 七类常见错因自查/答题思路/家庭伴读建议 | 6 | `bundled-skills/` 已含 | references/answer-sheet.md §8 阅读题规范 |
| 19 | `english-exam-authoring` | content | 出英语题/英语命题/英语练习卷/单元测试 | 考点清单/教材单元/学情数据 | 英语试题/学生版 docx/教师版 docx | 4 | `bundled-skills/` 已含 | scripts/qtypes.py + make_answer_key.py |
| 20 | `english-learning-card-generator` | content | 学习卡片/课文卡片/词汇填空/预习卡片 | 英语课文文本 | 图文卡片图片/关键词汇/中文翻译 | 6 | `bundled-skills/` 已含 | scripts/make_answer_html.py 卡片版式 |
| 21 | `study-planner` | content | 学习计划/周计划怎么排/复习安排/备考规划 | 目标/截止日/每日可用时长 | 粗略大纲 → 周任务清单 → 每日卡片（按需逐层展开） | 7 | `bundled-skills/` 已含 | skill_contracts.study_plan()：三层计划（学期/周/日） |
| 22 | `pdf` | tool | 合并PDF/拆分PDF/PDF加密/PDF转图片 | PDF 文件 | 处理后 PDF 或图片 | 9 | 外部依赖 | scripts/ingest_source.py（坐标重排，符号不错位） |
| 23 | `pdfkit-py` | tool | PDF提取/PDF编辑/OCR降级/扫描件提取 | PDF 文件 | 文本/图片/新 PDF | 9 | 外部依赖 | scripts/ingest_source.py |
| 24 | `markitdown` | tool | 转markdown/文档转换/docx转md | 各类文档 | Markdown | 9 | 外部依赖 | scripts/ingest_source.py |
| 25 | `wj-pdf2md` | tool | PDF转md/扫描件转md/版面分析 | PDF | document.md + 图片资产 + 转换报告 | 9 | 外部依赖 | scripts/ingest_source.py |
| 26 | `universal-doc-reader` | tool | 解析文档/文档转md/本地文档库 | PDF/图片/Office/EPUB | 可定位 Markdown | 9 | 外部依赖 | scripts/ingest_source.py |
| 27 | `xc-doc-parser-workbuddy` | tool | 文档解析/图片转文字/OCR | PDF/图片 | Markdown/JSON | 9 | 外部依赖 | scripts/ingest_source.py；手写材料必须走 quark_ocr.py |
| 28 | `cn-math-taxonomy` | tool | 根因回溯/先修关系/这道题该补哪个先修/课标条目 | cn 知识点 id/学生 knowledge_point | 先修链(含原因说明)/薄弱根因候选/课标条目 | 8 | 外部依赖 | references/three-subject-error-categories.md（本 |

## 逐条细则

### `duoduo-learning-system` (priority 1)

- **职责**：总调度 + 错题数据主库
- **触发**：学生, 错题, 作答纸, 答案册, 讲义, 任务单, 录入错题, 复习安排, 家长沟通, 整理错题, 今天学什么, 复习任务
- **输入**：学情分析PDF, 练习册照片, 错题原题, 作答纸照片或答案JSON
- **输出**：网页讲义, 作答纸docx/html, 答案册docx/html, 批改报告, 增量SQL
- **学科**：数学, 语文, 英语
- **具体内容**：external:本技能本体（总调度）
- **缺失兜底**：—
- **外部依赖说明**：本技能本体（总调度）

### `mingbian-error-attribution` (priority 2)

- **职责**：错因归因（数学）
- **触发**：错因, 归因, 为什么错, 错在第几步, 讲评课, 分层再练, 这题错在哪, 老是错, 反复错, 同类题还错
- **输入**：原题, 学生错解过程, 班级正确率
- **输出**：证据链, 主次错因, A/B/C分层再练题组, 讲评课建议
- **学科**：数学
- **具体内容**：bundled-skills/mingbian-error-attribution/SKILL.md
- **缺失兜底**：skill_contracts.attribute_error()：13 值 error_type 枚举 + 三段式归因

### `mingbian-tiered-variation` (priority 3)

- **职责**：分层变式命题（数学）
- **触发**：变式题, 分层命题, 专项题组, 培优补差题, 专项练习, 分层练习, 专项训练, 变式练习, 要分层, 出几道同类题, 再来几道
- **输入**：知识点, 或一道母题
- **输出**：A通道多题型题组 / B通道基础-提升-拓展三层变式, 附答案与命题意图
- **学科**：数学
- **具体内容**：bundled-skills/mingbian-tiered-variation/SKILL.md
- **缺失兜底**：skill_contracts.tiered_variation()：A/B/C 三档变式生成规则

### `mingbian-paper-blueprint` (priority 2)

- **职责**：组卷与双向细目表（数学）
- **触发**：出卷, 组卷, 命题, 双向细目表, 周测卷, 模拟卷, 出一套卷, 出卷子, 单元测试卷, 按考点出题
- **输入**：教材版本, 年级, 范围, 用途, 总分, 时长
- **输出**：双向细目表, 试卷, 答案, 分步评分标准
- **学科**：数学
- **具体内容**：bundled-skills/mingbian-paper-blueprint/SKILL.md
- **缺失兜底**：skill_contracts.paper_blueprint()：组卷细目表结构

### `study-methods-lookup` (priority 4)

- **职责**：方法卡检索（8学科16学段）
- **触发**：学习方法, 解题技巧, 怎么记, 怎么学, 记不住, 怎么背, 有什么方法
- **输入**：学科, 学段, 题型或知识点
- **输出**：结构化方法卡, 步骤, 易错提示
- **学科**：数学, 物理, 化学, 生物, 语文, 英语, 历史, 地理
- **具体内容**：bundled-skills/study-methods-lookup/SKILL.md
- **缺失兜底**：skill_contracts.method_lookup()：方法索引与命中规则

### `junior-school-portal` (priority 4)

- **职责**：初中全科知识口径与学习方法
- **触发**：知识点讲解, 概念辨析, 复习方法, 备考建议, 讲讲这个概念, 这个概念怎么理解, 知识点没听懂
- **输入**：学科, 知识点
- **输出**：知识梳理, 方法建议
- **学科**：数学, 物理, 化学, 英语, 语文, 历史, 道法
- **具体内容**：bundled-skills/junior-school-portal/SKILL.md
- **缺失兜底**：skill_contracts.concept_glossary()：初中概念口径校验

### `study-guide-html` (priority 5)

- **职责**：复习讲义生产线（版式与批量）
- **触发**：复习讲义, 学科复习系列, 做一册, 批量出册, 做一本讲义, 整理成册
- **输入**：学科, 章节或专题, 册次计划
- **输出**：单文件HTML复习讲义系列
- **学科**：数学, 英语, 语文, 历史, 政治, 地理, 化学, 物理, 生物, 科学, 社会
- **具体内容**：bundled-skills/study-guide-html/SKILL.md
- **缺失兜底**：scripts/lecture_dsl.py + assets/print.css

### `socrates-math-coach` (priority 6)

- **职责**：交互式数学实验
- **触发**：数学实验, 交互动图, 几何画板, 动点最值, 函数图像可视化, 画图看看, 动一下图
- **输入**：数学问题
- **输出**：交互式推演可视化
- **学科**：数学
- **具体内容**：bundled-skills/socrates-math-coach/SKILL.md
- **缺失兜底**：assets/figs/*.svg 程序框图示例 + 手工讲解，不生成交互页

### `muma-learning-expert` (priority 6)

- **职责**：理化生自主学习平台
- **触发**：物理, 化学, 自主学习平台
- **输入**：学科
- **输出**：讲解, 探究, 理解检验
- **学科**：物理, 化学, 数学
- **具体内容**：bundled-skills/muma-learning-expert/SKILL.md
- **缺失兜底**：references/learning-science.md / icap-framework.md

### `local-ocr` (priority 2)

- **职责**：本地离线 OCR（RapidOCR），读取通道的印刷体基准
- **触发**：扫描件识别, OCR, 拍照试卷, 老卷子, 印刷体提取
- **输入**：图片或扫描PDF
- **输出**：逐行文本 + 可选坐标与置信度
- **学科**：all
- **具体内容**：bundled-skills/local-ocr/SKILL.md
- **缺失兜底**：scripts/quark_ocr.py（需自备凭证）或纯文本输入

### `exercise-assistant` (priority 5)

- **职责**：K12 五段讲解骨架（审题→思路→解答→检查→举一反三）
- **触发**：五段讲解, 思路怎么讲, 举一反三, 这题讲清楚, 这题怎么做, 讲一下这道题, 思路是什么
- **输入**：题目, 学段, 学科, 题型
- **输出**：PROBE/STRATEGY/RUN/CHECK/TRANSFER 五段结构
- **学科**：数学, 语文, 英语, 物理, 化学, 生物, 历史, 地理
- **具体内容**：bundled-skills/exercise-assistant/SKILL.md
- **缺失兜底**：scripts/duoduo_query.py + make_answer_* 系列

### `homework-explain-card` (priority 7)

- **职责**：家长口播讲题卡（先问再讲，不给可抄答案）
- **触发**：我怎么跟他讲, 家长讲题, 别直接给答案, 辅导作业怎么开口, 怎么给孩子讲, 辅导时怎么问
- **输入**：题目, 年级, 孩子卡在哪
- **输出**：3 个启发问句 + 讲法步骤 + 单独放在最后的答案区
- **学科**：数学, 语文, 英语
- **具体内容**：bundled-skills/homework-explain-card/SKILL.md
- **缺失兜底**：skill_contracts.explain_card()：3 个启发问句 + 答案后置

### `class-analysis-junior` (priority 7)

- **职责**：学情诊断报告的 3-2-1 建议结构
- **触发**：学情分析, 3-2-1建议, 阶段总结怎么写, 这阶段学得怎么样
- **输入**：成绩或得分明细, 知识点掌握表
- **输出**：3 项立即行动 / 2 项中期调整 / 1 项长期机制
- **学科**：all
- **具体内容**：bundled-skills/class-analysis-junior/SKILL.md
- **缺失兜底**：scripts/metrics.py + duoduo_query.py stats

### `grade9-chinese-error-diagnosis-core` (priority 3)

- **职责**：语文错因诊断（A–G 七类）
- **触发**：语文错题, 语文错因, 阅读不会, 作文偏题, 文言文翻译错, 名著题错, 采分点, 语文阅读老丢分, 文言文看不懂
- **输入**：语文题目, 学生作答, 口述思路
- **输出**：考点定位, 采分点拆解, A–G 主因次因, 答题模板, 记忆口诀
- **学科**：语文
- **具体内容**：bundled-skills/grade9-chinese-error-diagnosis-core/SKILL.md
- **缺失兜底**：references/three-subject-error-categories.md 语文 A–G 七类

### `chinese-essay-grading-assistant` (priority 4)

- **职责**：语文作文批改（小初高通用）
- **触发**：作文批改, 改作文, 作文评语, 作文打分, 升格, 帮我看看作文
- **输入**：作文文本或图片, 学段, 批改重点
- **输出**：分项打分, 逐段批注, 病句错别字修正, 总评, 升格建议
- **学科**：语文
- **具体内容**：bundled-skills/chinese-essay-grading-assistant/SKILL.md
- **缺失兜底**：references/learning-science.md + 只批改不代写原则

### `english-tutor` (priority 3)

- **职责**：英语错题批改讲解（作文/阅读/完形/语法）
- **触发**：英语批改, 英语作文, 完形填空, 阅读理解, 长难句, 英语讲解, 英语这句对吗, 英语怎么改
- **输入**：英语题目, 学生作答, 练习类型
- **输出**：批改意见, 讲解, 知识点归纳, 资源推荐, 学习路径
- **学科**：英语
- **具体内容**：bundled-skills/english-tutor/SKILL.md
- **缺失兜底**：references/three-subject-error-categories.md 英语分门

### `english-vocab` (priority 5)

- **职责**：英语词汇（单词表 / 周期复习 / 词根词缀）
- **触发**：背单词, 词汇, 拼写错, 单词表, 词根词缀, 单词总记不住
- **输入**：单词范围, 学段
- **输出**：单词表, 周期复习计划, 练习, 记忆策略
- **学科**：英语
- **具体内容**：bundled-skills/english-vocab/SKILL.md
- **缺失兜底**：scripts/duoduo_query.py search + export_csv.py

### `edu-reading-diagnose` (priority 6)

- **职责**：语文阅读理解家长侧速查
- **触发**：阅读丢分, 阅读理解不会, 阅读错因, 伴读, 读不懂文章
- **输入**：阅读题, 学生答案
- **输出**：七类常见错因自查, 答题思路, 家庭伴读建议
- **学科**：语文
- **具体内容**：bundled-skills/edu-reading-diagnose/SKILL.md
- **缺失兜底**：references/answer-sheet.md §8 阅读题规范

### `english-exam-authoring` (priority 4)

- **职责**：英语命题（日常练习 / 中招模拟双模式）
- **触发**：出英语题, 英语命题, 英语练习卷, 单元测试, 改编语篇, 试题质检, 出一份英语卷
- **输入**：考点清单, 教材单元, 学情数据
- **输出**：英语试题, 学生版 docx, 教师版 docx, 五维质检结论
- **学科**：英语
- **具体内容**：bundled-skills/english-exam-authoring/SKILL.md
- **缺失兜底**：scripts/qtypes.py + make_answer_key.py

### `english-learning-card-generator` (priority 6)

- **职责**：英语课文学习卡片（原文/词汇/翻译/填空）
- **触发**：学习卡片, 课文卡片, 词汇填空, 预习卡片, 做个背诵卡
- **输入**：英语课文文本
- **输出**：图文卡片图片, 关键词汇, 中文翻译, 词汇填空练习
- **学科**：英语
- **具体内容**：bundled-skills/english-learning-card-generator/SKILL.md
- **缺失兜底**：scripts/make_answer_html.py 卡片版式

### `study-planner` (priority 7)

- **职责**：学习计划的渐进式三层展开
- **触发**：学习计划, 周计划怎么排, 复习安排, 备考规划, 排个计划, 怎么安排复习
- **输入**：目标, 截止日, 每日可用时长
- **输出**：粗略大纲 → 周任务清单 → 每日卡片（按需逐层展开）
- **学科**：all
- **具体内容**：bundled-skills/study-planner/SKILL.md
- **缺失兜底**：skill_contracts.study_plan()：三层计划（学期/周/日）

### `pdf` (priority 9)

- **职责**：纯 PDF 操作（合并/拆分/加密/转图/表单）
- **触发**：合并PDF, 拆分PDF, PDF加密, PDF转图片, 表单填写
- **输入**：PDF 文件
- **输出**：处理后 PDF 或图片
- **学科**：all
- **具体内容**：external:第三方 PDF 解析工具，请自行安装；本技能按路由表禁止它接手手写作业
- **缺失兜底**：scripts/ingest_source.py（坐标重排，符号不错位）
- **外部依赖说明**：第三方 PDF 解析工具，请自行安装；本技能按路由表禁止它接手手写作业

### `pdfkit-py` (priority 9)

- **职责**：PDF 工具箱（含 tesseract OCR 降级）
- **触发**：PDF提取, PDF编辑, OCR降级, 扫描件提取
- **输入**：PDF 文件
- **输出**：文本/图片/新 PDF
- **学科**：all
- **具体内容**：external:第三方 PDF 工具包，请自行安装
- **缺失兜底**：scripts/ingest_source.py
- **外部依赖说明**：第三方 PDF 工具包，请自行安装

### `markitdown` (priority 9)

- **职责**：文档转 Markdown（通用格式转换）
- **触发**：转markdown, 文档转换, docx转md
- **输入**：各类文档
- **输出**：Markdown
- **学科**：all
- **具体内容**：external:第三方文档转换工具，请自行安装
- **缺失兜底**：scripts/ingest_source.py
- **外部依赖说明**：第三方文档转换工具，请自行安装

### `wj-pdf2md` (priority 9)

- **职责**：PDF 转 Markdown（三级路由）
- **触发**：PDF转md, 扫描件转md, 版面分析
- **输入**：PDF
- **输出**：document.md + 图片资产 + 转换报告
- **学科**：all
- **具体内容**：external:第三方 PDF→MD 工具；矢量 PDF 优先走本技能 ingest_source.py
- **缺失兜底**：scripts/ingest_source.py
- **外部依赖说明**：第三方 PDF→MD 工具；矢量 PDF 优先走本技能 ingest_source.py

### `universal-doc-reader` (priority 9)

- **职责**：万能文档解析（MinerU 引擎）
- **触发**：解析文档, 文档转md, 本地文档库
- **输入**：PDF/图片/Office/EPUB
- **输出**：可定位 Markdown
- **学科**：all
- **具体内容**：external:第三方通用文档读取器，请自行安装
- **缺失兜底**：scripts/ingest_source.py
- **外部依赖说明**：第三方通用文档读取器，请自行安装

### `xc-doc-parser-workbuddy` (priority 9)

- **职责**：星辰文档解析（云端）
- **触发**：文档解析, 图片转文字, OCR
- **输入**：PDF/图片
- **输出**：Markdown/JSON
- **学科**：all
- **具体内容**：external:第三方解析技能；其自称的高优先级在本技能管辖内不成立
- **缺失兜底**：scripts/ingest_source.py；手写材料必须走 quark_ocr.py
- **外部依赖说明**：第三方解析技能；其自称的高优先级在本技能管辖内不成立

### `cn-math-taxonomy` (priority 8)

- **职责**：课标知识点图谱 + 先修依赖图 + 补充题库（**参考层，非分析主力**）
- **触发**：根因回溯, 先修关系, 这道题该补哪个先修, 课标条目, 补充题源, 知识点先后
- **输入**：cn 知识点 id, 学生 knowledge_point
- **输出**：先修链(含原因说明), 薄弱根因候选, 课标条目, 补充题目
- **学科**：数学
- **具体内容**：external:公开的初中数学题型分类参考层（GitHub 可获取），仅作参考不作主力
- **缺失兜底**：references/three-subject-error-categories.md（本技能自有分类）
- **外部依赖说明**：公开的初中数学题型分类参考层（GitHub 可获取），仅作参考不作主力

## 许可说明

`bundled-skills/` 内的技能卡是**接口契约与调用示例**，用于让下载者在没有这些技能时
仍能理解输入输出并使用本地兜底。各技能的版权归各自作者；如你是作者且不希望被收录，
提 Issue 即可移除。本包不分发任何第三方技能的可执行代码或依赖环境。
