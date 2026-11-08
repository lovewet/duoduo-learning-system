#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""病句 7 型速查卡（例句对照版）→ .html

与 make_bingju_card_docx.py **同源同数据**（都读 bingju_card.py + 同一份 EXAMPLES），
打印版与网页版内容一致。网页版方便手机随时翻。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import bingju_card as BJC
import answer_formula as AF
from make_bingju_card_docx import EXAMPLES

CSS = """
:root{
  --c-title:#7C2D12; --c-type:#C2410C; --c-sig:#1F2937; --c-fix:#92400E;
  --c-hint:#B45309; --c-tip:#15803D; --c-bad:#B91C1C;
  --f-head:#FDE68A; --f-box:#FFF7ED; --f-tip:#ECFDF5; --f-aff:#EEF2FF;
  --f-aft:#FFFBEB; --f-ok:#F0FDF4; --line:#E7E5E4;
}
*{box-sizing:border-box}
body{
  margin:0; background:#FAFAF9; color:var(--c-sig);
  font-family:"宋体",SimSun,"Times New Roman",serif;
  font-feature-settings:"liga" 1,"kern" 1;
  font-size:17px; line-height:1.72;
}
.wrap{max-width:900px;margin:0 auto;padding:28px 20px 60px}
h1{font-size:30px;color:var(--c-title);text-align:center;margin:0 0 6px;
   letter-spacing:1px}
.sub{text-align:center;color:var(--c-hint);font-size:15px;margin:0 0 22px}
h2{font-size:22px;color:var(--c-title);margin:30px 0 14px;
   border-bottom:2px solid var(--line);padding-bottom:6px}
.box{background:var(--f-box);border-left:5px solid var(--c-type);
     border-radius:4px;padding:9px 14px;margin:0 0 8px}
.box.bad{border-left-color:var(--c-bad)}
.box.ok{background:var(--f-ok);border-left-color:var(--c-tip)}
.box.aff{background:var(--f-aff);border-left-color:#4338CA}
.box.aft{background:var(--f-aft);border-left-color:var(--c-hint)}
.f-title{background:var(--c-type);color:#fff;font-size:21px;font-weight:bold;
         padding:5px 14px;margin:20px 0 0;border-radius:4px 4px 0 0}
.f-title.r{border-radius:0}
.sig{background:var(--f-head);padding:7px 12px;margin:0 0 8px;font-size:15px}
.lab{font-weight:bold;color:var(--c-type)}
.lab.f{color:var(--c-fix)}
.lab.b{color:var(--c-bad)}
.lab.t{color:var(--c-tip)}
.bad{color:var(--c-bad);font-weight:bold}
.hint{color:var(--c-hint);font-size:14px;margin:4px 0 0 22px}
.tip{color:var(--c-tip);font-size:14px;margin:4px 0 0 22px}
ol.chk{margin:8px 0 0;padding-left:26px}
ol.chk li{margin:5px 0}
.vid{border-left:4px solid var(--f-head);padding:2px 0 2px 12px;margin:0 0 12px}
.vid .t{font-weight:bold;font-size:15px}
.vid .m{color:var(--c-hint);font-size:13px;margin:2px 0}
.foot{text-align:center;color:#78716C;font-size:13px;margin-top:28px}
@media print{
  body{background:#fff}
  .wrap{max-width:none;padding:0}
  .f-title{page-break-after:avoid}
  .box,.sig,.vid{page-break-inside:avoid}
}
"""


def md(s):
    """把 **高亮** 渲染成红色加粗；同时清掉真源里可能带的 <b> 标签。"""
    import re
    s = re.sub(r"</?b>", "", s)
    return re.sub(r"\*\*(.+?)\*\*", r'<span class="bad">\1</span>', s)


