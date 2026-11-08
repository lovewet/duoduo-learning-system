# -*- coding: utf-8 -*-
"""语病 7 型速查卡 —— 唯一真源。

所有产物（网页 / 作答纸 docx+html / 答案册）都从这里取，
保证「网页上看到的」和「打印在纸上的」字字一致。

qtypes.BINGJU_TYPES 只给名字和 signal；这里补上「一句话判定」与「怎么改」，
作为**作答时对照用的速查卡**（不是答案——答案在答案册里）。
"""
import os
import qtypes

# 七类的固定展示顺序（由「结构性问题 → 语义性问题 → 语序」排列，先查结构）
ORDER = ["成分残缺", "句式杂糅", "重复赘余", "否定不当",
         "搭配不当", "两面对一面", "语序不当"]

# 每类补一条「怎么改」的短版（qtypes.fix 太长，纸上放不下）
FIX_SHORT = {
    "成分残缺": "删介词或删「使」，或补出主语",
    "句式杂糅": "两套说法留一套，删掉多余的那部分",
    "重复赘余": "删掉重复强调的那部分",
    "否定不当": "删掉多余的否定词",
    "搭配不当": "换掉搭不上的一方",
    "两面对一面": "改成前后两面一一对应",
    "语序不当": "按时间/地点/方式的先后调顺序",
}


def all_names():
    """7 型全名，用 ｜ 连接（写进【语病清单】标签）。"""
    return "｜".join(ORDER)


def cards():
    """返回 [(类型, 识别信号, 怎么改短版), ...]，供三处产物统一渲染。"""
    out = []
    for k in ORDER:
        v = qtypes.BINGJU_TYPES[k]
        out.append((k, v.get("signal", ""), FIX_SHORT[k]))
    return out


def cards_html(kind="plain"):
    """彩色速查卡 HTML（kind: plain 纯净 / print 打印）。"""
    rows = "".join(
        '<tr><td class="t">%s</td><td class="s">%s</td><td class="f">%s</td></tr>'
        % (t, s, f) for t, s, f in cards())
    return ('<table class="bjcard %s"><thead><tr><th>语病类型</th>'
            '<th>怎么认出它（信号）</th><th>怎么改</th></tr></thead>'
            '<tbody>%s</tbody></table>' % (kind, rows))


if __name__ == "__main__":
    print("语病 7 型速查卡 · %d 类" % len(ORDER))
    for t, s, f in cards():
        print("  %-5s %s → %s" % (t, s, f))
    print("清单串：%s" % all_names())