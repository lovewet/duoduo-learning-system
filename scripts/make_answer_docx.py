#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""从 DSL 源生成作答纸 .docx（手写 OOXML，零第三方依赖）。

【阶段19 用户最终要求】答题纸要把**全部题目**纳入进去，全部都要在纸上写：
  · 选择题 → 选项前留 ○，涂黑作答（不给横线，省纸）
  · 填空/简答 → 给出动态分配的答题横线
做完后**拍照或扫描**，作为批改依据并录入错题库（封面有《批改记录》栏）。
题号、题干与网页讲义同源（都从 _p5/day*.txt 生成），一一对应可交叉校验。

用法：python make_answer_docx.py [输出.docx]
"""
import io, os, re, sys, zipfile, html as H

import dsl_source as D
try:
    import frac_render as _FR
except Exception:
    _FR = None

try:
    import bingju_card as _BJC
except Exception:
    _BJC = None
try:
    import answer_formula as _AF
except Exception:
    _AF = None
try:
    import math_format as _MF
except Exception:
    _MF = None

# ---- 彩色板（与网页 CSS 同色系，打印出来才对得上）----
C_HEAD = "9A3412"   # 表头深橙棕
C_TYP  = "C2410C"   # 类型名橙
C_SIG  = "1F2937"   # 正文深灰
C_FIX  = "92400E"   # 改法棕
C_HINT = "B45309"   # 提示琥珀
C_TIP  = "15803D"   # 提示绿
F_HEAD = "FDE68A"   # 表头底纹（浅黄，打印可见）
F_BOX  = "FFF7ED"   # 卡片底纹（浅橙）
F_TIP  = "ECFDF5"   # 绿底
# G15 答题公式卡色板（靛蓝系，与网页端一致）
C_AFH  = "4338CA"   # 公式卡标题条靛蓝
C_AFF  = "312E81"   # 公式骨架深靛
C_AFK  = "4338CA"   # 每格名称
C_AFV  = "1F2937"   # 每格要求
F_AFF  = "EEF2FF"   # 公式骨架底纹（浅靛）
F_AFS  = "F5F3FF"   # 范例底纹（浅紫）
F_AFT  = "FFFBEB"   # tips 底纹（浅琥珀）

# ---------- 字体（阶段21 用户明确：英文要好看的印刷体）----------
# ⚠️ 之前 ascii/hAnsi 全用 SimSun（宋体）——宋体的西文字形是等宽衬线体，
#n/m 挤在一起、l 与 I 难分辨、b 与 6 易看错（语音题、音标题尤其吃亏）。
# 改为：**中文走宋体，西文走 Times New Roman + 连字（digraphs 合成符号）。
F_EA   = "宋体"          # 中文
F_ASCII = "Times New Roman"  # 西文（印刷体，教材标准）
F_MATH = "Cambria Math"      # 数学符号（WP 开元 / 公式感更正式）
F_RPR = ('<w:rFonts w:ascii="%s" w:eastAsia="%s" w:hAnsi="%s" w:cs="%s"/>'
         '<w:kern w:val="2"/>'
         % (F_ASCII, F_EA, F_ASCII, F_ASCII))

# ---------- OOXML 基础件 ----------
def esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

def run(text, bold=False, size=22, uline=False, color=None, shd=None):
    """一段文字。color=字色（RRGGBB），shd=底纹色（RRGGBB）——彩色打印靠这两个。"""
    rpr = ('<w:rPr>' + F_RPR
           + ('<w:b/>' if bold else '')
           + ('<w:u w:val="single"/>' if uline else '')
           + ('<w:color w:val="%s"/>' % color if color else '')
           + ('<w:shd w:val="clear" w:color="auto" w:fill="%s"/>' % shd if shd else '')
           + '<w:sz w:val="%d"/><w:szCs w:val="%d"/></w:rPr>' % (size, size))
    return '<w:r>%s<w:t xml:space="preserve">%s</w:t></w:r>' % (rpr, esc(text))


def para_c(text="", bold=False, size=22, color=None, shd=None, align=None,
           space_after=0, line=300, indent=0, border=False):
    """带字色 + 段落底纹的段落。border=True 时四边加框（卡片效果，打印可见）。"""
    ppr = '<w:pPr>'
    if border:
        ppr += ('<w:pBdr>'
                '<w:top w:val="single" w:sz="6" w:space="2" w:color="%s"/>'
                '<w:left w:val="single" w:sz="18" w:space="4" w:color="%s"/>'
                '<w:bottom w:val="single" w:sz="6" w:space="2" w:color="%s"/>'
                '<w:right w:val="single" w:sz="6" w:space="4" w:color="%s"/>'
                '</w:pBdr>' % (C_TYP, C_TYP, C_TYP, F_HEAD))
    if shd:
        ppr += '<w:shd w:val="clear" w:color="auto" w:fill="%s"/>' % shd
    ppr += '<w:spacing w:before="0" w:after="%d" w:line="%d" w:lineRule="auto"/>' % (space_after, line)
    if indent:
        ppr += '<w:ind w:left="%d"/>' % indent
    if align:
        ppr += '<w:jc w:val="%s"/>' % align
    ppr += '</w:pPr>'
    body = run(text, bold=bold, size=size, color=color, shd=shd) if text else ''
    return '<w:p>%s%s</w:p>' % (ppr, body)

def para(text="", bold=False, size=22, align=None, space_after=0, line=320, indent=0):
    ppr = '<w:pPr>'
    ppr += '<w:spacing w:before="0" w:after="%d" w:line="%d" w:lineRule="auto"/>' % (space_after, line)
    if indent:
        ppr += '<w:ind w:firstLine="%d"/>' % indent
    if align:
        ppr += '<w:jc w:val="%s"/>' % align
    ppr += '</w:pPr>'
    r = run(text, bold=bold, size=size) if text else ''
    return '<w:p>%s%s</w:p>' % (ppr, r)

def rule(height=520):
    """一条答题横线（带底边框的空段落）"""
    return ('<w:p><w:pPr><w:pBdr><w:bottom w:val="single" w:sz="4" w:space="1" w:color="A8A8A8"/>'
            '</w:pBdr><w:spacing w:before="0" w:after="0" w:line="%d" w:lineRule="exact"/></w:pPr></w:p>' % height)

def pagebreak():
    return '<w:p><w:r><w:br w:type="page"/></w:r></w:p>'


def frac_runs(num, den, size=None, bold=False):
    """真分数：**OMML 原生公式**（阶段21 用户要求「渲染成真正的数学的写法」）。

    ⚠️ 之前用 `<w:position>` 升降字号拼的只是**视觉近似**，不合格：
    分数线是一条下划线而非居中定线、分子分母不居中、长度随机。
    改用 OMML `<m:f>` —— Word/WPS 里就是**公式对象**，
    渲染出来与教材印刷体一致（分数线居中定宽、分子分母居中、可整体缩放）。
    """
    try:
        import omml_math as _OM
        return _OM.omath(_OM.frac(num, den, bold))
    except Exception:
        pass
    # 兜底：极简竖排（仅在 OMML 不可用时）
    size = size or D.SZ_BODY
    half = max(14, int(size * 0.82))
    def _r(t, sup=False):
        p = '<w:rPr>' + F_RPR + ('<w:b/>' if bold else '')
        p += '<w:position w:val="%d"/>' % (10 if sup else -8)
        p += '<w:sz w:val="%d"/><w:szCs w:val="%d"/></w:rPr>' % (half, half)
        return '<w:r>%s<w:t xml:space="preserve">%s</w:t></w:r>' % (p, esc(t))
    return _r(num, True) + _r("―") + _r(den, False)


def html_runs(s, size=None, bold=False):
    """把含 <b> / <u> / <span class="fr"> 的片段转成 docx runs。

    <u> 必须保留成真正的下划线：英语语音题考的就是「划线部分读音」，
    如果转成纯文本丢掉下划线，学生在纸上看不出哪个字母划线，题目就废了。

    <span class="fr"> 是**真分数竖式**（阶段21 用户要求，见 fix_fractions.py）：
    分子 / 分母 / 分数线，不能印成斜杠。
    """
    size = size or D.SZ_BODY
    s = H.unescape(s)
    # 分数先抽出来，换成占位符，避免被 <b>/<u> 切分逻辑打散
    frs = []

    def _stash(m):
        frs.append((m.group(1), m.group(2)))
        return "\x00FR%d\x00" % (len(frs) - 1)
    s = re.sub(_FR.FR_RE, _stash, s)   # FR_RE 已含 re.S
    out, b, u = [], bold, False
    for t in re.split(r'(</?(?:b|u)>)', s):
        if t == '<b>':
            b = True
        elif t == '</b>':
            b = False
        elif t == '<u>':
            u = True
        elif t == '</u>':
            u = False
        elif t:
            # 拆出分数占位符；**其余含数学结构的片段走 OMML 真公式**，
            # 纯中文/普通文字仍走普通 run（否则「求…的值」会被塞进公式对象，字形乱）。
            for piece in re.split(r'(\x00FR\d+\x00)', t):
                mf = re.match(r'^\x00FR(\d+)\x00$', piece)
                if mf:
                    n_, d_ = frs[int(mf.group(1))]
                    out.append(frac_runs(n_, d_, size=size, bold=b))
                elif piece:
                    om = _omml_mixed(piece, bold=b)
                    out.append(om if om else run(piece, bold=b, size=size, uline=u))
    return ''.join(out)


def _omml_mixed(text, bold=False):
    """把含数学结构的文本编译成 OMML 片段；纯文字返回 ""（不套公式）。

    走的是 `omml_math.mixed()` —— 它只把「含分数/根号/上标/下标」的片段
    包成 `<m:oMath>`，中文与普通英文保持普通 run。
    """
    try:
        import omml_math as _OM
        return _OM.mixed(text, bold)
    except Exception:
        return ""


def para_rich(html, size=None, prefix="", indent=0, space_after=20, line=None):
    """带前缀文字的富文本段落（用于选项行 ○ A．xxx）。"""
    size = size or D.SZ_BODY
    line = line or D.LINE_BODY
    ppr = '<w:pPr><w:spacing w:before="0" w:after="%d" w:line="%d" w:lineRule="auto"/>' % (space_after, line)
    if indent:
        ppr += '<w:ind w:left="%d"/>' % indent
    ppr += '</w:pPr>'
    body = run(prefix, bold=True, size=size) if prefix else ''
    body += html_runs(html, size)
    return '<w:p>%s%s</w:p>' % (ppr, body)


def bjcard_para():
    """语病 7 型速查卡（彩色打印版）——七种全列，带识别信号。"""
    if _BJC is None:
        return ""
    out = [para_c('📇 语病 7 型速查卡（七种全列 · 逐句判病时对照这张卡）',
                  bold=True, size=18, color="FFFFFF", shd=C_HEAD,
                  space_after=0, line=260)]
    out.append(para_c('类型 ｜ 怎么认出它（信号）｜ 怎么改',
                      bold=True, size=16, color=C_HEAD, shd=F_HEAD,
                      space_after=0, line=240))
    for name, sig, fix in _BJC.cards():
        ppr = ('<w:pPr><w:shd w:val="clear" w:color="auto" w:fill="%s"/>'
               '<w:spacing w:before="0" w:after="0" w:line="240" w:lineRule="auto"/>'
               '<w:ind w:left="60"/></w:pPr>' % F_BOX)
        body = (run(name + '　', bold=True, size=16, color=C_TYP)
                + run('｜ ' + sig + ' ｜ ', size=16, color=C_SIG)
                + run(fix, size=16, color=C_FIX))
        out.append('<w:p>%s%s</w:p>' % (ppr, body))
    out.append(para_c('★ 先看信号再定名字 —— 这七种是起点，不是限制。',
                      size=16, color=C_TIP, shd=F_TIP, space_after=60, line=240))
    return ''.join(out)


def afcard_para(qtype):
    """G15 答题公式卡（彩色打印版）—— 告诉他答案该写成什么句式。

    只给主观题（JUDGE）挂；客观题写法唯一，不需要公式。
    """
    if _AF is None or qtype not in _AF.ALL_FORMULA:
        return ""
    d = _AF.ALL_FORMULA[qtype]
    out = [para_c('✍ 答题公式 · %s（按这个句式写，阅卷按点给分）' % qtype,
                  bold=True, size=18, color="FFFFFF", shd=C_AFH,
                  space_after=0, line=260)]
    out.append(para_c(d["formula"], bold=True, size=19, color=C_AFF,
                      shd=F_AFF, space_after=0, line=250))
    for k, v in d["parts"]:
        ppr = ('<w:pPr><w:shd w:val="clear" w:color="auto" w:fill="FFFFFF"/>'
               '<w:spacing w:before="0" w:after="0" w:line="250" w:lineRule="auto"/>'
               '<w:ind w:left="60"/></w:pPr>')
        body = (run(k + '：', bold=True, size=16, color=C_AFK)
                + run(v, size=16, color=C_AFV))
        out.append('<w:p>%s%s</w:p>' % (ppr, body))
    out.append(para_c('范例：' + re.sub(r'<[^>]+>', '', d["sample"]),
                      size=16, color=C_AFF, shd=F_AFS, space_after=60, line=250))
    return ''.join(out)




def bjtab_para(q):
    """G11 逐句语病定性：病句题的正式作答内容。

    每句给两行——「语病类型」和「改正」都要手写，不能只圈选项。
    纸面用紧凑两行式（不用真表格），留白够写字且不跨页难排。
    """
    out = [para('✍逐句定性（本题的正式答案 · 下面每句话都要单独写病名和改法）',
                bold=True, size=D.SZ_NOTE, space_after=50)]
    for r in q["bjtab"]:
        out.append(para('%s　%s' % (r["no"], r["sent"]),
                        size=D.SZ_NOTE, space_after=20, line=280))
        out.append(para('语病类型：____________________　　改正：________________________________',
                        size=D.SZ_NOTE, space_after=30, line=280, indent=200))
    out.append(para('★ 写出病名才算做完这题；写不出就空着，别乱猜。',
                    size=D.SZ_NOTE, space_after=60))
    return ''.join(out)


def opt_para(q, size=None):
    """渲染选择题选项：按 dsl_source.opt_rows() 的装箱结果分行，选项前留 ○ 供涂黑。"""
    size = size or D.SZ_BODY
    opts = q.get("opts") or []
    rows = D.opt_rows(q)
    if not rows:
        return ''
    out = []
    for r in rows:
        ppr = ('<w:pPr><w:spacing w:before="0" w:after="12" w:line="%d" w:lineRule="auto"/>'
               '<w:ind w:left="280"/></w:pPr>' % D.LINE_BODY)
        body = ''
        for k, i in enumerate(r):
            if k:
                body += run('　　', size=size)
            body += run('○ %s．' % "ABCD"[i], bold=True, size=size)
            body += html_runs(opts[i], size)
        out.append('<w:p>%s%s</w:p>' % (ppr, body))
    return ''.join(out)


STYLES_XML = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
    '<w:docDefaults><w:rPrDefault><w:rPr>'
    '<w:rFonts w:ascii="Times New Roman" w:eastAsia="\u5b8b\u4f53" w:hAnsi="Times New Roman" w:cs="Times New Roman"/><w:kern w:val="2"/>'
    '<w:sz w:val="22"/><w:szCs w:val="22"/>'
    '</w:rPr></w:rPrDefault>'
    '<w:pPrDefault><w:pPr><w:spacing w:line="320" w:lineRule="auto"/></w:pPr></w:pPrDefault>'
    '</w:docDefaults>'
    '<w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/><w:qFormat/></w:style>'
    '</w:styles>')

DOC_RELS = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
    '</Relationships>')

SECT = ('<w:sectPr><w:pgSz w:w="11906" w:h="16838"/>'
        '<w:pgMar w:top="%d" w:right="%d" w:bottom="%d" w:left="%d" '
        'w:header="600" w:footer="600" w:gutter="0"/></w:sectPr>'
        % (D.MARGIN_TB, D.MARGIN_LR, D.MARGIN_TB, D.MARGIN_LR))

# ---------- HTML → 纯文本行 ----------
def to_lines(s):
    s = re.sub(r'<br\s*/?>', '\n', s)
    s = re.sub(r'<[^>]+>', '', s)
    s = H.unescape(s)
    return [x.strip() for x in s.split('\n') if x.strip()]

# ---------- 主流程 ----------
def build(out_docx, src_dir=None, only_day=None):
    """从 DSL 源生成作答纸。only_day 给定时只出那一天（每日推送用）。"""
    days = D.load_days(src_dir or D.SRC_DIR)
    if only_day:
        days = [d for d in days if d["n"] == only_day]
    # 【阶段19 用户最终要求】全部题目都进作答纸，包括选择题。
    # 选择题不给横线，在选项前留 ○ 让学生涂圈 + 可写一步关键过程。
    # 批改依据是拍照 / 扫描的作答纸，所以每道题都必须在纸上留下笔迹。

    body = []
    total = sum(len(d["qs"]) for d in days)
    # 每天动态分配横线数：按真实页高切分，取「不增加页数」的最大横线数
    plan = [(d, D.plan_day(d["qs"])) for d in days]
    n_rule = sum(per * sum(1 for q in d["qs"] if D.n_rules(q["kind"]) > 0)
                 for d, (per, _) in plan)
    # —— 首页（阶段21 用户：**第一页直接到题目**）——
    # 只留标题 + 姓名栏，**紧接着就是第 1 题**。
    #⚠️ 不要再加任何「本册共 N 题」「① 选择题…」「② 填空题…」这类说明——
    #   用户明确要求删掉：答题纸上只该有题目本身与作答空间。
    # ⚠️ 单日作答纸必须写「第 N 天」（阶段22 用户：只给当天的）：
    # 原来写死「三科考点 7 天攻坚 · 作答纸」，单日产物上还挂着"7 天"，容易误当合集。
    _dn = plan[0][0]["n"] if plan else 0
    body.append(para('学生 · 第 %d 天 · 作答纸' % _dn,
                     bold=True, size=D.SZ_HEAD, align='center', space_after=50))
    body.append(para('姓名：____________　日期：____________　得分：__________',
                     size=D.SZ_BODY, space_after=70))

    card_done = {}   # 每天只在第一道病句题前插一次速查卡
    for k, (d, (per, _pages)) in enumerate(plan):
        if k > 0:
            body.append(pagebreak())
        body.append(para('第 %d 天　%s' % (d["n"], d["title"]),
                         bold=True, size=D.SZ_HEAD, space_after=40))
        n_m = sum(1 for q in d["qs"] if q["kind"] == "MC")
        body.append(para('姓名：__________　日期：__________　用时：______ 分钟　得分：______',
                         size=D.SZ_NOTE, space_after=90))
        for q in d["qs"]:
            body.append(para('第 %d 题（%s · %s）' % (q["no"], q["subj"], D.KIND_CN[q["kind"]]),
                             bold=True, size=D.SZ_QNO, space_after=30))
            # G10 题型：**直接印出来**（阶段20 用户明确——题型不用他自己命名）
            if q.get("qtype"):
                body.append(para_c('题型：%s' % q["qtype"], bold=True, size=17,
                                   color="3730A3", shd="EEF2FF",
                                   space_after=30, line=250))
            # ⚠️ 这里**不再印「数学书写规范」卡**（阶段21 用户纠正）：
            # 那是我（大模型）出题时必须遵守的排版规范，不是给答题人的要求。
            # 题面本身已经是规范的印刷体（分数竖式 / 根号 / 变量斜体），
            # 孩子照着题面写就对了；再印一张「你要怎么写」的卡是多余的。
            # G15 答题公式卡：主观题才挂（客观题写法唯一，不需要公式）
            if q["kind"] == "JUDGE" and q.get("qtype"):
                card = afcard_para(q["qtype"])
                if card:
                    body.append(card)
            # 病句题额外给语病清单——作为**可选提示**（不是答案）
            if q.get("bingju"):
                body.append(para_c('语病 7 型速查卡在下方 · 逐句定性时对照用',
                                   bold=True, size=17, color="FFFFFF", shd=C_HEAD,
                                   space_after=0, line=250))
                body.append(para_c('语病类型备选（七种全列，可参考）：%s'
                                   % "　".join("□ " + x for x in q["bingju"]),
                                   size=17, color=C_HINT, shd="FEF3C7",
                                   space_after=40, line=260))
            for ln in D.to_lines(q["stem"]):
                # ⚠️ 走 html_runs 支持真分数竖式（阶段21）
                body.append('<w:p><w:pPr><w:spacing w:before="0" w:after="20" '
                            'w:line="%d" w:lineRule="auto"/></w:pPr>%s</w:p>'
                            % (D.LINE_BODY, html_runs(ln, size=D.SZ_BODY)))
            if q["kind"] == "MC":
                body.append(opt_para(q))          # ○ 选项，涂圈作答
            else:
                for _ in range(per):
                    body.append(rule(D.RULE_H))
            # G11 逐句语病定性：病句题的正式作答内容，**每句都要写病名 + 改正**
            if q.get("bjtab"):
                if card_done.get(d["n"]) is not True:
                    body.append(bjcard_para())
                    card_done[d["n"]] = True
                body.append(bjtab_para(q))
            body.append(para('', size=8, space_after=D.GAP_Q, line=240))
        body.append(para('— 第 %d 天作答结束 · 共 %d 题 —' % (d["n"], len(d["qs"])),
                         size=D.SZ_NOTE, align='center', space_after=40))

    # ⚠️ 《批改记录》栏已从**作答纸**移除（阶段21 用户：「这些也不要」）。
    # 它是老师填的对账单，不是孩子的卷面内容。
    # 对账单搬到了**答案册**（家长/老师那份）末尾，回写错题库的闭环不变。

    doc = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
           '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
           'xmlns:m="http://schemas.openxmlformats.org/officeDocument/2006/math">'
           '<w:body>' + ''.join(body) + SECT + '</w:body></w:document>')

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

    # ⚠️ 目标文件可能被 Word / WPS / 预览面板占用（PermissionError）。
    # 先写临时文件，再原子替换；替换失败则退回带时间戳的新文件名，
    # **绝不让整个构建因为「文件开着」而失败**（实测踩过）。
    try:
        with zipfile.ZipFile(out_docx, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("[Content_Types].xml", ct)
            z.writestr("_rels/.rels", rels)
            z.writestr("word/document.xml", doc)
            z.writestr("word/styles.xml", STYLES_XML)
            z.writestr("word/_rels/document.xml.rels", DOC_RELS)
    except PermissionError:
        import datetime as _dt
        alt = "%s_新%s.docx" % (os.path.splitext(out_docx)[0],
                              _dt.datetime.now().strftime("%H%M%S"))
        with zipfile.ZipFile(alt, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("[Content_Types].xml", ct)
            z.writestr("_rels/.rels", rels)
            z.writestr("word/document.xml", doc)
            z.writestr("word/styles.xml", STYLES_XML)
            z.writestr("word/_rels/document.xml.rels", DOC_RELS)
        print("  ⚠原文件被占用（Word/预览打开中），已另存为：%s" % os.path.basename(alt))
        out_docx = alt

    # 页数：各天分页结果之和 + 末尾批改记录 1 页（首页不再有独立封面）
    pages = 1 + sum(len(pg) for _, (_, pg) in plan)

    print("生成 %s" % out_docx)
    print("  天数 %d　题目 %d　答题横线 %d　大小 %.1f KB" % (len(days), total, n_rule, len(doc) / 1024))
    print("  版式：正文 %.1fpt / 题号 %.1fpt / 横线高 %.1fpt / 页边距 %.2fcm"
          % (D.SZ_BODY / 2.0, D.SZ_QNO / 2.0, D.RULE_H / 20.0, D.MARGIN_TB / 567.0))
    print("  可用版面 %.0fpt/页　预计 %d 页（首页直接到题目 + 末尾批改记录 1 页）" % (D.USABLE_PT, pages))
    for d, (per, pg) in plan:
        hs = " + ".join("%.0f" % h for _, h in pg)
        print("    第%d天 %2d题  每题 %d 行横线  %d 页（各页占高 %s / %.0fpt）"
              % (d["n"], len(d["qs"]), per, len(pg), hs, D.USABLE_PT))
    return total

if __name__ == "__main__":
    # 用法：[--day N] [输出文件名]；不给 --day 就出全部 7 天合集
    argv = sys.argv[1:]
    only_day = None
    if "--day" in argv:
        i = argv.index("--day")
        only_day = int(argv[i + 1]); del argv[i:i + 2]
    out = argv[0] if argv else "学生_七天作答纸合集.docx"
    if only_day:
        build(out, only_day=only_day)
    else:
        build(out)
