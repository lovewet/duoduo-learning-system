# -*- coding: utf-8 -*-
"""把教案 markdown 转成 Word 打印版（阶段22 用户：详细的教案给我一个 word 打印版）。

要求：
- A4、边距适中，能直接打印
- 标题分级清楚，表格保留
- 中文字体宋体、西文 Times New Roman（用户字体铁律）
- 加页码
"""
import io
import os
import re

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

SRC = r"<WORKSPACE>\07_技能与脚本\build_workspace\_jiaoan_src.md"
OUT = r"<WORKSPACE>\\04_口头教案//jiaoan_math_weekend.docx"

CN, EN = "宋体", "Times New Roman"


def set_font(run, size, bold=False, color=None):
    run.font.size = Pt(size)
    run.font.bold = bold
    run.font.name = EN
    r = run._element.rPr.rFonts
    r.set(qn("w:eastAsia"), CN)
    r.set(qn("w:ascii"), EN)
    r.set(qn("w:hAnsi"), EN)
    if color:
        run.font.color.rgb = RGBColor(*color)


def shade(cell_or_par, hexcolor):
    el = OxmlElement("w:shd")
    el.set(qn("w:val"), "clear")
    el.set(qn("w:fill"), hexcolor)
    if hasattr(cell_or_par, "_tc"):
        cell_or_par._tc.get_or_add_tcPr().append(el)
    else:
        cell_or_par.paragraph_format.element.get_or_add_pPr().append(el)


def add_page_number(doc):
    footer = doc.sections[0].footer
    p = footer.paragraphs[0]
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = p.add_run()
    fld = OxmlElement("w:fldSimple")
    fld.set(qn("w:instr"), "PAGE")
    run._r.addnext(fld)


doc = Document()
sec = doc.sections[0]
sec.page_height, sec.page_width = Cm(29.7), Cm(21.0)
sec.top_margin = sec.bottom_margin = Cm(2.2)
sec.left_margin = sec.right_margin = Cm(2.0)

style = doc.styles["Normal"]
style.font.name = EN
style.font.size = Pt(11)
style.element.rPr.rFonts.set(qn("w:eastAsia"), CN)

lines = io.open(SRC, encoding="utf-8").read().split("\n")
i = 0
n_h1 = 0
while i < len(lines):
    ln = lines[i].rstrip()
    s = ln.strip()

    if not s or set(s) <= {"-"} and len(s) >= 3:
        i += 1
        continue

    # ── 标题 ──
    if s.startswith("# "):
        n_h1 += 1
        p = doc.add_paragraph()
        p.paragraph_format.space_before = Pt(0 if n_h1 == 1 else 18)
        p.paragraph_format.space_after = Pt(10)
        set_font(p.add_run(s[2:].strip()), 18 if n_h1 == 1 else 15, bold=True,
                 color=(0x1A, 0x1A, 0x1A))
        i += 1
        continue
    if s.startswith("## "):
        p = doc.add_paragraph()
        p.paragraph_format.space_before = Pt(14)
        p.paragraph_format.space_after = Pt(6)
        set_font(p.add_run(s[3:].strip()), 13.5, bold=True, color=(0x1A, 0x3A, 0x6B))
        i += 1
        continue
    if s.startswith("### "):
        p = doc.add_paragraph()
        p.paragraph_format.space_before = Pt(9)
        p.paragraph_format.space_after = Pt(4)
        set_font(p.add_run(s[4:].strip()), 12, bold=True, color=(0x33, 0x33, 0x33))
        i += 1
        continue

    # ── 表格 ──
    if s.startswith("|") and i + 1 < len(lines) and re.match(r"^\|[\s:|-]+\|$", lines[i + 1].strip()):
        rows = []
        while i < len(lines) and lines[i].strip().startswith("|"):
            raw = lines[i].strip()
            if not re.match(r"^\|[\s:|-]+\|$", raw):
                rows.append([c.strip() for c in raw.strip("|").split("|")])
            i += 1
        cols = max(len(r) for r in rows)
        t = doc.add_table(rows=len(rows), cols=cols)
        t.style = "Table Grid"
        t.alignment = WD_TABLE_ALIGNMENT.CENTER
        for ri, row in enumerate(rows):
            for ci in range(cols):
                cell = t.cell(ri, ci)
                txt = row[ci] if ci < len(row) else ""
                txt = re.sub(r"\*\*(.+?)\*\*", r"\1", txt)
                cell.text = ""
                p = cell.paragraphs[0]
                p.paragraph_format.space_before = Pt(2)
                p.paragraph_format.space_after = Pt(2)
                set_font(p.add_run(txt), 9.5, bold=(ri == 0))
                if ri == 0:
                    shade(cell, "E8EEF7")
        doc.add_paragraph().paragraph_format.space_after = Pt(2)
        continue

    # ── 引用块（口诀/点破那几句）──
    if s.startswith(">"):
        p = doc.add_paragraph()
        p.paragraph_format.left_indent = Cm(0.6)
        p.paragraph_format.space_before = Pt(4)
        p.paragraph_format.space_after = Pt(6)
        shade(p, "F4F1EA")
        body = s.lstrip("> ").strip()
        parts = re.split(r"(\*\*.+?\*\*)", body)
        for seg in parts:
            if not seg:
                continue
            if seg.startswith("**") and seg.endswith("**"):
                set_font(p.add_run(seg[2:-2]), 11.5, bold=True, color=(0x7A, 0x3E, 0x00))
            else:
                set_font(p.add_run(seg), 11, color=(0x33, 0x33, 0x33))
        i += 1
        continue

    # ── 列表 ──
    m = re.match(r"^(\s*)[-·]\s+(.*)$", ln)
    if m:
        p = doc.add_paragraph(style="List Bullet")
        p.paragraph_format.space_before = Pt(2)
        p.paragraph_format.space_after = Pt(2)
        indent = len(m.group(1)) // 2
        p.paragraph_format.left_indent = Cm(0.7 + indent * 0.6)
        body = m.group(2)
        for seg in re.split(r"(\*\*.+?\*\*)", body):
            if not seg:
                continue
            if seg.startswith("**") and seg.endswith("**"):
                set_font(p.add_run(seg[2:-2]), 11, bold=True)
            else:
                set_font(p.add_run(seg), 11)
        i += 1
        continue

    # ── 普通段落 ──
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(2)
    p.paragraph_format.space_after = Pt(4)
    p.paragraph_format.line_spacing = 1.45
    for seg in re.split(r"(\*\*.+?\*\*)", s):
        if not seg:
            continue
        if seg.startswith("**") and seg.endswith("**"):
            set_font(p.add_run(seg[2:-2]), 11, bold=True)
        else:
            set_font(p.add_run(seg), 11)
    i += 1

add_page_number(doc)
doc.save(OUT)
print("✓ Word 版已生成：", OUT)
print("  大小 %.1f KB" % (os.path.getsize(OUT) / 1024))
print("  段落数 %d、表格数 %d" % (len(doc.paragraphs), len(doc.tables)))
