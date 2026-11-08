#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""合并校验 verify_all.py：交付前一条命令出总报告。

原来要分别跑 verify_lecture.py / verify_answer_key.py，再手工查作答纸有没有漏答案。
现在一次跑完，输出「交付前自检清单」的机器判定版。
"""
import io, os, re, sys, glob, zipfile, subprocess


ROOT = os.path.dirname(os.path.abspath(__file__))
# 产物（讲义 html、作答纸、答案册）实际生成在**工作区**，不在本脚本目录。
# 用环境变量 DUODUO_ROOT 指定；未指定时，若当前工作目录下有产物就用它。
_env = os.environ.get("DUODUO_ROOT")
if _env:
    ROOT = _env
elif os.path.isfile(os.path.join(os.getcwd(), "dsl_source.py")) is False and \
        glob.glob(os.path.join(os.getcwd(), "学生_*.html")):
    ROOT = os.getcwd()
SK = r"<SKILL_DIR>\scripts"
PY = sys.executable


def sh(script, *args):
    p = os.path.join(SK, script)
    if not os.path.exists(p):
        return 99, "脚本缺失：%s" % script
    r = subprocess.run([PY, p] + list(args), cwd=ROOT,
                       capture_output=True, text=True, encoding="utf-8")
    return r.returncode, ((r.stdout or "") + (r.stderr or ""))


def latest_web():
    best, bv = None, -1
    for p in glob.glob(os.path.join(ROOT, "学生_三科考点7天攻坚_v*.html")):
        m = re.search(r'_v(\d+)', p)
        if m and int(m.group(1)) > bv:
            best, bv = p, int(m.group(1))
    return best


def main():
    import dsl_source as _D
    items = []

    web = latest_web()
    if not web:
        print("❌ 找不到网页讲义")
        return 1
    rc, out = sh("verify_lecture.py", os.path.basename(web))
    bad = "❌" in out or rc != 0
    items.append(("讲义六类校验", "❌ 未通过" if bad else "✅ 通过", out.strip().splitlines()[-1] if out.strip() else ""))

    rc, out = sh("verify_answer_key.py")
    ok = "✅ 通过" in out
    items.append(("答案册 vs 网页 逐题对齐", "✅ 通过" if ok else "❌ 未通过",
                  [l for l in out.splitlines() if "逐题比对通过" in l][:1]))

    # 作答纸零答案自检（docx + html）
    for f, kind in [("学生_七天作答纸合集.docx", "docx"), ("学生_七天作答纸合集.html", "html")]:
        p = os.path.join(ROOT, f)
        if not os.path.exists(p):
            items.append(("作答纸 %s" % kind, "❌ 缺失", ""))
            continue
        if kind == "html":
            t = io.open(p, encoding="utf-8").read()
            leaks = sum(t.count(k) for k in ("【答案", "【解析", "【详解", "故选"))
            n_q = t.count('class="qh"')
        else:
            x = zipfile.ZipFile(p).read("word/document.xml").decode("utf-8")
            txt = "".join(re.findall(r"<w:t[^>]*>(.*?)</w:t>", x, re.S))
            leaks = sum(txt.count(k) for k in ("【答案", "【解析", "【详解", "故选"))
            # 题头「第 N 题（科目 · 题型）」跨 run 存储，按数字锚定避免误匹配封面文字
            n_q = len(re.findall(r"第\s*\d+\s*题（", txt))
        items.append(("作答纸 %s 零答案" % kind,
                      "✅ 无泄漏" if leaks == 0 else "❌ 泄漏 %d 处" % leaks,
                      "题卡 %d" % n_q))

    # ── 门禁 G10：题型齐全 + 病句题语病类型齐全 ──
    wt = io.open(web, encoding="utf-8").read()
    n_qt = len(re.findall(r'class="qtag qt2"', wt))
    n_bj = len(re.findall(r'class="qtag bq', wt))
    # 病句题一致性：**以解析后的 DSL 数据为准**（阶段21 修）。
    # ⚠️ 原先用正则扫 `_p*/day*.txt` 源文件，有两个错：
    #   ① glob 会把 `_p5_backup_*` 等备份目录一起数进来；
    #   ② 题干里插了 <span class='fr'> 真分数标记后，
    #      `【题型】病句…【语病清单】` 这两个标签不再相邻，正则漏匹配。
    # 解析后计数才是真的。
    n_bingju_q = 0
    for d in _D.load_days():
        n_bingju_q += sum(1 for q in d["qs"] if q.get("bingju"))
    # 作答纸题型必须**直接显示**（不是留空让他自己命名）；语病才要他自己写
    sp10 = os.path.join(ROOT, "学生_七天作答纸合集.html")
    sheet_t = io.open(sp10, encoding="utf-8").read() if os.path.exists(sp10) else ""
    n_qtg = sheet_t.count('class="qtg"')
    n_self_left = sheet_t.count('题型（<b>先自己写</b>')
    ok10 = (n_qt >= 63 and n_bj >= 4 and n_bj == n_bingju_q
            and n_qtg >= 63 and n_self_left == 0)
    items.append(("G10 题型标注齐全",
                  "✅ 通过" if ok10 else "❌ 未通过",
                  "网页题型 %d / 语病清单 %d / 病句题 %d / 作答纸题型直印 %d / 题型填空残留 %d"
                  % (n_qt, n_bj, n_bingju_q, n_qtg, n_self_left)))

    # 答案册题型标签
    ak = os.path.join(ROOT, "学生_七天题目详解与答案.html")
    if os.path.exists(ak):
        at = io.open(ak, encoding="utf-8").read()
        na = len(re.findall(r'class="tag qt3"', at))
        nb = len(re.findall(r'class="tag bq3"', at))
        items.append(("答案册题型标签",
                      "✅ 通过" if na >= 63 and nb >= 4 else "❌ 未通过",
                      "题型 %d / 语病 %d" % (na, nb)))
    else:
        items.append(("答案册题型标签", "❌ 缺失", "学生_七天题目详解与答案.html"))

    # ── 门禁 G11：病句题必须逐句写语病类型（语病类型是正式作答内容，不能只选选项）──
    import dsl_source as _D
    n_bj = sum(len(q.get("bjtab") or []) for d in _D.load_days() for q in d["qs"])
    n_bjq = sum(1 for d in _D.load_days() for q in d["qs"] if q.get("bjtab"))
    n_w_bj = len(re.findall(r'placeholder="语病类型"', wt))
    n_sol_bj = len(re.findall(r'class="t"><b>', io.open(ak, encoding="utf-8").read())) if os.path.exists(ak) else 0
    ok11 = n_bj > 0 and n_w_bj == n_bj and n_sol_bj == n_bj
    items.append(("G11 逐句语病定性",
                  "✅ 通过" if ok11 else "❌ 未通过",
                  "%d 道病句题 / %d 句 · 网页填写框 %d / 答案册标准答案 %d"
                  % (n_bjq, n_bj, n_w_bj, n_sol_bj)))

    # 作答纸必须留出逐句空白填写栏，且不得泄漏标准答案
    ok11b = True
    note11 = []
    for f, kind in [("学生_七天作答纸合集.docx", "docx"), ("学生_七天作答纸合集.html", "html")]:
        pp = os.path.join(ROOT, f)
        if not os.path.exists(pp):
            ok11b = False; continue
        if kind == "html":
            tt = io.open(pp, encoding="utf-8").read()
        else:
            xx = zipfile.ZipFile(pp).read("word/document.xml").decode("utf-8")
            tt = "".join(re.findall(r"<w:t[^>]*>(.*?)</w:t>", xx, re.S))
        cnt = tt.count("语病类型：____")
        leak = [k for k in ("删「通过」", "删「之所以」", "没有语病 ✅", "三种改法任选一种") if k in tt]
        note11.append("%s %d/%d" % (kind, cnt, n_bj))
        if cnt != n_bj or leak:
            ok11b = False
            if leak:
                note11.append("泄漏%s" % leak)
    items.append(("G11 作答纸逐句栏",
                  "✅ 通过" if ok11b else "❌ 未通过", " ".join(note11)))

    # ── 门禁 G12：语病 7 型必须全列 + 打印版 docx 必须是彩色的 ──
    import bingju_card as _BJC
    n_names = len(_BJC.ORDER)
    n_all_listed = all(q.get("bingju") and len(q["bingju"]) == n_names
                       for d in _D.load_days() for q in d["qs"] if q.get("bingju"))
    # 四处都要有 7 型速查卡
    n_card = {"web": wt.count('class="bjcardbox"'),
              "sheet_html": 0, "sheet_docx": 0}
    ap = os.path.join(ROOT, "学生_七天作答纸合集.html")
    if os.path.exists(ap):
        n_card["sheet_html"] = io.open(ap, encoding="utf-8").read().count('class="bjcardbox"')
    sp = os.path.join(ROOT, "学生_七天作答纸合集.docx")
    if os.path.exists(sp):
        n_card["sheet_docx"] = zipfile.ZipFile(sp).read("word/document.xml").decode("utf-8").count("语病 7 型速查卡（")
    ok12 = n_names == 7 and n_all_listed and n_card["web"] > 0 and n_card["sheet_html"] > 0 \
        and n_card["sheet_docx"] > 0
    items.append(("G12 语病7型全列",
                  "✅ 通过" if ok12 else "❌ 未通过",
                  "%d 型 · 清单全列 %s · 卡 %s"
                  % (n_names, "是" if n_all_listed else "否",
                     "/".join(str(v) for v in n_card.values()))))

    # 打印版 docx 必须是彩色的：字色 + 底纹都要有
    for f, label in [("学生_七天作答纸合集.docx", "作答纸"),
                     ("学生_七天题目详解与答案.docx", "答案册")]:
        pp = os.path.join(ROOT, f)
        if not os.path.exists(pp):
            items.append(("%s docx 彩色" % label, "❌ 缺失", ""))
            continue
        xx = zipfile.ZipFile(pp).read("word/document.xml").decode("utf-8")
        n_c = len(re.findall(r'<w:color w:val="[0-9A-F]{6}"', xx))
        n_s = len(re.findall(r'w:fill="[0-9A-F]{6}"', xx))
        okc = n_c >= 50 and n_s >= 50
        items.append(("%s docx 彩色" % label,
                      "✅ 通过" if okc else "❌ 未通过",
                      "字色 %d / 底纹 %d" % (n_c, n_s)))

    # 上云包新鲜度
    cloud = os.path.join(ROOT, "上云包", "errors.csv")
    # ── 门禁 G15：主观题必须挂「答题公式卡」──
    # 阶段21 用户要求：语文简答题要告诉他**答案该写成什么句式**，
    # 光教「怎么想」（三步动作）不够 —— 不知道句式就会写成流水账，阅卷按点给分对不上号。
    # 判定：凡是 JUDGE 题且题型已注册公式 → 四处产物都必须出现这张卡。
    import answer_formula as _AF
    n_judge = n_formula = 0
    for d in _D.load_days():
        for q in d["qs"]:
            if q["kind"] != "JUDGE":
                continue
            n_judge += 1
            if q.get("qtype") and _AF.get(q["qtype"]):
                n_formula += 1
    n_af = {"web": wt.count('class="afcard'),
            "sheet_html": 0, "sheet_docx": 0, "key_html": 0, "key_docx": 0}
    ap15 = os.path.join(ROOT, "学生_七天作答纸合集.html")
    if os.path.exists(ap15):
        n_af["sheet_html"] = io.open(ap15, encoding="utf-8").read().count('class="afcard')
    sp15 = os.path.join(ROOT, "学生_七天作答纸合集.docx")
    if os.path.exists(sp15):
        n_af["sheet_docx"] = zipfile.ZipFile(sp15).read("word/document.xml").decode("utf-8").count("答题公式 · ")
    for f15, key in [("学生_七天题目详解与答案.html", "key_html"),
                     ("学生_七天题目详解与答案.docx", "key_docx")]:
        p15 = os.path.join(ROOT, f15)
        if not os.path.exists(p15):
            continue
        if f15.endswith(".html"):
            n_af[key] = io.open(p15, encoding="utf-8").read().count('class="afcard')
        else:
            # 答案册 docx 的标签是「判分依据 · 答题公式：」，作答纸是「答题公式 · 」
            _x = zipfile.ZipFile(p15).read("word/document.xml").decode("utf-8")
            n_af[key] = _x.count("答题公式：") + _x.count("答题公式 · ")
    # 只要有主观题挂了公式，五处都得有（数量按各处覆盖的天数缩放，至少 1）
    ok15 = (n_formula == 0) or all(v >= 1 for v in n_af.values())
    items.append(("G15 答题公式卡",
                  "✅ 通过" if ok15 else "❌ 未通过",
                  "主观题 %d 题 · 已挂公式 %d · 卡 web%d/纸html%d/纸docx%d/册html%d/册docx%d"
                  % (n_judge, n_formula, n_af["web"], n_af["sheet_html"],
                     n_af["sheet_docx"], n_af["key_html"], n_af["key_docx"])))

# ── 门禁 G16：**规范不得印在作答纸上**（阶段21 用户纠正）──
    # 需求原话：「答题纸上的数学书写规范不要，我是要求**大模型出题时的书写规范**，
    # 不是对答题人的」。
    # 正确分工：
    #   · 出题侧（我）→ 题面/解析/答案必须是规范印刷体（真分数、根号、变量斜体）
    #   · 答题侧（孩子）→ 只印题目与答题空间，**不印「你要怎么写」的规范卡**
    # 反例（已修）：往作答纸上印「十条规范」+「本题必写几行」——越界了。
    n_math = sum(1 for d in _D.load_days() for q in d["qs"] if q["subj"] == "数学")
    leak = {"sheet_html": 0, "sheet_docx": 0, "key_html": 0, "key_docx": 0}
    ap16 = os.path.join(ROOT, "学生_七天作答纸合集.html")
    if os.path.exists(ap16):
        t16 = io.open(ap16, encoding="utf-8").read()
        leak["sheet_html"] = t16.count("mfcardbox") + t16.count('class="mfmust')
    sp16 = os.path.join(ROOT, "学生_七天作答纸合集.docx")
    if os.path.exists(sp16):
        t16 = zipfile.ZipFile(sp16).read("word/document.xml").decode("utf-8")
        leak["sheet_docx"] = t16.count("数学书写规范（十条") + t16.count("本题必须写出的几行")
    for f16, k16 in [("学生_七天题目详解与答案.html", "key_html"),
                     ("学生_七天题目详解与答案.docx", "key_docx")]:
        p16 = os.path.join(ROOT, f16)
        if not os.path.exists(p16):
            continue
        t16 = (io.open(p16, encoding="utf-8").read() if f16.endswith(".html")
               else zipfile.ZipFile(p16).read("word/document.xml").decode("utf-8"))
        leak[k16] = t16.count('class="mfmust') + t16.count("本题必须写出的几行")
    ok16 = all(v == 0 for v in leak.values())
    items.append(("G16 规范不上纸",
                  "✅ 通过" if ok16 else "❌ 未通过",
                  "数学 %d 题 · 规范卡泄漏 %s"
                  % (n_math, "/".join(str(v) for v in leak.values()))))

    # ── 门禁 G17：西文必须是印刷体，不能用宋体的西文字形 ──
    # 阶段21 用户要求「英文字体要好看，印刷体」。宋体(SimSun)的西文是
    # 等宽衬线体，n/m 挤、l 与 I 难分、b 与 6 易看错 —— 语音题首当其冲。
    font_issue = []
    for f17 in ("学生_七天作答纸合集.docx", "学生_七天题目详解与答案.docx"):
        p17 = os.path.join(ROOT, f17)
        if not os.path.exists(p17):
            continue
        xx17 = zipfile.ZipFile(p17).read("word/document.xml").decode("utf-8")
        n_tnr = xx17.count('w:ascii="Times New Roman"')
        n_sim = xx17.count('w:ascii="SimSun"')
        if n_tnr == 0 or n_sim > 0:
            font_issue.append("%s(TNR%d/SimSun%d)" % (f17[:12], n_tnr, n_sim))
    for f17 in ("学生_七天作答纸合集.html", "学生_七天题目详解与答案.html"):
        p17 = os.path.join(ROOT, f17)
        if os.path.exists(p17) and "Times New Roman" not in io.open(p17, encoding="utf-8").read():
            font_issue.append(f17[:12])
    items.append(("G17 西文印刷体",
                  "✅ 通过" if not font_issue else "❌ 未通过",
                  "Times New Roman 已设" if not font_issue else "、".join(font_issue)))

    # ── 门禁 G18：数学分数必须是真分数竖式，不能是斜杠 ──
    # 阶段21 用户指出：「(m + n)/2025 分数仍然是这样没有改过来」。
    # 根子：§5A.14 规范第①条教孩子「不能写斜杠」，但**题面自己全是斜杠** ——
    # 规范与题面不一致，孩子照着抄必然写斜杠。规范必须从题面开始落地。
    import frac_render as _FR18
    n_fr = {"web": 0, "sheet_html": 0, "sheet_docx": 0, "key_html": 0, "key_docx": 0}
    # 题干里还剩多少真分数斜杠（得分 4/8 分、d/f 字母组合不算）
    slash_left = 0
    for d in _D.load_days():
        for q in d["qs"]:
            txt = q["stem"] + " " + q.get("sol", "") + " " + q.get("hint", "")
            txt = _FR18.FR_RE.sub("", txt)      # 先去掉已转换的竖式
            _, hits = _FR18.slashes_to_frac(txt)
            slash_left += len(hits)
    web18 = os.path.join(ROOT, "学生_三科考点7天攻坚_v*.html")
    import glob as _g
    w18 = sorted(_g.glob(web18))
    if w18:
        n_fr["web"] = io.open(w18[-1], encoding="utf-8").read().count("<mfrac>")
    ap18 = os.path.join(ROOT, "学生_七天作答纸合集.html")
    if os.path.exists(ap18):
        n_fr["sheet_html"] = io.open(ap18, encoding="utf-8").read().count("<mfrac>")
    sp18 = os.path.join(ROOT, "学生_七天作答纸合集.docx")
    if os.path.exists(sp18):
        n_fr["sheet_docx"] = zipfile.ZipFile(sp18).read("word/document.xml").decode("utf-8").count("<m:f>")
    for f18, k18 in [("学生_七天题目详解与答案.html", "key_html"),
                     ("学生_七天题目详解与答案.docx", "key_docx")]:
        p18 = os.path.join(ROOT, f18)
        if not os.path.exists(p18):
            continue
        if f18.endswith(".html"):
            n_fr[k18] = io.open(p18, encoding="utf-8").read().count("<mfrac>")
        else:
            n_fr[k18] = zipfile.ZipFile(p18).read("word/document.xml").decode("utf-8").count("<m:f>")
    ok18 = slash_left == 0
    items.append(("G18 真数学排版",
                  "✅ 通过" if ok18 else "❌ 未通过",
                  "题面残留斜杠 %d · MathML web%d/纸%d/册%d · OMML 纸docx%d/册docx%d"
                  % (slash_left, n_fr["web"], n_fr["sheet_html"], n_fr["key_html"],
                     n_fr["sheet_docx"], n_fr["key_docx"])))

    # ── 门禁 G19：五份产物题号必须一一对应 ──
    # 阶段21 用户：「你的题目要跟网页版一一对应，这个检查也要进入技能」。
    # 题号是跨产物的唯一锚点：对不上，孩子手上是第5 题、网页讲的是第 4 题。
    rc19, out19 = sh("verify_alignment.py", "--root", ROOT)
    ok19 = rc19 == 0 and "✅ 通过" in out19
    last = [l.strip() for l in out19.splitlines() if "题号完全一致" in l]
    items.append(("G19 五产物题号对齐",
                  "✅ 通过" if ok19 else "❌ 未通过",
                  last[0] if last else (out19.strip().splitlines()[-1] if out19.strip() else "")))

    # ── 门禁 G20：每个分数都必须渲染成「分子在上 / 分母在下」──
    # 阶段21 用户发现网页把 (m+n)/2025 的 2025 显示成**指数**。
    # 根因：MathML <mfrac> 只接受 **2 个孩子**，第一版把分子拆成多段给了 4 个，
    # 浏览器只能瞎猜。docx 的 OMML <m:f> 结构本来就合法，所以纸面是对的、网页错。
    # 判定两条：① <mfrac> 孩子数必须 == 2  ② 分母不能为空
    rc20, out20 = sh("check_fracs.py")
    ok20 = rc20 == 0 and "全部渲染正确" in out20
    n20 = [l.strip() for l in out20.splitlines() if "结论" in l]
    items.append(("G20 分数渲染正确",
                  "✅ 通过" if ok20 else "❌ 未通过",
                  n20[0] if n20 else out20.strip().splitlines()[-1] if out20.strip() else ""))

    # ── 门禁 G21：内容质量四检（划线 / 阅读题顺序 / 范例泄露 / 视频对症）──
    # 阶段21 用户一次性指出的四类硬伤，都是「内容正确性」问题，
    # 之前的门禁只管格式（分数/字体/题号），管不到。
    import importlib.util as _ilu
    def _mod(fn):
        sp = _ilu.spec_from_file_location(fn[:-3], os.path.join(SK, fn))
        m = _ilu.module_from_spec(sp)
        sp.loader.exec_module(m)
        return m
    try:
        _VC = _mod("verify_content.py")
        _days21 = _VC.D.load_days(os.path.join(ROOT, "_p5"))
        for d21 in _days21:
            p21 = os.path.join(ROOT, "_p5", "day%d.txt" % d21["n"])
            d21["raw"] = io.open(p21, encoding="utf-8").read() if os.path.exists(p21) else ""
        _e21 = (_VC.check_underline(_days21) + _VC.check_reading_order(_days21)
                + _VC.check_sample_leak(_days21) + _VC.check_videos(_days21))
        items.append(("G21 内容质量四检",
                      "✅ 通过" if not _e21 else "❌ 未通过",
                      "划线/阅读顺序/范例/视频 %d 处问题" % len(_e21)))
    except Exception as _ex:
        items.append(("G21 内容质量四检", "❌ 未通过", "脚本异常：%s" % _ex))

    # ── 门禁 G22：题目完整性（每道题都要「能做」）──
    # 阶段21 用户：「除了第一二天的，其他都要检查完善」
    # 实测查出 3 处「选择题只有 3 个选项」（Day3/4/6），已补。
    try:
        _VQ = _mod("verify_quality.py")
        _e22 = _VQ.audit(_VQ.D.load_days(os.path.join(ROOT, "_p5")))
        items.append(("G22 题目完整性",
                      "✅ 通过" if not _e22 else "❌ 未通过",
                      "题干/选项/答案/解析/短文 %d 处缺陷" % len(_e22)))
    except Exception as _ex:
        items.append(("G22 题目完整性", "❌ 未通过", "脚本异常：%s" % _ex))

    if os.path.exists(cloud):
        import time
        age_h = (time.time() - os.path.getmtime(cloud)) / 3600
        items.append(("云端副本新鲜度",
                      "✅" if age_h < 72 else "⚠️ 已 %.0f 小时未刷新" % age_h,
                      "上云包/errors.csv"))

    print("=" * 64)
    print("交付前总校验")
    print("=" * 64)
    for name, st, note in items:
        print("  %-24s %-18s %s" % (name, st, note))
    fails = [i for i in items if i[1].startswith("❌")]
    print("-" * 64)
    if fails:
        print("❌ %d 项未通过，不交付" % len(fails))
        return 1
    print("✅ 全部通过，可以交付")
    return 0


if __name__ == "__main__":
    sys.exit(main())
