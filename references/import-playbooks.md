# 导入实战手册（P2/P3/阅读/完形/多题型/答案提取/外部题库）

> ## ⚠️ 环境说明（先读这段）
>
> 本文引用的 `workbook_1000ti_query.py`、`import_question_bank.py`、`import_vocab_and_grammar.py`、
> `import_basic_grammar_20260826.py`、`error_db_full_audit.py`、`error_db_llm_audit.py`、
> `error_db_weekly_check.py`、`docx_page_numbers.py`、`setup.py`
> 都是**原私有工作环境的历史脚本，不随本公开包分发**（本文是当时的导入实战记录）。
>
> 本包内可用的导入入口：`scripts/extract_bank.py`（题库抽取）、
> `scripts/import_lecture.py`（讲义入库）、`scripts/grade_submission.py`（批改入库）。
> **照本文的 `<RUNTIME_DIR>/...` 路径执行必然失败** —— 需要哪个能力，先确认本包 `scripts/` 里有没有对等脚本。
>
> 文中 `<RUNTIME_DIR>` / `<SCRIPTS_DIR>` / `<WORKSPACE>` 是**占位符**，指「你自己的运行目录 / 脚本目录 / 工作区」。

> 自 SKILL.md 拆分（阶段9 技能审计）。SKILL.md 保留架构与铁律，实战细节看本文件。

## "自己改卷子"卷答案恢复（阶段2 实战验证）

用户要昨天"自己改卷子"卷的答案对照修改。**🔴 docx 题干是 OMML 公式，`<w:t>` 文本提取为空**——不要尝试从 docx 解析公式，正确路径：

1. **提取卷内错题 ID**：卷面每行格式 `第N题（错题#ID）`，正则 `错题#(\d+)` 拿全部 ID（两份卷=20题）
2. **查 errors 表**：`SELECT id, date, knowledge_point, error_desc, correct_answer FROM errors WHERE id=?`
   - 🔴 errors 表**没有 question 列**——题目+当时写的混在 `error_desc` 里（如 `计算-(-3²)×2...：-(-3²)=-(-9)=+9...学生写成-18`）；先 `PRAGMA table_info(errors)` 再写查询
   - error_desc 里已含"错在哪"（老师批注式描述），可直接用于对照说明
3. **程序化重算验证**（数学答案铁律，不可手算）：`from fractions import Fraction` 逐题 eval 比对库答案。注意 -1²⁰²⁵ = -(1^2025) = -1 这类优先级、`-2³/3×27/8` 的除法顺序；20/20 全过才算交付
4. **输出对照清单**：每题为"题目 + 正确过程（分步）+ 学生错在哪"——用户用于对照修改，正确过程必须可复现的逐步展开（如 `-(-9)×2-9+(-27)÷9 = 18-9-3 = 6`）

## md 独立参考文档导入（思维导图/语法参考，阶段4 实战验证）

用户发**独立成篇的参考文档**（语法思维导图/知识整理 md，非单元教材内容、非练习题卷）并说"存入数据库"时，与下面"md 单词表/旧版教材导入"不同——那种挂 unit 或挂 101 综合英语；这种**自成一体的系统性参考**应建**专用知识点**承载，不并入任何单元，防止出题/默写单按单元提取时混料。触发器：用户发 md（非表格版教材/词典表）且内容像"整本书/整章知识地图"。

**脚本模板**：`<SCRIPTS_DIR>/import_basic_grammar_20260826.py`（`import_basic_grammar_20260826` 可复制改 SRC/DB/SOURCE 复用）

**步骤**（通用独立参考文档导入）：
1. **建独立知识点**（勿复用 101 综合英语——那是旧版语法汇总，语义不同）：
   ```sql
   INSERT INTO knowledge_base (subject,edition,grade,unit,point_name,point_type,detail,parent_id,source,created_at)
   VALUES ('英语','综合','综合','综合英语','基础语法','grammar','《基础语法(思维导图)》综合语法参考...',NULL,'基础语法思维导图_20260826',now);
   ```
   - point_type=grammar，unit=综合英语（跨单元尺度，grade 用「综合」而非「七上」）
   - 🔴 source 带日期可追溯：`基础语法思维导图_20260826`
