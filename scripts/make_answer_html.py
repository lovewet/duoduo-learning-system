#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""从 DSL 源生成作答纸 HTML（与 make_answer_docx.py 同源、同参数）。

用浏览器打开 → Ctrl+P 即可打印；Word 版用 make_answer_docx.py。
两份产物共用 dsl_source.py 的版式参数，改一处两边同步。

铁律：作答纸**不得出现任何答案**（答案只在 make_answer_key.py 的答案册里）。
用法：python make_answer_html.py [输出.html]
"""
import io, re, sys, html as H

import dsl_source as D

try:
    import bingju_card as _BJC
except Exception:
    _BJC = None
try:
    import answer_formula as _AF
except Exception:
    _AF = None
try:
    import frac_render as _FR
except Exception:
    _FR = None
try:
    import math_format as _MF
except Exception:
    _MF = None


def esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def rich(s):
    """题干 / 选项片段：只放行 <b> <u>，其余转义。保留 <u>（英语语音题考划线字母）。

    ⚠️ 同时清掉 markdown 星号残留（阶段21 实测踩坑）：
    DSL 里手写 `**加粗**` 会原样印到纸上，教辅不该有星号。
    """
    s = re.sub(r"\*\*(.+?)\*\*", r"\1", s)
    s = H.unescape(s)
    # 真分数竖式（阶段21）：<span class="fr">…<span class="nu">分子
    # </span><span class="de">分母</span></span> 必须原样放行，
    # 转义掉就退回斜杠 3/2，与 §5A.14 规范第①条（不能写斜杠）冲突。
    frs = []

    def _st(m):
        frs.append(m.group(0))
        return "\x00FR%d\x00" % (len(frs) - 1)
    s = re.sub(_FR.FR_BLOCK_RE, _st, s)   # FR_BLOCK_RE 已含 re.S
    parts = re.split(r'(</?(?:b|u)>)', s)
    out = []
    for t in parts:
        if t in ("<b>", "</b>", "<u>", "</u>"):
            out.append(t)
        elif t:
            out.append(re.sub(r"\x00FR(\d+)\x00",
                              lambda m: frs[int(m.group(1))], esc(t)))
    return "".join(out)


def opt_block(q):
    rows = D.opt_rows(q)
    if not rows:
        return ""
    out = []
    for r in rows:
        # 一行只有一个选项 = 超长选项，允许折行；多个选项才锁 nowrap 防止断在半句
        cls = "oc" if len(r) > 1 else "oc ow"
        cells = "".join(
            '<span class="%s">○ <b>%s．</b>%s</span>' % (cls, "ABCD"[i], rich(q["opts"][i]))
            for i in r)
        out.append('<div class="orow">%s</div>' % cells)
    return "".join(out)


CSS = """
*{box-sizing:border-box}
body{margin:0;background:#eef1f5;font-family:"PingFang SC","Microsoft YaHei",SimSun,"Times New Roman",serif;color:#111;
 font-feature-settings:"liga" 1,"kern" 1}
.sheet{width:210mm;min-height:297mm;margin:8mm auto;background:#fff;padding:15mm 14mm;
       font-size:12pt;line-height:1.4;box-shadow:0 2px 10px rgba(0,0,0,.12)}
