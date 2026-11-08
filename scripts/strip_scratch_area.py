#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""去掉练习题程序框图里的「你的演算区」面板（项目约定明确要求）。

要删的三类元素：
  1. 演算区外框：虚线矩形（fill #f8fafc + stroke #94a3b8 + dasharray 5,4）
  2. 标题文字：「你的演算区…」
  3. 面板内容：填空提示文字（fill #94a3b8）+ 手写横线（stroke #cbd5e1）

删完还要**收紧 viewBox**，否则画布底部/右侧会留一大片空白。

用法：python strip_scratch_area.py [源目录] [目标目录]
"""
import io, os, re, sys

# 每个文件删完后的画布尺寸（按删除后实际内容的最大 x / y 手工核定）
CANVAS = {
    "q1.svg": (545, 280),   # 无循环：菱形底点 y=260
    "q2.svg": (545, 360),   # 一轮循环：底部操作框 y=340
    "q3.svg": (545, 360),
    "q4.svg": (545, 360),
    "q5.svg": (545, 360),
}


def is_scratch(line):
    """判断这一行是否属于「演算区」面板。"""
    if "你的演算区" in line:
        return True
    # 外框：虚线矩形，浅灰底 + 灰边框
    if "<rect" in line and 'fill="#f8fafc"' in line and 'stroke="#94a3b8"' in line:
        return True
    # 手写横线
    if "<line" in line and 'stroke="#cbd5e1"' in line:
        return True
    # 填空提示文字（第一轮 / 第二轮 / 输出：____）
    if "<text" in line and 'fill="#94a3b8"' in line:
        return True
    return False


def process(path, out_path, name):
    lines = io.open(path, encoding="utf-8").read().split("\n")
    kept, removed = [], 0
    for ln in lines:
        if is_scratch(ln):
            removed += 1
            continue
        kept.append(ln)
    s = "\n".join(kept)
    # 收紧 viewBox
    if name in CANVAS:
        w, h = CANVAS[name]
        s = re.sub(r'viewBox="0 0 \d+ \d+"', 'viewBox="0 0 %d %d"' % (w, h), s, count=1)
        s = s.replace('max-width:660px', 'max-width:%dpx' % w)
    io.open(out_path, "w", encoding="utf-8").write(s)
    return removed


def main():
    src = sys.argv[1] if len(sys.argv) > 1 else "_p7/figs"
    dst = sys.argv[2] if len(sys.argv) > 2 else src
    os.makedirs(dst, exist_ok=True)
    total = 0
    for name in sorted(CANVAS):
        p = os.path.join(src, name)
        if not os.path.exists(p):
            print("  跳过（不存在）%s" % p)
            continue
        n = process(p, os.path.join(dst, name), name)
        total += n
        print("  %s：删除 %d 个元素 → %s" % (name, n, os.path.join(dst, name)))
    print("共删除 %d 个元素" % total)
    return 0


if __name__ == "__main__":
    sys.exit(main())
