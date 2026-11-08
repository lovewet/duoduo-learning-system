#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""DSL 字段结构审计（出题后必跑，通过才允许跑 build.py）。

## 为什么需要这个脚本

讲义 DSL 用 `|` 作字段分隔符，解析层（`lecture_dsl.render()`）用**倒数字段法**
（从右往左取 `sol/hint/ans/opts`），好处是题干里出现竖线也不会崩 ——
坏处是**字段一错位就会静默产出空白题干或空白题型**：页面照样生成，
构建时才在别处报错，人已经看傻。手工插入新题最容易犯这个错。

本脚本把「字段结构对不对」变成**机器判定**，在构建之前拦住。

## 题型与段数（按整行 `split("|")` 计，含最前面的 kind 段）

| 题型 | 段数 | 结构（从左往右） |
|:--:|:--:|---|
| MC | 6 | `MC \\| 题干 \\| 选项@分隔 \\| 正确索引 \\| 思路 \\| 详解` |
| FILL | 6 | `FILL \\| 题干 \\| 占位 \\| 答案 \\| 思路 \\| 详解` |
| JUDGE | 5 | `JUDGE \\| 题干 \\| 答案要点 \\| 思路 \\| 详解` |

## 用法

```bash
python scripts/dsl_audit.py --dir _p5            # 审计目录下 day1..day8.txt
python scripts/dsl_audit.py --file _p5/day3.txt  # 只审一个文件
python scripts/dsl_audit.py                      # 自动找 _p5/ 或当前目录的 day*.txt
python scripts/dsl_audit.py --selftest           # 离线自检
```

退出码：0 = 全部正常（可跑 build.py）｜1 = 有结构问题｜2 = 找不到源文件 / 参数错。

