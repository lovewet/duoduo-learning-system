#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""DSL 分数规范化：把数学斜杠分数改成真分数（竖式），阶段21 用户要求。

**为什么必须做**：本项目 §5A.14 规范第①条明写「分式写成分数形式，
分子分母各占一行，中间一条横线，**不能写成斜杠**」。
但题干、解析、答案里全都是 `3/2`、`(m+n)/2025`、`117/4` —— **规范卡教孩子
别写斜杠，题目自己却满篇斜杠**，说不过去。孩子照着题面抄，写出来的就是斜杠。

**改什么、不改什么**（误改比漏改更糟）：
| 改（真分数） | 不改（正常斜杠用法） |
|:--|:--|
| `3/2`、`−11/2`、`117/4`、`(m + n)/2025` | `4/8 分`（得分）、`d/f/l/m/n/s/p`（元音字母）、`ur / er / ir`、`A/B/C/D` 选项、`ln 2` 等 |
| `121/4`、`29.25` 保持小数 | 时间 `4:21`（不是斜杠）、日期 |

判定规则（宁可漏改也不误改）：
1. 必须是**纯数字/字母构成的分数**（分子分母都是数字、单个大写字母、
   或带括号的算式）；
2. 分母**必须不含**空格分隔的多个字母（`d/f/l/m/n` 直接排除）；
3. 分母长度 ≤ 4（`2025` 可以，`abcd` 疑似字母组合排除）；
4. 排除得分语境（前面 6 字内含「分」且分母 ≤ 12）。

输出用 <b> 包裹的竖式标签，由 CSS 渲染成真分数版式：
   <b class="fr"><span class="nu">3</span><span class='de'>2</span></b>
docx 侧由 make_answer_docx 识别 class="fr" 并渲染成上下两格。

用法：
    python fix_fractions.py            # dry-run，只报告
    python fix_fractions.py --apply    # 落盘
"""
import io, os, re, sys, glob

SRC = r"<WORKSPACE>\07_技能与脚本\build_workspace\_p5"

# 分数：分子分母都限定在「数字、单个大写字母、括号算式」内
# 分母必须以数字或 ) 结尾，且总长 ≤ 4（避免 ur/er、d/f 这类字母组合）
ATOM = r"(?:[0-9]+|[A-Za-z]|\([^()]{1,14}\)|[−\-][0-9]+)"
FRAC_RE = re.compile(
    r"(?<![\w/])"                 # 前面不是字母数字或斜杠（防二次匹配、URL）
    r"(?P<num>" + ATOM + r")"
    r"/"
    r"(?P<den>(?=[0-9)])"        # 分母必须以数字开头 → 排除 d/f/l、ur/er
    r"[0-9]{1,4})"
    r"(?![\w/])"                  # 后面不是字母数字或斜杠
)

# 得分语境：分母前面（同一句内）出现「分」字，如 "4/8 分"
SCORE_RE = re.compile(r"[0-9]{1,2}/[0-9]{1,2}\s*分")


def is_score(text, start):
    """判断该处斜杠是否是「得分」（如 4/8 分）。看它后面 8 字内有没有「分」。"""
    tail = text[start:start + 12]
    m = re.match(r"^[0-9]{1,2}/[0-9]{1,2}\s*分", tail)
    return bool(m)


def convert(text):
    """返回 (新文本, 命中列表[(原文, 替换后)])。"""
    hits = []

    # ⭐ 转换逻辑统一走 frac_render.slashes_to_frac（唯一真源，避免两处实现漂移）
    import frac_render as _FR
    new, hits = _FR.slashes_to_frac(text)
    return new, hits


def main():
    apply_ = "--apply" in sys.argv
    total = 0
    for f in sorted(glob.glob(os.path.join(SRC, "day*.txt"))):
        s = io.open(f, encoding="utf-8").read()
        new, hits = convert(s)
        if not hits:
            continue
        total += len(hits)
        print("\n%s  %d 处" % (os.path.basename(f), len(hits)))
        seen = set()
        for a, b in hits:
            if a in seen:
                continue
            seen.add(a)
            print("   %-14s → 分数竖式" % a)
        if apply_:
            io.open(f, "w", encoding="utf-8", newline="\n").write(new)
            print("   ✓ 已落盘")
    print("\n合计 %d 处%s" % (total, "（已落盘）" if apply_ else "（dry-run，加 --apply 落盘）"))


if __name__ == "__main__":
    main()
