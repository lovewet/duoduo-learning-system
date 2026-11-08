# 源材料摄取（PDF / 图片 / docx → 结构化块）

> **什么时候读这个文件**：要读 PDF、拍照件、扫描卷、别人发来的 docx 时。
> 一句话原则：**不许把整页图丢给模型"看一眼"就往下写。**
>
> **📌 脚本命名约定（先读）**：本文出现的 `ocr.py`、`setup.py` 是**原私有工作环境的历史脚本，
> 不随本公开包分发**。本包内的摄取入口是 `scripts/ingest_source.py`（+ `scripts/quark_ocr.py`
> 手写识别、`scripts/ocr_bridge.py`、`scripts/latex_math.py` 公式转换）。
> 文中 `<RUNTIME_DIR>` / `<SCRIPTS_DIR>` 是占位符，指「你自己的运行目录 / 脚本目录」。


---

## 一、为什么要有这一层

以前的读法是整页图 → 模型直接抄。整页缩到 1000px 宽时：

| 元素 | 实际后果 |
|:--|:--|
| 小字公式的指数 | `y = 3x²` 读成 `y = 3x2`，题目直接变味 |
| 程序框图 | 整块被跳过，只抄了题干文字，然后拿"没认出是框图题"当结论 |
| 表格 | 拍平成一行字，行列关系全丢 |
| 分式 | 分子分母糊成一串，`(x−1)/2` 读成 `x−1/2` |

**根因不在模型，在输入端**：没给够分辨率，也没告诉它"这里有块图"。
所以摄取层要做的是三件事——**切块、放大、标出哪里必须细看**。

---

## 二、工具选型：能用现成的绝不自研

> 阶段22 用户：「市场中有现成的工具就一定要使用。」

第一版曾手写 N行 LaTeX 递归下降解析器和 OMML 压平器——能跑，但那是
重复造轮子，符号表永远补不全，还自己踩出 `cases` 渲染成空表的 bug。
**已全部换成成熟库，自研部分只剩「现成工具不管的那一块」。**

### 已装（本机验证通过，阶段22）

| 环节 | 库 | 版本 | 干什么 | 为什么选它 |
|:--|:--|:--|:--|:--|
| PDF 文本/矢量/图片/表格 | **PyMuPDF** | 1.28.2 | 页面块、`get_drawings()` 矢量、`find_tables()` 表格、裁剪渲染 | 单库覆盖全部几何需求，不用引第二套 PDF 引擎 |
| docx → 文本+公式+表格 | **pandoc**（pypandoc-binary） | 3.9 | **OMML 公式 ↔ LaTeX 双向**、表格 AST、`--extract-media` 导图 | 成熟双向实现，`\frac`/`\sqrt`/cases/`\triangle`/`^{\circ}` 全部原样还原 |
| LaTeX → MathML | **latex2mathml** | 3.81.1 | 网页/答案册 html 的真公式 | 输出规范 MathML（含 `fence`/`stretchy`），比自研正确 |
| MathML → OMML | **mathml2omml** | 0.0.2 | Word/作答纸 docx 的原生公式 | 正确处理 `m:sty` 正体/斜体 |
| 图片处理 | **Pillow** | 13.0 | 拍照件切行、放大 | 已在用 |
| 印刷体 OCR | **RapidOCR**（经 `local-ocr` 技能的 venv） | rapidocr_onnxruntime 1.2.3 | 扫描件/拍照试卷的逐字文字基准 + 置信度 | 本地离线、免费、不下模型；**读不出手写** |
| **手写 OCR** | **夸克扫描王 API** | `quark_ocr.py` | **手写答案 / 公式 / 印刷体按类型分开标注** | 实测手写置信度 1.00；RapidOCR 完全读不出手写，这是唯一可行的通道 |
| 接线 | `scripts/ocr_bridge.py` | — | 复用 local-ocr 的 RapidOCR 引擎，批量给摄取层条带打基准 | local-ocr 自带 CLI 只吃整文件且 `--box` 丢坐标，无法按块对应 |

安装命令（清华源缺包，必须走官方源）：

```bash
python -m pip install -i https://pypi.org/simple latex2mathml mathml2omml pdfplumber pypandoc-binary
# 本地 OCR 走 local-ocr 技能自带部署（清华源同样会失败回退，实测 59 秒装完 394MB）
python "<HOME>/.workbuddy/skills/local-ocr/scripts/setup.py"
```

