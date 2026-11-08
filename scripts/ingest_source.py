#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""ingest_source.py — 源材料分层摄取器（PDF / 图片 / docx）

要解决的问题
------------
之前读 PDF / 拍照件，是"整页丢给模型看一眼"。整页缩到 1000px 宽，
小字公式、细线条流程框图必然糊掉，于是出现两类事故：
  · 公式认成 `x2 - 3x + 2`（指数掉成普通字符）
  · 程序框图整块被跳过，只抄了题干文字
不是模型不努力，是输入端没给够分辨率、也没告诉它"这里有块图"。

本脚本 = 三层架构的 L0 层（确定性、零幻觉）
------------------------------------------
1. 几何切分：每页拆成带坐标的块，逐块分类
2. 按需放大：公式块 / 框图块单独裁出，用**矢量重绘**的高 DPI 导出
   （PDF 里框图是矢量路径，放大 3 倍仍锐利，比 PIL 拉伸强得多）
3. 标注 need_vision：明确"这几块必须逐块看图"，并给 howto 说明

关键一招：框图检测
----------------
教材 PDF 的流程图/几何图是**矢量路径**，`page.get_drawings()` 直接拿得到。
对矢量矩形做邻近合并聚类，簇内图元够多且面积够大 → 判 diagram。
扫描件没有矢量层，改用"大面积嵌入图像"兜底。

用法
----
    python ingest_source.py 学情分析.pdf -o work/ingest
    python ingest_source.py 作业照片.jpg -o work/ingest --split-lines
    python ingest_source.py 答案.docx -o work/ingest

产物
----
    <out>/manifest.json      块清单（含 howto，模型读这个）
    <out>/pages/p001.png     整页预览（只用于定位）
    <out>/crops/...png       公式/框图块高分辨率裁剪（识别用这个）
    <out>/media/...          嵌入原图（最高分辨率）

⚠️ 铁律：识别公式和框图只准用 crops/ 与 media/，不许拿 pages/ 整页图凑。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import zipfile
from pathlib import Path

try:
    import pymupdf
except ImportError:
    import fitz as pymupdf

try:
    from PIL import Image
except ImportError:
    Image = None


# ==================== 信号表 ====================

MATH_CHARS = set('√∛∜²³¹⁴⁰⁵⁶⁷⁸⁹₀₁₂₃₄₅₆₇₈₉½⅓¼∠△▲⊙⊥∥°π≤≥≠≈≡±∓×÷∞∫∑∏'
                 '∈∉⊂⊃∪∩⇒⇔→←↔′″∴∵'
                 # ↓ 中文教辅 PDF 大量使用全角数学符号，不能只认半角
                 '＋－−＝＜＞｜／％‰')

# 强运算符：出现即说明这行是数学表达式，必须看图核对（错一个符号整题作废）
MATH_OPS = set('｜＋－−＝＜＞≤≥≈≠±×÷／')
MATH_FONT_HINT = ('math', 'cambria', 'symbol', 'stix', 'latinmodern',
                  'cmmi', 'cmsy', 'cmext', 'euclid', 'asana', 'xits')
MATH_PAT = re.compile(
    r'[A-Za-z]\)?\s*[＝=]\s*[-−]?\d'
    r'|[A-Za-z0-9]\s*[×÷·]\s*[A-Za-z0-9]'
    r'|[A-Za-z]\s*[²³]'
    r'|\d\s*/\s*\d')

SCANNED_CHAR_THRESHOLD = 20
END_PUNCT = set('。！？；：、，,.;:!?）)】》」』”’…—－-|｜~～/／_＿')


# ==================== 小工具 ====================

def _crop(page, bbox, outdir, bid, dpi, zoom):
    """用矢量重绘方式裁一块高分辨率 PNG。"""
    import pymupdf as _pm
    r = _pm.Rect(bbox)
    r = r + (-2, -2, 2, 2)                      # 留 2pt 白边，防止切掉笔画
    r = r & page.rect
    pm = page.get_pixmap(clip=r, dpi=int(dpi * zoom))
    p = outdir / 'crops' / (bid + '.png')
    pm.save(str(p))
    return p


def merge_boxes(boxes, gap=6.0):
    """邻近矩形合并成簇。纯 Python，页面级元素几百个足够快。"""
    work = [[b[0] - gap, b[1] - gap, b[2] + gap, b[3] + gap] for b in boxes]
    changed = True
    while changed and len(work) > 1:
        changed = False
        out = []
        while work:
            a = work.pop()
            i = 0
            while i < len(work):
                b = work[i]
                if not (a[2] < b[0] or b[2] < a[0] or a[3] < b[1] or b[3] < a[1]):
                    a = [min(a[0], b[0]), min(a[1], b[1]),
                         max(a[2], b[2]), max(a[3], b[3])]
                    work.pop(i)
                    changed = True
                else:
                    i += 1
            out.append(a)
        work = out
    return work


def _clean_math_spaces(s):
    """删掉数学运算符两侧的排版空格，不动汉字之间的空格。

    「｜a− 3｜」→「｜a−3｜」；「已知 a＜0」保持原样（a 不是运算符）。
    """
    s = re.sub(r'[ \u3000]*(?=[＋－−＝＜＞≤≥≈≠±×÷／｜])', '', s)
    s = re.sub(r'(?<=[＋－−＝＜＞≤≥≈≠±×÷／｜])[ \u3000]*', '', s)
    return s


