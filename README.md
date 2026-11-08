# duoduo-learning-system · K12 四库联动学习系统

> 一套给 AI 助手用的「学习系统技能包」：把**知识点库 / 错题库 / 题库 / 掌握度画像**用同一个 `knowledge_point_id` 串起来，跑通「录入 → 归因 → 出题 → 作答 → 拍照批改 → 回写 → 复习」的完整闭环。
>
> **本仓库只含方法论、工具脚本与模板资源，不含任何学生数据。**

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
![Zero student data](https://img.shields.io/badge/student%20data-none-brightgreen)
![Python](https://img.shields.io/badge/Python-3.10%2B-blue)

---

## 1. 它解决什么问题

普通「错题本」只是把题目存起来。这套系统要回答的是更难的几个问题：

- 这道错题**属于哪个知识点**？同类错误是不是反复出现？
- 从这个知识点出发，能不能**自动改编出变式题**、生成讲义和作答纸？
- 孩子手写作答后，**拍照批改的结果怎么回到库里**，并更新掌握度画像？
- 今晚 105 分钟，按什么顺序排任务才不浪费时间？

技能包把这些决策固化成：**一套数据模型 + 一套分类体系 + 一条讲义/作答纸流水线 + 20 多个质量门禁脚本**，让 AI 助手按同一套规则干活，而不是每次临场发挥。

---

## 2. 功能清单

| # | 能力 | 说明 | 主要入口 |
|:--|:--|:--|:--|
| 1 | **四库联动** | 知识点库 / 错题库 / 题库 / 掌握度画像，`knowledge_point_id` 为唯一贯穿键 | `references/four-library-design.md`、`scripts/db_gate.py` |
| 2 | **错题分类体系** | 五级分类；数学 13 值 `error_type` 枚举、语文 A–G 七类错因、三科分门（M/E/Y） | `SKILL.md` §2/§4、`references/three-subject-error-categories.md` |
| 3 | **资料摄取层** | 从 PDF / 图片 / 扫描件 / docx 提取公式与流程框图，LaTeX ↔ MathML / OMML 互转，坐标重排 | `scripts/ingest_source.py`、`latex_math.py`、`mathml_render.py`、`omml_math.py` |
| 4 | **手写 OCR** | 印刷体 / 手写 / 公式分块识别，带 QPS 控速与「公式降级」检测 | `scripts/quark_ocr.py`、`ocr_bridge.py` |
| 5 | **讲义与任务单** | DSL 驱动生成讲义，含八件套骨架、程序框图、视频候选、两段式判分 | `scripts/lecture_dsl.py`、`dsl_source.py`、`references/lecture-pipeline.md` |
| 6 | **作答纸 / 答案册分离** | 全部题目进纸、纸面零答案；答案册单独一张；可导出 Word / HTML，支持打印 | `scripts/make_answer_docx.py`、`make_answer_html.py`、`make_answer_key.py` |
| 7 | **批改闭环** | 打印 → 手写 → 拍照 → 三档判分 → 回写四库；含《批改记录》对账栏 | `scripts/grade_submission.py`、`references/grading-feedback-loop.md` |
| 8 | **出题与复习** | 错因归因 → 分层变式 → 组卷细目表 → 到期复习队列 | `SKILL.md` §5/§6、`scripts/duoduo_query.py due` |
| 9 | **排程方法论** | 晚间 105 分钟排程、学校/家庭任务优先级、周计划与时间账 | `SKILL.md` §7 |
| 10 | **技能编排** | 总调度注册表：命中触发词决定「调谁、给什么、谁让路」 | `references/skills-registry.yaml`、`skill-orchestration.md` |
| 11 | **质量门禁** | 20+ 校验脚本：答案册一致性、公式渲染、脏标记、题数对齐、书写规范等 | `scripts/verify_*.py`、`self_audit.py` |
| 12 | **家长讲题卡** | 先问再讲、3 个启发问句、答案放最后，避免直接给可抄的答案 | `SKILL.md` §6.6.1 |
| 13 | **学习科学背书** | ICAP 框架、提取练习、间隔重复、认知负荷等方法论索引 | `references/icap-framework.md`、`learning-science.md`、`learning-methods-index.md` |
| 14 | **B 站学习视频推荐（§8 v2.0）** | 四轮检索（指定 UP / 通用 / 方法专项 / 逐题特征）→ `view` 接口逐条核实（含付费·下架·分区·互动）→ 七维可解释评分 → 质量分档 → 逐题审计表；数学优先郭嘉，难题自动找针对性课程 | `SKILL.md` §8、`scripts/bili_video_engine.py`、`references/video-guardrails.json`、`references/video-recommendation.md` |
| 15 | **配套技能契约 + 具体内容** | 28 项技能的输入 / 输出 / 优先级 / 缺失兜底；20 个学习类技能附具体内容副本；7 个可直接运行的本地兜底实现 | `references/skill-contracts.*`、`bundled-skills/`、`scripts/skill_contracts.py` |

### 2.1 视频推荐：不编 BV 号，只推「效果最好且对症」的那条

这是本包最常被误做的一环。**主规范是 `SKILL.md` §8 v2.0**，护栏唯一来源是
`references/video-guardrails.json`（汇总 阶段27 ~ 阶段31 全部要求与踩坑），
完整历史台账在 `references/video-recommendation.md`（阶段19 ~ 阶段31，12 条红线）。

| 入口 | 用途 |
|:--|:--|
| `scripts/bili_video_engine.py --topics topics.json` | **主引擎**：整套讲义 / 逐题批量挂接，输出 `_all_recommendations.json` + 逐题 JSON + Markdown 审计表；全局 BV 去重、按身份键绑定 |
| `scripts/video_recommender.py --kp ... [--hard]` | **轻量即时入口**：临时查一个知识点或一道难题，直接给 2~3 条候选与 `VID` 行 |

两者共用同一份护栏（DROP / ★保留 / 指定 UP / 年级拒绝词 / 学科语境词 / 付费与娱乐分区淘汰），
因此结论一致；评分口径上批量场景以 §8.4 的七维可解释评分为准。

| 要求 | 实现 |
|:--|:--|
| 检索 | 搜索 API + 搜索页双通道；**不用 WebSearch 结果当视频清单**（搜索结果只返回专栏文章） |
| 验证 | 每条候选走 `view` 接口核实标题 / UP / 真实时长 / 播放 / 简介 / 互动 / 分 P / 发布时间；**付费或大会员、已下架、娱乐分区、非授课标题、缺学科语境词一律淘汰**；未核实只给搜索词，**绝不编造 BV 号** |
| 对症 | 标题未点名该考点直接 `reject`，播放量再高、UP 再有名也不补偿 |
| 效果 | 批量引擎按 §8.4 七维可解释评分（对位 40 / 热度 18 / **互动质量 12** / 时长 10 / UP 权威 12 / 新鲜度 4 / 轮次 4），分档 优质≥68 / 可用≥56 / 勉强≥42，<42 判 `gap` 不推荐；轻量入口用 `100 × (对口度+时长+口碑)/85 × 质量门`，讲原理加分、讲口诀砍半，效果分最高者标「首选」 |
| 数学优先 | 默认优先 `郭嘉老师数学思维`；该 UP 确无对应课时明写「暂无对应课」，**不拿别家顶替** |
| 难题 / 压轴 | `--hard` 追加「真题出处 / 核心方法 / 压轴专讲」定向检索；没有通用课时就找针对该题的课程，不用全章串讲顶替 |
| 覆盖 | 逐考点审计，覆盖不足出审计表而不是悄悄略过；换题必须重配视频 |
| 好视频留存 | ★保留 / 实测有效 / 命门课置顶有权重加成，淘汰留痕 |

```bash
# 整套讲义 / 逐题批量挂接（主引擎）
python scripts/bili_video_engine.py --topics topics.json --out OUT_DIR --cache CACHE_DIR
# 临时查一个知识点 / 一道难题（轻量入口）
python scripts/video_recommender.py --kp "绝对值 化简" --subject 数学 --grade 七年级 --limit 2
python scripts/video_recommender.py --kp "折线数轴 变速动点 压轴" --subject 数学 --hard --limit 2
python scripts/video_recommender.py --selftest # 离线，不联网
```

### 2.2 配套技能：从「只给名字」到「给契约 + 内容 + 兜底」

`skills-registry.yaml` 只回答「调谁」；本包额外提供：

- `references/skill-contracts.json` / `.md`：28 项技能的**输入、输出、优先级、缺失兜底、具体内容位置**；
- `bundled-skills/<name>/SKILL.md`：20 个学习类技能的具体内容副本（已脱敏，仅作接口契约与调用示例）；
- `scripts/skill_contracts.py`：`ContractRegistry.resolve()` 解析该调谁，另有 7 个具体兜底实现
  （13 值错因枚举、语文 A–G 映射、A/B/C 分层变式、双向细目表、方法索引、概念口径、家长讲题卡、三层学习计划）。

6 个第三方通用文档解析工具只提供契约，不分发他人技能全文。缺外部技能时兜底返回
**结构化可用结果**，并在交付物里注明「该能力由兜底实现提供」，不假装调过外部技能。

```bash
python scripts/skill_contracts.py --text "出一份绝对值专项练习，要分层"
python scripts/skill_contracts.py --list
python scripts/skill_contracts.py --selftest
```

---

## 3. 目录结构

```
duoduo-learning-system/
├── README.md ← 本文件
├── SKILL.md ← 技能主文档：路由表、SOP、铁律、门禁（约 100 KB）
├── LICENSE ← MIT
├── .gitignore ← 屏蔽所有数据文件
├── data/
│ └── README.md ← 只有说明，没有任何数据库
├── assets/ ← 打印 CSS、判分 JS、程序框图 SVG 示例
│ ├── print.css
│ ├── print.js.html
│ └── figs/q1..q5.svg
├── references/ ← 18 份方法论 / 规范 / Schema 文档
│ ├── four-library-design.md 四库表结构与字段
│ ├── error_record.schema.json 错题记录 JSON Schema
│ ├── lecture-pipeline.md 讲义与作答纸全流程（约 110 KB）
│ ├── answer-sheet.md 作答纸 / 答案册 / 批改入库规范
│ ├── grading-feedback-loop.md 批改反馈闭环
│ ├── db-audit-playbook.md 数据体检手册
│ ├── schema-change-procedure.md 改表流程（必备份）
│ ├── verification.md 校验与踩坑清单
│ ├── skills-registry.yaml 技能调度注册表（调谁）
│ ├── skill-contracts.json 28 项技能契约（给什么/拿回什么/缺了怎么办）
│ ├── skill-contracts.md 同上，人类可读版
│ ├── video-guardrails.json B 站视频唯一护栏（硬规则/偏好UP/★保留/DROP/阈值）
│ ├── video-recommendation.md B 站视频检索与验证规范 + 历史踩坑台账
│ └── ...
├── bundled-skills/ ← 20 个配套技能的具体内容副本（已脱敏）
│ └── <name>/SKILL.md
└── scripts/ ← 50+ 个 Python 工具（数据层 / 摄取 / 生成 / 校验 / OCR）
    ├── setup_paths.py 首次使用：路径占位符一键配置
    ├── duoduo_query.py 四库查询 CLI（9 个子命令）
    ├── ingest_source.py 资料摄取主程序
    ├── db_gate.py 数据库门禁
    ├── bili_video_engine.py B 站视频主引擎（四轮检索 + 批量挂接 + 审计表）
    ├── video_recommender.py B 站视频轻量入口（单知识点 / 单难题）
    ├── skill_contracts.py 配套技能契约解析 + 7 个本地兜底
    └── ...
```

---

## 4. 快速开始

### 4.1 获取

```bash
git clone https://github.com/<你的账号>/duoduo-learning-system.git
cd duoduo-learning-system
```

或直接下载仓库 ZIP，把解压后的 `duoduo-learning-system/` 整个目录放进你的 AI 助手技能目录
（WorkBuddy 用户：`~/.workbuddy/skills/`）。

也可以在 WorkBuddy 的「技能市场」里搜索 **K12 错题库学习系统**（免费）一键安装，
功能与仓库版一致；想改脚本或看完整台账，仍建议用仓库版。

### 4.2 环境

| 项 | 要求 |
|:--|:--|
| Python | 3.10+（开发时用的是 3.13） |
| 必需 | 标准库为主；`python-docx`（导出 Word）、`lxml`（OOXML 处理）按需安装 |
| 可选 | `Pillow`（图片裁剪）、夸克扫描王凭证（手写 OCR，走外部凭证文件） |
| 数据库 | SQLite 3，自带库文件，**仓库不提供** |

```bash
python -m pip install python-docx lxml
```

### 4.3 配置路径（重要）

文档与脚本里的本机路径已统一替换为占位符，**首次使用先跑一次**：

```bash
python scripts/setup_paths.py --skill-dir "/abs/path/to/duoduo-learning-system" \
                              --workspace "/abs/path/to/你的学习资料根目录"
python scripts/setup_paths.py --skill-dir "..." --workspace "..." --apply
```

第一条是预览，第二条才真正写回。也可以直接全局搜索 `<SKILL_DIR>` / `<WORKSPACE>` 手动替换。

占位符含义：

| 占位符 | 含义 |
|:--|:--|
| `<SKILL_DIR>` | 本技能包的绝对路径 |
| `<WORKSPACE>` | 你的学习资料根目录（讲义、作答纸、规划等子目录都挂在它下面） |
| `<DATA_DIR>` | 存放导入源材料的目录 |
| `<RUNTIME_DIR>` | 自建运行环境 / 容器内脚本目录 |
| `<NAS_DB_DIR>` | 可选：主库所在的共享目录 |
| `<HOME>` | 用户主目录 |
| `<LEGACY_DIR>` / `<LEGACY_SCRIPT>` | 历史目录 / 脚本占位，可直接删掉相关句子 |

### 4.4 建库

按 `references/four-library-design.md` 里的建表 SQL 和 `references/error_record.schema.json`
建自己的 SQLite 库，放到 `data/error_db.sqlite`。字段口径、改表流程见
`references/schema-change-procedure.md`。

> `*.sqlite` / `*.csv` / `*.docx` 等已被 `.gitignore` 排除，**不会被误提交**。

### 4.5 试跑

```bash
python scripts/duoduo_query.py stats # 总量 / 学科分布 / 严重度 / 消解状态
python scripts/duoduo_query.py gates # 三科分门覆盖率
python scripts/duoduo_query.py weak 10 # 最薄弱知识点 TOP10
python scripts/duoduo_query.py due # 到期复习队列
python scripts/duoduo_query.py search 冠词 # 全文检索错题
python scripts/fix_db.py # 数据体检（dry-run，不改库）
python scripts/verify_all.py # 交付前全量门禁
python scripts/video_recommender.py --selftest # 视频引擎离线自测
python scripts/skill_contracts.py --selftest # 技能契约离线自测
```

在 WorkBuddy 里，直接说「查一下最近的错题」「出一份绝对值专项练习」「做今天的讲义和作答纸」，
技能会按 `SKILL.md` 的路由表自动编排。

---

## 5. 数据流（一眼看懂）

```
试卷 / 作业 / 照片
   │ ingest_source.py + quark_ocr.py
   ▼
结构化题目与公式 ──► 错题库(errors) ──► 错因归类 ──► 知识点库(knowledge_base)
                                                        │
                              ┌─────────────────────────┘
                              ▼
                     题库(questions) ──► 讲义 / 作答纸 / 答案册（HTML + DOCX）
                                                │
                                     手写作答 → 拍照 → 三档判分
                                                │
                                                ▼
                         回写 errors + 掌握度画像(mastery) → 到期复习队列
```

四库之间始终靠 `knowledge_point_id` 关联；任何一步都要过门禁脚本，
「格式全绿 ≠ 内容干净」是这套系统反复强调的教训。

---

## 6. 隐私与数据说明（请务必读）

**本仓库不含任何学生数据。** 公开发布前做了以下处理：

| 处理 | 具体内容 |
|:--|:--|
| ❌ 完全不分发 | SQLite 错题库、CSV 导出（错题 / 题库 / 掌握度 / 任务卡）、学习档案摘要、讲义成品、作答纸与答案册、试卷照片 |
| ❌ 剪裁章节 | 真实学情基线、成绩与逐题批改明细、教师反馈原文、数据治理运行记录、家长私人对话与运维事故日志 |
| ❌ 剪裁脚本 | 7 个针对某几天具体产物的一次性讲义/教案/答案生成脚本（内嵌真实教学内容，非通用工具） |
| 🔄 泛化 | 真实姓名、学号、联系方式、本地绝对路径、内网 IP 与共享路径、私有设备与服务名、历史统计数字 |
| 🔄 占位 | 所有本机路径改为 `<WORKSPACE>` / `<SKILL_DIR>` 等占位符，见 §4.3 |
| ❌ **零 key / 零 ID** | 不含任何 API key、ClientSecret、token、PAT、Cookie、B 站登录态、GitHub 账号名或仓库 owner、自动化任务 ID、设备 SN、邮箱与手机号；上游仓库 owner 与凭证组标识一律占位化 |
| ✅ 保留 | 方法论、分类体系、SOP、门禁规则、工具脚本、教学示例图 |
| ✅ 新增（同样复检） | 视频推荐引擎、视频规范台账、28 项技能契约、20 份配套技能卡副本；全部为通用规则与工具，**不含任何真实学生的观看记录、成绩或视频清单** |

**关于凭证与 ID**：脚本和文档里出现的 `client_id`、`client_secret`、`SCAN_WEBSERVICE_KEY`、
`buvid3` 等**都是字段名或匿名默认值，不是任何人的凭证值**。仓库内没有密钥、令牌、账号、
任务 ID 或设备编号；需要凭证的功能一律读取使用者自己机器上的外部凭证文件，未配置即自动降级。
发布前会跑一次专项复检（PAT / GitHub token 格式、UUID、邮箱、手机号、设备 SN、平台账号名、
长随机串、凭证组标识），**任一项命中即中止发布**。

**关于学生称谓**：本包统一使用「学生」这一**通用称谓**，路由触发词与话术示例里
**不含任何真实姓名、昵称、小名或可识别到具体学生的代号**。文档中的讲义、作答纸、
诊断记录均以 `学生_DayN_…_YYYYMMDD` 这类占位模板表述，日期与版本号同样已泛化。

如需个性化话术，可只修改路由触发词与你自己的输出模板；**不要对全仓库做「学生」全局替换**，
那会误伤分类体系、语文教学等正常表述。本包不提供、也不需要任何真实学生称呼。

**使用建议**：把真实数据放在 `data/` 且不要改动 `.gitignore`；如需回传改动，
提交前跑一遍 `git status --ignored` 确认没有数据文件被跟踪。

---

## 7. 已知限制

- 脚本里的路径常量是占位符，**不配置就用不了**（见 §4.3）。
- 手写 OCR 通道需要**你自己**申请并配置的凭证（`client_id` / `client_secret`），默认读取位置见
  `scripts/quark_ocr.py`，可用环境变量覆盖；**仓库内不含任何 key、token、账号或 ID**。
  未配置时该通道自动降级为不可用，不影响其他功能。
- `references/` 里的「踩坑记录」是方法论经验，不是任何人的运行日志；其中提到的历史版本、门禁编号仅作规则标识。
- 20 个学习类配套技能已附具体内容副本；另 6 个第三方文档解析工具只给契约，需自行安装。
  **任何外部技能缺失时都不会静默跳过**，而是走 `scripts/skill_contracts.py` 的本地兜底并显式注明。
- 视频推荐引擎需要能访问 B 站公开接口；网络不通时用 `--offline` / `--selftest` 跑离线样例，
  **不会输出未经核实的 BV 号**。
- 本技能提供的是学习方法与工程流程，**不承诺任何学习成绩**，也不提供医疗/心理诊断建议。

---

## 8. 许可

[MIT](LICENSE)。可自由使用、修改、商用，只需保留版权声明。
文档中引用的教材、课程与图书名称归各自权利人所有。

---

## 9. 贡献

欢迎提 Issue / PR：修正文档漂移、补充新的校验门禁、适配其他学段或教材版本。
**请勿在 Issue 或 PR 中粘贴任何真实学生数据、成绩或照片。**