2. **按顶层标题切分节**：正则 `^##\s+(.+)$` 切出每个 `## 一、名词 (Noun)` 段；`# `（单井号）是文档总标题不入节
3. **逐节存 knowledge_detail**：一个知识点下每节一条，字段映射——
   - `sub_type` = 节标题（如 `名词 (Noun)`），精确到主题便于检索
   - `category` = 重点语法（语法参考统一归此；**别为它新造 category**，会破坏现有 category 提取逻辑）
   - `seq` = 中文序号→阿拉伯数字（一→1…十二→12，用 num_map dict，勿依赖列表 index）
   - `content` = 节正文（`re.sub(r"\n{3,}", "\n\n", ...)` 压缩多余空行）
4. **幂等**：先 `SELECT id FROM knowledge_base WHERE point_name=? AND source=?` 查重（存在则跳过创建只补 detail）；写 detail 前 `DELETE FROM knowledge_detail WHERE knowledge_point_id=? AND source=?` 去旧
5. **归档源文件**：`cp` 到 `<DATA_DIR>/基础语法思维导图_20260826.md`（cache/documents 会过期，必须留档）
6. **备份**：入库前 `sqlite3.connect(src).backup(sqlite3.connect(dst))` 到 `<DATA_DIR>/db_backups/`

**🔴 验证坑（本次踩过）**：`python3 -c "..."` 内联脚本里写 `replace(content,chr(10),\` \`)` 这种**含反引号**的 SQL 字符串，bash 会把反引号当命令替换执行 → `no such column` 报错。**验证/查询语句一律写进临时 .py 文件再跑**（或避开反引号字符），不要内联在 `-c` 里。

**内容校验**：每节 `LENGTH(content)` 对比源 md 对应段是否完整；`PRAGMA integrity_check`=ok、孤儿引用（`knowledge_detail` LEFT JOIN `knowledge_base` WHERE kb.id IS NULL）=0 才算收尾。

## md 单词表/旧版教材导入（阶段2 实战验证）

用户发 **markdown 表格版单词表/知识点整合**（新人教 2024 版）时走本模式，脚本 `<SCRIPTS_DIR>/import_vocab_and_grammar.py`（可复用）：

**1. 单词表表格解析**：`|序号|词汇|音标|汉意|册次|单元|页码|` 格式
- 行首 `|` 且 `int(序号)` 可解析才算有效行；`**` 粗体标记去除
- 音标列可能为空（短语/专有名词），汉意列为空则跳过（英译汉默写表变体）

**2. 单元映射 UNIT_MAP（新教材）**：单词表只有数字/代号，KB 单元是带全名——
```
S1/S2/S3 → Starter Units 1-3
1 → Unit 1 You and Me, 2 → Unit 2 We're Family, 3 → Unit 3 My School
4 → Unit 4 My Favourite Subject, 5 → Unit 5 Fun Clubs
6 → Unit 6 A Day in the Life, 7 → Unit 7 Happy Birthday
```

**3. 🔴 旧版教材隔离策略**：旧人教语法汇总（Starter unit 1-3 + Unit 1-9，与 2024 新版单元体系完全不同）**一律挂 knowledge_point_id=101（综合英语）**，unit 保留文档原名——绝不并入新版单元，防止出题/默写单按单元提取时新旧混料。

**4. 分类映射**：一、重点单词/二、重点短语→词汇与短语；三、重点句型→重点句式；四、重点语法→重点语法（旧版语法是连续说明文字，**整块存** content 截断 2000 字符）。

**5. source 命名**：`vocab_table_20260806`（单词表）、`zhishidian_zhenghe_20260806`（知识点整合）、`renjiao_old_grammar_20260806`（旧版语法）——按日期可追溯。

