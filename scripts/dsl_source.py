#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""DSL 源解析（唯一真值）+ 版式参数集中定义。

网页讲义、作答纸、答案册**三份产物都从同一份 DSL 源生成**，
因此题号、题干、答案天然同源，不需要在产物之间做二次对齐。

用法：import dsl_source as D; days = D.load_days()
"""
import io, os, re, html as H

SRC_DIR = "_p5"
KINDS = ("MC", "FILL", "JUDGE")
SUBJ_MAP = {"数学": "数学", "语文": "语文", "英语": "英语"}
KIND_CN = {"MC": "选择题", "FILL": "填空题", "JUDGE": "简答题"}

# ============================================================
# 版式参数（阶段19 压缩版：省纸 + 字号放大）
# 用户反馈：「空白太多太浪费纸，字体太小不便于阅读」
# ------------------------------------------------------------
# 单位换算：1pt = 20 twips；w:sz 单位是半磅（24 = 12pt）
# A4 高 16838 twips = 841pt；正文行距 w:line 是 240 分之几倍
# ============================================================
SZ_BODY   = 24    # 12.0pt 正文　　（原 22 = 11pt，用户嫌小）
SZ_QNO    = 26    # 13.0pt 题号　　（原 22）
SZ_HEAD   = 28    # 14.0pt 天标题　（原 28，保持）
SZ_NOTE   = 21    # 10.5pt 说明　　（原 19，太小）
SZ_TITLE  = 36    # 18.0pt 封面标题

LINE_BODY = 330   # 正文行距 1.375 倍（原 320 = 1.333）
RULE_H    = 440   # 答题横线行高 22pt（原 520 = 26pt，太占地方）
N_MC      = 0     # 选择题**不给横线**：在选项前留 ○ 涂圈即可（用户要求全部题进纸，但要省纸）
N_FILL    = 5     # 数学填空题横线数基线（原 9）
N_JUDGE   = 5     # 语文简答题横线数基线（原 13）
RULE_MIN  = 4     # 每题最少横线（再少写不下）
RULE_MAX  = 7     # 每题最多横线（再多就又浪费了）
OPT_INLINE_MAX = 18   # 选项纯文本 ≤18 字就横排一行，否则竖排（省纸）
CHARS_PER_LINE = 42   # 每行能放多少个「中文字宽」（A4 宽 − 左右边距，12pt 宋体实测）

MARGIN_TB = 850   # 上下页边距 1.50cm（原 1134 = 2.0cm）
MARGIN_LR = 800   # 左右页边距 1.41cm（原 1021 = 1.8cm）
GAP_Q     = 60    # 题间距（原 80）
HEAD_PT   = 55.0  # 每天首页页头（标题+统计+署名行）约占高度
HEAD_CONT = 22.0  # 续页只剩自然流出的内容，预留一点余量即可
GAP_PT    = 7.0   # 题间空段的实际高度（空段 4pt + 段后 3pt）
SAFETY    = 0.93  # 版面安全系数：只用 93% 的可用高度，防止估算误差导致溢出到第二页
TOL_PT    = 30.0  # 装箱容差：SAFETY 已留 53pt 余量，允许再挤 30pt 减少「就差一点点」分到下一页

# 推导：可用版面高度
PAGE_H    = 16838                       # A4 高（twips）
USABLE_PT = (PAGE_H - MARGIN_TB * 2) / 20.0   # ≈ 757pt


def to_lines(s):
    """HTML 片段 → 纯文本行列表（去标签 + 反转义 + 去空行）。

    ⚠️ **保留真分数竖式**（阶段21）：不能简单剥掉所有标签，否则
    <span class="fr"> 的分子/分母会丢，竖式退回斜杠 —— 与 §5A.14 规范第①条冲突。
    """
    try:
        import frac_render as _FR
        return _FR.to_lines_keep_frac(s)
    except Exception:
        pass
    s = re.sub(r'<br\s*/?>', '\n', s)
    s = re.sub(r'<[^>]+>', '', s)
    s = H.unescape(s)
    return [x.strip() for x in s.split('\n') if x.strip()]


def subj_of(name):
    """小节名 → 科目。识别不出时返回 None（调用方沿用上一个科目）。

    例：Day7 首个 SUB 是「📋 测评说明」，其下的 1~6 题其实是数学，
    识别不出时应沿用默认值而不应标成"综合"。
    """
    for k, v in SUBJ_MAP.items():
        if name.startswith(k):
            return v
    return None


def parse(text):
    """产出 (kind, payload) 序列；LEC<<<...>>> 合并为一块。"""
    lines = text.replace("\r\n", "\n").split("\n")
    out, i = [], 0
    while i < len(lines):
        ln = lines[i].strip()
        i += 1
        if not ln:
            continue
        # 块指令：LOGIC<<<...>>>（原理层）与 LEC<<<...>>>（操作层）同格式
        # LOGIC 不以 LEC 开头，故互不干扰；LOGIC 必须在 LEC 之前判断以免歧义。
        if ln.startswith("LOGIC<<<"):
            buf = [ln[8:]]
            while i < len(lines) and not lines[i].strip().startswith(">>>"):
                buf.append(lines[i])
                i += 1
            i += 1
            out.append(("LOGIC", "\n".join(buf)))
            continue
        if ln.startswith("LEC<<<"):
            buf = [ln[6:]]
            while i < len(lines) and not lines[i].strip().startswith(">>>"):
                buf.append(lines[i])
                i += 1
            i += 1
            out.append(("LEC", "\n".join(buf)))
            continue
        # BJ<<<...>>>：病句题「逐句语病定性表」，必须紧跟在题目行之后
        # 每行一条：序号|句子摘引|语病类型|改法
        if ln.startswith("BJ<<<"):
            buf = [ln[5:]]
            while i < len(lines) and not lines[i].strip().startswith(">>>"):
                buf.append(lines[i])
                i += 1
            i += 1
            out.append(("BJ", "\n".join(buf)))
            continue
        if ln == "ENDDAY":
            out.append(("ENDDAY", []))
            continue
        parts = ln.split("|")
        out.append((parts[0], parts[1:]))
    return out


def load_days(src_dir=SRC_DIR):
    """逐日解析 DSL，返回 [{n, title, goal, qs:[...]}]。

    每题字段：no / kind / subj / stem / opts / idx / letter /
              ans / ans_plain / hint / sol
    题号 no：遇 DAY 重置为 0，遇 MC/FILL/JUDGE +1 —— 与 lecture_dsl.py 的 dq 同逻辑。

    ⚠️ 阶段22 审计：`SRC_DIR = "_p5"` 是相对路径，本机没有这个目录 ——
    讲义 DSL 源（day1.txt~day7.txt）已丢失。调用方（如 grade_submission.py）
    原来只会看到「day=N 不存在」这种迷惑错误，根本不知道是源目录没了。
    这里改成目录不存在就直接抛 FileNotFoundError 并说清原因。
    """
    if not os.path.isdir(src_dir):
        raise FileNotFoundError(
            '题目 DSL 源目录不存在：%r\n'
            '  讲义源 day1.txt~day7.txt 不在本机（历史上用的是临时目录 _p5，已丢失）。\n'
            '  影响：grade_submission.py 无法运行（它靠这里读题）。\n'
            '  修法二选一：① 重新生成讲义 DSL 并存到固定目录，用 load_days(该目录)；'
            '② 改成从 questions 表读题（库里 7 天的讲义题还在）。' % src_dir)
    days = []
    for d in range(1, 9):
        path = os.path.join(src_dir, "day%d.txt" % d)
        if not os.path.exists(path):
            continue
        text = io.open(path, encoding="utf-8").read()
        day = {"n": d, "title": "", "goal": "", "qs": [], "logics": []}
        cur_sub = "数学"   # 默认；识别不出科目时沿用上一个
        qno = 0
        for kind, p in parse(text):
            if kind == "DAY":
                day["title"] = p[1] if len(p) > 1 else ""
                day["goal"] = "|".join(p[3:]) if len(p) > 3 else ""
            elif kind == "LOGIC":
                # 原理层：挂在当天上，供答案册复用；网页由 lecture_dsl.py 自行渲染
                day["logics"].append(p)
            elif kind == "SUB":
                s = subj_of(p[0])
                if s:
                    cur_sub = s
            elif kind == "BJ":
                # 逐句语病定性表：挂到上一道题（病句题）
                rows = []
                for ln2 in p.split("\n"):
                    ln2 = ln2.strip()
                    if not ln2:
                        continue
                    c = ln2.split("|")
                    if len(c) < 4:
                        continue
                    rows.append(dict(no=c[0].strip(), sent=c[1].strip(),
                                     typ=c[2].strip(), fix=c[3].strip()))
                if day["qs"]:
                    day["qs"][-1]["bjtab"] = rows
            elif kind in KINDS:
                qno += 1
                # 倒数字段法（题干里可能含 |，所以不能从左边数）
                if kind in ("MC", "FILL"):
                    sol, hint, a3, a4 = p[-1], p[-2], p[-3], p[-4]
                    stem = "|".join(p[:-4])
                else:  # JUDGE
                    sol, hint, a3 = p[-1], p[-2], p[-3]
                    a4 = ""
                    stem = "|".join(p[:-3])
                q = {"no": qno, "kind": kind, "subj": cur_sub, "stem": stem,
                     "opts": [], "idx": -1, "letter": "", "hint": hint, "sol": sol,
                     "qtype": "", "bingju": [], "bjtab": []}
                # 题干里的题型标签抽成结构化字段，标签本身从题干移除（避免与题头重复）
                mq = re.search(r'<b class="qt">【题型】([^<]+)</b>', stem)
                if mq:
                    q["qtype"] = mq.group(1).strip()
                    stem = stem.replace(mq.group(0), "", 1)
                mb = re.search(r'<b class="qb">【语病清单】([^<]+)</b>', stem)
                if mb:
                    q["bingju"] = [x.strip() for x in mb.group(1).split("｜") if x.strip()]
                    stem = stem.replace(mb.group(0), "", 1)
                stem = re.sub(r'^[　\s]+', '', stem)   # 去掉标签留下的前导空格
                q["stem"] = stem
                if kind == "MC":
                    try:
                        idx = int(a3)
                    except ValueError:
                        idx = 0
                    ol = a4.split("@")
                    q["opts"] = ol
                    q["idx"] = idx
                    q["letter"] = "ABCD"[idx] if 0 <= idx < 4 else "?"
                    q["ans_plain"] = ol[idx] if idx < len(ol) else ""
                    q["ans"] = "%s．%s" % (q["letter"], q["ans_plain"])
                else:
                    q["ans"] = a3
                    q["ans_plain"] = a3
                day["qs"].append(q)
        days.append(day)
    return days


def n_rules(kind):
    """该题型给几条答题横线（基线值）。选择题 0 条 —— 用 ○ 涂圈代替。"""
    if kind == "MC":
        return N_MC
    return N_FILL if kind == "FILL" else N_JUDGE


OPT_PREFIX_W = 7.0   # "○ A．" 前缀的视觉宽度（中文字宽计）


def opt_width(o):
    """单个选项的视觉宽度（含 ○ A． 前缀）。"""
    return _wlen(re.sub(r'<[^>]+>', '', H.unescape(o))) + OPT_PREFIX_W


def opt_rows(q):
    """选项装箱：返回 [[选项下标...], ...]，一个元素 = 纸上印一行。

    ⚠️ 不能简单判「最长选项 ≤18 字就横排」——4 个 18 字选项合计 72 字，
    远超每行 42 字，印出来照样折成两行。必须按宽度贪心装箱。
    """
    opts = q.get("opts") or []
    if not opts:
        return []
    ws = [opt_width(o) for o in opts]
    if max(ws) > CHARS_PER_LINE:
        # 有超长选项：独占一行，让它自然折行
        return [[i] for i in range(len(opts))]
    rows, cur, w = [], [], 0.0
    for i, ow in enumerate(ws):
        if cur and w + ow > CHARS_PER_LINE:
            rows.append(cur)
            cur, w = [], 0.0
        cur.append(i)
        w += ow
    if cur:
        rows.append(cur)
    return rows


def opt_lines(q):
    """选项最终占几行（含超长选项的自动折行）。"""
    rows = opt_rows(q)
    if not rows:
        return 0
    n = 0
    for r in rows:
        w = sum(opt_width(q["opts"][i]) for i in r)
        n += max(1, int(w // CHARS_PER_LINE) + (1 if w % CHARS_PER_LINE else 0))
    return n


def fit_rules(qs, head_pt=HEAD_PT):
    """【兼容旧调用】按真实可用高度分页，返回 (每题横线数, 当天总高 pt)。

    ⚠️ v14 起「每天强制 1 页」的假设不再成立（全部 63 题进纸后，
    单天实测 920~1683pt，远超 757pt 的可用版面），必须按真实页高切分。
    新代码请用 paginate() / plan_day()。
    """
    per, pages = plan_day(qs)
    return per, sum(h for _, h in pages)


def paginate(qs, per):
    """按真实可用高度把一天的题目切成若干页。

    返回 [(本页题目列表, 本页占高 pt)]。
    首页要扣掉页头 HEAD_PT，续页只扣 HEAD_CONT。
    一题不跨页（题号+题干+答题区保持完整），放不下就整个挪到下一页。
    """
    cap = USABLE_PT * SAFETY
    pages, cur, h = [], [], 0.0
    for q in qs:
        qh = est_height_pt(q, with_rule=True,
                            per=(per if n_rules(q["kind"]) > 0 else 0))
        limit = cap - (HEAD_PT if not pages else HEAD_CONT) + TOL_PT
        if cur and h + qh > limit:
            pages.append((cur, h))
            cur, h = [], 0.0
        cur.append(q)
        h += qh
    if cur:
        pages.append((cur, h))
    return pages or [([], 0.0)]


def plan_day(qs):
    """为一天挑一个「不增加页数」的最大横线数。

    逻辑：先按最少横线数 RULE_MIN 排一遍，得到最少页数 base；
    再从 RULE_MAX 往下试，取第一个页数仍 ≤ base 的值。
    这样既不多用纸，又把剩余空间尽量还给了书写区（回应「空白太多」）。

    返回 (每题横线数, 分页结果 pages)。
    """
    if not qs:
        return RULE_MIN, [([], 0.0)]
    base = len(paginate(qs, RULE_MIN))
    for p in range(RULE_MAX, RULE_MIN, -1):
        pg = paginate(qs, p)
        if len(pg) <= base:
            return p, pg
    return RULE_MIN, paginate(qs, RULE_MIN)


def _wlen(s):
    """视觉宽度：中日韩字符算 1，英文/数字/空格算 0.55（用于估算折行）。"""
    w = 0.0
    for ch in s:
        w += 1.0 if ord(ch) > 0x2E80 else 0.55
    return w


def est_lines(s, per_line=None):
    """估算一段文字在纸上要占几行。

    ⚠️ 不能只按 <br> 数行 —— 长题干（如英语阅读原文）没有 <br>，
    但在 12pt 下会折成 8~10 行。只数 <br> 会严重低估，导致横线分配过多、实际溢出。
    """
    per_line = per_line or CHARS_PER_LINE
    n = 0
    for ln in to_lines(s):
        w = _wlen(ln)
        n += max(1, int(w // per_line) + (1 if w % per_line else 0))
    return n


def est_height_pt(q, with_rule=True, per=None):
    """估算一题在纸上占多少 pt（用于页数测算与横线分配，不参与排版）。

    高度 = 题号行 + 题干行 + 选项行 + 答题横线 + 题间空段，
    每段都带上它自己的 space_after（twips → pt 除以 20）。
    """
    # ⚠️ w:sz 单位是**半磅**，除以 2 才是 pt（除以 20 是把 twips 换 pt，两者别混）
    line = SZ_BODY / 2.0 * (LINE_BODY / 240.0)         # 一个正文行的高度（12pt × 1.375 ≈ 16.5pt）
    h = SZ_QNO / 2.0 * (LINE_BODY / 240.0) + 30 / 20.0          # 题号行 + 段后 1.5pt
    h += est_lines(q["stem"]) * (line + 20 / 20.0)              # 题干（含自动折行）
    n = opt_lines(q)
    if n:                                                       # 选项行（装箱后）
        h += n * line + 12 / 20.0
    if with_rule:
        per = n_rules(q["kind"]) if per is None else per
        h += per * RULE_H / 20.0
    h += GAP_PT
    return h
