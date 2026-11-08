#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""从 DSL 源生成「七天题目详解与答案」独立册子（.docx + .html）。

与作答纸严格分离：
  作答纸  = 只有题面 + 空白横线，不得含任何答案；
  答案册  = 题面 + 正确答案 + 完整详解，供家长/老师批改用。

用法：python make_answer_key.py [输出基名]
默认读 _p5/day1.txt ... day7.txt，产出 基名.docx / 基名.html
"""
import io, os, re, sys, html as H

import make_answer_docx as M   # 复用 OOXML 基础件

import dsl_source as D   # DSL 解析 + 版式参数（与作答纸共用同一套）
try:
    import answer_formula as _AF
except Exception:
    _AF = None
try:
    import math_format as _MF
except Exception:
    _MF = None

SRC_DIR = D.SRC_DIR
KIND_CN = D.KIND_CN
to_lines = D.to_lines
load_days = D.load_days



# ---------- docx：带底纹的段落 ----------
def shade_para(text, fill, bold=True, size=D.SZ_BODY, space_after=60, indent=0):
    """底纹段落。⚠️ 走 html_runs 以支持**真分数竖式**（阶段21）。

    直接用 M.run 会把 <span class='fr'> 当普通文本打印，或被剥成分数斜杠。
    """
    ppr = ('<w:pPr><w:shd w:val="clear" w:color="auto" w:fill="%s"/>'
           '<w:spacing w:before="0" w:after="%d" w:line="330" w:lineRule="auto"/>'
           % (fill, space_after))
    if indent:
        ppr += '<w:ind w:left="%d"/>' % indent
    ppr += '</w:pPr>'
    return '<w:p>%s%s</w:p>' % (ppr, M.html_runs(text, size=size, bold=bold))


def shade_lines(s, fill, size=D.SZ_BODY, indent=280):
    """多行文本，每行一段，带底纹。"""
    ls = to_lines(s)
    if not ls:
        return ''
    return ''.join(shade_para(x, fill, bold=(i == 0), size=size, indent=indent)
                   for i, x in enumerate(ls))


def build_docx(days, out):
    body = []
    total = sum(len(d["qs"]) for d in days)
    # 封面
    body.append(M.para('七天题目详解与答案', bold=True, size=D.SZ_TITLE, align='center', space_after=100))
    body.append(M.para('学生 · 三科考点 7 天攻坚 · 配套答案册',
                       size=D.SZ_BODY, align='center', space_after=200))
    body.append(M.para('共 %d 天 · %d 题（数学 %d / 语文 %d / 英语 %d）' % (
        len(days), total,
        sum(1 for d in days for q in d["qs"] if q["subj"] == "数学"),
        sum(1 for d in days for q in d["qs"] if q["subj"] == "语文"),
        sum(1 for d in days for q in d["qs"] if q["subj"] == "英语")),
        size=D.SZ_NOTE, align='center', space_after=240))
    body.append(M.rule())
    body.append(M.para('使用说明', bold=True, size=D.SZ_BODY, space_after=80))
    body.append(M.para('① 本册含全部题目的正确答案与完整详解，供家长或老师批改、讲解使用。',
                       size=D.SZ_NOTE, space_after=60))
    body.append(M.para('② 学生做题时只用《七天作答纸合集》，本册请先收起来，不要提前翻看。',
                       size=D.SZ_NOTE, space_after=60))
    body.append(M.para('③ 题号与网页讲义、作答纸完全一致（第 N 天 · 第 X 题），可逐题对照。',
                       size=D.SZ_NOTE, space_after=60))
    body.append(M.para('④ 语文简答题给的是「参考答案要点」，学生答出关键意思即可给分，不必逐字相同。',
                       size=D.SZ_NOTE, space_after=60))
    body.append(M.pagebreak())

    for k, d in enumerate(days):
        if k > 0:
            body.append(M.pagebreak())
        body.append(M.para('第 %d 天　%s' % (d["n"], d["title"]), bold=True, size=D.SZ_HEAD, space_after=60))
        body.append(M.para('本日共 %d 题 · 题号与网页讲义一致' % len(d["qs"]),
                           size=D.SZ_NOTE, space_after=140))
        nm = {'数学': 0, '语文': 0, '英语': 0}
        for q in d["qs"]:
            nm[q["subj"]] = nm.get(q["subj"], 0) + 1
        body.append(M.para('分项：数学 %d / 语文 %d / 英语 %d' % (nm['数学'], nm['语文'], nm['英语']),
                           size=D.SZ_NOTE, space_after=160))

        # 原理层（LOGIC）：docx 侧只取纯文本首段作提要，避免 HTML 标签混入
        for lg in d.get("logics", []):
            head = re.sub(r"<[^>]+>", " ", lg).split("⚑")[0]
            head = re.sub(r"\s+", " ", head).strip()
            if head:
                body.append(M.para('🧠 原理回顾：' + head[:120],
                                   bold=True, size=D.SZ_NOTE, space_after=140))

        for q in d["qs"]:
            # 题头：题型与语病类型必须带上（批改时靠它判断孩子有没有归对类）
            head = '第 %d 题（%s · %s · 题型：%s）' % (
                q["no"], q["subj"], KIND_CN[q["kind"]], q.get("qtype", "—"))
            body.append(M.para_c(head, bold=True, size=D.SZ_QNO,
                                 color=M.C_HEAD, shd=M.F_BOX, space_after=40))
            if q.get("bingju"):
                body.append(M.para_c('语病 7 型速查卡：%s' % "｜".join(q["bingju"]),
                                     bold=True, size=16, color=M.C_HINT,
                                     shd="FEF3C7", space_after=40, line=250))
            # G15 答题公式卡：判分时按这几格逐格对，缺格扣分
            if q["kind"] == "JUDGE" and q.get("qtype"):
                afk = _AF.card_text(q["qtype"]) if _AF else ""
                if afk:
                    body.append(M.para_c('判分依据 · 答题公式：%s'
                                         % _AF.ALL_FORMULA[q["qtype"]]["formula"],
                                         bold=True, size=17, color="FFFFFF",
                                         shd=M.C_AFH, space_after=0, line=250))
                    for ln2 in afk.split("\n")[1:]:
                        body.append(M.para_c(ln2.strip(), size=16,
                                             color=M.C_AFV, shd="FFFFFF",
                                             space_after=0, line=250))
            # 题干（走 html_runs 支持真分数竖式）
            for ln in to_lines(q["stem"]):
                body.append('<w:p>%s</w:p>' % M.html_runs(ln, size=D.SZ_BODY))
                body.append(M.para('', size=2, space_after=20))
            # 选项（仅选择题，标出正确项）
            if q["opts"]:
                for i, o in enumerate(q["opts"]):
                    mark = ' ✔' if i == q["idx"] else ''
                    # ⚠️ 必须走 html_runs（OMML）：选项里常有 `3n² + 3n + 1`
                    # 这类指数，走纯文本 para 会留下裸 Unicode 上标（实测 3 处）
                    body.append(
                        '<w:p><w:pPr><w:ind w:left="280"/>'
                        '<w:spacing w:before="0" w:after="25" w:line="300" w:lineRule="auto"/>'
                        '</w:pPr>%s</w:p>'
                        % M.html_runs('%s．%s%s' % ("ABCD"[i],
                                      to_lines(o)[0] if to_lines(o) else o, mark),
                                      size=D.SZ_NOTE))
                body.append(M.para('', size=8, space_after=0))
            # 答案
            ls = to_lines(q["ans_plain"]) or to_lines(q["ans"])
            first = ('【答案】' + (ls[0] if ls else '')) if q["kind"] != "JUDGE" else '【参考答案要点】'
            body.append(shade_para(first, 'D1FAE5', bold=True, size=D.SZ_BODY, indent=0))
            for x in (ls[1:] if q["kind"] != "JUDGE" else ls):
                body.append(shade_para(x, 'D1FAE5', bold=False, size=D.SZ_NOTE, indent=280))
            # 思路
            if q["hint"]:
                hl = to_lines(q["hint"])
                body.append(shade_para('【思路】' + hl[0], 'EFF6FF', bold=True, size=D.SZ_NOTE))
                for x in hl[1:]:
                    body.append(shade_para(x, 'EFF6FF', bold=False, size=D.SZ_NOTE, indent=280))
            # 详解
            sl = to_lines(q["sol"])
            body.append(shade_para('【详解】' + sl[0], 'FEF3C7', bold=True, size=D.SZ_NOTE))
            for x in sl[1:]:
                body.append(shade_para(x, 'FEF3C7', bold=False, size=D.SZ_NOTE, indent=280))
            # G11 逐句语病定性的**标准答案**：孩子纸面上那两栏就照这里判
            if q.get("bjtab"):
                body.append(M.para_c('【逐句定性 · 标准答案】（纸面「语病类型」「改正」两栏按此判分）',
                                     bold=True, size=18, color="FFFFFF", shd=M.C_HEAD,
                                     space_after=0, line=250))
                body.append(M.para_c('句　这句话　｜　标准病名　｜　标准改法',
                                     bold=True, size=16, color=M.C_HEAD,
                                     shd=M.F_HEAD, space_after=0, line=240))
                for r in q["bjtab"]:
                    ppr = ('<w:pPr><w:shd w:val="clear" w:color="auto" w:fill="%s"/>'
                           '<w:spacing w:before="0" w:after="0" w:line="250" w:lineRule="auto"/>'
                           '<w:ind w:left="60"/></w:pPr>' % M.F_BOX)
                    body.append('<w:p>%s%s</w:p>' % (ppr,
                        M.run(r["no"] + '　', bold=True, size=17, color=M.C_TYP)
                        + M.run(re.sub(r"<[^>]+>", "", r["sent"]) + '　｜　',
                                size=17, color=M.C_SIG)
                        + M.run(r["typ"], bold=True, size=17, color=M.C_TIP)
                        + M.run('　｜　', size=17, color=M.C_SIG)
                        + M.run(r["fix"], size=17, color=M.C_FIX)))
                body.append(M.para('', size=8, space_after=0))
            body.append(M.para('', size=10, space_after=90))

        body.append(M.para('— 第 %d 天答案结束 · 共 %d 题 —' % (d["n"], len(d["qs"])),
                           size=D.SZ_NOTE, align='center', space_after=60))

    # —— 《批改记录》对账单：从作答纸搬到**答案册末尾**（阶段21 用户要求）——
    # 它是老师填的、不是孩子的卷面；但它是错题库回写的对账单，闭环不能断。
    body.append(M.pagebreak())
    body.append(M.para('批 改 记 录（老师批改后填写 · 拍照/扫描件即批改依据）',
                       bold=True, size=D.SZ_BODY, space_after=70))
    body.append(M.para('天次　　得分　　错题号（写“第几题”）　　　　主要问题（一句话）',
                       size=D.SZ_NOTE, space_after=40))
    for _d in days:
        body.append(M.para('第%d天　______　______________________　______________________________'
                           % _d["n"], size=D.SZ_BODY, space_after=60, line=300))
    body.append(M.para('★ 录入：批改结果按“天次 → 题号 → 错因 → 知识点”写回错题库，'
                       '并生成下一次复习任务。', size=D.SZ_NOTE, space_after=0))

    doc = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
           '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
           'xmlns:m="http://schemas.openxmlformats.org/officeDocument/2006/math">'
           '<w:body>' + ''.join(body) + M.SECT + '</w:body></w:document>')

    ct = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
          '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
          '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
          '<Default Extension="xml" ContentType="application/xml"/>'
          '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
          '<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>'
          '</Types>')
    rels = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
            '</Relationships>')
    import zipfile
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", ct)
        z.writestr("_rels/.rels", rels)
        z.writestr("word/document.xml", doc)
        z.writestr("word/styles.xml", M.STYLES_XML)
        z.writestr("word/_rels/document.xml.rels", M.DOC_RELS)
    print("生成 %s　天数 %d　题目 %d　%.1f KB" % (out, len(days), total, len(doc) / 1024))
    return total


# ---------- HTML（可预览、可打印） ----------
CSS = """
*{box-sizing:border-box}
body{margin:0;background:#f1f5f9;color:#152033;
 font-family:"PingFang SC","Microsoft YaHei","Noto Sans CJK SC","Times New Roman",serif;font-size:15px;line-height:1.85;
 font-feature-settings:"liga" 1,"kern" 1}