h1{font-size:18pt;text-align:center;margin:0 0 6pt}
.sub{text-align:center;font-size:11pt;color:#555;margin-bottom:14pt}
.note{font-size:10.5pt;line-height:1.7;color:#333}
.rec{font-size:11pt;line-height:1.9;margin:6pt 0 16pt}
.rec .rh{font-weight:800;display:block;margin:8pt 0 2pt}
.dh{font-size:14pt;font-weight:800;margin:0 0 3pt}
.dm{font-size:10.5pt;color:#555;margin-bottom:4pt}
.sg{font-size:10.5pt;color:#555;margin-bottom:10pt}
.qh{font-size:13pt;font-weight:800;margin:10pt 0 3pt}
/* 题型：直接印出的彩色徽标（不是填空） */
.qtg{display:inline-block;font-size:11.5px;font-weight:700;color:#3730a3;
  background:#eef2ff;border:1px solid #c7d2fe;border-radius:20px;padding:2px 11px;margin:3px 0 5px;}
.qtg b{color:#312e81;}
.qself{border:1px dashed #f59e0b;border-radius:8px;background:#fffbeb;
 padding:5pt 9pt;margin:4pt 0 7pt;font-size:10.5pt;color:#92400e;line-height:1.7}
.qself b{color:#b45309}



@media print{.qself{break-inside:avoid;page-break-inside:avoid}}
/* G15 答题公式卡（作答纸） */
.afcard{margin:4pt 0 7pt;border:1px solid #a5b4fc;border-radius:9px;overflow:hidden;
 background:#f5f7ff;line-height:1.7}
.afcard .afh{padding:4pt 9pt;font-size:11pt;font-weight:800;color:#fff;
 background:linear-gradient(135deg,#4338ca,#6d28d9)}
.afcard .aff{padding:5pt 9pt 4pt;font-size:12pt;font-weight:800;color:#312e81;background:#eef2ff}
.afcard .aft{width:100%;border-collapse:collapse;font-size:10.5pt;background:#fff}
.afcard .aft td{padding:3pt 7pt;border-bottom:1px solid #e0e7ff;vertical-align:top}
.afcard .aft td.k{width:66pt;font-weight:800;color:#4338ca;white-space:nowrap}
.afcard .aft td.v{color:#1f2937}
.afcard .afs{padding:5pt 9pt;font-size:10.5pt;color:#312e81;background:#f5f3ff;
 border-top:1px dashed #c7d2fe}
.afcard .aftip{padding:4pt 9pt;font-size:10.5pt;color:#92400e;background:#fffbeb;
 border-top:1px dashed #fcd34d}
@media print{.afcard{break-inside:avoid;page-break-inside:avoid}}

/* 真分数竖式（阶段21 用户要求：不能写成斜杠 3/2，必须竖式） */
.fr{display:inline-flex;flex-direction:column;vertical-align:middle;
  text-align:center;line-height:1.05;margin:0 2px;position:relative;
  padding:0 2px;font-size:.92em;vertical-align:-0.55em}
.fr .nu{padding:0 3px 1px;border-bottom:1.4px solid currentColor;line-height:1.1}
.fr .de{padding:1px 3px 0;line-height:1.1}

/* G11 逐句语病定性（作答纸） */
.bjbox{margin:8px 0 4px;border:1px solid #fdba74;border-radius:10px;overflow:hidden;
  break-inside:avoid;page-break-inside:avoid;}
.bjlab2{padding:6px 11px;font-size:12.5px;font-weight:800;color:#fff;background:#7c2d12;}
.bjt{width:100%;border-collapse:collapse;font-size:12.5px;}
.bjt th{background:#fff7ed;color:#7c2d12;font-size:11.5px;text-align:left;padding:5px 7px;
  border-bottom:1px solid #fdba74;}
.bjt td{padding:7px;border-bottom:1px solid #fde68a;vertical-align:top;line-height:1.7;}
.bjt .bn{width:30px;text-align:center;font-weight:800;color:#c2410c;}
.bjt .bs{width:38%;color:#1f2937;}
.bjt .bw,.bjt .bf{width:31%;color:#92400e;}
.bjn{padding:5px 11px;font-size:11.5px;color:#92400e;background:#fffbeb;}
/* 语病 7 型速查卡（作答纸，与网页/docx 同一份数据） */
.bjcardbox{margin:8px 0 4px;border:1px solid #fdba74;border-radius:10px;overflow:hidden;
  break-inside:avoid;page-break-inside:avoid;}
.bjcardlab{padding:6px 11px;font-size:12.5px;font-weight:800;color:#fff;background:#9a3412;}
.bjcardlab span{display:block;font-size:11px;font-weight:500;opacity:.92;margin-top:2px;}
.bjcard{width:100%;border-collapse:collapse;font-size:12.5px;}
.bjcard th{background:#fde68a;color:#7c2d12;font-size:11.5px;text-align:left;
  padding:4px 7px;border-bottom:1px solid #fdba74;}
.bjcard td{padding:5px 7px;border-bottom:1px solid #fed7aa;background:#fff7ed;line-height:1.6;}
.bjcard .t{width:17%;font-weight:800;color:#c2410c;}
.bjcard .s{width:44%;color:#1f2937;}
.bjcard .f{width:39%;color:#92400e;}
.qt{font-size:12pt;line-height:1.4;margin:0 0 2pt}
.orow{margin:2pt 0 3pt 14pt;font-size:12pt}
.oc{margin-right:2.2em;white-space:nowrap}
.ow{white-space:normal;display:block;margin-right:0}
.ln{border-bottom:1px solid #999;height:22pt}
.gap{height:7pt}
.end{text-align:center;font-size:10.5pt;color:#666;margin-top:10pt}
.pb{page-break-after:always;height:0}
@media print{body{background:#fff}.sheet{box-shadow:none;margin:0;padding:12mm 12mm;page-break-after:always}}
"""


def build(out_html, src_dir=None, only_day=None):
    days = D.load_days(src_dir or D.SRC_DIR)
    if only_day:
        days = [d for d in days if d["n"] == only_day]
    plan = [(d, D.plan_day(d["qs"])) for d in days]
    total = sum(len(d["qs"]) for d in days)
    n_mc = sum(1 for d in days for q in d["qs"] if q["kind"] == "MC")

    b = ['<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">',
         '<title>七天作答纸合集 · 学生</title><style>%s</style></head><body>' % CSS]

    # 首页（阶段21 用户要求：第一页直接到题目，不要封面页）
    # 最小必要信息压在一页顶部；批改记录移到**末尾**。
    # ⚠️ 第一页直接到题目：只留标题 + 姓名栏，不加任何「本册共 N 题」「① 选择题…」说明
    _dn = plan[0][0]["n"] if plan else 0
    b.append('<h1>学生 · 第 %d 天 · 作答纸</h1>' % _dn)
    b.append('<div class="note">姓名：____________　日期：____________　得分：__________</div>')

    card_done = {}   # 每天只在第一道病句题前插一次速查卡
    for k, (d, (per, _pg)) in enumerate(plan):
        if k:
            b.append('<div class="pb"></div>')
        b.append('<div class="sheet">')
        n_m = sum(1 for q in d["qs"] if q["kind"] == "MC")
        b.append('<div class="dh">第 %d 天　%s</div>' % (d["n"], esc(d["title"])))
        b.append('<div class="sg">姓名：__________　日期：__________　用时：______ 分钟　得分：______</div>')
        for q in d["qs"]:
            b.append('<div class="qh">第 %d 题（%s · %s）</div>'
                     % (q["no"], q["subj"], D.KIND_CN[q["kind"]]))
            # G10 题型：**直接印出来**（阶段20 用户明确——题型不用他自己命名）
            if q.get("qtype"):
                b.append('<div class="qtg">题型：<b>%s</b></div>' % esc(q["qtype"]))
            # G15 答题公式卡：主观题（JUDGE）才挂 —— 告诉他答案该写成什么句式
            if q["kind"] == "JUDGE" and q.get("qtype") and _AF is not None and _AF.get(q["qtype"]):
                b.append(_AF.card_html(q["qtype"], kind="plain"))
            # ⚠️ 这里**不再印「数学书写规范」卡**（阶段21 用户纠正）：
            # 那是出题（题面排版）必须遵守的规范，不是给答题人的要求。
            # 题面本身已是规范印刷体，孩子照着写就对了。
            if q.get("bingju"):
                b.append('<div class="qself">语病类型备选（<b>可参考</b>）：%s</div>'
                         % "　".join("□ " + x for x in q["bingju"]))
            for ln in D.to_lines(q["stem"]):
                b.append('<div class="qt">%s</div>' % rich(ln))
            if q["kind"] == "MC":
                b.append(opt_block(q))
            else:
                for _ in range(per):
                    b.append('<div class="ln"></div>')
            # G11 逐句语病定性：病句题的正式作答内容，每句都要写病名 + 改正
            if q.get("bjtab"):
                if _BJC is not None and not card_done.get(d["n"]):
                    card_done[d["n"]] = True
                    b.append('<div class="bjcardbox"><div class="bjcardlab">'
                             '📇 语病 7 型速查卡（七种全列 · 逐句判病时对照这张卡）'
                             '<span>先看信号再定名字 —— 这七种是起点，不是限制</span></div>'
                             + _BJC.cards_html("print") + '</div>')
                rows = "".join(
                    '<tr><td class="bn">%s</td><td class="bs">%s</td>'
                    '<td class="bw">语病类型：____________________</td>'
                    '<td class="bf">改正：________________________________</td></tr>'
                    % (r["no"], H.unescape(re.sub(r'<[^>]+>', '', r["sent"])))
                    for r in q["bjtab"])
                b.append('<div class="bjbox">'
                         '<div class="bjlab2">✍ 逐句定性（本题的正式答案 · 每句话都要单独写病名和改法）</div>'
                         '<table class="bjt"><thead><tr><th>句</th><th>这句话</th>'
                         '<th>语病类型（自己写）</th><th>改正（写出改好的句子）</th></tr></thead>'
                         '<tbody>%s</tbody></table>'
                         '<div class="bjn">★ 写出病名才算做完这题；写不出就空着，别乱猜。</div>'
                         '</div>' % rows)
            b.append('<div class="gap"></div>')
        b.append('<div class="end">— 第 %d 天作答结束 · 共 %d 题 —</div>' % (d["n"], len(d["qs"])))
        b.append('</div>')

    # ⚠️《批改记录》对账单已移到**答案册**（家长/老师那份）末尾。

    b.append('</body></html>')
    h = "".join(b)
    # ══ 数学排版升级（阶段21）：CSS 拼的分数 → MathML 真公式 ══
    # MathML 是浏览器原生数学排版，分数线居中定宽、分子分母居中，
    # 与教材印刷体一致；CSS flex 拼出来的只是视觉近似。
    try:
        import mathml_render as _ML
        h = _ML.upgrade(h)
    except Exception:
        pass
    io.open(out_html, "w", encoding="utf-8", newline="\n").write(h)

    # 自检：不得出现答案痕迹
    bad = []
    for d in days:
        for q in d["qs"]:
            if q["kind"] == "MC":
                if q["letter"] and ("答案" + q["letter"]) in h:
                    bad.append((d["n"], q["no"]))
    print("生成 %s　天数 %d　题目 %d　%.1f KB" % (out_html, len(days), total, len(h) / 1024))
    print("  版式：正文 %.1fpt / 题号 %.1fpt / 横线高 %.1fpt　每题横线 %s"
          % (D.SZ_BODY / 2.0, D.SZ_QNO / 2.0, D.RULE_H / 20.0,
             "·".join(str(p) for _, (p, _) in plan)))
    print("  答案泄漏自检：%s" % ("✅ 无" if not bad else "❌ %s" % bad))
    return total


if __name__ == "__main__":
    # 用法：[--day N] [输出文件名]；不给 --day 就出全部 7 天合集
    argv = sys.argv[1:]
    only_day = None
    if "--day" in argv:
        i = argv.index("--day")
        only_day = int(argv[i + 1]); del argv[i:i + 2]
    out = argv[0] if argv else "学生_七天作答纸合集.html"
    build(out, only_day=only_day)