### 备选（重，按需再装）

| 工具 | 什么时候值得装 | 代价 |
|:--|:--|:--|
| **MinerU 4.x** | 整本中文教材/教辅 PDF 要一次性转 Markdown（公式 CDM 97.45、表格 TEDS 93.42，中文第一梯队） | 需下模型，CPU 能跑但慢 |
| **PaddleOCR-VL** | 中文试卷（含手写批注）公式识别 | 需下模型 |
| **pymupdf_layout** | 复杂多栏版面顺序更准 | 额外依赖 |

> 单个文件、几十页以内 → **不用装重的**，PyMuPDF + 视觉模型足够。
> 整本书、要批量 → 再上 MinerU。

### 明确不用

| 工具 | 原因 |
|:--|:--|
| Marker | 模型权重 RAIL-M + 代码 GPL-3.0，商用有门槛；公式不如 MinerU |
| Nougat | 不支持中文 |
| Tesseract 打公式 | 只认字不认结构，公式必错 |

---

## 三、三层架构

```
L0 几何切分（ingest_source.py，确定性、零幻觉）
   ├─ 文本块 → type=text / math_text / formula，带 bbox
   ├─ 矢量聚类 → type=diagram（程序框图/几何图）
   ├─ find_tables() → type=table，已结构化
   ├─ get_images() → type=image，导出原始最高分辨率
   └─ 每块标 need_vision + 高 DPI 裁剪图
        ↓
L1 视觉识别（Read 逐块看图，只读 crops/ 与 media/）
   ├─ formula → LaTeX
   ├─ diagram → 先判类型，再转节点表（程序框图）/ 条件+辅助线（几何图）
   ├─ table → 逐格核对
   └─ image → LaTeX / 结构化表 / 描述
        ↓
L2 校验（确定性）
   ├─ LaTeX → latex_math.latex_to_mathml / latex_to_omml（转不动就报错）
   ├─ 框图 → 按技能框图规范画 SVG，节点表条目数要对得上
   └─ 覆盖率 → stats 里每类块数必须都能在结果里数出来
```

**⚠️ 铁律：识别公式和框图只准用 `crops/` 和 `media/`，不许拿 `pages/` 整页图凑。**
`pages/` 是给你定位"这块在第几页哪个位置"用的，分辨率故意做低。

---

## 四、怎么用

```bash
# PDF / 扫描卷
python scripts/ingest_source.py 学情分析.pdf -o work/ingest

# 拍照作业：按横向空白带切题
python scripts/ingest_source.py 作业.jpg -o work/ingest --split-lines

# 别人发来的 docx（含 Word 公式）
python scripts/ingest_source.py 答案.docx -o work/ingest
```

产物：

```
work/ingest/
  manifest.json ← 模型读这个（含 howto 说明）
  pages/p001.png ← 整页预览，只用于定位
  crops/p001_b003.png ← 公式/框图块的高清裁剪，识别用这个
  media/p001_i1.png ← 嵌入原图（公式截图最高分辨率就在这）
```

`manifest.json` 关键字段：

```jsonc
{
  "stats": {"pages": 2, "formula_blocks": 3, "diagram_blocks": 2,
            "table_blocks": 1, "image_blocks": 2, "scanned_pages": 1},
  "pages": [{
    "no": 1, "text_chars": 132, "scanned": false,
    "blocks": [{
      "id": "p001_b004", "type": "formula",
      "bbox": [60, 159, 445, 172], "text": "△ ABC 中，AD ⊥ BC…",
      "need_vision": true, "crop": "crops/p001_b004.png",
      "suspect": ["letter_digit"],
      "hint": "⚠️ 文本层疑似丢了上标（letter_digit）…"
    }]
  }]
}
```

块类型速查：

| type | 含义 | 要不要看图 |
|:--|:--|:--|
| `text` | 普通文字 | 不用 |
| `math_text` | 含数学符号/角标的中文题干 | `need_vision` 时要 |
| `formula` | 纯公式 | 要 |
| `diagram` | 矢量图形簇（框图/几何图） | 要 |
| `table` | 表格，已结构化 | 要（逐格核对） |
| `image` | 嵌入位图 | 要 |

---

## 五、已经踩过的坑（别再踩）

