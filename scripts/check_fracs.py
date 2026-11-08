# -*- coding: utf-8 -*-
"""分数渲染核对：确保每个分数都渲染成「分子在上 / 分母在下」。

阶段21 用户发现网页把 `(m+n)/2025` 的 2025 显示成**指数**而不是分母。
根因：MathML `<mfrac>` 只接受 2 个孩子，第一版给了 4 个（分子被拆成多段）。
本脚本把「结构正确」变成机器判定。

## 判定原则（阶段21 修正，避免误报）

**不同产物印的内容本来就不同**，不能用一个标准卡所有：

| 产物 | 印什么 | 该有几个分数 |
|:--|:--|:--|
| 作答纸 docx/html | **只印题干** | 只有题干里的 |
| 单日讲义（daily） | 题干，答案已剥掉 | 只有题干里的 |
| 答案册 docx/html | 题干 + 答案 + 解析 | 全部 |
| 合集讲义（build） | 题干 + 答案 + 解析 | 全部 |

所以判定只查两件**真错误**：
1. **结构错误**：html 的 `<mfrac>` 孩子数 ≠ 2（会被浏览器渲染成指数/错位）
2. **分母为空**：分数没有分母
3. **凭空多出的分数**：产物里的分数在 DSL 里找不到（说明渲染串了）

**不**要求「产物必须包含所有 DSL 分数」—— 那是内容职责，不是渲染职责。
"""
import io
import os
import re
import sys
import zipfile

SK = r"<SKILL_DIR>\scripts"
R = r"<WORKSPACE>\07_技能与脚本\build_workspace"
sys.path.insert(0, SK)

import dsl_source as D  # noqa: E402


def _norm(x):
    """归一化：去掉所有空白。

    ⚠️ 必须做 —— DSL 写 `(m + n)/2025`（带空格），渲染后 MathML 里
    空格被吃掉变成 `(m+n)`，不归一化会全部误报「凭空多出」。
    """
    return re.sub(r'\s+', '', x)


def dsl_fracs():
    """DSL 里所有分数 {(分子, 分母)} —— 题干 + 答案 + 解析，用于查「凭空多出」。"""
    seen = set()
    for d in D.load_days(os.path.join(R, "_p5")):
        for q in d["qs"]:
            blob = q["stem"] + " " + q.get("sol", "") + " " + q.get("ans", "")
            for m in re.finditer(
                    r"<span class='fr'><span class='nu'>(.*?)</span>"
                    r"<span class='de'>(.*?)</span></span>", blob, re.S):
                num = re.sub(r"<[^>]+>", "", m.group(1)).strip()
                den = re.sub(r"<[^>]+>", "", m.group(2)).strip()
                seen.add((_norm(num), _norm(den)))
    return seen


KID = re.compile(
    r"<mrow>.*?</mrow>|<mn>[^<]*</mn>|<mi>[^<]*</mi>"
    r"|<mo[^>]*>[^<]*</mo>|<msup>.*?</msup>|<msub>.*?</msub>"
    r"|<msqrt>.*?</msqrt>|<mfrac>.*?</mfrac>", re.S)


def check_html(path, known):
    """html：每个 <mfrac> 必须恰好 2 个孩子；分母不能空。"""
    t = io.open(path, encoding="utf-8").read()
    n, bad = 0, []
    for m in re.finditer(r"<mfrac>(.*?)</mfrac>", t, re.S):
        inner = m.group(1)
        kids = KID.findall(inner)
        n += 1
        if len(kids) != 2:
            txt = re.sub(r"<[^>]+>", "", inner)[:32]
            bad.append("结构错：<mfrac> 有 %d 个孩子（必须 2）→ 「%s」"
                       % (len(kids), txt))
            continue
        num = re.sub(r"<[^>]+>", "", kids[0]).strip()
        den = re.sub(r"<[^>]+>", "", kids[1]).strip()
        if not den:
            bad.append("分母为空：分子「%s」" % num[:24])
        elif known and (_norm(num), _norm(den)) not in known:
            bad.append("凭空多出：%s / %s（DSL 里没有这对分子分母）" % (num[:20], den[:12]))
    # ⚠️ 裸 Unicode 上标残留 = 没渲染成真指数（用户：「该是指数要是指数」）
    bare = len(re.findall(r"[⁰¹²³⁴⁵⁶⁷⁸⁹]", t))
    if bare:
        bad.append("残留裸上标 %d 个（未渲染成 <msup> 真指数）" % bare)
    return n, bad


def check_docx(path, known):
    """docx：每个 <m:f> 必须同时有 <m:num> 与 <m:den>，且分母非空。"""
    x = zipfile.ZipFile(path).read("word/document.xml").decode("utf-8")
    n, bad = 0, []
    for m in re.finditer(r"<m:f>(.*?)</m:f>", x, re.S):
        inner = m.group(1)
        num = re.search(r"<m:num>(.*?)</m:num>", inner, re.S)
        den = re.search(r"<m:den>(.*?)</m:den>", inner, re.S)
        n += 1
        if not (num and den):
            bad.append("结构错：<m:f> 缺 num 或 den")
            continue
        nt = re.sub(r"<[^>]+>", "", num.group(1)).strip()
        dt = re.sub(r"<[^>]+>", "", den.group(1)).strip()
        if not dt:
            bad.append("分母为空：分子「%s」" % nt[:24])
        elif known and (_norm(nt), _norm(dt)) not in known:
            bad.append("凭空多出：%s / %s" % (nt[:20], dt[:12]))
    bare = len(re.findall(r"[⁰¹²³⁴⁵⁶⁷⁸⁹]", x))
    if bare:
        bad.append("残留裸上标 %d 个（未渲染成 <m:sSup> 真指数）" % bare)
    return n, bad


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    known = dsl_fracs()
    print("DSL 里的分数（去重）：%d 种" % len(known))
    for num, den in sorted(known):
        print("   %s / %s" % (num, den))

    print()
    targets = [
        ("单日讲义 Day2", "学生_DayN_讲义_YYYYMMDD.html", "html", False),
        ("作答纸 Day2 docx", "学生_DayN_作答纸_YYYYMMDD.docx", "docx", False),
        ("作答纸合集 docx", "学生_七天作答纸合集.docx", "docx", False),
        ("作答纸合集 html", "学生_七天作答纸合集.html", "html", False),
        ("答案册 docx", "学生_七天题目详解与答案.docx", "docx", True),
        ("答案册 html", "学生_七天题目详解与答案.html", "html", True),
    ]

    total_bad = 0
    for label, fn, kind, strict in targets:
        p = os.path.join(R, fn)
        if not os.path.exists(p):
            print("  %-18s ⚠ 不存在" % label)
            continue
        # strict：答案册才反查「凭空多出」（它印全部内容，能对得上）
        n, bad = (check_docx(p, known if strict else set()) if kind == "docx"
                  else check_html(p, known if strict else set()))
        flag = "✅" if not bad else "❌"
        print("  %-18s 分数 %3d 个　%s" % (label, n, flag))
        for b in bad:
            print("       " + b)
        total_bad += len(bad)

    # 单独汇总「结构错」——这是致命的
    print()
    print("结论：%s" % ("✅ 全部渲染正确" if total_bad == 0 else "❌ %d 处问题" % total_bad))
    return 0 if total_bad == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