**6. 🔴 WAL 快照坑**：写操作后立即查 `sqlite_master` 表清单可能**只返回部分表**（读到写中间态快照）——重查即恢复，不是数据丢失；查询用参数化占位符避免单元名撇号（`We're Family`）炸 SQL。

**7. 入库后验证**：`GROUP BY unit, category` 看覆盖 + `PRAGMA integrity_check` + 孤儿引用计数（LEFT JOIN knowledge_base WHERE kb.id IS NULL）=0。

## P2 详解入库方法论（批量，按单元）

从已提取JSON（`<DATA_DIR>/七年级上期英语核心知识/核心知识归纳_按单元切分.json`，10单元×行列表）逐行解析：
- 分类切换：`detect_category()` 识别"知识点一~五"（词汇与短语/重点句式/重点语法/重点知识/写作背默）
- 子类型：`【重点单词】`【重点短语】等正则切分
- 单元归一化：JSON名（"Starter Unit1"/"Unit1"）→ KB单元名（"Starter Units 1-3"/"Unit 1 You and Me"）unit_map
- 挂接 knowledge_point_id：取该单元KB第一条知识点（英语27条kb）
- 结果：10单元×5分类全覆盖，后续背诵单/默写单 `SELECT * FROM knowledge_detail WHERE unit='X' AND category='词汇与短语'` 直接提取

## P3 docx 批量导入题库方法论

脚本：`<SCRIPTS_DIR>/import_question_bank.py`（可复用，改src_dirs/KP_RULES即可）

**四步解析**：
1. `extract_docx()`：zipfile读document.xml→`</w:p>`切段→`<w:t>`提取文本（转义&amp;等）
2. `parse_questions()`：题号正则 `^(\d+)[.、．]` 开新题；`^([A-E])[.、．]` 行并入选项；短行续题干；过滤"一、二、"标题/【原理回顾】/姓名/注意行
3. `parse_answers()`：答案md配对（`_答案.md`同名文件）→ `^(\d+)[.、．]` 题号 → 答案（`B. xxx`取B，填空取首词）+解析+`变式自 #ID` 溯源到errors.source_error_id
4. 挂知识点：**KP_RULES正则表**（题目文本特征→KB point_name，如"乘方|幂|负号"→乘方、"冠词|a\b|an\b|the\b"→冠词）；文件名兜底；MD5去重（同题多源留1条）

**结果校验**：按知识点挂接率、去重率、答案配对率三项核对，不达标回到解析规则调整。

**补挂至100%（+48题）**：剩余未挂多为三类——①公式损坏（docx里数学公式丢字符，如"若 3"）②文件级可推断 ③翻译默写类。两层补挂：
- `CONTENT_RULES` 内容正则：`若 |x-a|+|y+b|=0`→正负数与数轴、`鹦鹉|吉他|售货员`→综合词汇、`favourite|学科`→综合语法
- `FILE_KP` 文件级映射：`学生英语练习题_20260720.docx`→冠词、`英语错题练习_0001_20260728.docx`→综合词汇（单词翻译）、`数学错题综合提高卷_20260730.docx`→乘方…（文件名校验+首题内容特征推断）
- 最终 **584/584 (100%)** 挂knowledge_point_id（kp_mapping_log用 error_id 负值标记题目映射，避免与错题映射混淆）

**坑**：docx题干换行续段、多题号体系（一、二、三标题内题号重置）导致部分docx识别不全（如有理数练习题_0003只入1/12题）——需按文件实际格式微调正则；答案md缺失时answer留空不阻塞入库。

## 阅读理解整篇导入

用户发的 `7年级阅读理解（上）.docx` **文件名误导——实为英语阅读300题专练**（初中7-9年级，含260小题，但标题称"含答案"实际正文无答案区）。处理：识别为英语阅读题，导入题库。后用户补发`（上）-答案`/`（下）`题目+答案四份文档，全部答案回填。