1. **`is_empty` 会吞掉所有连线。** PyMuPDF 里水平/垂直线段的 bbox 宽度或高度为 0，
   `rect.is_empty` 返回 True。用面积或 `is_empty` 过滤矢量，会把框图的所有箭头丢掉，
   于是流程图被拆成互不相连的碎块（一个框一个 diagram 块）。
   **正确写法**：`if max(r.width, r.height) < 3: continue`。

2. **表格边框也是矢量，会被误判成框图。** 先用 `find_tables()` 拿到表格区域，
   聚类时与表格重叠 >50% 的簇直接跳过（`_overlap_ratio`）。

3. **中文教辅 PDF 的文本层经常是乱的 —— 这是最危险的一条。**
   实测《绝对值专题练习试卷》（3 页 26 块）：第一版只标了 1 块待核对，其余全信文本层，
   拿到的是 `化简：｜a 3−｜＋｜a｜`、`化：｜简a＋b｜−｜a b−｜`、`（提示：注意符号前面的号）绝对值负`。
   根因不是字符顺序错，而是**排版软件把同一视觉行的字符拆进了多个 line**，
   减号、竖线被甩到下一行。字都认得，符号没了，整道题作废。
   **正确写法**：`regroup_block()` 用 `get_text('rawdict')` 拿字符级坐标，
   块内按 y 聚行（容差 `max(2pt, 字号×0.5)`）、行内按 x 排序，再清掉运算符两侧的排版空格。
   修复后同一份卷子 26 块全部正确还原，13 个含运算符的块被标 `need_vision`。
   **绝不可以用 `get_text('dict')` 的 line 顺序直接当文本。**

4. **全角运算符必须进 `MATH_CHARS`。** 中文教辅用的是 `｜＋＜＞＝－`（U+FF5C 等），
   不是 `|+<>=`。只认半角的话，`｜a−b｜` 这类题面 math_score 只有 0，
   永远不会被标 `need_vision`。另设 `MATH_OPS`：**含运算符的块一律强制看图**——
   数学题干错一个符号整题作废，宁可多核一遍。

5. **`get_text('rawdict')` 的 span 没有 `'text'` 键，只有 `'chars'`。**
   拿 `sp.get('text','')` 拼原文本会恒得空串，于是 `layout_repaired` 永远为 True、
   标记彻底失效（还连带让所有块都进 need_vision）。必须用 `chars` 里的 `c` 拼。

6. **`x2` 这种丢了上标的写法必须强制复核。** 字都认得，但 `x²` 变成 `x2`
   整道题就变了。`suspect_flags()` 专门抓三类：`letter_digit`（x2）、
   `paren_digit`（(x)2）、`coef_digit`（3x2），命中即 `need_vision=true`。
   ⚠️ 注意 `china-s` 内置字体连 `−`(U+2212) 都渲染不出来（回读直接丢字），
   所以「丢了运算符」也会以 `a3` 的形态出现，和丢上标无法区分 —— 一律按丢上标复核。

7. **pandoc 3.x 的 Table AST 是无标签裸数组。** 不是 `{"t":"TableHead","c":[...]}`。
   而且 `TableBody = [attr, rowheadcols, 中间行, 正文行]`，**正文行在第 4 槽**，
   取第 3 槽会得到空表（表头有、数据没）。两种格式都要兼容。

8. **pandoc 会把 `\begin{cases}` 转成 `\left\{\begin{matrix}`。** 内容不变，
   但别拿 `'cases' in text` 当断言，会误报。

