#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""病句 7 型速查卡（例句对照版）→ .docx

【定位】阶段26 用户：「我只要病句类型的名字，然后举例说明 供学生答题时参考」
→ 这不是练习卷，是**参考卡**：7 型全列 + 每型错例（病名 + 改法）+ 正确句对照。
   因为是参考卡不是学生卷，所以**答案内嵌**（病名与改法就在卡上），不另出答案册。

【唯一真源】类型顺序 / 识别信号 / 怎么改  → bingju_card.py（不许另写一份）
            答题公式卡（主观题必挂）      → answer_formula.py
【版式】手写 OOXML，零第三方依赖
   · 中文字体 宋体（eastAsia），西文 Times New Roman + kern=2（用户字体铁律）
   · 彩色打印版（用户明确「打印版 docx 必须彩色」），色板与网页 CSS 同色系
   · 错句中的病处用红色加粗标出（**...** 标记）
"""
import os
import re
import sys
import zipfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import bingju_card as BJC      # 语病 7 型唯一真源
import answer_formula as AF    # 答题公式卡唯一真源

# ────────────────────────── 字体（用户字体铁律）──────────────────────────
F_EA = "宋体"                 # 中文
F_ASCII = "Times New Roman"   # 西文印刷体（宋体的西文是等宽衬线体，b/6、l/I 易混）
F_RPR = ('<w:rFonts w:ascii="%s" w:eastAsia="%s" w:hAnsi="%s" w:cs="%s"/>'
         '<w:kern w:val="2"/>' % (F_ASCII, F_EA, F_ASCII, F_ASCII))

# ────────────────────────── 色板（与网页 CSS 同色系）──────────────────────
C_TITLE = "7C2D12"   # 主标题 深棕
C_TYPE = "C2410C"    # 类型名 橙
C_SIG = "1F2937"     # 正文 深灰
C_FIX = "92400E"     # 改法 棕
C_HINT = "B45309"    # 提示 琥珀
C_TIP = "15803D"     # 提示绿
C_BAD = "B91C1C"     # 病处 ��红
C_AFH = "4338CA"     # 公式卡标题条 靛蓝
C_AFF = "312E81"     # 公式骨架 深靛
C_AFK = "4338CA"
C_AFV = "1F2937"
C_HEADT = "FFFFFF"   # 表头字 白
F_HEAD = "FDE68A"    # 表头底纹 浅黄
F_BOX = "FFF7ED"     # 卡片底纹 浅橙
F_TIP = "ECFDF5"     # 绿底
F_AFF = "EEF2FF"     # 公式卡底纹 浅靛
F_AFS = "F5F3FF"     # 范例底纹 浅紫
F_AFT = "FFFBEB"     # tips 底纹 浅琥珀
F_OK = "F0FDF4"      # 正确句 浅绿底
F_LINE = "E7E5E4"    # 分隔线

# 字号（半点单位：22 = 11pt）
SZ_TITLE = 36   # 18pt
SZ_SUB = 21    # 10.5pt
SZ_H2 = 27     # 13.5pt
SZ_TYPE = 26   # 13pt
SZ_BODY = 21   # 10.5pt
SZ_NOTE = 18   # 9pt
LINE = 300


def esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def strip_tags(s):
    """去掉 HTML 标签 —— 真源里带 <b> 的提示语不许原样印到纸上。"""
    return re.sub(r"<[^>]+>", "", s)


def run(text, bold=False, size=SZ_BODY, color=None, shd=None, italic=False):
    rpr = "<w:rPr>" + F_RPR
    if bold:
        rpr += "<w:b/>"
    if italic:
        rpr += "<w:i/>"
    if color:
        rpr += '<w:color w:val="%s"/>' % color
    if shd:
        rpr += '<w:shd w:val="clear" w:color="auto" w:fill="%s"/>' % shd
    rpr += '<w:sz w:val="%d"/><w:szCs w:val="%d"/></w:rPr>' % (size, size)
    return '<w:r>%s<w:t xml:space="preserve">%s</w:t></w:r>' % (rpr, esc(text))


def mark_runs(text, size=SZ_BODY, color=C_SIG, bold=False):
    """把 **标记** 渲染成红色加粗（标出病处）。"""
    out = []
    for seg in re.split(r"(\*\*.+?\*\*)", text):
        if not seg:
            continue
        if seg.startswith("**") and seg.endswith("**"):
            out.append(run(seg[2:-2], bold=True, size=size, color=C_BAD))
        else:
            out.append(run(seg, size=size, color=color, bold=bold))
    return "".join(out)


def para(text="", bold=False, size=SZ_BODY, color=None, align=None,
         space_after=0, space_before=0, line=LINE, shd=None, indent=None,
         first_line=None, border_bottom=False):
    ppr = "<w:pPr>"
    if shd:
        ppr += '<w:shd w:val="clear" w:color="auto" w:fill="%s"/>' % shd
    if border_bottom:
        ppr += ('<w:pBdr><w:bottom w:val="single" w:sz="6" w:space="2" '
                'w:color="%s"/></w:pBdr>' % F_LINE)
    ppr += ('<w:spacing w:before="%d" w:after="%d" w:line="%d" w:lineRule="auto"/>'
            % (space_before, space_after, line))
    if indent is not None:
        ppr += '<w:ind w:left="%d"/>' % indent
    if first_line is not None:
        ppr += '<w:ind w:firstLine="%d"/>' % first_line
    if align:
        ppr += '<w:jc w:val="%s"/>' % align
    ppr += "</w:pPr>"
    body = run(text, bold=bold, size=size, color=color) if text else ""
    return "<w:p>%s%s</w:p>" % (ppr, body)


def para_mark(text, size=SZ_BODY, color=C_SIG, bold=False, align=None,
              space_after=0, space_before=0, line=LINE, shd=None, indent=None,
              first_line=None):
    """带 **病处高亮** 的段落。"""
    ppr = "<w:pPr>"
    if shd:
        ppr += '<w:shd w:val="clear" w:color="auto" w:fill="%s"/>' % shd
    ppr += ('<w:spacing w:before="%d" w:after="%d" w:line="%d" w:lineRule="auto"/>'
            % (space_before, space_after, line))
    if indent is not None:
        ppr += '<w:ind w:left="%d"/>' % indent
    if first_line is not None:
        ppr += '<w:ind w:firstLine="%d"/>' % first_line
    if align:
        ppr += '<w:jc w:val="%s"/>' % align
    ppr += "</w:pPr>"
    return "<w:p>%s%s</w:p>" % (ppr, mark_runs(text, size=size, color=color, bold=bold))


def box(runs_xml, shd=F_BOX, line_color=C_TYPE, space_before=0, space_after=0,
        left_bar=True):
    """卡片：底纹 + 左侧色条（打印可见）。"""
    ppr = "<w:pPr>"
    if left_bar:
        ppr += ('<w:pBdr>'
                '<w:left w:val="single" w:sz="18" w:space="4" w:color="%s"/>'
                '<w:top w:val="single" w:sz="4" w:space="3" w:color="%s"/>'
                '<w:bottom w:val="single" w:sz="4" w:space="3" w:color="%s"/>'
                '<w:right w:val="single" w:sz="4" w:space="3" w:color="%s"/>'
                '</w:pBdr>' % (line_color, shd, shd, shd))
    ppr += '<w:shd w:val="clear" w:color="auto" w:fill="%s"/>' % shd
    ppr += ('<w:spacing w:before="%d" w:after="%d" w:line="%d" w:lineRule="auto"/>'
            % (space_before, space_after, LINE))
    ppr += '<w:ind w:left="120" w:right="80"/>'
    ppr += "</w:pPr>"
    return "<w:p>%s%s</w:p>" % (ppr, runs_xml)


def spacer(h=80):
    return '<w:p><w:pPr><w:spacing w:before="0" w:after="0" w:line="%d" w:lineRule="exact"/></w:pPr></w:p>' % h


def pagebreak():
    return '<w:p><w:r><w:br w:type="page"/></w:r></w:p>'


# ══════════════════════ 例句库（我逐条验算过，改法唯一可判）══════════════════
# 每型：2 个错例（病名 + 改法）+ 1 个正确句对照
# 错句中的 ** 标记 = 病处（红色加粗）
EXAMPLES = {
    "成分残缺": {
        "note": "句子里的主语被介词或「使」吃掉了",
        "bad": [
            ("通过这次社会实践活动，使我们学会了如何与同伴合作。",
             "成分残缺",
             "删「通过」→　这次社会实践活动使我们学会了如何与同伴合作。\n"
             "（或删「使」→　通过这次社会实践活动，我们学会了如何与同伴合作。）"),
            ("在老师的帮助下，使他的成绩提高得很快。",
             "成分残缺",
             "删「使」→　在老师的帮助下，他的成绩提高得很快。"),
        ],
        "ok": "通过这次社会实践活动，我们学会了如何与同伴合作。",
    },
    "句式杂糅": {
        "note": "两套说法套在一句话里叠罗汉",
        "bad": [
            ("他取得进步的原因，是因为他每天坚持复盘。",
             "句式杂糅",
             "删「的原因」→　他取得进步，是因为他每天坚持复盘。"),
            ("这次考试失败的原因是，由于我们准备不够充分。",
             "句式杂糅",
             "删「的原因是」→　这次考试失败，是由于我们准备不够充分。\n"
             "（或删「是由于」→　这次考试失败的原因，是我们准备不够充分。）"),
        ],
        "ok": "他取得进步，是因为他每天坚持复盘。",
    },
    "重复赘余": {
        "note": "同一个意思说了两遍",
        "bad": [
            ("这次活动的参加人数比上次**增加了很多**。",
             "重复赘余",
             "删「很多」→　这次活动的参加人数比上次增加了不少。\n"
             "（道理：「比」已经表示比较，后面不必再说「很多」）"),
            ("我们**必须要**遵守纪律。",
             "重复赘余",
             "删「要」→　我们必须遵守纪律。\n"
             "（道理：「必须」本身就含「要」的意思）"),
        ],
        "ok": "这次活动的参加人数比上次增加了不少。",
    },
    "否定不当": {
        "note": "否定词用多了，意思反过来了",
        "bad": [
            ("为了防止此类事故**不再**发生，公司加强了安全检查。",
             "否定不当",
             "删「不」→　为了防止此类事故再次发生，公司加强了安全检查。\n"
             "（道理：「防止」已经含否定义，再加「不」就成了双重否定）"),
            ("为了避免**不再**犯同样的错误，他在草稿纸上写下每一个步骤。",
             "否定不当",
             "删「不再」→　为了避免再犯同样的错误，他在草稿纸上写下每一个步骤。\n"
             "（或删「避免」→　为了不再犯同样的错误，……）"),
        ],
        "ok": "为了防止此类事故再次发生，公司加强了安全检查。",
    },
    "搭配不当": {
        "note": "谁跟谁搭不上——主语和谓语、动词和宾语",
        "bad": [
            ("这本书的内容非常丰富，**很受读者欢迎**。",
             "搭配不当",
             "换主语→　这本书内容丰富，很受读者欢迎。\n"
             "（道理：受读者欢迎的是「这本书」，不是「这本书的内容」）"),
            ("他**改进**了自己的缺点。",
             "搭配不当",
             "换动词→　他改正了自己的缺点。\n"
             "（道理：缺点要「改正」，「改进」是配方法、措施的）"),
        ],
        "ok": "这本书内容丰富，很受读者欢迎。",
    },
    "两面对一面": {
        "note": "前面两面，后面只有一面",
        "bad": [
            ("能否取得好成绩，关键在于**努力**。",
             "两面对一面",
             "补成两面→　能否取得好成绩，关键在于**是否**努力。\n"
             "（或去掉两面→　取得好成绩，关键在于努力。）"),
            ("这次的主题班会能否开得成功，关键在于同学们的积极参与。",
             "两面对一面",
             "补成两面→　这次的主题班会能否开得成功，关键在于同学们**是否**积极参与。"),
        ],
        "ok": "能否取得好成绩，关键在于是否努力。",
    },
    "语序不当": {
        "note": "谁先谁后放错了位置",
        "bad": [
            ("她穿着一件**红色的漂亮的**连衣裙。",
             "语序不当",
             "调顺序→　她穿着一件**漂亮的红色的**连衣裙。\n"
             "（道理：多层定语一般按「性质 → 颜色 → 形状 → 新旧 → 材质 → 用途」排）"),
            ("**他像今天这样高兴是从来没有过的**。",
             "语序不当",
             "调顺序→　**他从来没有像今天这样高兴过**。\n"
             "（道理：主语和宾语位置颠倒，「从来没有过」要放在前面）"),
            ("他先**预习**明天的课文，然后写今天的作业，最后才去玩。",
             "语序不当",
             "调顺序→　他先写今天的作业，然后预习明天的课文，最后才去玩。\n"
             "（道理：先做今天的事，再做明天的事）"),
        ],
        "ok": "她穿着一件漂亮的红色的连衣裙。",
    },
}

# ═══════════════════════════════ 正文 ═══════════════════════════════════════
def build_body():
    b = []
    # ── 标题 ──
    b.append(para("初中语文 · 病句类型速查卡", bold=True, size=SZ_TITLE,
                  color=C_TITLE, align="center", space_after=40))
    b.append(para("学生专用 · 七型全列 · 举例说明 · 答题时对照用",
                  size=SZ_SUB, color=C_HINT, align="center", space_after=90))

    # ── 答题公式卡（G15：主观题必挂，来源 answer_formula.py 唯一真源）──
    f = AF.get("病句辨析题")
    if f:
        b.append(para("【答题公式 · 病句辨析题】" + f["formula"],
                      bold=True, size=21, color=C_AFH, shd=F_AFF, space_after=0, line=250))
        for k, v in f["parts"]:
            b.append(box(run(k + "：", bold=True, size=19, color=C_AFK)
                         + run(v, size=19, color=C_AFV),
                         shd=F_AFF, line_color=C_AFH, space_after=0))
        b.append(box(run(strip_tags(f["tip"]), size=18, color=C_HINT),
                     shd=F_AFT, line_color=C_HINT, space_after=0))
        b.append(spacer(100))

    # ── 七型总表（数据来自 bingju_card.py，不另写一份）──
    b.append(para("一、七型一览", bold=True, size=SZ_H2, color=C_TITLE,
                  space_after=50, border_bottom=True))
    for t, sig, fix in BJC.cards():
        b.append(box(run(t, bold=True, size=21, color=C_TYPE)
                     + run("　│　", size=19, color=F_LINE)
                     + run("怎么认出它：", bold=True, size=19, color=C_SIG)
                     + run(sig + "　", size=19, color=C_SIG)
                     + run("怎么改：", bold=True, size=19, color=C_FIX)
                     + run(fix, size=19, color=C_FIX),
                     shd=F_BOX, line_color=C_TYPE, space_after=40))
    b.append(spacer(60))

    # ── 每型详解 ──
    b.append(para("二、每型举例", bold=True, size=SZ_H2, color=C_TITLE,
                  space_after=50, border_bottom=True))
    b.append(para("用法：先看「怎么认出它」→ 对着例句找病处（红色）→ "
                  "写下病名 → 写出改好的完整句子。干净的那句也要写「没有语病」。",
                  size=SZ_NOTE, color=C_TIP, space_after=80))

    for idx, (typ, sig, fix) in enumerate(BJC.cards()):
        ex = EXAMPLES[typ]
        # 类型标题条
        b.append(para("%d　%s" % (idx + 1, typ), bold=True, size=SZ_TYPE,
                      color=C_HEADT, shd=C_TYPE, space_after=0, line=260))
        b.append(para_mark("怎么认出它：" + sig + "　│　" + ex["note"],
                           size=19, color=C_SIG, shd=F_HEAD, space_after=60))

        for wrong, name, fix_txt in ex["bad"]:
            b.append(box(run("错例　", bold=True, size=19, color=C_BAD)
                         + mark_runs(wrong, size=20, color=C_SIG),
                         shd=F_BOX, line_color=C_BAD, space_after=0))
            # 病名 + 怎么改（改法可能多行，每行一段；** 高亮走 mark_runs）
            b.append(box(run("病名　", bold=True, size=19, color=C_TYPE)
                         + run(name, bold=True, size=19, color=C_TYPE),
                         shd=F_BOX, line_color=C_TYPE, space_after=0))
            b.append(box(run("怎么改　", bold=True, size=19, color=C_FIX),
                         shd=F_BOX, line_color=C_TYPE, space_after=0))
            for ln in fix_txt.split("\n"):
                b.append(box(mark_runs(ln, size=19, color=C_FIX),
                             shd=F_BOX, line_color=C_TYPE, space_after=0))
            b.append(spacer(50))

        b.append(box(run("对照　", bold=True, size=19, color=C_TIP)
                     + run("这一句没有语病　", size=19, color=C_TIP)
                     + run(ex["ok"], size=19, color=C_SIG),
                     shd=F_OK, line_color=C_TIP, space_after=60))
        if idx < len(BJC.cards()) - 1:
            b.append(spacer(120))

    # ── 考场自检四问 ──
    b.append(para("三、交卷前自检四问", bold=True, size=SZ_H2, color=C_TITLE,
                  space_after=50, border_bottom=True))
    for i, q in enumerate([
        "主语还在吗？（成分残缺）",
        "前后两套说法打架了吗？（句式杂糅）",
        "有没有同一个意思说了两遍？（重复赘余）",
        "否定词是多了还是少了？前后两面对得齐吗？搭配搭得上吗？语序放对了吗？",
    ], 1):
        b.append(para("%d. %s" % (i, q), size=SZ_BODY, color=C_SIG,
                      indent=200, space_after=40))

    # ── 视频（B 站 API 核实的真实 BV 号，不编造）──
    b.append(para("四、想看视频（BV 号已核实）", bold=True, size=SZ_H2, color=C_TITLE,
                  space_after=50, border_bottom=True))
    for title, bv, up, dur, why in [
        ("送分题你都接不住？病句六大类型速通排雷，7分钟拿捏满分！丨贞贞语文",
         "BV1U7gY6KEGj", "阿贞爱上了语文", "7分31秒",
         "首选 · 7 分钟讲完六大类型通排，和这张卡一一对应"),
        ("病句快速解法“一眼看病”，新学期就别在这丢分了",
         "BV18n9GYxEun", "语文五爷", "3分21秒",
         "3 分钟极短 · 讲怎么一眼看出病处，适合先看"),
        ("一个万能口诀，搞定七年级上期末病句！",
         "BV1ZbBKB3EFK", "甲哥语文", "3分52秒",
         "明确讲七年级 · 口诀式记忆，和卡上的「怎么认出它」对照"),
        ("【句子】第32节：病句辨析精讲，做病句题，你需要具备这些知识（上）",
         "BV1Zo4y1A7h5", "梓墨说语文", "24分47秒",
         "讲原理最细 · 超 20 分钟，只看前 12 分钟（辨析方法那部分）"),
    ]:
        b.append(para_mark(title, size=19, color=C_SIG, space_after=20))
        b.append(para("%s　│　UP：%s　│　时长：%s" % (bv, up, dur),
                      size=18, color=C_HINT, indent=200, space_after=20))
        b.append(para("看它做什么：" + why, size=18, color=C_TIP, indent=200, space_after=50))

    b.append(spacer(80))
    b.append(para("本卡类型、识别信号、怎么改三项，均取自学生学习系统技能库的语病速查卡唯一真源；"
                  "例句与改法逐条验算。", size=SZ_NOTE, color="78716C", align="center"))
    return b


STYLES_XML = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
    '<w:docDefaults><w:rPrDefault><w:rPr>'
    '<w:rFonts w:ascii="Times New Roman" w:eastAsia="\u5b8b\u4f53" '
    'w:hAnsi="Times New Roman" w:cs="Times New Roman"/><w:kern w:val="2"/>'
    '<w:sz w:val="21"/><w:szCs w:val="21"/>'
    '</w:rPr></w:rPrDefault>'
    '<w:pPrDefault><w:pPr><w:spacing w:line="300" w:lineRule="auto"/></w:pPr></w:pPrDefault>'
    '</w:docDefaults>'
    '<w:style w:type="paragraph" w:default="1" styleId="Normal"><w:name w:val="Normal"/>'
    '<w:qFormat/></w:style>'
    '</w:styles>')

DOC_RELS = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/'
    'relationships/styles" Target="styles.xml"/>'
    '</Relationships>')

FOOTER_XML = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<w:ftr xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
    '<w:p><w:pPr><w:jc w:val="center"/></w:pPr>'
    '<w:r><w:rPr>' + F_RPR + '<w:sz w:val="18"/></w:rPr>'
    '<w:t xml:space="preserve">— </w:t></w:r>'
    '<w:r><w:fldChar w:fldCharType="begin"/></w:r>'
    '<w:r><w:instrText xml:space="preserve"> PAGE </w:instrText></w:r>'
    '<w:r><w:fldChar w:fldCharType="end"/></w:r>'
    '<w:r><w:rPr>' + F_RPR + '<w:sz w:val="18"/></w:rPr>'
    '<w:t xml:space="preserve"> —</w:t></w:r>'
    '</w:p></w:ftr>')

SECT = ('<w:sectPr><w:pgSz w:w="11906" w:h="16838"/>'
        '<w:pgMar w:top="1134" w:right="1134" w:bottom="1134" w:left="1134" '
        'w:header="567" w:footer="567" w:gutter="0"/>'
        '<w:footerReference w:type="default" r:id="rId2"/></w:sectPr>')

DOC_RELS_FULL = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/'
    'relationships/styles" Target="styles.xml"/>'
    '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/'
    'relationships/footer" Target="footer1.xml"/>'
    '</Relationships>')


def build(out_docx):
    body = build_body()
    doc = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
           '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
           'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
           'xmlns:m="http://schemas.openxmlformats.org/officeDocument/2006/math">'
           '<w:body>' + "".join(body) + SECT + '</w:body></w:document>')
    ct = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
          '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
          '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.'
          'relationships+xml"/>'
          '<Default Extension="xml" ContentType="application/xml"/>'
          '<Override PartName="/word/document.xml" ContentType="application/vnd.'
          'openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
          '<Override PartName="/word/styles.xml" ContentType="application/vnd.'
          'openxmlformats-officedocument.wordprocessingml.styles+xml"/>'
          '<Override PartName="/word/footer1.xml" ContentType="application/vnd.'
          'openxmlformats-officedocument.wordprocessingml.footer+xml"/>'
          '</Types>')
    rels = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/'
            '2006/relationships/officeDocument" Target="word/document.xml"/>'
            '</Relationships>')

    os.makedirs(os.path.dirname(os.path.abspath(out_docx)), exist_ok=True)
    with zipfile.ZipFile(out_docx, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", ct)
        z.writestr("_rels/.rels", rels)
        z.writestr("word/document.xml", doc)
        z.writestr("word/styles.xml", STYLES_XML)
        z.writestr("word/footer1.xml", FOOTER_XML)
        z.writestr("word/_rels/document.xml.rels", DOC_RELS_FULL)
    print("✓ 生成 %s (%.1f KB)" % (out_docx, os.path.getsize(out_docx) / 1024))
    return out_docx


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else "学生_病句类型速查卡_例句版.docx"
    build(out)