**步骤**：
1. 新建知识点：`INSERT OR IGNORE INTO knowledge_base (subject,edition,grade,unit,point_name,point_type,detail,source) VALUES ('英语','综合','七上','综合英语','阅读理解','reading','英语阅读理解题型（文章理解/细节/主旨/推断）','docx_import')` → id=102
2. 每篇阅读作为**一题**入库（question=文章+全部小题全文，q_type='阅读理解'，answer留空）——出题按整篇出，不拆小题
3. 源docx存档到 `<DATA_DIR>/`（cache/documents会过期）

**🔴 篇边界检测启发式（本次踩坑）**：docx里"篇号"和"小题号"都是行首数字格式（`1.`、`2.`），直接按递增数字切分会失败：
- 纯"递增"判断：篇号不连续时中断（本篇缺16，遇到17不递增就漏掉后面全部）
- 正确启发式：**数字递增 且 距上一个数字行 gap≥3段**（篇号之间隔着整篇文章长文本，小题"1. 2. 3. 4. 5."密集出现gap=1）→ 59篇识别成功
```python
for i, t in enumerate(texts):
    m = re.match(r"^(\d{1,3})[.、．]\s*(.*)$", t)
    if not m: continue
    num, gap = int(m.group(1)), i - last_digit_i
    if num > current and gap >= 3: # 递增 + 间隔≥3段 = 新篇
        candidates.append((i, num)); current = num
    last_digit_i = i
```
- 切分后每篇内容=起始到下一篇前的全部段落（title=去编号首行，body=其余）
- 验证：59篇覆盖1-60（缺16=文档本身无），篇2有2643字符、含判断题小题"1.-5."未被误切

**出题适配**：阅读理解题挂"阅读理解"知识点，出题引擎 `generate_practice_sheet.py 英语 N` 会按薄弱点选到它们（整篇输出）。

**答案回填（118/118 100%，阶段1 实战验证）**：用户补发`7年级阅读理解（上）-答案.docx`+`（下）`题目/答案后，从答案docx逐篇提取【答案】+【解析】回填questions.answer/solution。两个坑：
- **🔴 答案文档篇号与题目错位——绝不能按篇号匹配**（下册答案篇2=药瓶说明书≠题目篇2=Emily Jones；答案篇22海豚=题目篇20）。正确做法：**文章内容关键词定位**——取题目文章首行核心词（"Emily"/"Dolphin"/"Tea Day"），在答案文档找含该词的段，向后扫【答案】…【解析】…到下一篇号行止（`find_answer_by_content`）
- **🔴 【答案】标记行可能缺失**（篇24答案区直接跳`（2） C`，无【答案】行且（1）答案丢失；上册4篇+下册6篇共10篇首轮漏掉）——v2提取逻辑：无标记时收集`（n） X`形式的连续答案行，**仅当后面出现【解析】才确认是答案**（防把题目当答案）；收集行去重防重复

## 答案小题级关联 question_items（用户硬性需求：答案也要形成关联存入数据库，阶段1）

用户要求"答案也要形成关联"——答案不能只作为questions表一大块文本，要**小题级结构化**：每篇阅读的每个小题（题号+题干+答案+解析）独立成记录，经 `question_id` 外键挂回篇目。这使"逐小题对答案、精确到第几小题错"成为可能（后续可做小题级错题记录→出同知识点变式）。

**表结构**：`question_items(id, question_id→questions.id, item_no, item_text, answer, solution)` + idx_qi_question 索引。

**拆分逻辑**（三个解析器，实测709条/题干99%/答案98%/解析93%）：
1. `parse_answer_items`：从 `【答案】（1）A （2）B` 正则 `（\s*(\d+)\s*）\s*([A-Za-z]|...)` 拆 {1:'A',2:'B'}
2. `parse_solution_items`：按 `（\s*(\d+)\s*）` 切分【解析】文本 → 逐小题解析
3. `extract_item_texts`：从篇目全文匹配所有 `（n）`，取该标记到下一个标记间的文本作题干
- 合并三处小题号取并集，逐条INSERT
- 练习/变式题也拆（每题作为1个item_no=1的记录），统一答案管理