> 本脚本只做**结构审计**，不含也不产出任何学生数据。
"""
from __future__ import annotations

import argparse
import glob
import io
import os
import re
import sys

# ---------------------------------------------------------------- 常量
# 整行段数（含 kind 段），与 SKILL.md §6.5.5 的表格严格一致
Q_SEG_COUNT = {"MC": 6, "FILL": 6, "JUDGE": 5}

# 三引号块：内部是多行 HTML，**不能按 | 切分**，必须整块跳过
TRIPLE_PREFIXES = ("LOGIC<<<", "LEC<<<", "BJ<<<")

# 其它已知非题目块（只校验不至于误报，不做字段检查）
KNOWN_OTHER = {
    "DAY", "SUB", "VID", "FIG", "ENDDAY", "TITLE", "NOTE", "BOX",
    "TABLE", "HR", "QUOTE", "TAG", "CARD",
}

DEFAULT_DIRS = ("_p5", ".", "dsl", "dsl_source")


# ---------------------------------------------------------------- 扫描
def iter_blocks(text: str):
    """逐块产出 (起始行号, kind, segs, closed, raw)。

    - 三引号块（LOGIC<<< / LEC<<< / BJ<<<）：segs 为空，closed 表示是否有 `>>>` 收口，
      raw 是整个块的行列表。
    - 普通行：segs = 整行按 `|` 切开的列表（[0] 是 kind）。

    不复用 `lecture_dsl.parse()`，因为它在合并三引号块时**丢掉了行号**，
    而本脚本的每条问题都必须能定位到「第几行」。切分规则与 parse() 完全一致。
    """
    lines = text.split("\n")
    i = 0
    while i < len(lines):
        raw = lines[i].rstrip("\r")
        if not raw.strip():
            i += 1
            continue

        hit = next((p for p in TRIPLE_PREFIXES if raw.startswith(p)), None)
        if hit is not None:
            kind = hit[: -len("<<<")]
            start = i + 1
            j = i + 1
            closed = False
            while j < len(lines):
                if lines[j].rstrip("\r").startswith(">>>"):
                    closed = True
                    break
                j += 1
            body = lines[i:j + 1] if closed else lines[i:]
            yield (start, kind, [], closed, body)
            i = (j + 1) if closed else len(lines)
            continue

        segs = raw.split("|")
        yield (i + 1, segs[0].strip(), segs, True, [raw])
        i += 1


# ---------------------------------------------------------------- 检查
class Problem:
    """一条审计问题。"""

    __slots__ = ("lineno", "kind", "desc", "fix")

    def __init__(self, lineno: int, kind: str, desc: str, fix: str):
        self.lineno = lineno
        self.kind = kind
        self.desc = desc
        self.fix = fix

    def __str__(self) -> str:
        return f"  第 {self.lineno:>4} 行  [{self.kind}]  {self.desc}\n               → {self.fix}"


def _is_int(s: str) -> bool:
    return bool(re.fullmatch(r"[+-]?\d+", s.strip()))


def check_question(lineno: int, kind: str, segs: list, out: list) -> None:
    """单道题的结构审计，问题追加到 out。"""
    want = Q_SEG_COUNT[kind]
    got = len(segs)
    payload = segs[1:]

    # ---- 1) 段数
    if got != want:
        if got > want:
            extra = got - want
            # 判断多余段在哪：右侧四个字段里出现竖线最危险（会把取字段整体推偏）
            risk = []
            for name, val in (("选项", payload[-4] if len(payload) >= 4 else ""),
                              ("索引", payload[-3] if len(payload) >= 3 else ""),
                              ("思路", payload[-2] if len(payload) >= 2 else ""),
                              ("详解", payload[-1] if len(payload) >= 1 else "")):
                if "|" in val:
                    risk.append(name)
            out.append(Problem(
                lineno, kind,
                f"段数 {got} 段，多出 {extra} 段（标准 {want} 段）"
                + ("；**右侧字段含半角竖线**：" + "/".join(risk) if risk else ""),
                "题干或字段里的绝对值/竖线一律改用**全角 ｜**（U+FF5C）；"
                "分隔符只能是半角 |。改完重新数段数。",
            ))
        else:
            out.append(Problem(
                lineno, kind,
                f"段数 {got} 段，少 {want - got} 段（标准 {want} 段）",
                "补全缺失字段（顺序见文件头表格），不要靠解析层的倒数字段法兜底。",
            ))
        # 段数不对就不要再往下判字段语义，否则一路误报
        return

    # ---- 2) 字段语义
    if kind == "MC":
        opts_s, idx_s, hint, sol = payload[-4], payload[-3], payload[-2], payload[-1]
        stem = "|".join(payload[:-4]).strip()

        if not stem:
            out.append(Problem(lineno, kind, "题干为空", "倒数字段法把题干吃空了 —— 检查是否字段顺序错位。"))

        # 先判索引段：不是整数时，再区分「整体错位」与「单纯写错」
        if not _is_int(idx_s):
            if _is_int(opts_s) and "@" in idx_s:
                out.append(Problem(
                    lineno, kind,
                    f"字段顺序错位：索引与选项位置颠倒（第4段是 `{opts_s}`，第5段才是选项）",
                    f"改成 `MC|题干|{idx_s}|{opts_s}|思路|详解`。",
                ))
            else:
                out.append(Problem(
                    lineno, kind, f"正确索引 `{idx_s}` 不是整数",
                    "索引是从 0 开始的整数（A=0/B=1/C=2/D=3）。",
                ))
            return

        opts = [o.strip() for o in opts_s.split("@")]
        opts = [o for o in opts if o]
        if len(opts) < 2:
            out.append(Problem(
                lineno, kind, f"选项只有 {len(opts)} 个（要求 ≥2）",
                "选项用半角 @ 分隔，如 `A@B@C@D`。",
            ))
            return

        v = int(idx_s)
        if not (0 <= v < len(opts)):
            out.append(Problem(
                lineno, kind, f"正确索引 {v} 越界（共 {len(opts)} 个选项，合法 0–{len(opts) - 1}）",
                "索引从 0 开始数，不是从 1。",
            ))

    elif kind == "FILL":
        ph, ans, hint, sol = payload[-4], payload[-3], payload[-2], payload[-1]
        stem = "|".join(payload[:-4]).strip()
        if not stem:
            out.append(Problem(lineno, kind, "题干为空", "检查字段顺序是否错位。"))
        if not ans.strip():
            out.append(Problem(
                lineno, kind, "答案段为空",
                "填空必须有答案，否则无法批改；确实无唯一答案就改成 JUDGE 题型。",
            ))

    elif kind == "JUDGE":
        keys, hint, sol = payload[-3], payload[-2], payload[-1]
        stem = "|".join(payload[:-3]).strip()
        if not stem:
            out.append(Problem(lineno, kind, "题干为空", "检查字段顺序是否错位。"))
        if not keys.strip():
            out.append(Problem(
                lineno, kind, "参考答案要点为空",
                "简答题必须给判分要点，否则判分器无从比对。",
            ))


def audit_text(text: str, label: str = "") -> tuple[list, int, int]:
    """审计一份 DSL 文本，返回 (problems, 题数, 块总数)。"""
    problems: list = []
    q_count = 0
    total = 0
    for lineno, kind, segs, closed, body in iter_blocks(text):
        total += 1
        if kind in Q_SEG_COUNT:
            q_count += 1
            check_question(lineno, kind, segs, problems)
            continue
        if kind in ("LOGIC", "LEC", "BJ"):
            if not closed:
                problems.append(Problem(
                    lineno, kind, f"`{kind}<<<` 块没有 `>>>` 收口",
                    "补上独立的 `>>>` 行；未闭合会把后面所有题目都吞进这个块，"
                    "页面直接少一整节。",
                ))
            continue
        if kind in KNOWN_OTHER:
            continue
        problems.append(Problem(
            lineno, kind, f"未知块类型 `{kind}`",
            "拼写检查；已知类型见 lecture_dsl.py 文件头的指令表。"
            "（新类型要么注册进解析层，要么是笔误。）",
        ))
    return problems, q_count, total


# ---------------------------------------------------------------- 源定位
def locate_files(args) -> list:
    """确定要审计的文件列表。"""
    if args.file:
        return [args.file] if os.path.exists(args.file) else []

    dirs = [args.dir] if args.dir else list(DEFAULT_DIRS)
    for d in dirs:
        if not os.path.isdir(d):
            continue
        found = sorted(glob.glob(os.path.join(d, "day*.txt")))
        if found:
            return found
        found = sorted(glob.glob(os.path.join(d, "*.dsl")))
        if found:
            return found
    return []


# ---------------------------------------------------------------- CLI
def run_cli(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="讲义 DSL 字段结构审计（出题后必跑，通过才允许跑 build.py）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--file", help="只审一个 DSL 文件")
    ap.add_argument("--dir", help="审该目录下的 day*.txt（默认依次找 _p5 / . / dsl / dsl_source）")
    ap.add_argument("--selftest", action="store_true", help="离线自检，不读任何外部文件")
    args = ap.parse_args(argv)

    if args.selftest:
        return selftest()

    files = locate_files(args)
    if not files:
        print("❌ 找不到 DSL 源文件。")
        print("   已尝试目录：%s" % ("、".join([args.dir] if args.dir else list(DEFAULT_DIRS))))
        print("   找的是 day1.txt~day8.txt 或 *.dsl。请用 --file 或 --dir 显式指定。")
        return 2

    all_problems: list = []
    total_q = 0
    print("DSL 字段结构审计")
    print("=" * 62)
    for path in files:
        try:
            text = io.open(path, encoding="utf-8").read()
        except Exception as e:
            print(f"  ⚠️ 读取失败：{path}（{e}）")
            continue
        problems, q, _ = audit_text(text, path)
        total_q += q
        all_problems.extend(problems)
        status = "✅" if not problems else f"❌ {len(problems)} 处"
        print(f"  {status:<10} {path}（{q} 道题）")

    print("-" * 62)
    print(f"检查题目：{total_q} 道　问题：{len(all_problems)} 处")

    if not all_problems:
        print("\n✅ 全部正常")
        print("   字段结构一致，可以跑 `python scripts/build.py`。")
        return 0

    print("\n问题清单：")
    for p in all_problems:
        print(str(p))
    print("\n❌ 有结构问题，修完再跑 build.py。")
    return 1


# ---------------------------------------------------------------- 自检
def selftest() -> int:
    """离线自检：不依赖任何工作区文件。"""
    cases = []  # (说明, DSL 文本, 期望问题数)

    ok_mc = "MC|化简 ｜−3｜ 的值|3@−3@±3@−1|0|先判符号|绝对值为非负数。"
    ok_fill = "FILL|3 的相反数是____|____|−3|看符号|相反数改变符号。"
    ok_judge = "JUDGE|说说你为什么这么算|<b class=\"qt\">【题型】说理</b>要写清步骤|抓住符号|第一步定符号。"

    cases.append(("正常 MC", ok_mc, 0))
    cases.append(("正常 FILL", ok_fill, 0))
    cases.append(("正常 JUDGE", ok_judge, 0))

    # MC 少一段
    cases.append(("MC 少一段", "MC|题干|A@B|0|思路", 1))
    # MC 多一段（右侧字段混入半角竖线）
    cases.append(("MC 多一段", "MC|题干|A@B|0|看 |a| 的大小|详解", 1))
    # index 非整数
    cases.append(("MC index 非整数", "MC|题干|A@B@C@D|一|思路|详解", 1))
    # index 越界
    cases.append(("MC index 越界", "MC|题干|A@B@C@D|7|思路|详解", 1))
    # 选项只有 1 个
    cases.append(("MC 选项不足", "MC|题干|A|0|思路|详解", 1))
    # 索引与选项位置颠倒
    cases.append(("MC 索引选项颠倒", "MC|题干|0|A@B@C@D|思路|详解", 1))
    # FILL 答案为空
    cases.append(("FILL 答案为空", "FILL|题干|____||思路|详解", 1))
    # JUDGE 要点为空
    cases.append(("JUDGE 要点为空", "JUDGE|题干||思路|详解", 1))
    # 半角竖线导致段数翻倍
    cases.append(("半角竖线炸字段", "MC|求 |a|+|b| 的值|A@B|0|思路|详解", 1))

    # 三引号块不应被当题目，也不应报错
    block_ok = "LEC<<<\n<div>讲义</div>\n|这不是字段|\n>>>\n" + ok_mc
    cases.append(("LEC 块被误当题目", block_ok, 0))

    # 未闭合三引号块
    cases.append(("三引号块未闭合", "LOGIC<<<\n<div>原理</div>\n", 1))

    # 未知块类型
    cases.append(("未知块类型", "MCC|题干|A@B|0|思路|详解", 1))

    passed = failed = 0
    print("DSL 字段审计 · 离线自检")
    print("=" * 62)
    for desc, text, expect in cases:
        problems, _, _ = audit_text(text)
        ok = len(problems) == expect
        if ok:
            passed += 1
            print(f"  PASS  {desc:<22} 问题数 {len(problems)}（期望 {expect}）")
        else:
            failed += 1
            print(f"  FAIL  {desc:<22} 问题数 {len(problems)}（期望 {expect}）")
            for p in problems:
                print(f"        {p.desc}")

    # 额外：整份多题 + 混合块
    multi = "\n".join([ok_fill, "LOGIC<<<\n<p>x</p>\n>>>", ok_judge, ok_mc])
    problems, q, total = audit_text(multi)
    cond = (len(problems) == 0 and q == 3)
    print(f"  {'PASS' if cond else 'FAIL'}  {'混合多题计数':<22} 题数 {q}（期望 3）问题 {len(problems)}")
    passed, failed = (passed + 1, failed) if cond else (passed, failed + 1)

    print("-" * 62)
    print(f"PASS {passed} / FAIL {failed}")
    if failed:
        print("FAIL")
        return 1
    print("PASS")
    return 0


if __name__ == "__main__":
    sys.exit(run_cli())
