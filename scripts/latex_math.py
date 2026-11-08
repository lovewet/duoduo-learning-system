#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""latex_math.py — LaTeX 数学式 → MathML / OMML（现成库适配层）

设计原则：**能用现成库就不自己写**
--------------------------------
阶段22 用户明确要求：「市场中有现成的工具就一定要使用」。

第一版这里写过一个 N行的自制 LaTeX 递归下降解析器，用例能过，
但那是重复造轮子：符号表永远补不全，还自己踩出 cases 渲染成空表的 bug
（`\\cong` 没映射就印成字面量、`array` 的列格式被当成内容）。
现已全部换成成熟库：

    LaTeX ──latex2mathml(3.81+)──▶ MathML        （网页 / 答案册 html）
                                 └─mathml2omml──▶ OMML（Word / 作答纸 docx）

本文件只剩四件真正需要的事：
  1. 统一入口（两个函数两种出口，调用方不关心底层库）
  2. **注入 Cambria Math 字体** —— Word 公式必须印刷体，技能铁律
  3. 失败兜底（latex2mathml 遇不支持的命令会抛异常 → 安全文本，不崩流水线）
  4. `normalize` 去 $ 包裹、`find_latex` 从混排文本里抠公式

用法
----
    from latex_math import latex_to_mathml, latex_to_omml, find_latex
    latex_to_mathml(r"\\frac{1}{2}x^2+\\sqrt{3}")
    latex_to_omml(r"x^{2}=4")

命令行
------
    python latex_math.py                 # 自检
    python latex_math.py "\\frac{1}{2}"  # 打印单个式子的两种输出