.wrap{max-width:900px;margin:0 auto;background:#fff;padding:34px 40px 60px}
h1{font-size:27px;margin:0 0 6px;letter-spacing:1px}
.sub{color:#64748b;font-size:14px;margin-bottom:18px}
.cover{border:1px solid #e2e8f0;border-radius:12px;padding:22px 26px;background:#f8fafc;margin-bottom:26px}
.cover ol{margin:8px 0 0;padding-left:22px}
.cover li{margin:5px 0}
.warn{background:#fffbeb;border:1px solid #fcd34d;border-radius:8px;padding:10px 14px;
 margin-bottom:22px;font-size:13.5px;color:#92400e}
.daysec{margin-top:34px;page-break-before:always}
.dhead{border-left:5px solid #4338ca;background:#eef2ff;padding:12px 18px;border-radius:0 10px 10px 0;margin-bottom:6px}
.dnum{font-size:20px;font-weight:800;color:#3730a3}
.dttl{font-size:14px;color:#4b5563}
.dmeta{font-size:12.5px;color:#94a3b8;margin:0 0 16px 2px}
.logic{border:1px solid #ddd6fe;border-left:5px solid #6d28d9;background:#faf5ff;
 border-radius:10px;padding:14px 18px;margin:0 0 18px;font-size:14.5px;line-height:1.9;color:#3b0764}
.logic .lbadge{display:inline-block;font-size:11px;font-weight:800;letter-spacing:.08em;
 background:#ede9fe;border:1px solid #c4b5fd;border-radius:20px;padding:1px 10px;margin-bottom:8px;color:#5b21b6}
.logic .lhead{font-size:16px;font-weight:800;color:#4c1d95;margin-bottom:8px;line-height:1.6}
.logic .lrow{margin-bottom:6px}
.logic .lk{display:inline-block;min-width:70px;font-weight:800;color:#b45309;margin-right:6px}
.logic .lexit{background:#fffbeb;border-left:3px solid #f59e0b;border-radius:7px;padding:8px 12px;margin-top:9px}
.logic em{font-style:normal;color:#7c3aed;font-size:12.5px}
@media print{.logic{page-break-inside:avoid}}

/* 数学书写规范卡（阶段21 用户要求：正式印刷的书写规范） */
.mfcardbox{margin:6px 0 4px;border:1px solid #a5b4fc;border-radius:10px;overflow:hidden}
.mfcardlab{padding:5px 11px;font-size:12.5px;font-weight:800;color:#fff;
  background:linear-gradient(135deg,#3730a3,#4338ca)}
.mfcardlab span{display:block;font-size:11px;font-weight:500;opacity:.92;margin-top:2px}
.mfcard{width:100%;border-collapse:collapse;font-size:12px}
.mfcard th{background:#e0e7ff;color:#312e81;font-size:11px;text-align:left;
  padding:4px 7px;border-bottom:1px solid #c7d2fe}
.mfcard td{padding:4px 7px;border-bottom:1px solid #e0e7ff;background:#fff;line-height:1.6}
.mfcard td.n{width:20%;font-weight:800;color:#3730a3}
.mfcard td.r{width:44%;color:#1f2937}
.mfcard td.b{color:#92400e;background:#fffbeb}
.mfmust{margin:6px 0 4px;border:1px solid #93c5fd;border-radius:9px;
  background:#eff6ff;line-height:1.7}
.mfmust .mh{padding:5px 11px;font-size:12px;font-weight:800;color:#fff;background:#1d4ed8}
.mfmust ol{margin:6px 0 4px;padding-left:26px;font-size:12px;color:#1f2937}
.mfmust li{margin-bottom:2px}
.mfmust .mtr{padding:5px 11px;font-size:11.5px;color:#92400e;background:#fffbeb;
  border-top:1px dashed #fcd34d}
@media print{.mfcardbox,.mfmust{break-inside:avoid;page-break-inside:avoid}}

/* G15 答题公式卡（答案册侧 = 判分依据） */
.afcard{border:1px solid #a5b4fc;border-radius:11px;overflow:hidden;
 background:#f5f7ff;line-height:1.75;margin:0 0 12px}
.afcard .afh{padding:7px 13px;font-size:13px;font-weight:800;color:#fff;
 background:linear-gradient(135deg,#4338ca,#6d28d9)}
.afcard .aff{padding:9px 13px 7px;font-size:14.5px;font-weight:800;color:#312e81;background:#eef2ff}
.afcard .aft{width:100%;border-collapse:collapse;font-size:12.5px;background:#fff}
.afcard .aft td{padding:5px 9px;border-bottom:1px solid #e0e7ff;vertical-align:top}
.afcard .aft td.k{width:88px;font-weight:800;color:#4338ca;white-space:nowrap}
.afcard .aft td.v{color:#1f2937}
.afcard .afs{padding:8px 13px;font-size:12.5px;color:#312e81;background:#f5f3ff;
 border-top:1px dashed #c7d2fe}
.afcard .aftip{padding:7px 13px;font-size:12.5px;color:#92400e;background:#fffbeb;
 border-top:1px dashed #fcd34d}
@media print{.afcard{page-break-inside:avoid}}

/* 真分数竖式（阶段21 用户要求：不能写成斜杠 3/2，必须竖式） */
.fr{display:inline-flex;flex-direction:column;vertical-align:middle;
  text-align:center;line-height:1.05;margin:0 2px;position:relative;
  padding:0 2px;font-size:.92em;vertical-align:-0.55em}
.fr .nu{padding:0 3px 1px;border-bottom:1.4px solid currentColor;line-height:1.1}
.fr .de{padding:1px 3px 0;line-height:1.1}

.qcard{border:1px solid #e5e7eb;border-radius:10px;padding:16px 18px;margin-bottom:16px;background:#fff}
.qh{display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin-bottom:8px}
.qno{background:#4338ca;color:#fff;font-size:12.5px;font-weight:700;padding:2px 10px;border-radius:20px}
.tag{font-size:11.5px;padding:2px 9px;border-radius:20px;border:1px solid #cbd5e1;color:#475569;background:#f8fafc}
.tag.m{background:#eff6ff;border-color:#bfdbfe;color:#1d4ed8}
.tag.c{background:#fdf2f8;border-color:#fbcfe8;color:#be185d}
.tag.e{background:#ecfdf5;border-color:#a7f3d0;color:#047857}
.tag.qt3{background:#eef2ff;border-color:#c7d2fe;color:#3730a3;font-weight:700}
.tag.bq3{background:#fff7ed;border-color:#fdba74;color:#9a3412;font-weight:700}
/* G11 逐句语病定性标准答案 */
.bjsolt{margin:10px 0 6px;border:1px solid #fdba74;border-radius:8px;overflow:hidden;}
.bjsolt .h{background:#7c2d12;color:#fff;font-size:12px;font-weight:700;padding:6px 11px;}
.bjsol table{width:100%;border-collapse:collapse;font-size:12.5px;}
.bjsol th{background:#fff7ed;color:#7c2d12;font-size:11.5px;text-align:left;padding:5px 8px;
  border-bottom:1px solid #fdba74;}
.bjsol td{padding:6px 8px;border-bottom:1px solid #fde68a;vertical-align:top;line-height:1.7;}
.bjsol .n{width:32px;text-align:center;font-weight:800;color:#c2410c;}
.bjsol .s{width:38%;color:#1f2937;}
.bjsol .t,.bjsol .f{width:31%;color:#7c2d12;}
.stem{font-size:15px;margin-bottom:10px}
.opts{margin:6px 0 12px;padding-left:4px}
.opt{display:block;font-size:14px;color:#334155;padding:3px 0}
.opt.ok{color:#047857;font-weight:700}
.opt.ok::after{content:" ✔";color:#059669}
.box{border-radius:8px;padding:10px 14px;margin:8px 0;font-size:14px}
.box .bl{font-weight:800;margin-bottom:4px;display:block}
.b-ans{background:#ecfdf5;border:1px solid #6ee7b7}
.b-ans .bl{color:#047857}
.b-hint{background:#eff6ff;border:1px solid #93c5fd}
.b-hint .bl{color:#1d4ed8}
.b-sol{background:#fffbeb;border:1px solid #fcd34d}
.b-sol .bl{color:#b45309}
.dend{text-align:center;color:#94a3b8;font-size:12.5px;margin:18px 0 4px}
.foot{margin-top:34px;padding-top:14px;border-top:1px dashed #cbd5e1;color:#94a3b8;font-size:12.5px;text-align:center}
@media print{
 body{background:#fff}
 .wrap{max-width:none;padding:0}
 .daysec{page-break-before:always}
 .qcard{page-break-inside:avoid}
 .noprint{display:none}
}
"""

BTN = """
<div class="noprint" style="position:sticky;top:0;z-index:9;background:#fff;border-bottom:1px solid #e5e7eb;
 padding:10px 0;margin-bottom:18px;display:flex;gap:10px;align-items:center">
  <button onclick="window.print()" style="padding:7px 16px;border-radius:8px;border:1px solid #4338ca;
   background:#4338ca;color:#fff;font-size:13.5px;cursor:pointer">🖨 打印 / 存为 PDF</button>
  <span style="font-size:12.5px;color:#94a3b8">本页含答案与详解，学生做题前请先收起</span>
</div>
"""


def build_html(days, out):
    total = sum(len(d["qs"]) for d in days)
    cnt = {'数学': 0, '语文': 0, '英语': 0}
    for d in days:
        for q in d["qs"]:
            cnt[q["subj"]] = cnt.get(q["subj"], 0) + 1
    P = []
    P.append('<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">')
    P.append('<meta name="viewport" content="width=device-width,initial-scale=1">')
    P.append('<title>七天题目详解与答案 · 学生</title>')
    P.append('<style>%s</style></head><body><div class="wrap">' % CSS)
    P.append(BTN)
    P.append('<h1>七天题目详解与答案</h1>')
    P.append('<div class="sub">学生 · 三科考点 7 天攻坚 · 配套答案册　|　共 %d 天 %d 题（数学 %d / 语文 %d / 英语 %d）</div>'
             % (len(days), total, cnt['数学'], cnt['语文'], cnt['英语']))
    P.append('<div class="cover"><b>使用说明</b><ol>'
             '<li>本册含全部题目的<b>正确答案</b>与<b>完整详解</b>，供家长或老师批改、讲解使用。</li>'
             '<li>学生做题时只用《七天作答纸合集》，本册请先收起来，不要提前翻看。</li>'
             '<li>题号与网页讲义、作答纸完全一致（第 N 天 · 第 X 题），可逐题对照。</li>'
             '<li>语文简答题给的是「参考答案要点」，答出关键意思即可给分，不必逐字相同。</li>'
             '</ol></div>')
    # ⚠️ 阶段22 修正：原写「选择题已不在作答纸上出现」，与铁律 7 矛盾
    #（全部题目必须进纸，选择题留 ○ 涂黑）。这句是过时文案，会让孩子以为
    # 选择题不用做、答案册里才有 —— 实际作答纸上 5 道选择题都在。
    P.append('<div class="warn">⚠ 作答纸上<b>每一道题都在</b>（含选择题，选题请在 ○ 里涂黑）；'
             '本册的答案与详解用于做完之后自查，不要提前看。</div>')

    for d in days:
        nm = {'数学': 0, '语文': 0, '英语': 0}
        for q in d["qs"]:
            nm[q["subj"]] = nm.get(q["subj"], 0) + 1
        P.append('<div class="daysec">')
        P.append('<div class="dhead"><div class="dnum">第 %d 天</div><div class="dttl">%s</div></div>'
                 % (d["n"], d["title"]))
        P.append('<div class="dmeta">本日共 %d 题 · 数学 %d / 语文 %d / 英语 %d · 题号与网页讲义一致</div>'
                 % (len(d["qs"]), nm['数学'], nm['语文'], nm['英语']))
        for lg in d.get("logics", []):
            P.append('<div class="logic">%s</div>' % lg)
        for q in d["qs"]:
            cls = {'数学': 'm', '语文': 'c', '英语': 'e'}.get(q["subj"], '')
            P.append('<div class="qcard">')
            P.append('<div class="qh"><span class="qno">第 %d 题</span>'
                     '<span class="tag %s">%s</span><span class="tag">%s</span>'
                     '<span class="tag qt3">题型：%s</span>%s</div>'
                     % (q["no"], cls, q["subj"], KIND_CN[q["kind"]],
                        q.get("qtype", "—"),
                        ('<span class="tag bq3">语病：%s</span>' % "｜".join(q["bingju"]))
                        if q.get("bingju") else ""))
            P.append('<div class="stem">%s</div>' % q["stem"])
            # G15 答题公式卡（答案册版带 tips，作为判分依据）
            if q["kind"] == "JUDGE" and q.get("qtype") and _AF and _AF.get(q["qtype"]):
                P.append(_AF.card_html(q["qtype"], kind="key"))
            if q["opts"]:
                P.append('<div class="opts">')
                for i, o in enumerate(q["opts"]):
                    P.append('<span class="opt%s">%s．%s</span>'
                             % (' ok' if i == q["idx"] else '', "ABCD"[i], o))
                P.append('</div>')
            lab = '💡 思路' if q["kind"] != "JUDGE" else '💡 思路'
            anslab = '✔ 正确答案' if q["kind"] != "JUDGE" else '✔ 参考答案要点'
            # ⚠️ 清洗 markdown 星号（阶段21）：DSL 里手写 **加粗** 会原样印出。
            # 真分数竖式标记 <span class="fr"> 不含星号，不受影响。
            _md = lambda x: re.sub(r"\*\*(.+?)\*\*", lambda m: m.group(1), x)
            P.append('<div class="box b-ans"><span class="bl">%s</span>%s</div>'
                     % (anslab, _md(q["ans"])))
            if q["hint"]:
                P.append('<div class="box b-hint"><span class="bl">%s</span>%s</div>'
                         % (lab, _md(q["hint"])))
            P.append('<div class="box b-sol"><span class="bl">📖 完整详解</span>%s</div>'
                     % _md(q["sol"]))
            # G11 逐句语病定性的标准答案（判分依据）
            if q.get("bjtab"):
                P.append('<div class="bjsolt"><div class="h">✍ 逐句定性 · 标准答案'
                         '（作答纸「语病类型」「改正」两栏按此判分）</div><table><thead><tr>'
                         '<th>句</th><th>这句话</th><th>语病类型</th><th>改正</th></tr></thead><tbody>'
                         + "".join('<tr><td class="n">%s</td><td class="s">%s</td>'
                                   '<td class="t"><b>%s</b></td><td class="f">%s</td></tr>'
                                   % (r["no"], re.sub(r"<[^>]+>", "", r["sent"]), r["typ"], r["fix"])
                                   for r in q["bjtab"])
                         + '</tbody></table></div>')
            P.append('</div>')
        P.append('<div class="dend">— 第 %d 天答案结束 · 共 %d 题 —</div>' % (d["n"], len(d["qs"])))
        P.append('</div>')

    # —— 《批改记录》对账单：搬到答案册末尾（从作答纸移来）——
    P.append('<div class="pb"></div><div class="sheet">')
    P.append('<div class="rec"><span class="rh">批 改 记 录（老师批改后填写 · 拍照/扫描件即批改依据）</span>'
             '天次　　得分　　错题号（写“第几题”）　　　　主要问题（一句话）</div>')
    for _d in days:
        P.append('<div class="rec">第%d天　______　______________________　'
                 '______________________________</div>' % _d["n"])
    P.append('<div class="note">★ 录入：批改结果按“天次 → 题号 → 错因 → 知识点”写回错题库，并生成下一次复习任务。</div>')
    P.append('</div>')

    P.append('<div class="foot">学生 · 七天题目详解与答案 · 与《七天作答纸合集》配套使用</div>')
    P.append('</div></body></html>')
    _html = "\n".join(P)
    # ══ 数学排版升级（阶段21）：CSS 分数 → MathML 真公式 ══
    try:
        import mathml_render as _ML
        _html = _ML.upgrade(_html)
    except Exception:
        pass
    # ⚠️ markdown 星号残留清洗（阶段21 实测踩坑）：
    # DSL 里手写 `**加粗**` 会原样印到答案册上，教辅不该有星号。
    # 这里只清 DSL 正文里的星号，不动 CSS。
    _body_start = _html.find("<body")
    if _body_start > 0:
        _head, _bd = _html[:_body_start], _html[_body_start:]
        _bd = re.sub(r"\*\*(.+?)\*\*", r"\1", _bd)
        _html = _head + _bd
    io.open(out, "w", encoding="utf-8").write(_html)
    print("生成 %s　天数 %d　题目 %d　%.1f KB" % (out, len(days), total, len(_html) / 1024))


def main():
    # 用法：[--day N] [输出基名]；不给 --day 就出全部 7 天
    argv = sys.argv[1:]
    only_day = None
    if "--day" in argv:
        i = argv.index("--day")
        only_day = int(argv[i + 1]); del argv[i:i + 2]
    base = argv[0] if argv else "学生_七天题目详解与答案"
    days = load_days()
    if only_day:
        days = [d for d in days if d["n"] == only_day]
        if not days:
            print("未找到第 %d 天" % only_day); return 1
    if not days:
        print("未找到 DSL 源：%s/day*.txt" % SRC_DIR)
        return 1
    build_docx(days, base + ".docx")
    build_html(days, base + ".html")
    # 控制台核对清单
    for d in days:
        kinds = {}
        for q in d["qs"]:
            kinds[q["kind"]] = kinds.get(q["kind"], 0) + 1
        print("  第%d天 %2d题  " % (d["n"], len(d["qs"]))
              + " ".join("%s%d" % (KIND_CN[k], v) for k, v in sorted(kinds.items())))
    return 0


if __name__ == "__main__":
    sys.exit(main())
