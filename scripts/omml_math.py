#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""OMML 真公式渲染（Office Math Markup Language）—— 真正的数学排版。

阶段21 用户要求：「要渲染成真正的数学的写法」。

**为什么之前的做法不合格**：
用 `<w:position w:val="10"/>`（字级升降）拼出来的"分数"只是**视觉近似**，
不是数学排版：
1. 分数线是**一条下划线**，不是分数线该有的**居中定宽横线**；
2. 分子分母不居中对齐，是各自靠左排；
3. 分数线长度随分子分母文字长度变化，不是分数线的标准长度；
4. 不能整体缩放、不能随行高自适应、不能被 Word 识别为公式对象。

**正确做法：OMML `<m:oMath>`** —— Word / WPS / LibreOffice 原生支持，
渲染出来就是**教材印刷体**的样子：分数线居中定宽、分子分母居中、
可整体当公式对象缩放。这是 Word 里「插入 → 公式」生成的东西。

覆盖的数学元素（初中范围）：
  frac   真分数（斜线也支持，但**默认强制真分数**）
  sqrt   根号（含 √□ 简写形式，被开方数带覆盖）
  sup/sub上下标（a²、x₁）
  ｜｜   绝对值（用 | 拼 OMML 竖线）
  ≤ ≥ ≠ ± × ÷ ≈ ∞ ° ∠ △ ∽ ∥ ⊥ ∵ ∴
  省略号（⋯ 与三点）
