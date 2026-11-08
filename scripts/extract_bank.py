#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""从学情分析 PDF 提取的 raw_text.txt 中，挖出全部「变式练习」题库。

PDF 结构（每科一份）：
  前 2 页  薄弱知识点表
  后面     逐题错题：题面 → 选项 → 【考察知识点】 → 【错因分析】 → 变式练习 N.N（题面+选项）
  末尾     【参考答案】区：同样按 原题ID / 变式练习 N.N 列出答案与详解

产出：_p8/题库_语文.md / 题库_数学.md / 题库_英语.md
"""
import io, os, re

RAW = "raw_text.txt"
OUT = "_p8"

FILES = [
    ("语文", 0),
    ("数学", 1),
    ("英语", 2),
]

# 需要清掉的页眉页脚噪声
NOISE = [
    re.compile(r'^===== FILE'),
    re.compile(r'^--- page \d+ len=\d+ ---$'),
    re.compile(r'^四川省成都市石室天府中学'),
    re.compile(r'^\d+\s*/\s*\d+\s*$'),
    re.compile(r'^学情分析\s*$'),
]


def split_files(text):
    """按 FILE 标记切成三段。"""
    idx = [(m.start(), m.group(1)) for m in re.finditer(r'^===== FILE (\d+):.*?=====$', text, re.M)]
    idx.append((len(text), None))
    segs = []
    for i in range(len(idx) - 1):
        segs.append(text[idx[i][0]:idx[i + 1][0]])
    return segs


def clean(lines):
    out = []
    for ln in lines:
        s = ln.strip()
        if not s:
            out.append('')
            continue
        if any(p.match(s) for p in NOISE):
            continue
        out.append(s)
    return out


def parse_variants(seg):
    """提取该科目所有变式练习：题面 + 选项 + 来源。"""
    lines = clean(seg.split("\n"))
    items = []
    i = 0
    n = len(lines)
    while i < n:
        m = re.match(r'^变式练习\s*([\d.]+)\s*$', lines[i])
        if not m:
            i += 1
            continue
        vid = m.group(1)
        body = []
        j = i + 1
        while j < n:
            s = lines[j]
            # 遇到下一个变式、下一个错题、参考答案区标题 → 停
            if re.match(r'^变式练习\s*[\d.]+\s*$', s):
                break
            if s.startswith('我的错题') or s.startswith('【考察知识点】') or s.startswith('【错因分析】'):
                break
            if s in ('参考答案', '参考答案及解析', '【参考答案】') and len(body) > 2:
                break
            body.append(s)
            j += 1
        # 去掉尾部空行
        while body and not body[-1]:
            body.pop()
        items.append({"id": vid, "body": body})
        i = j
    return items


def parse_answers(seg):
    """提取参考答案区：变式练习 N.N → 答案/详解。"""
    lines = clean(seg.split("\n"))
    # 找参考答案区起点
    start = None
    for i, s in enumerate(lines):
        if s in ('参考答案', '参考答案及解析'):
            start = i
    ans = {}
    if start is None:
        return ans
    i = start
    n = len(lines)
    while i < n:
        m = re.match(r'^变式练习\s*([\d.]+)\s*$', lines[i])
        if m:
            vid = m.group(1)
            buf = []
            j = i + 1
            while j < n:
                s = lines[j]
                if re.match(r'^变式练习\s*[\d.]+\s*$', s):
                    break
                if re.match(r'^来源：', s):
                    break
                if s.startswith('我的错题'):
                    break
                buf.append(s)
                j += 1
            while buf and not buf[-1]:
                buf.pop()
            ans[vid] = buf
            i = j
            continue
        i += 1
    return ans


def main():
    text = io.open(RAW, encoding="utf-8").read()
    segs = split_files(text)
    os.makedirs(OUT, exist_ok=True)
    total = 0
    for name, fi in FILES:
        if fi >= len(segs):
            continue
        seg = segs[fi]
        vs = parse_variants(seg)
        an = parse_answers(seg)
        P = ["# 学情分析题库 · %s\n" % name,
             "来源：学生_%s.pdf（学情分析报告）\n" % ("0000000000" + ("" if fi == 0 else "(%d)" % fi)),
             "\n共 %d 道变式练习，其中 %d 道有参考答案。\n" % (len(vs), len(an))]
        for v in vs:
            total += 1
            P.append("\n---\n")
            P.append("## 变式练习 %s\n" % v["id"])
            src = [x for x in v["body"] if x.startswith('来源：')]
            if src:
                P.append("> %s\n" % src[0])
            for ln in v["body"]:
                if ln.startswith('来源：'):
                    continue
                P.append(ln)
            if v["id"] in an:
                P.append("\n**参考答案**\n")
                for ln in an[v["id"]]:
                    P.append(ln)
            else:
                P.append("\n**参考答案**：（原文未单列）\n")
        p = os.path.join(OUT, "题库_%s.md" % name)
        io.open(p, "w", encoding="utf-8").write("\n".join(P))
        print("题库_%s.md：变式 %d 道，答案 %d 条" % (name, len(vs), len(an)))
    print("合计 %d 道变式练习 → %s/" % (total, OUT))


if __name__ == "__main__":
    main()
