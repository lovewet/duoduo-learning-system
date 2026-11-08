#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""MathML 真数学排版（网页端）—— 与 docx 的 OMML 对应。

阶段21 用户要求：「要渲染成真正的数学的写法」。

## ⚠️ 曾经踩过的致命坑（务必保留这段注释）

`<mfrac>` 在 MathML 规范里**必须恰好有 2 个子元素**（分子、分母）。
第一版把分子拆成了多个并列元素：

    <mfrac><mi>m</mi><mo>+</mo><mi>n</mi><mn>2025</mn></mfrac>   ← 4 个孩子，错

浏览器拿到这种结构只能瞎猜，结果 **2025 被当成指数显示**，
而不是分母 —— 用户一眼看出来了。

修法两条，缺一不可：
1. 分子/分母各自用 `<mrow>` **包成一个孩子**；
2. `_plain()` 里**连续数字必须合并成一个 `<mn>`**（否则 2025 → 四个 2/0/2/5）。

## 覆盖元素
真分数 `<mfrac>` / 根号 `<msqrt>` / 上标 `<msup>` / 下标 `<msub>`
/ 括号 `<mo stretchy>`。变量斜体、数字与运算符正立（教材体例）。
"""
import re

# ==================== 元素构造 ====================
def _wrap(x):
    """把一个片段包成**单个**孩子。

    ⚠️ 这是 `<mfrac>`/`<msup>`/`<msub>` 能正确渲染的前提：
    这些元素都要求「每个位置恰好 1 个孩子」，多个并列会渲染错乱。
    """
    x = x.strip()
    if not x:
        return "<mrow></mrow>"
    # 已经是单个完整元素就直接用（省一层 mrow，输出更干净）
    if re.match(r'^<m[a-z]+[ >].*</m[a-z]+>$', x, re.S) and x.count("<m") == 1:
        return x
    return "<mrow>%s</mrow>" % x


def frac(num, den):
    """真分数 <mfrac>：**分子分母各包一个 mrow**，这是唯一正确写法。"""
    return "<mfrac>%s%s</mfrac>" % (_wrap(num), _wrap(den))


def sqrad(body):
    """根号 <msqrt>：自带上横线（覆盖被开方数）。"""
    return "<msqrt>%s</msqrt>" % _wrap(body)


def msup(base, exp):
    return "<msup>%s%s</msup>" % (_wrap(base), _wrap(exp))


def msub(base, idx):
    return "<msub>%s%s</msub>" % (_wrap(base), _wrap(idx))


def mrow(*items):
    return "<mrow>%s</mrow>" % "".join(items)


def fenced(body, beg="(", end=")"):
    """自动伸缩括号（随内容高度变化）。"""
    return ('<mrow><mo stretchy="true">%s</mo>%s'
            '<mo stretchy="true">%s</mo></mrow>' % (beg, body, end))


def mi(t):
    return '<mi>%s</mi>' % t


def mn(t):
    return '<mn>%s</mn>' % t


def mo(t):
    return '<mo>%s</mo>' % t


def mtext(t):
    return '<mtext>%s</mtext>' % t


# ==================== 文本 → MathML ====================
_VARS = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ")
SUP_MAP = {"⁰": "0", "¹": "1", "²": "2", "³": "3", "⁴": "4",
           "⁵": "5", "⁶": "6", "⁷": "7", "⁸": "8", "⁹": "9"}
SUB_MAP = {"₀": "0", "₁": "1", "₂": "2", "₃": "3", "₄": "4",
           "₅": "5", "₆": "6", "₇": "7", "₈": "8", "₉": "9"}


def _esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


# ==================== LaTeX 命令 → Unicode ====================
# 🔴 阶段29 实测踩坑：`_plain` 只按**单字符**切分，`\le` 会被拆成
# `<mo>\</mo><mi>l</mi><mi>e</mi>` 三个 run —— 浏览器上显示成 "\l e"，公式直接报废。
# 根因不是 mfrac，是**运算符命令根本没进识别表**。
# 修法：在切分之前先把 LaTeX 命名运算符替换成等价的 Unicode 符号，
# 让 `_plain` 只处理单字符即可（Unicode 符号走 mo，符合教材体例）。
# ⚠️ 这层是**纯替换**，不做 LaTeX 解析 —— 真正复杂的公式仍走 latex2mathml。
_LATEX_OPS = {
    r"\leqslant": "≤", r"\geqslant": "≥",
    r"\leq": "≤", r"\geq": "≥",
    r"\le": "≤", r"\ge": "≥",
    r"\neq": "≠", r"\ne": "≠",
    r"\cdot": "·", r"\times": "×", r"\div": "÷",
    r"\pm": "±", r"\mp": "∓",
    r"\approx": "≈", r"\equiv": "≡",
    r"\rightarrow": "→", r"\to": "→",
    r"\in": "∈", r"\notin": "∉",
    r"\cup": "∪", r"\cap": "∩",
    r"\subset": "⊂", r"\subseteq": "⊆",
    r"\infty": "∞",
    r"\ldots": "…", r"\cdots": "⋯",
    r"\quad": "　", r"\qquad": "　　",
    r"\,": " ", r"\;": " ", r"\!": "",
    # LaTeX 的「控制空格」`\ ` —— 在数学里表示一个空格间距。
    # 不映射的话会被 _plain 当成字面反斜杠，渲染成 <mo>\</mo>（实测踩到）。
    "\\ ": " ",
}
_LATEX_RE = re.compile("|".join(re.escape(k) for k in
                          sorted(_LATEX_OPS, key=len, reverse=True)))


def latex_ops(s):
    """把 LaTeX 命名运算符换成 Unicode（幂等，可重复调用）。"""
    if not s or "\\" not in s:
        return s
    return _LATEX_RE.sub(lambda m: _LATEX_OPS[m.group(0)], s)


def _plain(t):
    """普通文本 → MathML run 序列。

    ⚠️ **连续数字必须合并成一个 `<mn>`** —— 逐字符拆成
    `<mn>2</mn><mn>0</mn><mn>2</mn><mn>5</mn>` 会让数字间距变宽、
    且把 mfrac 的孩子数搞错（实测导致 2025 显示成指数）。
    """
    out, i = [], 0
    while i < len(t):
        ch = t[i]
        if ch.isspace():
            i += 1
            continue
        if ch.isdigit():
            j = i
            while j < len(t) and (t[j].isdigit() or t[j] == "."):
                j += 1
            out.append(mn(_esc(t[i:j])))
            i = j
            continue
        if ch in _VARS:
            out.append(mi(_esc(ch)))
        else:
            out.append(mo(_esc(ch)))
        i += 1
    return "".join(out)


# 公式片段识别。顺序：长的在前，避免被短规则抢走。
TOKEN = re.compile(
    r"([A-Za-z0-9]*\([^()]{1,20}\))\s*/\s*(\d{1,5})"   # (m+n)/2025、n(n+1)/2
    r"|(?<![\w/.])(\d{1,4})/(\d{1,5})(?![\w/])"    # 3/2
    r"|√\s*\(([^()]{1,20})\)"                      # √(a²+b²)
    r"|√\s*(\d+(?:\.\d+)?)"                        # √25
    r"|([A-Za-z0-9\)）])\s*([⁰¹²³⁴⁵⁶⁷⁸⁹]+)"      # a²（Unicode 上标）
    r"|([A-Za-z0-9\)）])\s*([₀₁₂₃₄₅₆₇₈₉]+)"      # x₁（Unicode 下标）
)


def compile_mathml(s):
    """把题面文字编译成 MathML 片段（不含外层 <math>）。"""
    if not s:
        return ""
    s = latex_ops(s)
    out, pos = [], 0

    def emit(t):
        if t:
            out.append(_plain(t))

    for m in TOKEN.finditer(s):
        emit(s[pos:m.start()])
        if m.group(1) is not None:                       # (m+n)/2025
            # ⚠️ group(1) 已含括号（正则里带了 `\(...\)`），
            # 不能再 fenced() 包一层 —— 否则渲染成 `((m+n))` 双括号。
            out.append(frac(_plain(m.group(1)), mn(m.group(2))))
        elif m.group(3) is not None:                     # 3/2
            out.append(frac(mn(m.group(3)), mn(m.group(4))))
        elif m.group(5) is not None:                     # √(a²+b²)
            out.append(sqrad(compile_mathml(m.group(5))))
        elif m.group(6) is not None:                     # √25
            out.append(sqrad(mn(m.group(6))))
        elif m.group(7) is not None:                     # a²
            e = "".join(SUP_MAP.get(c, c) for c in m.group(8))
            out.append(msup(mi(_esc(m.group(7))), mn(e)))
        else:                                            # x₁
            e = "".join(SUB_MAP.get(c, c) for c in m.group(10))
            out.append(msub(mi(_esc(m.group(9))), mn(e)))
        pos = m.end()
    emit(s[pos:])
    return "".join(out)


def mathml(s):
    """完整 MathML 公式对象。"""
    inner = compile_mathml(s)
    if not inner:
        return ""
    return ('<math xmlns="http://www.w3.org/1998/Math/MathML" display="inline">'
            '<mstyle displaystyle="false">%s</mstyle></math>' % inner)


# ==================== 与旧 `<span class="fr">` 标记对接 ====================
FR_SPAN = re.compile(
    r"<span class=['\"]fr['\"]><span class=['\"]nu['\"]>(.*?)</span>"
    r"<span class=['\"]de['\"]>(.*?)</span></span>", re.S)


def upgrade(s):
    """把 HTML 里的 CSS 分数标记 + **裸 Unicode 上标**都换成 MathML 真公式。

    分子/分母里可能带 <b>/<u>，先剥掉再用 MathML 排版
    （公式内强调要用 mathvariant，不依赖 HTML 标签）。

    ⚠️ **两件事都要做**（阶段21 用户：「该是指数要是指数」）：
    1. `<span class='fr'>` 分数标记 → `<mfrac>`
    2. 正文里裸的 `m²⁰²⁵`、`(a+b)²` → `<msup>`（这些从来没被处理过，
       之前只是 Unicode 上标字符，不是真的数学指数）
    """
    def rep(m):
        num = re.sub(r"<[^>]+>", "", m.group(1)).strip()
        den = re.sub(r"<[^>]+>", "", m.group(2)).strip()
        return mathml_raw(num, den)
    s = FR_SPAN.sub(rep, s)
    return upgrade_sup(s)


# 裸上标：底（单个字母/数字/右括号）+ Unicode 上标串
_BARE_SUP = re.compile(r"([A-Za-z0-9\)\]）])\s*([⁰¹²³⁴⁵⁶⁷⁸⁹]+)")


def _supify_text(t):
    """把文本节点里的裸 Unicode 上标转成 <msup>。"""
    def rep(m):
        e = "".join(SUP_MAP.get(c, c) for c in m.group(2))
        base = m.group(1)
        # 底按语义选标签：数字 mn / 括号 mo / 字母 mi（斜体）
        if base.isdigit() or base == ".":
            b = mn(_esc(base))
        elif base in ")]）":
            b = mo(_esc(base))      # 右括号：教材里上标挂在右括号右上角
        else:
            b = mi(_esc(base))
        # ⚠️ 上标用 HTML `<sup>`，**不用 MathML `<msup>`**（阶段22 修）：
        # MathML 在 Word 粘贴、部分预览器里不渲染，`(b−10)²` 会退化成
        # `(b−10)2`（用户看到的就是这个）。`<sup>` 所有浏览器/编辑器都认。
        # 分数仍用 MathML（`<mfrac>` 无可替代）。
        return "%s<sup>%s</sup>" % (_esc(base), e)
    return _BARE_SUP.sub(rep, t)


def upgrade_sup(html):
    """只对**文本节点**做上标替换，绝不碰标签、CSS、JS。

    ⚠️ 绝不能对整份 HTML 直接正则替换 —— 会改坏 `<style>` 里的
    `content:"²"` 或 class 名。必须先切出标签与文本，
    并把 `<style>/<script>` 整块占位保护。
    """
    if not html:
        return html
    guards = []

    def guard(m):
        guards.append(m.group(0))
        return "\x01G%d\x01" % (len(guards) - 1)
    s = re.sub(r"<(style|script)\b[^>]*>.*?</\1>", guard, html, flags=re.S | re.I)
    parts = re.split(r"(<[^>]+>)", s)
    for i in range(0, len(parts), 2):        # 偶数下标是文本节点
        if parts[i]:
            parts[i] = _supify_text(parts[i])
    s = "".join(parts)
    return re.sub(r"\x01G(\d+)\x01", lambda m: guards[int(m.group(1))], s)


def mathml_raw(num, den):
    """直接用给定分子分母造真分数 MathML（**分子分母各包一个 mrow**）。"""
    return ('<math xmlns="http://www.w3.org/1998/Math/MathML" display="inline">'
            '<mstyle displaystyle="false">%s</mstyle></math>'
            % frac(_plain(num), _plain(den)))


# ==================== 自检 ====================
if __name__ == "__main__":
    import sys
    if sys.platform == "win32":
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass
    tests = ["3/2", "(m + n)/2025", "117/4", "√9", "√(a²+b²)", "a²", "x₁",
             "求 (m + n)/2025 − pq + (a + b)² 的值"]
    print("=== mfrac 孩子数必须是 2 ===")
    for t in tests:
        x = compile_mathml(t)
        for mf in re.findall(r"<mfrac>(.*?)</mfrac>", x, re.S):
            n = len(re.findall(r"<m[a-z]+[ >]", mf))
            # 顶层孩子数：把 mrow 当 1 个
            tops = re.findall(r"<mrow>.*?</mrow>|<mn>[^<]*</mn>|<mi>[^<]*</mi>|<mo>[^<]*</mo>|<msqrt>.*?</msqrt>", mf, re.S)
            print("  %-22s 顶层孩子 %d %s" % (t, len(tops), "✅" if len(tops) == 2 else "❌"))
            break
    print()
    print("=== (m+n)/2025 完整结构 ===")
    print(mathml("(m + n)/2025"))