9. **`latex2mathml` 对 `\\` 换行处理正确**（方程组会出多个 `<mtr>`）。
   如果只在 shell 里 `-c "..."` 测试，bash 会把 `\\` 吃成 `\`，看着像 bug ——
   **测试矩阵/方程组一定要写成 .py 文件跑，别在命令行里拼 LaTeX。**

10. **扫描页没有文本层**，`text_chars < 20` 判为 `scanned=true`，
    整页走视觉识别。此时 `pages/` 的低分辨率图不够用，要用 `media/` 里的原图。

11. **块会切断半句。** 真实卷子里 `求 a 的最大` + 换行 + `值；` 是两个块，
    只读一块就漏字。块末不是标点时打 `open_ended=true`，
    hint 里写明「需与相邻块连读」。

12. **极长宽比的图 OCR 会返回空。** 矢量 PDF 的公式裁剪条通常 2600×110 px
    （500dpi × 2.5 zoom），RapidOCR 检测不到文字行，返回空数组；就算出字置信度也低
    （实测 `化简：Ｉb-a丨＋「a＋cｌ－Ｉb-l`，0.578，全角符号被认成 `Ｉ 丨 「 ｌ`）。
    **结论：OCR 只该用在拍照/扫描件上**（正常比例，实测 0.71–0.93），
    不要拿它去校验矢量 PDF 的文本层 —— 那本来就更准。
    另：`ocr_bridge.py` 遇到单块失败只标 `ok=false`，绝不打断整批。

13. **OCR 的 `--box` 其实不输出坐标。** local-ocr 的 `ocr.py` 里
    `lines.append(f"[{score:.2f}] {text}" if box else text)` —— 坐标 `bx` 被丢掉了，
    与它 SKILL.md 写的「输出带坐标」不符。要坐标得自己调 `ocr_image()`。
    我们只需要文本基准，所以按块 bbox 对应即可。

14. **🔴 别用合成手写样本判断 OCR 的手写能力 —— 结论会反过来。**
    我先用楷体 + 抖动造了一张「手写作业」，夸克把它整张判成 `PrintedText`
    （太规整，没触发手写通道），两处复杂公式还降级成 `FormulaFigure`，
    于是得出「夸克手写差」的错误结论。
    换成学生的真实作业照片后，**手写「重复赘余」「这次活动比上次增加了」置信度 1.00**。
    **判断手写必须用真样本。** 真样本在哪：`~/.workbuddy/blobs/<2位>/<sha>.png`
    （会话附件），按修改时间对 `submissions` 表的提交时间就能锁定批次。

15. **夸克的 `reqId` 是必填，漏了报 `A0201 缺少必填参数`。**
    官方参数表里它排在一堆签名参数中间，很像可选字段，实际不是。
    另外连发会触发 `A0300 QPS limit` —— 是瞬时限流不是额度用完，
    间隔 ≥1.2 秒（`quark_ocr.py` 的 `MIN_INTERVAL`）就能稳定跑。

16. **夸克会把复杂公式降级成 `FormulaFigure`**（只返回 base64 图片，`Value` 是图不是文本）。
    这是**静默失效**：调用成功、`code=00000`，但公式内容根本没拿到。
    必须检查 `formula_figures > 0` 并回退视觉模型补，`quark_ocr.py` 已把它转成 `degraded` 标记。

17. **有文本层 ≠ 没有手写。** 老师批改过的卷子，题面是原生文本，但红笔批改和学生手写答案
    **不在文本层里** —— 只看文本层会把「学生写了答案」误判成「没写」。
    `annotation_signal()` 用两个信号补调夸克：① 嵌入位图；② 彩色（红/蓝）矢量笔迹 ≥3 笔。
    **宁可误报不可漏报**：误报只多花 1.2 秒，漏报等于没读到答案。
    实测干净试卷 3 页 0 次误触发；带 5 条红笔的页面正确命中 `color_ink×5`。

---

## 六、和现有流水线的接法

```
① 摄取 ingest_source.py → manifest.json
② 读块 按 blocks 逐块处理，need_vision 的读 crops/
③ 公式落地 latex_math.latex_to_mathml() → 网页
                latex_math.latex_to_omml() → docx（Word 原生公式）
④ 框图落地 节点表 → 按 assets/figs/ 的框图规范画 SVG
⑤ 剩余流程 归因 → 排期 → 讲义 → 作答纸 → 批改（§6.5 主链）
```

**公式只认 LaTeX 这一种中间形态。** 视觉模型认出来写 LaTeX，
`latex_math` 负责转两个出口，网页和打印件同源，保证长得一样。

---

## 七、自检

```bash
python scripts/selftest_ingest.py # 26 项一键回归（local-ocr 未部署时 20 项），自己造样本，不依赖外部文件
python scripts/latex_math.py # 公式转换 12 例
python scripts/ingest_source.py <任一文件> -o /tmp/t # 摄取冒烟
```

`selftest_ingest.py` 改完代码必跑。它覆盖：PDF 块分类、上标丢失标记、
全角运算符强制看图、框图不被拆碎、表格、扫描页、**文本层乱序按坐标还原**、
docx 公式与表格（pandoc）、公式落地 MathML+OMML。

`latex_math.py` 自检会打印 `latex2mathml=True mathml2omml=True`，
任一为 False 说明库没装好，先按第二节的官方源命令装。