## 完形填空 .doc 导入（OLE老格式提取，阶段1 实战验证）

用户发 `初中英语题型专练—完形填空（含答案）.doc`——**.doc 是 OLE 复合文档**（魔数 `d0cf11e0a1b11ae1`），python-docx 读不了；系统无 LibreOffice/antiword。**纯Python方案**：
1. `venv python3 -m pip install olefile`（系统python3无此包；`<RUNTIME_DIR>/bin/python3` 可用，但 pip 不可执行，用 `python3 -m pip`）
2. `olefile.OleFileIO(path).openstream("WordDocument").read()` → `decode("utf-16-le", errors="ignore")`
3. **二进制残留清理**：`re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', text)`（否则写出的txt被grep当binary）
4. 篇切分复用阅读理解启发式（数字递增+gap≥3段）；答案解析 `1. B　2. A　3. C` → `(\d+)\s*[.、．]\s*([A-D])`
- 结果：8篇Cloze（每篇10空+选项+【主旨大意】+答案）→ questions（q_type='完形填空'）+ 80条 question_items；新建知识点"完形填空"（id=103，point_type=reading）
- 文档中部还有"强化训练"题（在Cloze 1-8与详解区之间），本导入只取题目区（Cloze标记 i<140）避免混入详解区重复Cloze

## 多题型批量导入 v3（语法选择/短文填空/阅读专练/完形填空专题，阶段1 实战验证）

用户批量发4份题型文档（docx+doc混合）并要求**"答案管理要确保全部正确，检查一遍再存入"**——形成本方法论：解析→答案校验（数量/合法性/连续性）→修复→入库，校验不过不入库。

## 外部练习册题库导入

用户发**完整练习册电子版**（多份分卷 docx）说\"全文读取后存入数据库供生成练习题使用\"时走本模式——区别于上文 P3 的\"自制练习题 docx\"，这里是**市售教辅扫描版分卷**：

1. **归档**：每份分卷 cp 到 `<DATA_DIR>/教辅电子版/`（命名 `书名_高清版_页码范围.docx`，删无后缀重复件）
2. **建独立题库库**：`<LEGACY_DIR>/workbook_1000ti.sqlite`（独立于 error_db.sqlite，因为是题库不是错题）
   - 表 `workbook_pages`：workbook/part(分卷名)/chapter(章节索引)/raw_text(全文文本)/image_count
   - 表 `workbook_chapters`：章节名+专题数
3. **提取**：zipfile 读 `word/document.xml` → `re.findall(r'<w:t[^>]*>([^<]*)</w:t>')` 逐段提取；**⚠️ 数学公式在图片里（2611张 media）不是OMML**——`<w:t>` 只能拿到题目文字/避错指南/正确步骤/答案解析，算式主体是图片，文本版可检索但无法直接引用算式
4. **🔴 章节识别坑**：扫描版每份分卷的**文本都含全书所有章节关键词**（因为是整书扫描按页切分）——按\"关键词是否出现在全文\"判断章节会把每份都标成全部章节，无意义；正确做法是按**页码范围归属**（文件名 `1-110` 等）或仅作分卷级索引，别试图从文本切出精确章节
5. **查询助手**：`<SCRIPTS_DIR>/workbook_1000ti_query.py`（list-chapters/list-parts/search <词>/chapter <章>/stats）——search 走全文 LIKE 定位，能命中薄弱点题目+避错指南，供生成练习题时选题
6. **存量**：4份分卷、76,730字、10章节（有理数→一元二次方程）、第一章有理数正好命中学生4大薄弱点（负号乘方/绝对值/混合运算/符号陷阱）
