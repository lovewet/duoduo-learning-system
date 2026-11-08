# -*- coding: utf-8 -*-
"""讲义版式门禁 G23：讲义「薄」、教案「厚」（阶段23 用户定标，固化进技能）

检查四件事：
  A 讲义每节 LEC 可见汉字 ≤ 450（超出 = 又在讲义里展开详解）
  B 单个要点卡 .one ≤ 90 汉字
  C 单个提示框 .note ≤ 110 汉字
  D 生成的 HTML 里字号达标（sname≥21、.one .lb≥14、.lec≥16、.one≥17）
  E 配套教案 docx 段落数 ≥ 100（教案必须比讲义厚）

用法：
  python verify_lecture_style.py            # 检查全部天
  python verify_lecture_style.py --days 4   # 只检查 Day4
  python verify_lecture_style.py --days 4,5,6 --root "<WORKSPACE>\07_技能与脚本\build_workspace"

退出码：0 = 全过；1 = 有问题
"""
import io
import os
import re
import sys

ROOT = os.environ.get("DUODUO_ROOT", r"<WORKSPACE>\07_技能与脚本\build_workspace")
PLAN_DIR = os.environ.get("DUODUO_PLAN_DIR", r"<WORKSPACE>\04_口头教案")

# 每天对应的教案 docx（讲义薄、教案厚 —— 教案必须存在且够厚）
PLANS = {
    4: "dongdian_lesson_plan.docx",
    5: "oral_day5_min_value.docx",
    6: "oral_day6_pattern.docx",
    7: "oral_day7_axis_abs.docx",
    8: "oral_day8_ops_app.docx",
}
DATES = {4: "YYYYMMDD", 5: "YYYYMMDD", 6: "YYYYMMDD", 7: "YYYYMMDD", 8: "YYYYMMDD"}

LIM_LEC = 450      # 每节 LEC 汉字上限
LIM_ONE = 90       # 单个要点卡上限
LIM_NOTE = 110     # 单个提示框上限
MIN_PLAN_PARA = 100  # 教案最少段落数


def cn(s):
    return len(re.findall(r"[\u4e00-\u9fff]", s))


def strip_tags(s):
    s = re.sub(r"<svg.*?</svg>", "", s, flags=re.S)
    s = re.sub(r"<[^>]+>", "", s)
    return s


def check_dsl(day, errs, warns):
    """A/B/C：查 DSL 源里的 LEC 块与要点卡字数。"""
    p = os.path.join(ROOT, "_p5", "day%d.txt" % day)
    if not os.path.exists(p):
        errs.append("Day%d 找不到 DSL：%s" % (day, p))
        return
    s = io.open(p, encoding="utf-8").read()

    lecs = re.findall(r"LEC<<<\n(.*?)\n>>>", s, re.S)
    if not lecs:
        errs.append("Day%d 没有任何 LEC 块" % day)
    for i, lec in enumerate(lecs, 1):
        n = cn(strip_tags(lec))
        if n > LIM_LEC:
            errs.append("Day%d 第 %d 节 LEC 有 %d 汉字（上限 %d）——讲义里展开了详解，"
                        "应删到要点、把讲法移进教案" % (day, i, n, LIM_LEC))
        for m in re.finditer(r'<div class="one"[^>]*>(.*?)</div>', lec, re.S):
            k = cn(strip_tags(m.group(1)))
            if k > LIM_ONE:
                head = strip_tags(m.group(1)).strip()[:14]
                errs.append("Day%d 第 %d 节要点卡「%s…」%d 汉字（上限 %d）"
                            % (day, i, head, k, LIM_ONE))
        for m in re.finditer(r'<div class="note[^"]*"[^>]*>(.*?)</div>', lec, re.S):
            k = cn(strip_tags(m.group(1)))
            if k > LIM_NOTE:
                head = strip_tags(m.group(1)).strip()[:14]
                errs.append("Day%d 第 %d 节提示框「%s…」%d 汉字（上限 %d）"
                            % (day, i, head, k, LIM_NOTE))


def check_html(day, errs):
    """D：字号必须达标（标题与重点必须醒目）。"""
    p = os.path.join(ROOT, "学生_Day%d_讲义_%s.html" % (day, DATES[day]))
    if not os.path.exists(p):
        errs.append("Day%d 找不到讲义 HTML：%s" % (day, os.path.basename(p)))
        return
    t = io.open(p, encoding="utf-8").read()
    need = [
        (r"\.subhead \.sname\{font-size:(\d+(?:\.\d+)?)px", 21, "小节标题 .sname"),
        (r"\.one \.lb\{display:block; font-size:(\d+(?:\.\d+)?)px", 14, "要点卡标题 .one .lb"),
        (r"\.lec\{font-size:(\d+(?:\.\d+)?)px", 16, "讲义正文 .lec"),
        (r"font-size:17\.6px|border-left:5px solid var\(--m\).*?font-size:(\d+(?:\.\d+)?)px", 17, "要点卡正文 .one"),
    ]
    for pat, low, label in need:
        m = re.search(pat, t)
        if not m:
            errs.append("Day%d 讲义里找不到 %s 的字号定义" % (day, label))
        else:
            try:
                v = float(m.group(1))
            except (IndexError, ValueError):
                continue
            if v < low:
                errs.append("Day%d %s 字号 %.1fpx，低于基准 %dpx" % (day, label, v, low))


def check_plan(day, errs, warns):
    """E：教案必须够厚（讲义删掉的详解要靠教案承接）。"""
    f = PLANS.get(day)
    if not f:
        warn_s = None
        errs.append("Day%d 未登记配套教案文件名（PLANS 表）" % day)
        return
    p = os.path.join(PLAN_DIR, f)
    if not os.path.exists(p):
        errs.append("Day%d 教案缺失：%s" % (day, f))
        return
    try:
        from docx import Document
    except ImportError:
        warns.append("Day%d 未装 python-docx，跳过教案段数检查" % day)
        return
    d = Document(p)
    n = len([x for x in d.paragraphs if x.text.strip()])
    if n < MIN_PLAN_PARA:
        errs.append("Day%d 教案只有 %d 段（下限 %d）——讲义删掉的讲解没有落进教案"
                    % (day, n, MIN_PLAN_PARA))


def main():
    args = sys.argv[1:]
    days = [4, 5, 6, 7, 8]
    if "--days" in args:
        v = args[args.index("--days") + 1]
        days = [int(x) for x in v.split(",") if x.strip()]
    errs, warns = [], []
    for d in days:
        check_dsl(d, errs, warns)
        check_html(d, errs)
        check_plan(d, errs, warns)

    print("=" * 60)
    print("G23 讲义版式门禁（讲义薄 / 教案厚）")
    print("=" * 60)
    print("检查范围：Day %s" % ",".join(str(d) for d in days))
    print("门槛：每节 LEC ≤ %d 字｜要点卡 ≤ %d 字｜提示框 ≤ %d 字｜教案 ≥ %d 段"
          % (LIM_LEC, LIM_ONE, LIM_NOTE, MIN_PLAN_PARA))
    print()
    if warns:
        for w in warns:
            print("  ⚠️ ", w)
        print()
    if not errs:
        print("结论：✅ 全部达标")
        return 0
    print("共 %d 处问题：" % len(errs))
    for e in errs:
        print("  ❌ ", e)
    print()
    print("结论：❌ 有 %d 处需要处理" % len(errs))
    return 1


if __name__ == "__main__":
    sys.exit(main())