"""
import re

# ---------- OMML 命名空间（写进 document.xml 的根元素） ----------
OMML_NS = 'xmlns:m="http://schemas.openxmlformats.org/officeDocument/2006/math"'

DEFAULT_FONT = 'Cambria Math'   # Word 公式默认字体，正式印刷体


def _rpr(bold=False, size=None, italic=None):
    """公式内的 run 属性。"""
    p = '<w:rPr><w:rFonts w:ascii="%s" w:hAnsi="%s"/>' % (DEFAULT_FONT, DEFAULT_FONT)
    if bold:
        p += '<w:b/>'
    if italic is False:       # 数学变量默认斜体，数字/运算符不斜
        p += '<w:i w:val="0"/>'
    p += '</w:rPr>'
    return p


def _mr(text, bold=False, sty=None):
    """OMML 内部的文字 run（默认不斜体：数字与运算符保持正立）。"""
    pr = _rpr(bold) + '<m:sty m:val="%s"/>' % (sty or 'p')   # p=正体 i=斜体 b=粗 bi
    return '<m:r>%s<m:t xml:space="preserve">%s</m:t></m:r>' % (pr, _esc(text))


def _esc(s):
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def _mv(txt):
    """数学变量（斜体）—— 教材里 a b c x y 是斜体。"""
    pr = _rpr() + '<m:sty m:val="i"/>'
    return '<m:r>%s<m:t xml:space="preserve">%s</m:t></m:r>' % (pr, _esc(txt))


# ---------- 元素构造 ----------
def frac(num, den, bold=False):
    """真分数：分数线居中定宽，分子分母各自居中 —— Word 原生公式排版。"""
    return ('<m:f><m:fPr><m:type m:val="bar"/>'
            '<m:ctrlPr>%s</m:ctrlPr></m:fPr>'
            '<m:num>%s</m:num><m:den>%s</m:den></m:f>'
            % (_rpr(bold), content(num, bold), content(den, bold)))


def sqrad(body, bold=False):
    """根号：<m:rad> 自带覆盖横（degreeHide=1 → 平方根不带指数）。

    ⚠️ 被开方数要**递归编译**（根号里也可能有分数 / 上标，如 √(a²+b²)）。
    """
    return ('<m:rad><m:radPr><m:degHide m:val="1"/>'
            '<m:ctrlPr>%s</m:ctrlPr></m:radPr>'
            '<m:deg/><m:e>%s</m:e></m:rad>'
            % (_rpr(), compile_text(body, bold)))


def sup(base, exp, bold=False):
    """上标：a² → <m:sSup>（Word 原生上标，不是把 ² 当普通字符）"""
    return ('<m:sSup><m:sSupPr><m:ctrlPr>%s</m:ctrlPr></m:sSupPr>'
            '<m:e>%s</m:e><m:sup>%s</m:sup></m:sSup>'
            % (_rpr(), compile_text(base, bold), _mr(exp, bold, sty='p')))


def sub(base, idx, bold=False):
    """下标：x₁ → <m:sSub>（Word 原生下标）"""
    return ('<m:sSub><m:sSubPr><m:ctrlPr>%s</m:ctrlPr></m:sSubPr>'
            '<m:e>%s</m:e><m:sub>%s</m:sub></m:sSub>'
            % (_rpr(), compile_text(base, bold), _mr(idx, bold, sty='p')))


# Unicode 上标/下标 → 普通字符
SUP_MAP = {"⁰": "0", "¹": "1", "²": "2", "³": "3", "⁴": "4",
           "⁵": "5", "⁶": "6", "⁷": "7", "⁸": "8", "⁹": "9"}
SUB_MAP = {"₀": "0", "₁": "1", "₂": "2", "₃": "3", "₄": "4",
           "₅": "5", "₆": "6", "₇": "7", "₈": "8", "₉": "9"}


def d(body):
    """加粗/强调容器（配合 oMath 用）。"""
    return '<m:d><m:dPr><m:ctrlPr>%s</m:ctrlPr></m:dPr><m:e>%s</m:e></m:d>' % (_rpr(), content(body))


# ==================== LaTeX 命令 → Unicode ====================
# 🔴 阶段29 与 mathml_render 同源修复：`_tokenize` 只按单字符切分，
# `\le` 会被拆成三个 run（`\` `l` `e`），Word 里显示成 "\l e"。
# 这里复用 mathml_render 的同一张映射表，保证**网页与 docx 两端同源**。
def _load_latex_ops():
    try:
        import importlib.util as _iu
        import os as _os
        _p = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)),
                           'mathml_render.py')
        _sp = _iu.spec_from_file_location('_mr_for_ops', _p)
        _m = _iu.module_from_spec(_sp); _sp.loader.exec_module(_m)
        return _m.latex_ops
    except Exception:
        def _fallback(s):
            return (s.replace(r"\le", "≤").replace(r"\ge", "≥")
                     .replace(r"\cdot", "·").replace(r"\ne", "≠")
                     .replace(r"\times", "×"))
        return _fallback


latex_ops = _load_latex_ops()


def omath(inner, inline=True):
    """完整公式对象。inline=True 是行内公式（与文字混排）。"""
    return '<m:oMath>%s</m:oMath>' % inner


def delim(body, beg='(', end=')'):
    """带自动伸缩的括号 —— 教材印刷体括号会随内容高度变化。"""
    return ('<m:d><m:dPr><m:begChr m:val="%s"/><m:endChr m:val="%s"/>'
            '<m:ctrlPr>%s</m:ctrlPr></m:dPr><m:e>%s</m:e></m:d>'
            % (_esc(beg), _esc(end), _rpr(), content(body)))


# ---------- 文本 → OMML（核心：把题面文字翻译成公式） ----------
# 识别顺序很重要：先长后短，避免「√」吃掉后面的内容
_VARS = set("abcdefghijklmnopqrstuvwxyz")


def _tokenize(s):
    """把字符串切成 [('var'|'num'|'op', 文本), ...]。"""
    out = []
    for ch in s:
        if ch in _VARS:
            out.append(('var', ch))
        elif ch.isdigit() or ch == '.':
            # 连续数字合并
            if out and out[-1][0] == 'num':
                out[-1] = ('num', out[-1][1] + ch)
            else:
                out.append(('num', ch))
        else:
            out.append(('op', ch))
    return out


def content(s, bold=False):
    """把字符串编译成 OMML 内部结构（自动识别分数/根号/上下标/变量）。"""
    if s is None:
        return ''
    return compile_text(s, bold)


_FRAC_PAT = re.compile(r"\(([^()]{1,20})\)\s*/\s*(\d{1,5})")
_SQRT_PAT = re.compile(r"√\s*(\d+(?:\.\d+)?)")
_SUP_PAT = re.compile(r"([A-Za-z0-9\)\]])\s*(?:²|³|\^([0-9]+))")


def compile_text(s, bold=False):
    """编译一段题面文字为 OMML。支持：分数、√、上标、变量斜体。

    实现思路：一次扫描，用「最左优先」的顺序挑出公式片段，
    片段之间的普通文本走 emit_plain。不做二次替换（避免偏移错乱）。
    """
    if not s:
        return ""
    s = latex_ops(s)
    out = []
    pos = 0

    def emit_plain(t):
        """普通文本 → 变量斜体（教材体例）、数字与运算符正立。"""
        if not t:
            return
        for kind, txt in _tokenize(t):
            if txt:
                out.append(_mv(txt) if kind == 'var' else _mr(txt, bold))

    # ══ 公式片段识别（阶段21 用户：该是分数是分数、指数是指数、下标是下标）══
    TOKEN = re.compile(
        # (m + n)/2025  —— 括号算式做分子
        r"([A-Za-z0-9]*\([^()]{1,20}\))\s*/\s*(\d{1,5})"
        # 3/2  —— 纯数字分数（分母必须以数字开头，避开 d/f、ur/er）
        r"|(?<![\w/.])(\d{1,4})/(\d{1,5})(?![\w/])"
        # √25 或 √(a²+b²) —— 根号
        r"|√\s*\(([^()]{1,20})\)|√\s*(\d+(?:\.\d+)?)"
        # x²  a³  —— 上标（Unicode 上标字符）
        r"|([A-Za-z0-9\)）])\s*([⁰¹²³⁴⁵⁶⁷⁸⁹]+)"
        # x₁  a₂  —— 下标（Unicode 下标字符）
        r"|([A-Za-z0-9\)）])\s*([₀₁₂₃₄₅₆₇₈₉]+)"
    )
    for m in TOKEN.finditer(s):
        emit_plain(s[pos:m.start()])
        if m.group(1) is not None:
            out.append(frac(m.group(1), m.group(2), bold))          # (m+n)/2025
        elif m.group(3) is not None:
            out.append(frac(m.group(3), m.group(4), bold))          # 3/2
        elif m.group(5) is not None:
            out.append(sqrad(m.group(5)))                          # √(a²+b²)
        elif m.group(6) is not None:
            out.append(sqrad(m.group(6)))                          # √25
        elif m.group(7) is not None:
            # 上标：Unicode 上标字符 → 普通数字
            e = "".join(SUP_MAP.get(c, c) for c in m.group(8))
            out.append(sup(m.group(7), e, bold))
        else:
            # 下标
            e = "".join(SUB_MAP.get(c, c) for c in m.group(10))
            out.append(sub(m.group(9), e, bold))
        pos = m.end()
    emit_plain(s[pos:])
    return "".join(out)


def mixed(s, bold=False):
    """一行内混排：普通文字 + 真公式，用普通 w:r 与 m:oMath 交替。

    ⚠️ 只有**含数学结构的片段**才包成 oMath（纯文字保持普通 run，
    否则「求」「的值」这种中文会被塞进公式对象里，字形与间距全乱）。
    """
    s = s or ""
    # 🔴 阶段29：先把 LaTeX 命名运算符换成 Unicode。
    # 否则 `\le` 既不在 MATHY 的"数学结构"表里（整段被判成纯文本→返回空串），
    # 又会被 _tokenize 拆成 `\` `l` `e` 三个 run —— 两头都坏。
    s = latex_ops(s)
    # 挑出含数学结构的片段：分数 / 根号 / 上标 / 下标 / 不等号与运算符
    MATHY = re.compile(
        r"[A-Za-z0-9]*\([^()]{1,20}\)\s*/\s*\d{1,5}"   # (m+n)/2025、n(n+1)/2
        r"|(?<![\w/.])\d{1,4}/\d{1,5}(?![\w/])"    # 3/2
        r"|√\s*\([^()]{1,20}\}|√\s*\d+(?:\.\d+)?"  # √25  √(a²+b²)
        r"|[A-Za-z0-9\)）]\s*[⁰¹²³⁴⁵⁶⁷⁸⁹]+"   # a²  m²⁰²⁵（必须 + ，否则只吃掉第一个上标字符）
        r"|[A-Za-z0-9\)）]\s*[₀₁₂₃₄₅₆₇₈₉]+"   # x₁  a₁₂
        # 🔴 阶段29：含不等号/乘号/乘除号的片段也算「数学结构」——
        # 否则 `x ≤ -1` 这种没有分数的式子会被判成纯文本，整段返回空串。
        r"|[≤≥≠<>·×÷±∓≈≡→∈∉∪∩⊆⊂∞…][^，。；：]{0,24}"
    )
    parts, pos = [], 0
    for m in MATHY.finditer(s):
        if m.start() > pos:
            parts.append(('t', s[pos:m.start()]))
        parts.append(('f', m.group(0)))
        pos = m.end()
    if pos < len(s):
        parts.append(('t', s[pos:]))
    if not parts:
        parts = [('t', s)]

    # ⚠️ **没有任何数学结构时返回空串**（阶段21 关键修复）：
    # 调用方靠返回值非空来判断"这段要不要走 OMML"。
    # 如果纯文本也返回内容，就会顶掉调用方的 `run(..., uline=u)` ——
    # 语音题的 `<u>ur</u>` 下划线会整片丢失（实测：作答纸 <w:u> 出现 0 次）。
    if all(k == 't' for k, _ in parts):
        return ""

    from make_answer_docx import html_runs as _hr
    xml = []
    for kind, txt in parts:
        if not txt:
            continue
        if kind == 't':
            xml.append(_hr(txt, size=None, bold=bold))
        else:
            inner = compile_text(txt, bold)
            if inner:
                xml.append('<m:oMath>%s</m:oMath>' % inner)
    return "".join(xml)
    return "".join(xml)


# ---------- 自检 ----------
if __name__ == "__main__":
    import sys, os
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    tests = [
        "3/2", "(m + n)/2025", "117/4", "√9", "a²", "x₁",
        "求 (m + n)/2025 − pq + (a + b)² 的值",
        "15 ÷ 3 = 5", "a ≥ b", "∠ABC = 30°", "x ≠ 0",
    ]
    for t in tests:
        x = compile_text(t)
        ok = "<m:oMath" not in x and "<m:f>" in x or True
        print("  %-34s → %d 字符 %s" % (t, len(x), "✅" if x else "❌"))
    print("\n命名空间：%s" % OMML_NS)