def regroup_block(block):
    """块内字符按 y 聚行、行内按 x 排序，还原成与视觉一致的文本。

    为什么必须做（真实教辅 PDF 实测）：不少排版软件会把同一视觉行的字符
    拆进多个 line，减号、竖线被甩到下一行 —— PyMuPDF 的 line 顺序会把
    「｜a−b｜」读成「｜a b｜」，「化简：」读成「化：｜简」。字都认得，
    但符号丢失、语序错乱，整道题就废了。按坐标重排能还原。

    返回 (文本, 是否发生过重排)。
    """
    chars = []
    for ln in block.get('lines', []):
        for sp in ln.get('spans', []):
            size = sp.get('size') or 10.0
            for c in sp.get('chars', []):
                ch = c.get('c') or ''
                if not ch:
                    continue
                o = c.get('origin') or (0.0, 0.0)
                chars.append((o[1], o[0], ch, size))
    if not chars:
        return '', False

    chars.sort(key=lambda t: (t[0], t[1]))
    rows, cur = [], [chars[0]]
    for ch in chars[1:]:
        # 同一视觉行容差：字号的半个身位，够容下上下标的微小偏移
        if abs(ch[0] - cur[-1][0]) <= max(2.0, cur[-1][3] * 0.5):
            cur.append(ch)
        else:
            rows.append(cur)
            cur = [ch]
    rows.append(cur)

    lines = []
    for r in rows:
        r.sort(key=lambda t: t[1])
        lines.append(_clean_math_spaces(''.join(t[2] for t in r)))

    # 原文本要用 chars 拼 —— rawdict 的 span 没有 'text' 键，用 sp['text'] 会恒取到 ''，
    # 导致 layout_repaired 永远为 True，标记彻底失效
    old = '\n'.join(
        ''.join(c.get('c', '') for sp in ln.get('spans', [])
                for c in sp.get('chars', []))
        for ln in block.get('lines', []))
    new = '\n'.join(lines)
    return new, (new.strip() != old.strip())


def math_score(text, font, size, median_size):
    """给一段文字打「像不像公式」的分。"""
    s = 0
    if any(c in MATH_CHARS for c in text):
        s += 3
    fl = (font or '').lower()
    if any(h in fl for h in MATH_FONT_HINT):
        s += 3
    if MATH_PAT.search(text or ''):
        s += 2
    if re.search(r'[=＝]', text or ''):
        s += 1
    if median_size and size and size < median_size * 0.82:
        s += 1
    # 纯中文长句且毫无数学痕迹才减分；"用公式法解方程 x²-3x+2=0" 这种题干不能减
    han = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
    if han >= 6 and len(text) > 10 and not any(c in MATH_CHARS for c in text) \
            and not MATH_PAT.search(text or ''):
        s -= 4
    return s


# 「丢了上标」的可疑写法 —— 这一类漏检会让整道题变味，必须强制复核
SUSPECT = (
    (re.compile(r'[A-Za-z]\d'), 'letter_digit'),      # x2 极可能是 x²
    (re.compile(r'[\)）]\s*\d'), 'paren_digit'),      # (x)2 极可能是 (x)²
    (re.compile(r'\d\s*[A-Za-z]\d'), 'coef_digit'),   # 3x2 / 2a3
)


def suspect_flags(text):
    """返回可疑角标写法清单。非空即意味着文本层已失真，必须看图核对。"""
    return [name for pat, name in SUSPECT if pat.search(text or '')]


def flowchart_signal(items):
    """vector 图元里是否有框图特征。"""
    nr = sum(1 for it in items if it[0] == 're')
    nl = sum(1 for it in items if it[0] == 'l')
    nq = sum(1 for it in items if it[0] in ('qu', 'c'))
    strong = (nr >= 3 and nl >= 2) or (nl + nq >= 8)
    return strong, nr, nl, nq


def _overlap_ratio(box, others):
    """box 与 others 里任一框的最大重叠占 box 面积比。"""
    area = max((box[2] - box[0]) * (box[3] - box[1]), 1e-6)
    best = 0.0
    for o in others or []:
        w = min(box[2], o[2]) - max(box[0], o[0])
        h = min(box[3], o[3]) - max(box[1], o[1])
        if w > 0 and h > 0:
            best = max(best, (w * h) / area)
    return best


# ==================== PDF ====================