"""

from __future__ import annotations

import re
import sys

DEFAULT_FONT = 'Cambria Math'
OMML_NS = 'http://schemas.openxmlformats.org/officeDocument/2006/math'

# ---- 现成库 ----
_HAVE_L2M = _HAVE_M2O = False
try:
    import latex2mathml.converter as _l2m
    _HAVE_L2M = True
except ImportError:
    _l2m = None
try:
    import mathml2omml as _m2o
    _HAVE_M2O = bool(getattr(_m2o, 'convert', None))
except ImportError:
    _m2o = None


def _esc(s):
    return (str(s).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;'))


# ==================== 归一化 ====================

def normalize(s: str) -> str:
    """去掉 $...$ / $$...$$ / \\(...\\) / \\[...\\] 包裹，压平空白。"""
    if not s:
        return ''
    t = s.strip()
    for beg, end in (('$$', '$$'), ('$', '$'), ('\\[', '\\]'), ('\\(', '\\)')):
        if t.startswith(beg) and t.endswith(end) and len(t) > len(beg) + len(end) - 1:
            t = t[len(beg):len(t) - len(end)].strip()
            break
    t = t.replace('\\dfrac', '\\frac').replace('\\tfrac', '\\frac')
    t = re.sub(r'[\r\n\t]+', ' ', t)
    return re.sub(r'\s{2,}', ' ', t).strip()


_INLINE = re.compile(r'\$\$(.+?)\$\$|\$(.+?)\$|\\\((.+?)\\\)|\\\[(.+?)\\\]', re.S)


def find_latex(text: str):
    """从混排文本里抠出所有公式片段。"""
    return [next(g for g in m.groups() if g is not None).strip()
            for m in _INLINE.finditer(text or '')]


def has_latex(text: str) -> bool:
    return bool(_INLINE.search(text or ''))


# ==================== 出口一：MathML ====================

def latex_to_mathml(latex: str, display=False) -> str:
    """LaTeX → 完整 <math> 对象（可直接嵌 HTML）。

    失败时返回安全的 <mtext>，绝不抛异常打断整条流水线 ——
    一道题的公式坏了不该让整张卷子生不出来。
    """
    src = normalize(latex)
    if not src:
        return ''
    if _HAVE_L2M:
        try:
            ml = _l2m.convert(src)
            if display and 'display="inline"' in ml:
                ml = ml.replace('display="inline"', 'display="block"', 1)
            return ml
        except Exception:
            pass
    return ('<math xmlns="http://www.w3.org/1998/Math/MathML" display="%s">'
            '<mtext>%s</mtext></math>'
            % ('block' if display else 'inline', _esc(src)))


# ==================== 出口二：OMML ====================

_RUN = re.compile(r'<m:r>(?!<w:rPr>)')


def inject_font(omml: str, font=DEFAULT_FONT) -> str:
    """给每个公式 run 注入 Cambria Math 字体（Word 印刷体铁律）。"""
    w = ('<w:rPr><w:rFonts w:ascii="%s" w:hAnsi="%s" w:cs="%s"/></w:rPr>'
         % (font, font, font))
    return _RUN.sub('<m:r>' + w, omml)


def latex_to_omml(latex: str) -> str:
    """LaTeX → 完整 <m:oMath> 对象。

    ⚠️ 放进 <w:p> 之前，文档必须声明 math 命名空间：
        xmlns:m="http://schemas.openxmlformats.org/officeDocument/2006/math"
    """
    src = normalize(latex)
    if not src:
        return ''
    if _HAVE_L2M and _HAVE_M2O:
        try:
            ml = _l2m.convert(src)
            om = _m2o.convert(ml)
            om = re.sub(r'^<math[^>]*>|</math>$', '', om.strip())
            if om.startswith('<m:oMath'):
                return inject_font(om)
            return inject_font('<m:oMath>%s</m:oMath>' % om)
        except Exception:
            pass
    return ('<m:oMath><m:r><w:rPr><w:rFonts w:ascii="%s" w:hAnsi="%s"/></w:rPr>'
            '<m:rPr><m:sty m:val="p"/></m:rPr>'
            '<m:t xml:space="preserve">%s</m:t></m:r></m:oMath>'
            % (DEFAULT_FONT, DEFAULT_FONT, _esc(src)))


# ==================== 混排：正文里的 $...$ ====================

def splice(text: str, to='mathml') -> str:
    """把混排文本里的 $...$ 就地换成公式对象，其余部分保持原样。

    ⚠️ 调用方负责对"非公式部分"做 HTML 转义；本函数只处理公式替换。
    """
    fn = latex_to_mathml if to == 'mathml' else latex_to_omml

    def rep(m):
        raw = next(g for g in m.groups() if g is not None)
        return fn(raw)

    return _INLINE.sub(rep, text or '')


# ==================== 自检 ====================

CASES = [
    r'\frac{1}{2}',
    r'x^{2}-3x+2=0',
    r'\sqrt{3}\approx1.732',
    r'\frac{\sqrt{5}-1}{2}',
    r'\left(\frac{a}{b}\right)^{2}',
    r'\sqrt[3]{-8}=-2',
    r'\angle ABC=90^{\circ}',
    r'\triangle ABC\cong\triangle DEF',
    r'\begin{cases}x+y=5\\x-y=1\end{cases}',
    r'\sin 30^{\circ}=\frac{1}{2}',
    r'AB\parallel CD',
    r'\frac{x-1}{x+2}\div\frac{x^{2}-1}{x}',
]


def self_test(verbose=True):
    print('latex2mathml=%s  mathml2omml=%s' % (_HAVE_L2M, _HAVE_M2O))
    bad = 0
    for c in CASES:
        ml, om = latex_to_mathml(c), latex_to_omml(c)
        # 判定：两端非空，且没掉进兜底分支（兜底会把 LaTeX 原文塞进 mtext/m:t）
        fell_back = ('<mtext>' in ml and '\\' in ml) or ('\\frac' in om or '\\sqrt' in om)
        if not ml or not om or fell_back:
            bad += 1
            if verbose:
                print('FAIL', c)
        elif verbose:
            print('ok  ', c)
    if verbose:
        print('\n%d/%d 通过' % (len(CASES) - bad, len(CASES)))
    return bad == 0


if __name__ == '__main__':
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    if len(sys.argv) > 1:
        print('--- MathML ---')
        print(latex_to_mathml(sys.argv[1], display=True))
        print('\n--- OMML ---')
        print(latex_to_omml(sys.argv[1]))
    else:
        self_test()
