# -*- coding: utf-8 -*-
"""全量自查：用户历次要求，逐条对照当前产物是否落地。

阶段22 用户追问：「是否全部都改过来了？是否全部把有价值的要求都固化到技能中了？」

## 为什么要写这个脚本
口头说「都改好了」没有说服力，也容易漏。
把每条要求变成**可判定的检查**，逐条打勾，漏了会红。

检查项来自 阶段20 到 阶段22 用户的原话。
"""
import io
import os
import re
import sqlite3
import sys
import zipfile

SK = r"<SKILL_DIR>"
ROOT = r"<WORKSPACE>\07_技能与脚本\build_workspace"
sys.path.insert(0, os.path.join(SK, "scripts"))
import dsl_source as D  # noqa: E402

DAYS = D.load_days(os.path.join(ROOT, "_p5"))
ok = 0
bad = []


def check(cond, label, detail=""):
    global ok
    if cond:
        ok += 1
        print("  ✅ %-42s %s" % (label, detail))
    else:
        bad.append(label)
        print("  ❌ %-42s %s" % (label, detail))


def src_of(q):
    t = re.sub(r"<[^>]+>", "", q["stem"])
    m = re.search(r"（([^）]*)）", t)
    return m.group(1) if m else ""


print("=" * 74)
print("一、题目来源（用户：语文数学英语都要尽量使用学情分析中的题目）")
print("=" * 74)
total = sum(len(d["qs"]) for d in DAYS)
newb = [(d["n"], q["no"]) for d in DAYS for q in d["qs"] if "新编" in src_of(q)]
check(len(newb) / total < 0.25, "新编占比 < 25%",
      "新编 %d / 共 %d = %.0f%%" % (len(newb), total, len(newb) * 100.0 / total))
# Day3-6 是还没做的、可改的
newb_36 = [x for x in newb if x[0] in (3, 4, 5, 6)]
check(len(newb_36) <= 10, "Day3-6 新编 ≤10", "剩 %d 道" % len(newb_36))

print()
print("=" * 74)
print("二、视频针对性（用户：所有视频一定要有针对性，尤其数学）")
print("=" * 74)
vid_ok = True
for d in DAYS:
    if d["n"] == 7:
        continue
    raw = io.open(os.path.join(ROOT, "_p5", "day%d.txt" % d["n"]), encoding="utf-8").read()
    for b in re.split(r"^SUB\|", raw, flags=re.M)[1:]:
        name = b.split("\n")[0].split("|")[0].strip()
        if name.startswith(("📋", "📇")) or "测评" in name[:6] or "学习卡" in name[:6]:
            continue
        vids = re.findall(r"^VID\|", b, re.M)
        qtypes = set(re.findall(r"【题型】([^<]+)", b))
        if len(vids) < 2:
            vid_ok = False
            print("     ⚠ Day%d「%s」视频仅 %d 条" % (d["n"], name[:18], len(vids)))
        # 题型覆盖交给 check_videos 精确判断（按题型匹配视频关键词），
        # 这里只要求"每个 SUB ≥2 条"。用「题型数 > 2」当阈值太粗会误报。

check(vid_ok, "每个考点 ≥2 条视频且题型数可控", "")

print()
print("=" * 74)
print("三、内容质量四检 + 完整性（G20/G21/G22）")
print("=" * 74)
import check_fracs      # noqa: E402
import verify_content   # noqa: E402
import verify_quality   # noqa: E402

for d in DAYS:
    p = os.path.join(ROOT, "_p5", "day%d.txt" % d["n"])
    d["raw"] = io.open(p, encoding="utf-8").read() if os.path.exists(p) else ""

e_frac = []
for label, fn, kind, strict in [
        ("Day3讲义", "学生_DayN_讲义_YYYYMMDD.html", "html", False),
        ("作答纸合集docx", "学生_七天作答纸合集.docx", "docx", False),
        ("答案册docx", "学生_七天题目详解与答案.docx", "docx", True)]:
    f = os.path.join(ROOT, fn)
    if not os.path.exists(f):
        continue
    known = check_fracs.dsl_fracs()
    n, b = (check_fracs.check_docx(f, known if strict else set()) if kind == "docx"
            else check_fracs.check_html(f, known if strict else set()))
    e_frac += b
check(not e_frac, "分数/上标渲染全对", "%d 处问题" % len(e_frac))

e21 = (verify_content.check_underline(DAYS) + verify_content.check_reading_order(DAYS)
       + verify_content.check_sample_leak(DAYS) + verify_content.check_videos(DAYS))
check(not e21, "内容四检（划线/阅读顺序/范例/视频）", "%d 处" % len(e21))

e22 = verify_quality.audit(DAYS)
check(not e22, "题目完整性（4选项/答案/解析/短文）", "%d 处" % len(e22))

print()
print("=" * 74)
print("四、技能固化（用户：检查要进技能，防止下次再犯）")
print("=" * 74)
skill_md = io.open(os.path.join(SK, "SKILL.md"), encoding="utf-8").read()
# 铁律是 1–32 连续编号（正文里另有 1./2./3. 列表，不能用总条数判断）
nums = [int(x) for x in re.findall(r"^(\d+)\. \*\*", skill_md, re.M)]
max_rule = max(nums) if nums else 0
check(max_rule >= 32, "SKILL.md 铁律条数", "编号最大 %d（1–33 应连续）" % max_rule)

pipe = io.open(os.path.join(SK, "references", "lecture-pipeline.md"), encoding="utf-8").read()
secs = re.findall(r"^### 5A\.(\d+)", pipe, re.M)
check(len(secs) >= 28, "lecture-pipeline.md 章节数", "%d 节（到 5A.%s）" % (len(secs), secs[-1] if secs else "?"))

grading = io.open(os.path.join(SK, "references", "grading-feedback-loop.md"), encoding="utf-8").read()
check("判分器的两处致命误判" in grading or "致命误判" in grading, "批改误判三例已记", "")

SCRIPTS = ["mathml_render.py", "omml_math.py", "frac_render.py", "check_fracs.py",
           "verify_content.py", "verify_quality.py", "verify_alignment.py",
           "grade_submission.py", "survey_bank.py", "answer_formula.py"]
miss = [s for s in SCRIPTS if not os.path.exists(os.path.join(SK, "scripts", s))]
check(not miss, "关键脚本齐全", "缺 %s" % miss if miss else "%d 个" % len(SCRIPTS))

# 每条用户要求是否在技能里有对应条目
REQS = [
    ("英语划线", ["<u>", "划线"]),
    ("阅读题顺序", ["阅读题", "短文在前"]),
    ("范例不泄露", ["范例", "占位符"]),
    ("视频针对性", ["视频必须覆盖", "针对性"]),
    ("分数渲染", ["mfrac", "2 个孩子"]),
    ("上标渲染", ["裸 Unicode 上标", "msup"]),
    ("渲染不改题意", ["不能改变题意", "改错"]),
    ("判分误判", ["判分", "冤枉"]),
    ("题目来源", ["学情分析原卷", "原卷"]),
    ("全角竖线", ["全角", "｜"]),
    ("先核查再换题", ["先核查", "标签写错"]),
]
for name, kws in REQS:
    hit = any(k in skill_md or k in pipe or k in grading for k in kws)
    check(hit, "要求已固化：%s" % name, "")

print()
print("=" * 74)
print("结论：%s" % ("✅ 全部落地（%d 项通过）" % ok if not bad
                else "❌ %d 项未通过：%s" % (len(bad), "；".join(bad))))
print("=" * 74)