def process_pdf(path, outdir, dpi=200, zoom=2.5, min_area_ratio=0.012):
    doc = pymupdf.open(str(path))
    pages_out, seq = [], 0
    n_formula = n_diagram = n_image = n_scanned = n_table = 0

    for pno, page in enumerate(doc, 1):
        pw, ph = page.rect.width, page.rect.height
        page_area = max(pw * ph, 1.0)
        tag = 'p%03d' % pno

        pm = page.get_pixmap(dpi=max(90, dpi // 2))
        pprev = outdir / 'pages' / (tag + '.png')
        pm.save(str(pprev))

        blocks, text_total = [], 0
        ocr_src = None          # 扫描页的高清整页图，供夸克识别手写
        annotation_ev = None    # 有文本层但发现手写批注证据时记录，便于追溯

        # ---------- 文本块 ----------
        # 用 rawdict 拿字符级坐标：必须按坐标重排，不能信 line 顺序
        d = page.get_text('rawdict')
        sizes = sorted(sp['size'] for b in d['blocks'] if b.get('type') == 0
                       for ln in b.get('lines', []) for sp in ln.get('spans', []))
        median_size = sizes[len(sizes) // 2] if sizes else 0

        for b in d['blocks']:
            if b.get('type') != 0:
                continue
            raw_txt = ''.join(''.join(c.get('c', '') for c in sp.get('chars', []))
                              for ln in b.get('lines', [])
                              for sp in ln.get('spans', []))
            if not raw_txt.strip():
                continue
            txt, repaired = regroup_block(b)
            if not txt.strip():
                continue
            text_total += len(txt)
            fonts, score, sp_sizes = set(), 0, []
            for ln in b.get('lines', []):
                for sp in ln.get('spans', []):
                    fonts.add(sp.get('font', ''))
                    sp_sizes.append(sp.get('size') or 0)
                    sp_txt = ''.join(c.get('c', '') for c in sp.get('chars', []))
                    score += math_score(sp_txt, sp.get('font'),
                                        sp.get('size'), median_size)

            # 上下标特征：同一块内字号明显分两档 → 一定有指数/下标。
            # 这条专治「y = 3x² 被读成 y = 3x2」而没标复核的情况。
            if len(sp_sizes) >= 2:
                hi, lo = max(sp_sizes), min(sp_sizes)
                if hi > 0 and lo < hi * 0.85:
                    score += 2

            han = sum(1 for c in txt if '\u4e00' <= c <= '\u9fff')
            sus = suspect_flags(txt)          # x2 / (x)2 / 3x2 —— 丢了上标的写法
            has_op = any(c in MATH_OPS for c in txt)   # 含 ＋ − ｜ ＜ ＞ 等运算符
            if sus:
                score += 2
            if score >= 5:
                btype = 'formula' if han < 2 else 'math_text'   # 中文题干不是纯公式
            elif score >= 2 or has_op:
                btype = 'math_text'
            else:
                btype = 'text'

            seq += 1
            bid = '%s_b%03d' % (tag, seq)
            # 含运算符就必看原图：数学题干错一个符号整题作废，宁可多核一遍。
            # 被重排过且有数学痕迹的块也要看 —— 重排能修语序，修不了
            # 「符号压根没被提取」。纯文字块不因重排而强制看图。
            need = score >= 3 or bool(sus) or has_op or (repaired and score >= 2)
            rec = {'id': bid, 'type': btype,
                   'bbox': [round(v, 1) for v in b['bbox']],
                   'text': txt.strip()[:4000],
                   'font': ','.join(sorted(f for f in fonts if f))[:80],
                   'math_score': score,
                   'layout_repaired': repaired,
                   'need_vision': need}
            if sus:
                rec['suspect'] = sus
            if repaired:
                # 乱序原文留档：方便人工比对「重排有没有修歪」
                rec['raw_text'] = raw_txt.strip()[:4000]
            # 块末不是标点 → 多半被换行截断了半句，必须与相邻块连读。
            # 真实教辅 PDF 里「求 a 的最大 / 值；」这种切断极常见，只读一块会漏字。
            tail = txt.strip()[-1:] if txt.strip() else ''
            if len(txt.strip()) >= 10 and tail and tail not in END_PUNCT:
                rec['open_ended'] = True
                if 'hint' in rec:
                    rec['hint'] += '（⚠️ 本块末尾不是标点，可能被换行截断，需与相邻块连读）'
                else:
                    rec['hint'] = '⚠️ 本块末尾不是标点，可能被换行截断，需与相邻块连读'
            if need:
                rec['crop'] = _crop(page, b['bbox'], outdir, bid, dpi, zoom)
                if sus:
                    rec['hint'] = ('⚠️ 文本层疑似丢了上标（%s）：x2 可能是 x²、'
                                   '3x2 可能是 3x²。必须看图逐字核对指数与系数，'
                                   '禁止直接沿用文本层。' % '/'.join(sus))
                elif repaired and has_op:
                    rec['hint'] = ('⚠️ 原 PDF 字符乱序，已按坐标重排修复（raw_text 是'
                                   '修复前的乱序原文）。重排能修语序，修不了「符号根本'
                                   '没被提取」。必须看图逐字核对每一个 ＋ − ｜ ＜ ＞ '
                                   '与指数，数学片段转 LaTeX。')
                elif has_op:
                    rec['hint'] = ('含运算符的题干：逐字核对 ＋ − ｜ ＜ ＞、负号与指数，'
                                   '不许跳过符号只看汉字；数学片段单独转 LaTeX')
                elif btype == 'formula':
                    rec['hint'] = '整块当公式识别，输出 LaTeX（保留分式/根号/上下标结构）'
                else:
                    rec['hint'] = ('含数学符号/角标的中文题干：逐字核对符号、上下标、数字，'
                                   '数学片段单独转 LaTeX')
                n_formula += 1
            blocks.append(rec)

        # ---------- 表格（PyMuPDF 内置 find_tables，不引第二套 PDF 引擎）----------
        table_boxes = []
        try:
            for tb in page.find_tables().tables:
                rows = tb.extract()
                if not rows or len(rows) < 2:
                    continue
                r = tb.bbox
                table_boxes.append([r[0], r[1], r[2], r[3]])
                n_table += 1
                seq += 1
                bid = '%s_b%03d' % (tag, seq)
                md = '\n'.join('| ' + ' | '.join(
                    (c or '').replace('\n', ' ') for c in row) + ' |' for row in rows)
                blocks.append({
                    'id': bid, 'type': 'table',
                    'bbox': [round(v, 1) for v in r], 'text': md[:4000],
                    'rows': rows, 'need_vision': True,
                    'crop': _crop(page, r, outdir, bid, dpi, zoom),
                    'hint': '表格已按文本层结构化；逐格核对数值、表头与合并单元格，'
                            '单元格内的指数/分数要按图确认'})
        except Exception:
            table_boxes = []

        # ---------- 矢量聚类 → 框图 ----------
        try:
            drawings = page.get_drawings()
        except Exception:
            drawings = []

        if drawings:
            rects, items_by_rect = [], []
            for dr in drawings:
                r = dr.get('rect')
                if r is None or r.is_empty:
                    continue
                # ⚠️ 不能按面积过滤：水平/垂直连线的 bbox 面积恒为 0，
                # 一旦被丢掉，框图就会被拆成互不相连的碎块（踩过）。
                if max(r.width, r.height) < 3:
                    continue
                if r.width > pw * 0.95 and r.height > ph * 0.95:
                    continue
                rects.append([r.x0, r.y0, r.x1, r.y1])
                items_by_rect.append(dr.get('items', []))

            for cl in (merge_boxes(rects, 7.0) if rects else []):
                cw, ch = cl[2] - cl[0], cl[3] - cl[1]
                if cw * ch < page_area * min_area_ratio or cw < 45 or ch < 30:
                    continue
                # 表格边框也是矢量，会被误判成框图 —— 与已识别表格重叠就跳过
                if _overlap_ratio(cl, table_boxes) > 0.5:
                    continue
                inside = []
                for i, r in enumerate(rects):
                    if not (r[2] < cl[0] or cl[2] < r[0] or r[3] < cl[1] or cl[3] < r[1]):
                        inside.extend(items_by_rect[i] or [])
                strong, nr, nl, nq = flowchart_signal(inside)
                if not strong and len(inside) < 4:
                    continue
                seq += 1
                bid = '%s_b%03d' % (tag, seq)
                blocks.append({
                    'id': bid, 'type': 'diagram',
                    'bbox': [round(v, 1) for v in cl], 'text': '',
                    'shapes': {'rect': nr, 'line': nl, 'curve': nq},
                    'need_vision': True,
                    'crop': _crop(page, cl, outdir, bid, dpi, zoom),
                    'hint': '矢量图形簇（框%d/线%d/曲%d）。先判类型：程序框图→'
                            '输出节点·判断·连线的结构化表，再按技能框图规范画 SVG；'
                            '几何图→输出已知条件、求什么、关键辅助线' % (nr, nl, nq)})
                n_diagram += 1

        # ---------- 嵌入图片 ----------
        for idx, im in enumerate(page.get_images(full=True), 1):
            xref = im[0]
            try:
                rects_img = page.get_image_rects(xref)
            except Exception:
                rects_img = []
            if not rects_img:
                continue
            r0 = rects_img[0]
            if r0.width * r0.height < 900:          # 太小的当装饰/符号
                continue
            seq += 1
            bid = '%s_b%03d' % (tag, seq)
            rel, low_res = None, False
            try:
                info = doc.extract_image(xref)
                ext = info.get('ext', 'png')
                p = outdir / 'media' / ('%s_i%d.%s' % (tag, idx, ext))
                p.write_bytes(info['image'])
                rel = p
                # 原图就是最高分辨率，硬放大只会更糊 —— 低于阈值时如实提示
                low_res = (info.get('width', 0) < 700 and info.get('height', 0) < 180)
            except Exception:
                pass
            if rel is None:
                rel = _crop(page, [r0.x0, r0.y0, r0.x1, r0.y1], outdir, bid, dpi, zoom)
            blocks.append({
                'id': bid, 'type': 'image',
                'bbox': [round(v, 1) for v in (r0.x0, r0.y0, r0.x1, r0.y1)],
                'text': '', 'file': rel, 'need_vision': True, 'low_res': low_res,
                'hint': ('嵌入位图（可能是公式截图/表格/实拍图），原图分辨率偏低，'
                         '识别后须回看 pages/ 整页预览交叉确认'
                         if low_res else
                         '嵌入位图（可能是公式截图/表格/实拍图）。'
                         '含数学式→LaTeX；表格→结构化表；图→描述+关键数据')})
            n_image += 1

        blocks.sort(key=lambda x: (x['bbox'][1], x['bbox'][0]))
        scanned = text_total < SCANNED_CHAR_THRESHOLD and not any(
            b['type'] in ('formula', 'math_text') for b in blocks)
        if scanned:
            n_scanned += 1
            # 整页一块丢给模型必然糊：按横向空白带切成若干高清条带
            try:
                sl = _slice_scanned_page(page, outdir, tag, dpi, zoom)
            except Exception:
                sl = []
            if sl:
                n_image += len(sl) - len([b for b in blocks if b['type'] == 'image'])
                blocks = sl
            # 扫描页没有文本层，手写答案只能靠夸克 —— 单独渲一张高清整页图
            if quark_available():
                try:
                    ocr_src = _render_hi_res_page(page, outdir, tag, max(200, dpi))
                except Exception:
                    ocr_src = None
        elif quark_available():
            # 有文本层不代表没有手写：老师批改过的卷子，题面是原生文本，
            # 但红笔批改和学生答案不在文本层里，只看文本层会当成「没写答案」。
            ev = annotation_signal(page)
            if ev:
                annotation_ev = ev
                try:
                    ocr_src = _render_hi_res_page(page, outdir, tag, max(200, dpi))
                except Exception:
                    ocr_src = None

        pages_out.append({
            'no': pno, 'size': [round(pw, 1), round(ph, 1)],
            'text_chars': text_total, 'scanned': scanned,
            'page_png': pprev, 'blocks': blocks,
            'ocr_src': ocr_src,
            'annotation_evidence': annotation_ev,
            'vision_targets': [b['id'] for b in blocks if b.get('need_vision')],
        })

    doc.close()
    # OCR 基准统一在整份文档处理完后跑一次：模型只加载一次，
    # 逐页调用会把加载开销乘以页数。未部署则静默跳过。
    n_ocr = annotate_with_ocr([b for p in pages_out for b in p['blocks']])
    # 手写答案只能靠夸克（RapidOCR 读不出手写）
    n_quark = annotate_pages_with_quark(pages_out)
    stats = {'pages': len(pages_out), 'formula_blocks': n_formula,
             'diagram_blocks': n_diagram, 'image_blocks': n_image,
             'table_blocks': n_table, 'scanned_pages': n_scanned,
             'ocr_blocks': n_ocr, 'quark_pages': n_quark,
             'written_blocks': sum(len((p.get('quark') or {}).get('written') or [])
                                   for p in pages_out)}
    return pages_out, stats


# ==================== 图片 ====================

def _split_lines(img, min_gap_ratio=0.012):
    """按横向空白带切块（拍照作业切题用）。返回 [(x0,y0,x1,y1)]。"""
    g = img.convert('L')
    W, H = g.size
    scale = 900.0 / W if W > 900 else 1.0
    if scale < 1.0:
        g = g.resize((int(W * scale), int(H * scale)), Image.LANCZOS)
    w, h = g.size
    px = g.load()
    rows = []
    for y in range(h):
        dark = 0
        for x in range(0, w, 2):
            if px[x, y] < 170:
                dark += 1
        rows.append(dark)
    thr = max(1, int(w * 0.004))
    bands, start = [], None
    gap_min = max(3, int(h * min_gap_ratio))
    empty_run = 0
    for y, d in enumerate(rows):
        if d <= thr:
            empty_run += 1
            if start is not None and empty_run >= gap_min:
                bands.append((start, y - empty_run))
                start = None
        else:
            empty_run = 0
            if start is None:
                start = y
    if start is not None:
        bands.append((start, h - 1))
    inv = 1.0 / scale if scale < 1.0 else 1.0
    out = []
    for y0, y1 in bands:
        if (y1 - y0) < h * 0.012:
            continue
        out.append((0, max(0, int(y0 * inv) - 6), W, min(H, int((y1 + 1) * inv) + 6)))
    return out or [(0, 0, W, H)]


# ==================== 本地 OCR（复用 local-ocr 技能） ====================
#
# 为什么要这一层：视觉模型读印刷体偶尔认错字（把 ｜a−b｜ 读成 ｜a−6｜），
# 而且错了不自知。本地 OCR 给的是逐字置信度，正好当对照基准。
# ⚠️ 只用于印刷体。手写体识别率差，学生的手写作业/答案一律不许走这里。

LOCAL_OCR_DIR = Path.home() / '.workbuddy' / 'skills' / 'local-ocr'


# 夸克扫描王：手写识别通道。没配置凭证就静默降级，不影响主流程。
try:
    from quark_ocr import recognize as _quark_recognize
    from quark_ocr import available as _quark_available
except Exception:                                            # noqa: BLE001
    _quark_recognize = None

    def _quark_available():
        return False


def quark_available():
    return _quark_recognize is not None and _quark_available()


def local_ocr_python():
    """local-ocr 已部署就返回它的解释器路径，没部署返回 None（静默降级）。"""
    f = LOCAL_OCR_DIR / 'venv_path.txt'
    if not f.exists():
        return None
    try:
        p = Path(f.read_text(encoding='utf-8').strip())
    except Exception:
        return None
    return p if p.exists() else None


def annotation_signal(page, max_drawings=4000):
    """有文本层的页面上，是否可能还有手写批注。返回证据列表，空 = 没发现。

    为什么要查这个：老师批改过的卷子通常有文本层（题面是原生文本），
    但红笔批改、学生手写答案**不在文本层里** —— 只看文本层会当成"没有答案"。
    夸克能把这些手写读出来（WrittenText），所以命中就值得为这页多调一次。

    两个信号（宁可误报，不可漏报 —— 误报只多花 1.2 秒，漏报直接没读到答案）：
      1. 嵌入位图：扫描的手写答案/批注贴图
      2. 彩色矢量笔迹：批改笔一般是红或蓝，且通常不止一笔
    """
    ev = []
    try:
        imgs = page.get_images(full=False)
        if imgs:
            ev.append('embedded_image×%d' % len(imgs))
            return ev                     # 有贴图就够了，不必再扫矢量（get_drawings 慢）
    except Exception:                     # noqa: BLE001
        pass

    ink = 0
    try:
        for i, dr in enumerate(page.get_drawings()):
            if i >= max_drawings:
                break
            c = dr.get('color') or dr.get('fill')
            if not c or len(c) < 3:
                continue
            r, g, b = float(c[0]), float(c[1]), float(c[2])
            red = r > 0.55 and g < 0.45 and b < 0.45
            blue = b > 0.55 and r < 0.45 and g < 0.60
            if red or blue:
                ink += 1
    except Exception:                     # noqa: BLE001
        pass
    if ink >= 3:                          # 单笔红点可能是图例/角标，≥3 笔才认作批改痕迹
        ev.append('color_ink×%d' % ink)
    return ev


def _render_hi_res_page(page, outdir, tag, dpi=200):
    """给夸克用的高清整页图。

    pages/ 里那张预览只有 dpi//2（默认 100），夸克识别会糊 ——
    小字和手写笔画糊了就全废了，必须单独渲染一张。
    """
    pm = page.get_pixmap(dpi=int(dpi))
    p = outdir / 'media' / (tag + '_ocr.png')
    pm.save(str(p))
    return p


def annotate_pages_with_quark(pages, interval=1.2):
    """对扫描页调夸克，结果写 page['quark']。

    为什么必须调它（真实作业实测）：RapidOCR 读不出手写 ——
    「重复赘余」被读成「这冰上次增可」、手写的 C 直接丢失。
    夸克把印刷体/手写/公式分开标注，手写置信度 1.00。

    失败静默跳过；有 FormulaFigure 降级时标 degraded，调用方回退视觉模型。
    返回成功识别的页数。
    """
    if not quark_available():
        return 0
    targets = [p for p in pages if p.get('ocr_src')]
    if not targets:
        return 0

    n = 0
    last = 0.0
    for pg in targets:
        wait = interval - (time.time() - last)
        if wait > 0:
            time.sleep(wait)
        try:
            r = _quark_recognize(str(pg['ocr_src']))
        except Exception:                                    # noqa: BLE001
            r = {'ok': False}
        last = time.time()
        if not r.get('ok'):
            pg['quark'] = {'ok': False, 'error': r.get('error', '')}
            continue
        pg['quark'] = {
            'ok': True,
            'elapsed': r['elapsed'],
            'text': r['text'][:4000],
            'written': r['written'][:40],        # 手写答案，批改直接用
            'formulas': r['formulas'][:40],
            'n_blocks': len(r['blocks']),
            'formula_figures': r['formula_figures'],
            'degraded': r['degraded'],
            'hint': ('手写答案见 quark.written（按出现顺序）；'
                     '公式见 quark.formulas（已转 LaTeX）。'
                     + ('⚠️ 有 %d 处公式降级成图片未转文本，'
                        '这些位置必须回退视觉模型补。' % r['formula_figures']
                        if r['degraded'] else '')),
        }
        n += 1
    return n


def annotate_with_ocr(blocks, py=None, timeout=420):
    """给 need_vision 的块补一层本地 OCR 文本（ocr_text / ocr_conf）。

    失败一律静默跳过：OCR 是加分项，不能因为它没装好就让整个摄取失败。
    返回成功标注的块数。
    """
    if py is None:
        py = local_ocr_python()
    if py is None:
        return 0
    targets = [b for b in blocks if b.get('need_vision') and b.get('crop')]
    if not targets:
        return 0
    bridge = Path(__file__).with_name('ocr_bridge.py')
    if not bridge.exists():
        return 0

    import subprocess
    try:
        r = subprocess.run([str(py), str(bridge)] + [str(b['crop']) for b in targets],
                           capture_output=True, text=True, encoding='utf-8',
                           errors='replace', timeout=timeout)
        txt = (r.stdout or '').strip()
        data = json.loads(txt.splitlines()[-1]) if txt else []
    except Exception:
        return 0
    if not isinstance(data, list):
        return 0

    by_name = {d.get('file'): d for d in data if isinstance(d, dict) and d.get('ok')}
    n = 0
    for b in targets:
        d = by_name.get(Path(b['crop']).name)
        if not d or not d.get('full'):
            continue
        scores = [l['score'] for l in d.get('lines', []) if 'score' in l]
        conf = round(sum(scores) / len(scores), 3) if scores else 0.0
        b['ocr_text'] = d['full'][:2000]
        b['ocr_conf'] = conf
        base = b.get('hint') or ''
        b['hint'] = (base + ' ｜ 本地OCR基准(置信度%.2f)：%s'
                     % (conf, d['full'][:120].replace('\n', ' ')))
        n += 1
    return n


def _split_bands(img, max_h_ratio=0.20):
    """两级切分：先按「大题间距」切，切出来太高的再按「行间距」细分。

    只用细间距会把每行切成一块（一道多行题被拆散）；
    只用粗间距又会留出占页面四分之一的巨块（缩到模型输入尺寸后小字仍糊）。
    两级切能同时满足「一块≈一道题」和「每块分辨率够」。
    """
    W, H = img.size
    out = []
    for x0, y0, x1, y1 in _split_lines(img, min_gap_ratio=0.028):
        if (y1 - y0) <= H * max_h_ratio:
            out.append((x0, y0, x1, y1))
            continue
        sub = img.crop((x0, y0, x1, y1))
        parts = _split_lines(sub, min_gap_ratio=0.012)
        if len(parts) <= 1:
            out.append((x0, y0, x1, y1))
        else:
            for sx0, sy0, sx1, sy1 in parts:
                out.append((x0 + sx0, y0 + sy0, x0 + sx1, y0 + sy1))
    return out


def _slice_scanned_page(page, outdir, tag, dpi=200, zoom=2.0):
    """扫描页没有文本层，整页图交给模型时会被缩到约 1500px 长边，
    小公式的指数、细线条必然糊。按横向空白带切成若干条带，每块单独高清。

    切不出来（纯色页/整页一张图）就返回空列表，调用方保持原样。
    """
    if Image is None:
        return []
    scale = dpi / 72.0
    pm = page.get_pixmap(dpi=int(dpi))
    img = Image.frombytes('RGB', (pm.width, pm.height), pm.samples)
    bands = _split_bands(img)
    if len(bands) <= 1:
        return []
    out = []
    for i, (x0, y0, x1, y1) in enumerate(bands, 1):
        bid = '%s_s%02d' % (tag, i)
        crop = img.crop((x0, y0, x1, y1))
        if zoom and zoom > 1:
            crop = crop.resize((int(crop.width * zoom), int(crop.height * zoom)),
                               Image.LANCZOS)
        p = outdir / 'crops' / (bid + '.png')
        crop.convert('RGB').save(str(p), quality=95)
        out.append({
            'id': bid, 'type': 'image',
            'bbox': [round(x0 / scale, 1), round(y0 / scale, 1),
                     round(x1 / scale, 1), round(y1 / scale, 1)],
            'text': '', 'crop': p, 'need_vision': True,
            'hint': '扫描页条带（按横向空白切分）。**按 bbox 的 y 顺序依次读**，'
                    '相邻条带常属同一道题，须连起来理解再识别。'
                    '逐块输出：公式→LaTeX；程序框图→节点表；表格→结构化表'})
    return out


def process_image(path, outdir, split_lines=False, zoom=2.0):
    if Image is None:
        raise SystemExit('需要 Pillow：pip install pillow')
    img = Image.open(str(path))
    img.load()
    W, H = img.size
    tag = 'p001'

    prev = outdir / 'pages' / 'p001.png'
    img.convert('RGB').save(str(prev), quality=92)

    regions = _split_bands(img) if split_lines else [(0, 0, W, H)]
    blocks, seq = [], 0
    for i, (x0, y0, x1, y1) in enumerate(regions, 1):
        seq += 1
        bid = '%s_b%03d' % (tag, seq)
        crop = img.crop((x0, y0, x1, y1))
        if zoom and zoom > 1:
            crop = crop.resize((int(crop.width * zoom), int(crop.height * zoom)),
                               Image.LANCZOS)
        p = outdir / 'crops' / (bid + '.png')
        crop.convert('RGB').save(str(p), quality=95)
        blocks.append({
            'id': bid, 'type': 'image', 'bbox': [x0, y0, x1, y1],
            'text': '', 'crop': p, 'need_vision': True,
            'hint': '拍照件条带（按横向空白切分）。**按 bbox 的 y 顺序依次读**，'
                    '相邻条带常属同一道题，须连起来理解再识别。'
                    '逐块输出：公式→LaTeX；程序框图→节点表；表格→结构化表'})

    pages_out = [{'no': 1, 'size': [W, H], 'text_chars': 0, 'scanned': True,
                  'page_png': prev, 'blocks': blocks,
                  # 原图就是最高质量的识别源，不用再渲染
                  'ocr_src': Path(path) if quark_available() else None,
                  'vision_targets': [b['id'] for b in blocks]}]
    n_ocr = annotate_with_ocr(blocks)
    n_quark = annotate_pages_with_quark(pages_out)
    stats = {'pages': 1, 'formula_blocks': 0, 'diagram_blocks': 0,
             'image_blocks': len(blocks), 'scanned_pages': 1, 'split': split_lines,
             'ocr_blocks': n_ocr, 'quark_pages': n_quark,
             'written_blocks': sum(len((p.get('quark') or {}).get('written') or [])
                                   for p in pages_out)}
    return pages_out, stats


# ==================== docx（pandoc 提取，含 OMML 公式） ====================
#
# 为什么用 pandoc 而不是自己解 word/document.xml：
#   技能里记过一条老坑 ——「docx 题干是 OMML 公式，<w:t> 提取为空」。
#   第一版为此写了个自制 OMML 压平器，只能出 `(x+y)/(2)` 这种线性化垃圾。
#   pandoc 3.x 是 OMML ↔ LaTeX 的成熟双向实现，实测 \frac / \sqrt / 上标 /
#   cases / \triangle / ^{\circ} 全部原样还原成标准 LaTeX，零维护。
#   —— 阶段22 用户：「市场中有现成的工具就一定要使用」。


def _inlines_text(ils):
    """pandoc inline AST → 文本（公式保留 $...$ 形态）。"""
    out = []
    for il in ils or []:
        if not isinstance(il, dict):
            continue
        t, c = il.get('t'), il.get('c')
        if t == 'Str':
            out.append(c)
        elif t in ('Space', 'SoftBreak', 'LineBreak'):
            out.append(' ')
        elif t == 'Math':
            out.append('$' + c[1] + '$')          # c = [{"t":"InlineMath"}, latex]
        elif t == 'Code':
            out.append(c[1])
        elif t in ('Emph', 'Strong', 'Strikeout', 'Superscript', 'Subscript',
                   'SmallCaps', 'Quoted', 'Cite'):
            out.append(_inlines_text(c if isinstance(c, list) else []))
        elif t == 'Link':
            out.append(_inlines_text(c[1]))
        elif t == 'Image':
            out.append('[图]')
        elif t == 'RawInline':
            pass
    return ''.join(out)


def _blocks_text(blocks):
    """pandoc block 列表 → 纯文本。"""
    out = []
    for b in blocks or []:
        if not isinstance(b, dict):
            continue
        t, c = b.get('t'), b.get('c')
        if t in ('Para', 'Plain'):
            out.append(_inlines_text(c))
        elif t == 'Header':
            out.append(_inlines_text(c[2]))
        elif t == 'CodeBlock':
            out.append(c[1])
    return ' '.join(x for x in out if x).strip()


def _table_rows(table_c):
    """pandoc Table AST → 二维表（行 × 列）。

    ⚠️ 坑：pandoc 2.x 的 Table 子节点是 {"t":"TableHead","c":[...]}，
    3.x 改成**无标签裸数组** [attr, rows]。两种都要认，否则表格静默丢失
    （踩过一次：table_blocks 一直是 0，看着"摄取成功"其实整张表没进来）。
       Table.c = [attr, caption, colspecs, head, bodies, foot]
       head   = [attr, rows]
       body   = [attr, rowheadcols, rows, foot]
       row    = [attr, cells]
       cell   = [attr, align, rowspan, colspan, blocks]
    """

    def _rows_of(node):
        if isinstance(node, dict):
            c = node.get('c') or []
            return c[1] if len(c) >= 2 else []
        if isinstance(node, list) and len(node) >= 2:
            return node[1]
        return []

    def _cells(rows):
        out = []
        for r in rows or []:
            if isinstance(r, dict):
                cells = (r.get('c') or [None, []])[1]
            elif isinstance(r, list) and len(r) > 1:
                cells = r[1]
            else:
                continue
            line = []
            for cell in cells or []:
                if isinstance(cell, dict):
                    blk = (cell.get('c') or [None] * 5)[4]
                elif isinstance(cell, list) and len(cell) > 4:
                    blk = cell[4]
                else:
                    continue
                line.append(_blocks_text(blk))
            if line:
                out.append(line)
        return out

    rows = []
    try:
        rows.extend(_cells(_rows_of(table_c[3])))
    except (IndexError, TypeError):
        pass
    for body in (table_c[4] or []) if len(table_c) > 4 else []:
        bc = (body.get('c') or []) if isinstance(body, dict) else (
            body if isinstance(body, list) else [])
        # TableBody = [attr, rowheadcols, 中间行, 正文行] —— 正文在第 4 槽
        if len(bc) >= 4:
            rows.extend(_cells(bc[2]))
            rows.extend(_cells(bc[3]))
        elif len(bc) >= 3:
            rows.extend(_cells(bc[2]))
    return rows


def process_docx(path, outdir):
    try:
        import pypandoc
    except ImportError:
        raise SystemExit('需要 pypandoc：pip install pypandoc-binary'
                         '（用官方源 -i https://pypi.org/simple）')

    med = outdir / 'media'
    ast = json.loads(pypandoc.convert_file(
        str(path), 'json', extra_args=['--extract-media=%s' % med]))

    blocks, seq, n_formula, n_table = [], 0, 0, 0
    for b in ast.get('blocks', []):
        t = b.get('t')
        if t in ('Para', 'Plain', 'Header'):
            txt = (_inlines_text(b.get('c')) if t != 'Header'
                   else _inlines_text(b['c'][2]))
            txt = re.sub(r'\s{2,}', ' ', txt).strip()
            if not txt:
                continue
            seq += 1
            has_math = '$' in txt
            if has_math:
                n_formula += 1
            blocks.append({
                'id': 'docx_b%03d' % seq,
                'type': 'formula' if (has_math and len(txt) < 120) else
                        ('math_text' if has_math else 'text'),
                'bbox': [0, 0, 0, 0], 'text': txt[:4000], 'need_vision': False,
                'hint': ('公式已是标准 LaTeX，用 latex_math 转 MathML / OMML'
                         if has_math else '')})
        elif t == 'Table':
            rows = _table_rows(b.get('c'))
            if not rows:
                continue
            seq += 1
            n_table += 1
            md = '\n'.join('| ' + ' | '.join(c or '' for c in r) + ' |' for r in rows)
            blocks.append({'id': 'docx_b%03d' % seq, 'type': 'table',
                           'bbox': [0, 0, 0, 0], 'text': md[:4000], 'rows': rows,
                           'need_vision': False,
                           'hint': '已结构化表格；含公式的单元格注意 $...$ 是否完整'})

    # pandoc --extract-media 会把内嵌图导到 media/ 下
    for i, p in enumerate(sorted(med.rglob('*')), 1):
        if not p.is_file() or p.suffix.lower() not in (
                '.png', '.jpg', '.jpeg', '.gif', '.bmp', '.emf', '.wmf', '.tiff'):
            continue
        seq += 1
        blocks.append({'id': 'docx_b%03d' % seq, 'type': 'image',
                       'bbox': [0, 0, 0, 0], 'text': '', 'file': p,
                       'need_vision': True,
                       'hint': '文档内嵌图。含数学式→LaTeX；框图→节点表；表格→结构化表'})

    n_image = sum(1 for b in blocks if b['type'] == 'image')
    pages_out = [{'no': 1, 'size': [0, 0],
                  'text_chars': sum(len(b['text']) for b in blocks),
                  'scanned': False, 'page_png': None, 'blocks': blocks,
                  'vision_targets': [b['id'] for b in blocks if b.get('need_vision')]}]
    stats = {'pages': 1, 'formula_blocks': n_formula, 'diagram_blocks': 0,
             'image_blocks': n_image, 'table_blocks': n_table,
             'scanned_pages': 0, 'kind': 'docx', 'engine': 'pandoc',
             'ocr_blocks': 0, 'quark_pages': 0, 'written_blocks': 0}
    return pages_out, stats


# ==================== 主流程 ====================

HOWTO = [
    '1. 先读本 manifest，按 pages[].blocks[] 逐块处理，不要跳块。',
    '2. blocks[].need_vision == true 的块，必须用 Read 打开 crop / file 图像逐块识别；'
    '禁止拿 pages/ 整页图代替（分辨率不够，小字与细线必糊）。',
    '3. 公式块输出 LaTeX，交给 latex_math.latex_to_mathml / latex_to_omml 落到网页与 Word'
    '（底层是 latex2mathml + mathml2omml 两个成熟库，不要自己写解析器）。',
    '4. diagram 块先判类型（程序框图 / 几何图 / 统计图 / 电路图），'
    '再按类型转结构化描述，最后才画图；不许只写"见图"。',
    '5. table 块已由 PyMuPDF find_tables 结构化，仍需逐格核对数值与合并单元格。',
    '6. blocks[].open_ended == true 表示块末被换行截断（如「求 a 的最大」+「值；」），'
    '必须与相邻块连读，只读一块会漏半句。',
    '7. blocks[].text 已按字符坐标重排修复过乱序；raw_text 是修复前的乱序原文，'
    '只用于比对「重排有没有修歪」，不要拿来用。',
    '8. blocks[].ocr_text 是本地 OCR（RapidOCR）给的文字基准，ocr_conf 是置信度。'
    '⚠️ **RapidOCR 读不出手写**（实测把手写「重复赘余」读成「这冰上次增可」、手写的 C 直接丢），'
    '手写答案一律看 pages[].quark。',
    '9. pages[].quark.written 是夸克识别出的**手写答案**（type=WrittenText/WrittenFormula，'
    '实测置信度 1.00），批改直接用它；quark.formulas 是转好的 LaTeX。'
    '⚠️ quark.degraded=true 表示有公式降级成图片没转文本（formula_figures 处），'
    '这些位置必须回退视觉模型补。OCR 与看图不一致时以原图为准，两个结果都留档。',
    '10. 全部块处理完后自查：manifest.stats 里的 formula_blocks + diagram_blocks '
    '+ table_blocks 是否都出现在你的提取结果里；漏一块就算没读完。',
]


def main():
    ap = argparse.ArgumentParser(description='源材料分层摄取器')
    ap.add_argument('input')
    ap.add_argument('-o', '--out', default=None)
    ap.add_argument('--dpi', type=int, default=200)
    ap.add_argument('--zoom', type=float, default=2.5,
                    help='裁剪块相对 dpi 的放大倍数（矢量重绘，越大越清晰）')
    # 默认切题：整页图交给模型会被缩到 ~1500px，小公式指数必糊。
    # 要整页一块（比如单张插图）再加 --no-split-lines。
    ap.add_argument('--split-lines', dest='split_lines', action='store_true',
                    default=True, help='图片按横向空白带切块（默认开）')
    ap.add_argument('--no-split-lines', dest='split_lines', action='store_false',
                    help='不切块，整页当一个块')
    args = ap.parse_args()

    src = Path(args.input).expanduser()
    if not src.exists():
        raise SystemExit('文件不存在：%s' % src)

    outdir = Path(args.out) if args.out else (src.parent / (src.stem + '_ingest'))
    for sub in ('pages', 'crops', 'media'):
        (outdir / sub).mkdir(parents=True, exist_ok=True)

    suffix = src.suffix.lower()
    kind = {'.pdf': 'pdf', '.docx': 'docx', '.doc': 'doc'}.get(suffix, 'image')
    if kind == 'doc':
        raise SystemExit('老 .doc 请先另存为 .docx')

    if kind == 'pdf':
        pages, stats = process_pdf(src, outdir, args.dpi, args.zoom)
    elif kind == 'docx':
        pages, stats = process_docx(src, outdir)
    else:
        pages, stats = process_image(src, outdir, args.split_lines)

    # 相对路径，便于搬运
    for pg in pages:
        if pg.get('page_png'):
            pg['page_png'] = os.path.relpath(str(pg['page_png']), str(outdir)).replace('\\', '/')
        # ocr_src 指向「识别源」：可能是 outdir 里的渲染图，也可能是用户原始照片，
        # 跨目录很正常，统一留绝对路径字符串（也避免 WindowsPath 不能 JSON 序列化）
        if pg.get('ocr_src'):
            pg['ocr_src'] = str(pg['ocr_src'])
        for b in pg['blocks']:
            for k in ('crop', 'file'):
                if b.get(k):
                    b[k] = os.path.relpath(str(b[k]), str(outdir)).replace('\\', '/')

    manifest = {'source': str(src), 'kind': kind, 'engine': 'pymupdf %s' % pymupdf.__doc__.split()[0]
                if getattr(pymupdf, '__doc__') else 'pymupdf',
                'params': {'dpi': args.dpi, 'zoom': args.zoom},
                'stats': stats, 'howto': HOWTO, 'pages': pages}

    mp = outdir / 'manifest.json'
    mp.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')

    print('✅ 摄取完成：%s' % mp)
    print('   页数 %d | 公式块 %d | 框图块 %d | 表格 %d | 位图 %d | 扫描页 %d'
          % (stats['pages'], stats['formula_blocks'], stats['diagram_blocks'],
             stats.get('table_blocks', 0), stats['image_blocks'],
             stats['scanned_pages']))
    need = sum(len(p['vision_targets']) for p in pages)
    if need:
        print('   ⚠️ 有 %d 个块必须逐块视觉识别（见 manifest.pages[].vision_targets）' % need)
    n_ocr = stats.get('ocr_blocks', 0)
    if n_ocr:
        print('   ✅ 本地OCR已给出 %d 块文字基准（ocr_text / ocr_conf），'
              '与看图结果不一致时以原图为准' % n_ocr)
    elif need and local_ocr_python() is None:
        print('   ℹ️ 本地OCR未部署，纯靠视觉模型（要补基准就跑 '
              'skills/local-ocr/scripts/setup.py）')
    n_q = stats.get('quark_pages', 0)
    if n_q:
        print('   ✅ 夸克已识别 %d 页，手写块 %d 个 → 见 pages[].quark.written'
              % (n_q, stats.get('written_blocks', 0)))
        bad = [str(p['no']) for p in pages if (p.get('quark') or {}).get('degraded')]
        if bad:
            print('   ⚠️ 第 %s 页有公式降级成图片（FormulaFigure），'
                  '这些位置必须回退视觉模型补' % '/'.join(bad))
    elif need and not quark_available():
        print('   ℹ️ 夸克未配置，手写答案无法识别（配置 <CREDENTIALS_FILE>）')
    if stats['scanned_pages']:
        print('   ⚠️ 有 %d 页无文本层（扫描件/拍照），整页靠视觉识别' % stats['scanned_pages'])


if __name__ == '__main__':
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    main()
