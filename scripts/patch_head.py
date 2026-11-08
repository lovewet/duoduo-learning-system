#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""把 _p6/print.css 与 _p6/print.js.html 的最新参数同步进 _p6/00_head.html。

00_head.html 在构建时把这两个文件内联进去了，所以改源文件后必须重新同步，
否则网页上的「下载作答纸 / 打印」按钮仍用旧参数（横线数、字号、行高）。
"""
import io, re, sys

HEAD = "_p6/00_head.html"
CSS_SRC = "_p6/print.css"
JS_SRC = "_p6/print.js.html"

# (旧片段, 新片段) —— 逐个精确替换，命中不到就报警
PAIRS = [
    # --- print.css 部分 ---
    ("#printArea .sheet{font-family:\"PingFang SC\",\"Microsoft YaHei\",sans-serif;color:#111;font-size:13px;}",
     "#printArea .sheet{font-family:\"PingFang SC\",\"Microsoft YaHei\",sans-serif;color:#111;font-size:14px;}"),
    ("#printArea .pq{margin-bottom:17px;", "#printArea .pq{margin-bottom:14px;"),
    ("#printArea .ph{font-size:13px;font-weight:800;margin-bottom:5px;color:#111;}",
     "#printArea .ph{font-size:13.5px;font-weight:800;margin-bottom:4px;color:#111;}"),
    ("#printArea .ps{font-size:12.5px;line-height:1.75;margin-bottom:7px;}",
     "#printArea .ps{font-size:13.5px;line-height:1.7;margin-bottom:6px;}"),
    ("#printArea .ln{height:28px;", "#printArea .ln{height:24px;"),
    # --- print.js.html 部分 ---
    ("n:isWrite?13:9", "n:isWrite?6:6"),
    ("font-size:11pt;line-height:1.6", "font-size:12pt;line-height:1.5"),
    (".tip{font-size:9.5pt", ".tip{font-size:10.5pt"),
    (".dh2{font-size:10pt", ".dh2{font-size:10.5pt"),
    (".qh{font-size:11pt", ".qh{font-size:12pt"),
    (".qt2{font-size:11pt", ".qt2{font-size:12pt"),
    (".ln{border-bottom:1px solid #999;height:26pt;}",
     ".ln{border-bottom:1px solid #999;height:22pt;}"),
    (".end{font-size:9pt", ".end{font-size:10pt"),
]


def main():
    s = io.open(HEAD, encoding="utf-8").read()
    miss = []
    for a, b in PAIRS:
        if a in s:
            s = s.replace(a, b)
        else:
            miss.append(a[:56])
    io.open(HEAD, "w", encoding="utf-8").write(s)
    print("已同步 %s" % HEAD)
    print("  命中 %d / %d" % (len(PAIRS) - len(miss), len(PAIRS)))
    for m in miss:
        print("  [未命中] " + m)
    # 复核：确认没有残留旧值
    leftover = [a[:40] for a, b in PAIRS if a in io.open(HEAD, encoding="utf-8").read()]
    print("  残留旧值：%d" % len(leftover))
    return 1 if leftover else 0


if __name__ == "__main__":
    sys.exit(main())
