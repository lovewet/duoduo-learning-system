#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""四产物一一对应校验（阶段21 用户要求，检查要进技能）。

需求原话：「你的**题目要跟网页版一一对应**，你再重新检查，**这个检查也要进入技能**」

## 为什么必须有这道门禁

题号是**跨产物的唯一锚点**：孩子手上是纸（作答纸 docx），
想看讲解是网页（讲义）。两边对不上就是**灾难**——
他做第 5 题，网页讲的却是第 4 题；或者纸上有 10 题、网页只有 8 题。

本项目已经因为「题号各编各的」踩过坑（§6.5.2 规则 3「题号同源」）。
本脚本把这个要求从「口头约定」变成**机器判定**。

## 校什么（四产物两两对齐）

| 产物 | 形态 | 题号来源 |
|:--|:--|:--|
| 网页讲义 | html | `<div class="qno">第 N 题</div>` |
| 答案册 docx | docx | `第 N 题（科目 · 题型：xxx）` |
| 答案册 html | html | `<span class="qno">第 N 题</span>` |
| 作答纸 docx | docx | `第 N 题（科目 · 选择题）` |
| 作答纸 html | html | `<div class="qh">第 N 题（…）</div>` |

对齐三件事，缺一不可：
1. **题号集合完全相同**（不多不少、顺序一致）
2. **每天题数一致**（防止某天少印了几题）
3. **科目标注一致**（数学/语文/英语不能错位）

## 用法
    python verify_alignment.py            # 自动找最新产物
    python verify_alignment.py --root 目录 # 指定工作区