def build(out_html):
    h = ['<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">',
         '<meta name="viewport" content="width=device-width,initial-scale=1">',
         '<title>初中语文 · 病句类型速查卡</title>',
         '<style>%s</style></head><body><div class="wrap">' % CSS]
    h.append('<h1>初中语文 · 病句类型速查卡</h1>')
    h.append('<p class="sub">学生专用 · 七型全列 · 举例说明 · 答题时对照用</p>')

    # 答题公式卡
    f = AF.get("病句辨析题")
    if f:
        h.append('<div class="box aff"><b style="color:#312E81">【答题公式 · 病句辨析题】%s</b></div>'
                 % f["formula"])
        for k, v in f["parts"]:
            h.append('<div class="box aff"><span class="lab" style="color:#4338CA">%s：</span>%s</div>'
                     % (k, v))
        h.append('<div class="box aft">%s</div>' % md(f["tip"]))

    # 七型一览
    h.append('<h2>一、七型一览</h2>')
    for t, sig, fix in BJC.cards():
        h.append('<div class="box"><span class="lab">%s</span>'
                 '<b>　│　</b>怎么认出它：%s　'
                 '<span class="lab f">怎么改：</span>%s</div>' % (t, sig, fix))

    # 每型举例
    h.append('<h2>二、每型举例</h2>')
    h.append('<p class="tip">用法：先看「怎么认出它」→ 对着例句找病处（红色）→ '
             '写下病名 → 写出改好的完整句子。干净的那句也要写「没有语病」。</p>')
    for idx, (typ, sig, fix) in enumerate(BJC.cards()):
        ex = EXAMPLES[typ]
        h.append('<div class="f-title">%d　%s</div>' % (idx + 1, typ))
        h.append('<div class="sig">怎么认出它：%s　│　%s</div>' % (sig, ex["note"]))
        for wrong, name, fix_txt in ex["bad"]:
            h.append('<div class="box bad"><span class="lab b">错例　</span>%s</div>'
                     % md(wrong))
            h.append('<div class="box"><span class="lab">病名　</span>'
                     '<b>%s</b></div>' % name)
            h.append('<div class="box"><span class="lab f">怎么改　</span></div>')
            for ln in fix_txt.split("\n"):
                h.append('<div class="box">%s</div>' % md(ln))
            h.append('<div style="height:8px"></div>')
        h.append('<div class="box ok"><span class="lab t">对照　</span>'
                 '这一句没有语病　%s</div>' % ex["ok"])
        h.append('<div style="height:14px"></div>')

    # 自检
    h.append('<h2>三、交卷前自检四问</h2><ol class="chk">')
    for q in ["主语还在吗？（成分残缺）",
              "前后两套说法打架了吗？（句式杂糅）",
              "有没有同一个意思说了两遍？（重复赘余）",
              "否定词是多了还是少了？前后两面对得齐吗？搭配搭得上吗？语序放对了吗？"]:
        h.append('<li>%s</li>' % q)
    h.append('</ol>')

    # 视频
    h.append('<h2>四、想看视频（BV 号已核实）</h2>')
    for title, bv, up, dur, why in [
        ("送分题你都接不住？病句六大类型速通排雷，7分钟拿捏满分！丨贞贞语文",
         "BV1U7gY6KEGj", "阿贞爱上了语文", "7分31秒",
         "首选 · 7 分钟讲完六大类型通排，和这张卡一一对应"),
        ("病句快速解法“一眼看病”，新学期就别在这丢分了",
         "BV18n9GYxEun", "语文五爷", "3分21秒",
         "3 分钟极短 · 讲怎么一眼看出病处，适合先看"),
        ("一个万能口诀，搞定七年级上期末病句！",
         "BV1ZbBKB3EFK", "甲哥语文", "3分52秒",
         "明确讲七年级 · 口诀式记忆，和卡上的「怎么认出它」对照"),
        ("【句子】第32节：病句辨析精讲，做病句题，你需要具备这些知识（上）",
         "BV1Zo4y1A7h5", "梓墨说语文", "24分47秒",
         "讲原理最细 · 超 20 分钟，只看前 12 分钟（辨析方法那部分）"),
    ]:
        h.append('<div class="vid"><div class="t">%s</div>'
                 '<div class="m">%s　│　UP：%s　│　时长：%s　│　'
                 '<a href="https://www.bilibili.com/video/%s" target="_blank">打开视频</a></div>'
                 '<div class="m">看它做什么：%s</div></div>' % (title, bv, up, dur, bv, why))

    h.append('<p class="foot">本卡类型、识别信号、怎么改三项，均取自学生学习系统技能库的'
             '语病速查卡唯一真源；例句与改法逐条验算。</p>')
    h.append('</div></body></html>')

    os.makedirs(os.path.dirname(os.path.abspath(out_html)), exist_ok=True)
    with open(out_html, "w", encoding="utf-8") as f:
        f.write("\n".join(h))
    print("✓ 生成 %s (%.1f KB)" % (out_html, os.path.getsize(out_html) / 1024))
    return out_html


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else "学生_病句类型速查卡_例句版.html"
    build(out)
