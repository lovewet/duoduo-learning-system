# -*- coding: utf-8 -*-
"""真分数竖式的公共工具（阶段21 用户要求）。

**背景**：§5A.14 规范第①条明写「分式写成分数形式，分子分母各占一行，
中间一条横线，**不能写成斜杠**」。但题干、解析、答案里全是`3/2`、
`(m+n)/2025`、`117/4` —— **规范卡教孩子别写斜杠，题目自己却满篇斜杠**，
孩子照着题面抄，写出来的必然是斜杠。规范与题面必须一致，故全面改造。

**标记格式**（由 fix_fractions.py 生成，三处产物统一识别）：
    <span class="fr"><span class="nu">分子</span><span class="de">分母</span></span>

**为什么不用 `a/b` 直接替换成 `a⁄b`**：那个 Unicode 分数斜线（U+2044）
仍然是斜杠，只是细一点，不符合印刷规范；且 Word 里不支持真竖排。

**判定哪些斜杠该改、哪些不该**（误改比漏改更糟）：
| 改（真分数）| 不改（斜杠的正常用法） |
|:--|:--|
| `3/2` `−11/2` `117/4` `(m+n)/2025` `2025 分之1` | `4/8 分`（得分）`d/f/l/m/n/s/p`（元音字母组合）`ur / er / ir`（语法术语）`A/B/C/D` |
"""
import re

# 真分数竖式标记的识别正则：**单双引号通吃**
#（DSL 源用单引号，历史产物是双引号，两种都要认）
FR_RE = re.compile(
    r"<span class=['\"]fr['\"]><span class=['\"]nu['\"]>(.*?)</span>"
    r"<span class=['\"]de['\"]>(.*?)</span></span>", re.S)

# 只匹配整块（占位保护用）
FR_BLOCK_RE = re.compile(r"<span class=['\"]fr['\"].*?</span></span>", re.S)

# 只在「数学语境」里转换，避免误伤英语的 d/f、得分 4/8
# 分子形态：数字 / 单字母 / 括号算式 / **字母+括号**（如 n(n+1)）/ 负号数字
_NUM = r"(?:[A-Za-z0-9]*\([^()]{1,14}\)|[0-9]+|[A-Za-z]|[−\-][0-9]+)"
SLASH_FRAC = re.compile(
    r"(?<![\w/])"
    r"(?P<num>" + _NUM + r")"
    r"/"
    r"(?P<den>(?=[0-9])[0-9]{1,4})"
    r"(?![\w/])")


def is_score(text, start):
    """得分语境（`4/8 分`）→ 不改。"""
    return bool(re.match(r"^[0-9]{1,2}/[0-9]{1,2}\s*分", text[start:start + 12]))


def slashes_to_frac(text):
    """把真分数的斜杠写法转成竖式标记；得分/字母组合不动。"""
    out, last, hits = [], 0, []
    for m in SLASH_FRAC.finditer(text):
        if is_score(text, m.start()):
            continue
        out.append(text[last:m.start()])
        num, den = m.group("num"), m.group("den")
        tag = ("<span class='fr'><span class='nu'>%s</span>"
               "<span class='de'>%s</span></span>" % (num, den))
        out.append(tag)
        hits.append((m.group(0), tag))
        last = m.end()
    out.append(text[last:])
    return "".join(out), hits


def protect(s):
    """把竖式标记抠成占位符，防止下游的转义/切分逻辑打散。

    返回 (占位后的串, [原标记...])。
    """
    frs = []

    def _st(m):
        frs.append(m.group(0))
        return "\x00FR%d\x00" % (len(frs) - 1)
    s = FR_RE.sub(_st, s)
    return s, frs


def restore(s, frs):
    """把 protect 的占位符还原成真标记。"""
    return re.sub(r"\x00FR(\d+)\x00", lambda m: frs[int(m.group(1))], s)


def count(text):
    """文本里有多少个竖式分数（验收用）。"""
    return len(FR_RE.findall(text))


def to_lines_keep_frac(s):
    """等价于 dsl_source.to_lines，但**保留分数竖式 + <u> 划线 + <b> 加粗**。

    ⚠️ **`<u>` 必须保留**（阶段21 用户：「英语题该划线的没有划线」）：
    语音辨析题考的就是「画线部分读音」，`to_lines` 把所有标签剥掉后，
    纸上只剩 `nurse`、`surprised`，**孩子不知道要比对哪个字母，题目直接作废**。
    实测：作答纸 docx 的 `<w:u w:val` 出现 0 次，等于全卷划线全丢。

    做法：先把分数标记与 `<u>/<b>` 都换成占位符，剥完标签再还原。
    """
    s, frs = protect(s)
    s = re.sub(r"<br\s*/?>", "\n", s)
    # 保护行内富文本标签（不参与剥除）
    guards = [("<u>", "\x02U1\x02"), ("</u>", "\x02U0\x02"),
              ("<b>", "\x02B1\x02"), ("</b>", "\x02B0\x02")]
    for a, b in guards:
        s = s.replace(a, b)
    s = re.sub(r"<[^>]+>", "", s)
    import html as H
    s = H.unescape(s)
    for a, b in guards:
        s = s.replace(b, a)
    return [restore(x.strip(), frs) for x in s.split("\n") if x.strip()]