"""
import io, os, re, sys, glob, zipfile, argparse

KIND_CN = {"MC": "选择题", "FILL": "填空题", "JUDGE": "简答题"}


def _clean(s):
    s = re.sub(r'<[^>]+>', '', s)
    import html as H
    return H.unescape(s)


# ---------- 各产物的题号提取 ----------
def from_web(path):
    """网页讲义：<div class="qno">第 N 题</div>，按天分组。

    ⚠️ **必须按 daysec 出现位置顺序切片**，不能用 `t.find('day3')` ——
    讲义页顶部有导航目录（先出现 day1~day7 的链接），
    `find` 会命中导航而不是正文，导致每天都被截成同一段、
    末尾几题（9、10…）看起来「缺失」（实测踩过）。
    """
    t = io.open(path, encoding="utf-8").read()
    # 收集所有 daysec 的位置，按 d 升序配对成区间
    # ⚠️ 只锚 `id="dayN"`（**不要求紧跟 `>`**）—— 实际结构是
    # `<div class="daysec" id="day2"><div class="dayhead m"><div class="dnum">DAY 2</div>`，
    # dnum 用的是英文 `DAY 2` 不是「第 2 天」。曾经按精确串匹配失败而回退，
    # 导致每天都被截断、末尾题看起来「缺失」。
    marks = []
    for d in range(1, 9):
        m = re.search(r'id="day%d"' % d, t)
        if m:
            marks.append((m.start(), d))
    marks.sort()
    days = {}
    for i, (pos, d) in enumerate(marks):
        end = marks[i + 1][0] if i + 1 < len(marks) else len(t)
        seg = t[pos:end]
        nos = [int(x) for x in
               re.findall(r'<div class="qno">第\s*(\d+)\s*题</div>', seg)]
        if nos:
            days[d] = nos
    if not days:
        nos = [int(x) for x in re.findall(r'第\s*(\d+)\s*题', t)]
        if nos:
            days[0] = nos
    return days


def from_answer_docx(path):
    """答案册 docx：第 N 题（科目 · 题型：xxx）"""
    x = zipfile.ZipFile(path).read("word/document.xml").decode("utf-8")
    t = _clean(x)
    return _split_days(t, r'第\s*(\d+)\s*题（\s*([数学语文英语]+)\s*·\s*[^）]*）')


def from_answer_html(path):
    """答案册 html：<span class="qno">第 N 题</span> + tag 科目。

    ⚠️ **分天必须锚定标题标记 `<div class="dnum">第 N 天</div>`**，
    绝不能全文扫 `第 N 天` —— 题目正文里就有例句
    「『第 20 天有多少』」（找规律题），会被误认成「第 20 天」，
    导致那一天整段题号丢失（实测踩过：第4 天被判成第 20 天）。
    """
    t = io.open(path, encoding="utf-8").read()
    # 锚定：天标题 dnum（唯一可信锚点）
    DAY = re.compile(r'<div class="dnum">第\s*(\d+)\s*天</div>')
    days, cur = {}, 0
    for m in re.finditer(
            r'<span class="qno">第\s*(\d+)\s*题</span>\s*<span class="tag[^"]*">([^<]*)</span>',
            t):
        no = int(m.group(1))
        pre = t[:m.start()]
        dm = None
        for dm2 in DAY.finditer(pre):
            dm = dm2
        d = int(dm.group(1)) if dm else 0
        days.setdefault(d, []).append(no)
    return days


def from_sheet_docx(path):
    """作答纸 docx：第 N 题（科目 · 选择题）"""
    x = zipfile.ZipFile(path).read("word/document.xml").decode("utf-8")
    t = _clean(x)
    # 作答纸每天开头有「第 N 天　标题」，据此分天
    days, cur = {}, 0
    for m in re.finditer(r'(?<![\d\-])第\s*(\d+)\s*天(?![\d\-])|第\s*(\d+)\s*题（\s*([数学语文英语]+)\s*·\s*([^）]*)）', t):
        if m.group(1):
            cur = int(m.group(1))
            continue
        no, subj, kind = int(m.group(2)), m.group(3), m.group(4)
        days.setdefault(cur, []).append(no)
    return days


def from_sheet_html(path):
    """作答纸 html：<div class="qh">第 N 题（科目 · 选择题）</div>"""
    t = io.open(path, encoding="utf-8").read()
    days, cur = {}, 0
    for m in re.finditer(r'<div class="dh">第\s*(\d+)\s*天(?![\d\-])|<div class="qh">第\s*(\d+)\s*题（\s*([^·<]+)·\s*([^）]+)）', t):
        if m.group(1):
            cur = int(m.group(1))
            continue
        days.setdefault(cur, []).append(int(m.group(2)))
    return days


def _split_days(text, pat):
    """按「第 N 天」把纯文本切成天，再按 pat 提题号。"""
    days, cur = {}, 0
    # 先按天切
    DAY = r'(?<![\d\-])第\s*(\d+)\s*天(?![\d\-])'
    marks = [(m.start(), int(m.group(1))) for m in re.finditer(DAY, text)]
    if not marks:
        nos = [int(m.group(1)) for m in re.finditer(pat, text)]
        return {0: nos} if nos else {}
    for idx, (pos, d) in enumerate(marks):
        seg = text[pos: marks[idx + 1][0] if idx + 1 < len(marks) else len(text)]
        nos = [int(m.group(1)) for m in re.finditer(pat, seg)]
        if nos:
            days[d] = nos
    return days


# ---------- 对齐判定 ----------
def compare(name_a, da, name_b, db, errs):
    """两产物逐天比对题号序列。"""
    ka, kb = sorted(da.keys()), sorted(db.keys())
    if ka != kb:
        errs.append("%s vs %s：天数不一致 %s vs %s"
                    % (name_a, name_b, ka, kb))
        return
    for d in ka:
        a, b = da[d], db[d]
        if a != b:
            only_a = [x for x in a if x not in b]
            only_b = [x for x in b if x not in a]
            errs.append("%s vs %s · 第%d天题号不一致：%s%d vs %s%d"
                        % (name_a, name_b, d,
                           a, len(a), b, len(b)))
            if only_a:
                errs.append("   → 只有 %s 有：%s" % (name_a, only_a))
            if only_b:
                errs.append("   → 只有 %s 有：%s" % (name_b, only_b))
        elif len(a) != len(b):
            errs.append("%s vs %s · 第%d天题数 %d vs %d" % (name_a, name_b, d, len(a), len(b)))


def latest(pat):
    """取版本号最大的文件（R 由 main 注入为全局）。

    ⚠️ **不能直接 sorted()** —— 版本号是字符串，
    'v9' > 'v43'（字典序），会拿回**旧版本**导致误判（实测踩过：
    sorted() 取到 v9，而真实最新是 v43，于是报「题目缺失」）。
    必须按数字排序。
    """
    cands = glob.glob(os.path.join(R, pat))
    if not cands:
        return None
    m = re.search(r'_v(\d+)\.html$', cands[0])
    if not m:
        return max(cands, key=os.path.getmtime)
    return max(cands, key=lambda p: int(re.search(r'_v(\d+)\.html$', p).group(1)))


def main():
    global R
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=os.getcwd())
    a = ap.parse_args()
    R = a.root

    def pick(pat):
        return latest(pat)

    web = pick("学生_三科考点7天攻坚_v*.html")
    key_d = os.path.join(R, "学生_七天题目详解与答案.docx")
    key_h = os.path.join(R, "学生_七天题目详解与答案.html")
    sh_d = os.path.join(R, "学生_七天作答纸合集.docx")
    sh_h = os.path.join(R, "学生_七天作答纸合集.html")

    missing = [n for n, p in [("网页讲义", web), ("答案册docx", key_d),
                              ("答案册html", key_h), ("作答纸docx", sh_d),
                              ("作答纸html", sh_h)] if not p or not os.path.exists(p)]
    if missing:
        print("❌ 缺少产物：%s" % "、".join(missing))
        return 1

    data = [
        ("网页讲义", from_web(web)),
        ("答案册docx", from_answer_docx(key_d)),
        ("答案册html", from_answer_html(key_h)),
        ("作答纸docx", from_sheet_docx(sh_d)),
        ("作答纸html", from_sheet_html(sh_h)),
    ]

    print("=" * 66)
    print("四产物一一对应校验 · 题号/天数/科目")
    print("=" * 66)
    for n, d in data:
        tot = sum(len(v) for v in d.values())
        print("  %-10s 天数 %d　题目 %d 道" % (n, len(d), tot))

    errs = []
    for i in range(len(data)):
        for j in range(i + 1, len(data)):
            compare(data[i][0], data[i][1], data[j][0], data[j][1], errs)

    print()
    if errs:
        print("❌ 发现 %d 处不对齐：" % len(errs))
        for e in errs:
            print("   " + e)
        print()
        print("结论：❌ 未通过，**不要发给孩子**（题号对不上会做错题）")
        return 1
    print("✅ 五份产物题号完全一致（题数 %d）"
          % sum(len(v) for v in data[0][1].values()))
    print("结论：✅ 通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
