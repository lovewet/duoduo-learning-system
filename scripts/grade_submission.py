#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""作答提交 → 自动判分 → 入库（P1-3）。

入口有两条，都产出同一种 JSON：
  A. 网页「提交」按钮导出的 `作答_第N天.json`（电脑端）
  B. 手机上把答案报给 AI，由 AI 落成同样的 JSON（手机端主路径）

JSON 格式（最小可用）：
{
  "learner": "学生",
  "day": 3,
  "date": "阶段20",
  "channel": "web" | "phone" | "paper",
  "answers": {
     "1": {"type": "MC",    "value": "B"},
     "3": {"type": "FILL",  "value": "10"},
     "7": {"type": "JUDGE", "value": "① 内容上……② 效果上……"}
  }
}

判分口径（对应 lecture-pipeline.md §8.8 三档）：
  ✅ 对     答案一致（简答按要点覆盖率）
  ⚠️ 半对   答案一致但要点覆盖 < 60%（记 errors，标「答题不全」）
  ❌ 错     答案不一致（记 errors）
未提交的题一律算「未作答」，不写 errors。

用法：
  python grade_submission.py 作答_第3天.json            # 判分 + 入库 + 出报告
  python grade_submission.py 作答_第3天.json --dry      # 只判分不入库
"""
import io, os, re, sys, json, sqlite3, datetime, html as H

import dsl_source as D

DB = r"<SKILL_DIR>\data\error_db.sqlite"

DDL_SUB = """
CREATE TABLE IF NOT EXISTS submissions(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  learner TEXT, day INTEGER, date TEXT, channel TEXT,
  submitted_at TEXT, payload TEXT,
  total INTEGER, correct INTEGER, half INTEGER, wrong INTEGER, blank INTEGER,
  score REAL, report TEXT
)"""
DDL_ITEM = """
CREATE TABLE IF NOT EXISTS submission_items(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  submission_id INTEGER, day INTEGER, qno INTEGER, subject TEXT, q_type TEXT,
  knowledge_point TEXT, student_answer TEXT, correct_answer TEXT,
  verdict TEXT, coverage REAL, note TEXT
)"""


def norm(s):
    """答案归一化：去标签、去标点空白、去引号与序号标记、统一符号。"""
    s = H.unescape(s or "")
    s = re.sub(r'<[^>]+>', '', s)
    for ch in "「」『』“”\"'()【】[]｛｝":
        s = s.replace(ch, "")
    for ch in "①②③④⑤⑥":
        s = s.replace(ch, "")
    s = re.sub(r'[。．.，,；;：:！!？?\s　]+', '', s)
    s = s.replace("－", "-").replace("−", "-").replace("×", "*").replace("÷", "/")
    return s.strip().lower()


def mc_letter(s):
    """从作答/答案文本里取出选择题字母。

    ⚠️ 标准答案常写成「B．2 小时或 2.8 小时」，孩子写「B」。
    直接比字符串会判错 —— 必须先抽字母再比。
    """
    t = re.sub(r'<[^>]+>', '', H.unescape(s or "")).strip()
    t = t.lstrip("（(【[").strip()
    m = re.match(r'^\s*([ABCD])[\s．.、,，:：]', t) or re.match(r'^\s*([ABCD])\s*$', t)
    return m.group(1).upper() if m else ""


def points(text):
    """把简答要点拆成集合。

    兼容三种写法：① ② ③ 序号、`结构上/内容上/效果上` 小标题、分号分条。

    ⚠️ **短要点必须保留**（阶段21 实测踩坑）：
    原阈值 `len >= 6` 会把「拟人」「对比」「托物言志」这类**核心术语**过滤掉，
    于是孩子答了「拟人」反而不计入命中，被判 0/2 要点错 —— **冤枉孩子**。
    改为 ≥2 字即保留（1 字多为标点噪声）。
    """
    t = H.unescape(re.sub(r'<[^>]+>', '', text or ""))
    t = t.replace("★", "\n")
    t = re.sub(r'(结构上|内容上|效果上|方法上|情感上|思想上|作用上)', r'\n\1', t)
    parts = re.split(r'(?:[①②③④⑤⑥]|\(\d\)|\d+[.、)]|；|;|\n)', t)
    return [norm(p) for p in parts if len(norm(p)) >= 2]


# ══ 语文答题常用同义词组（阶段21 加）══
# 为什么需要：孩子用自己的话写（「思念故乡」），标准答案是术语（「思乡怀亲」），
# 字面重合度必然低。**不能用字面重合度判语文主观题** —— 会把对的判成错的，
# 污染错题库、冤枉孩子、误导复习。
SYN_GROUPS = [
    {"思乡", "思念故乡", "怀乡", "想家", "思乡之情", "思乡怀亲", "乡愁", "怀念家乡"},
    {"托雁传书", "托大雁捎信", "借雁传书", "雁传书", "捎信", "托物寄情"},
    {"拟人", "拟人化", "人格化"},
    {"时序交替", "新旧交替", "时序更替", "新旧更替"},
    {"新事物必将取代旧事物", "新事物代替旧事物", "新必替旧", "新陈代谢"},
    {"借景抒情", "借物抒情", "情景交融"},
    {"以偏概全", "只覆盖部分", "局部"},
]


def _same_group(a, b):
    """两个短语是否属于同一语义组。"""
    for g in SYN_GROUPS:
        if any(x in a for x in g) and any(x in b for x in g):
            return True
    return False


def hit_ratio(gp, s):
    """要点命中率：整段包含 / 字面重合 ≥60% / **同义词组** 三种都算命中。"""
    hit = 0
    for p in gp:
        if not p:
            continue
        if p in s or (len(s) >= 4 and s in p):
            hit += 1
            continue
        if _same_group(p, s):
            hit += 1
            continue
        common = sum(1 for ch in set(p) if ch in s)
        need = max(2, int(len(set(p)) * 0.6)) if len(set(p)) <= 5 \
            else max(4, len(set(p)) * 0.6)
        if common >= need:
            hit += 1
    return hit


def grade_q(q, ans):
    """返回 (verdict, coverage, note)。verdict ∈ 对 / 半对 / 错 / 未作答。"""
    if ans is None or str(ans).strip() == "":
        return "未作答", 0.0, ""
    qa = q["kind"]
    sv = ans.get("value") if isinstance(ans, dict) else ans
    sv = "" if sv is None else str(sv).strip()
    gold = q["ans"]

    if qa == "MC":
        sl, gl = mc_letter(sv), mc_letter(gold)
        if not sl:
            return "未作答", 0.0, ""
        if sl == gl:
            return "对", 1.0, ""
        return "错", 0.0, "选了 %s，正确 %s" % (sl, gold[:20])

    if qa == "FILL":
        s = norm(sv)
        if not s:
            return "未作答", 0.0, ""

        # ⚠️ **分数与小数必须等价**（阶段21 实测踩坑）：
        # 标准答案 117/4（真分数标记），孩子写 29.25，
        # 原逻辑剥标签得 "1174"、数值提取得 1174≠29.25 → **判错**，
        # 但 117/4 就是 29.25，孩子是对的。冤枉一次就会污染错题库。
        def _frac_value(text):
            """从答案里取数值：支持 fr 标记（分子/分母）、a/b、纯数字。"""
            # fr 标记：<span class='fr'><span class='nu'>117</span><span ... 'de'>4</span>
            m = re.search(r"class=['\"]nu['\"]>\s*(-?\d+(?:\.\d+)?)\s*</span>"
                          r".*?class=['\"]de['\"]>\s*(-?\d+(?:\.\d+)?)\s*</span>",
                          text or "", re.S)
            if m:
                try:
                    return float(m.group(1)) / float(m.group(2))
                except ZeroDivisionError:
                    return None
            m = re.match(r"^\s*(-?\d+(?:\.\d+)?)\s*/\s*(-?\d+(?:\.\d+)?)\s*$", text or "")
            if m:
                try:
                    return float(m.group(1)) / float(m.group(2))
                except ZeroDivisionError:
                    return None
            m = re.search(r"-?\d+(?:\.\d+)?", text or "")
            return float(m.group(0)) if m else None

        gv = _frac_value(q["ans"])
        sv_val = _frac_value(sv)
        if gv is not None and sv_val is not None and abs(gv - sv_val) < 1e-6:
            return "对", 1.0, ""

        # 标准答案常写成「2 或 6」「1 或 −8 或 10」这种**多解**，
        # 必须拆开逐个比对，否则孩子写对另一个解也会被判错。
        alts = [a for a in re.split(r'或|或者|/', q["ans"]) if norm(a)]
        for a in alts:
            g = norm(a)
            if g and (g in s or s in g):
                return "对", 1.0, ""
        # 数值型容差：把各候选解里的数字和学生答案里的数字两两比
        gn = [x for a in alts for x in re.findall(r'-?\d+(?:\.\d+)?', norm(a))]
        sn = re.findall(r'-?\d+(?:\.\d+)?', s)
        if gn and sn:
            try:
                if any(abs(float(a) - float(b)) < 1e-9 for a in gn for b in sn):
                    return "对", 1.0, ""
            except ValueError:
                pass
        return "错", 0.0, "写了 %s，应为 %s" % (sv[:24], q["ans"][:24])

    # JUDGE：按要点覆盖率
    gp = points(gold) or [norm(gold)]
    sp = norm(sv)
    if not sp:
        return "未作答", 0.0, ""
    hit = hit_ratio(gp, sp)
    cov = hit / float(len(gp))
    if cov >= 0.8:
        return "对", cov, ""
    if cov >= 0.4:
        return "半对", cov, "只覆盖 %d/%d 个要点" % (hit, len(gp))

    # ⚠️ 改写型简答题（病句修改、说明改法等）的兜底判定：
    # 字面覆盖率天然偏低（孩子用自己的话写，标准答案是术语），所以要看
    # 【关键术语】和【引号内的原文操作】有没有命中，而不是逐字比对。
    # 依据：语文主观题失分诊断早已定性为「提取失败」，不能用字面重合度判。
    key_terms = [x for x in re.findall(r"[\u4e00-\u9fa5]{3,6}", sp)
                 if any(x in p for p in gp)] or []
    # 病名类：标准答案/题干里出现过的语病类型名，孩子写出来就算命中
    BJ = ["成分残缺", "句式杂糅", "重复赘余", "否定不当", "搭配不当", "两面对一面", "语序不当"]
    bj_hit = [b for b in BJ if b in sp and any(b in p for p in gp + [gold])]
    # 操作类：引号里的话，或"删/去掉/改为/改成 + ……"这种动作
    op = re.findall(r"[「\"“]([^」\"”]{1,20})[」\"”]", sp)
    op_hit = [o for o in op if any(o in p for p in gp) or o in gold]
    op_key = re.findall(r"(?:删[去掉]?|去掉|改[为成])([\u4e00-\u9fa5]{1,8})", sp)
    op_key = [k for k in op_key if any(k[:2] in p for p in gp) or k[:2] in gold]

    soft = (len(set(bj_hit)) + len(set(op_hit)) + len(set(op_key)))
    if soft >= 1 and (sp in gold or gold in sp):
        return "对", 1.0, ""
    if soft >= 1 and len(sp) >= 12:
        # 孩子给出了病因名 + 具体操作，只是没用标准答案的表述
        return "半对", max(cov, 0.5), "已写出病因/操作，但表述与标准答案不一致，请老师人工确认"
    return "错", cov, "要点几乎没覆盖（%d/%d）" % (hit, len(gp))


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    path = sys.argv[1]
    dry = "--dry" in sys.argv
    payload = json.load(io.open(path, encoding="utf-8"))

    day = int(payload.get("day") or 0)
    learner = payload.get("learner") or "学生"
    channel = payload.get("channel") or "web"
    date = payload.get("date") or datetime.date.today().isoformat()
    answers = payload.get("answers") or {}

    days = {d["n"]: d for d in D.load_days()}
    if day not in days:
        print("❌ JSON 里的 day=%s 不存在（应为 1~7）" % day)
        return 1
    qs = {q["no"]: q for q in days[day]["qs"]}

    items, cnt = [], {"对": 0, "半对": 0, "错": 0, "未作答": 0}
    for no in sorted(qs):
        q = qs[no]
        v, cov, note = grade_q(q, answers.get(str(no)))
        cnt[v] += 1
        items.append({"no": no, "q": q, "verdict": v, "coverage": cov, "note": note})
    total = len(items)
    done = total - cnt["未作答"]
    score = round((cnt["对"] + cnt["半对"] * 0.5) / total * 100, 1) if total else 0

    # ---------- 报告 ----------
    L = ["# 第 %d 天批改报告 · %s" % (day, learner), "",
         "| 项 | 值 |", "|---|---|",
         "| 日期 | %s |" % date,
         "| 提交方式 | %s |" % {"web": "网页提交", "phone": "手机上报",
                                   "paper": "拍照扫描"}.get(channel, channel),
         "| 总题数 | %d（已作答 %d）|" % (total, done),
         "| 对 / 半对 / 错 / 未答 | %d / %d / %d / %d |" % (cnt["对"], cnt["半对"], cnt["错"], cnt["未作答"]),
         "| 得分 | %.1f |" % score, "",
         "| # | 学科 | 题型 | 判定 | 你的答案 | 正确答案 |", "|---|---|---|---|---|---|"]
    for it in items:
        q = it["q"]
        sv = answers.get(str(it["no"])) or {}
        sv = sv.get("value", "") if isinstance(sv, dict) else sv
        L.append("| %d | %s | %s | %s%s | %s | %s |" % (
            it["no"], q["subj"], D.KIND_CN[q["kind"]],
            {"对": "✅", "半对": "⚠️", "错": "❌", "未作答": "—"}[it["verdict"]],
            ("（%s）" % it["note"]) if it["note"] else "",
            re.sub(r'\s+', ' ', sv)[:26] or "—",
            re.sub(r'\s+', ' ', q["ans"])[:26]))
    wrong = [it for it in items if it["verdict"] in ("错", "半对")]
    L += ["", "## 需要订正的题（%d）" % len(wrong), ""]
    if not wrong:
        L.append("全部答对，这天可以过。")
    for it in wrong:
        q = it["q"]
        L.append("**第 %d 题（%s · %s）**" % (it["no"], q["subj"], D.KIND_CN[q["kind"]]))
        L.append("- 你的答案：%s" % (it["note"] or "未作答"))
        L.append("- 正确答案：%s" % q["ans"])
        L.append("- 参考思路：%s" % H.unescape(re.sub(r'<[^>]+>', ' ', q["hint"]))[:120])
        L.append("")
    L += ["", "---", "",
          "录入说明：错题已按「天次→题号→错因→知识点」写回 errors 表；",
          "「错在第几步」需要老师/家长补一句人话，可直接发我，我补进 error_pattern。"]

    out_md = os.path.splitext(path)[0] + "_批改报告.md"
    io.open(out_md, "w", encoding="utf-8", newline="\n").write("\n".join(L))

    print("批改完成：第%d天 %s" % (day, learner))
    print("  对 %d / 半对 %d / 错 %d / 未答 %d　得分 %.1f"
          % (cnt["对"], cnt["半对"], cnt["错"], cnt["未作答"], score))
    print("  报告 → %s" % out_md)
    if dry:
        print("  --dry：未写库")
        return 0

    # ---------- 入库 ----------
    con = sqlite3.connect(DB)
    cur = con.cursor()
    cur.execute(DDL_SUB)
    cur.execute(DDL_ITEM)
    cur.execute(
        "INSERT INTO submissions(learner,day,date,channel,submitted_at,payload,total,"
        "correct,half,wrong,blank,score,report) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (learner, day, date, channel, datetime.datetime.now().isoformat(timespec="seconds"),
         json.dumps(answers, ensure_ascii=False), total, cnt["对"], cnt["半对"],
         cnt["错"], cnt["未作答"], score, out_md))
    sid = cur.lastrowid
    for it in items:
        q = it["q"]
        sv = answers.get(str(it["no"])) or {}
        sv = sv.get("value", "") if isinstance(sv, dict) else sv
        cur.execute(
            "INSERT INTO submission_items(submission_id,day,qno,subject,q_type,"
            "knowledge_point,student_answer,correct_answer,verdict,coverage,note) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (sid, day, it["no"], q["subj"], q["kind"], "", str(sv)[:500],
             q["ans"][:500], it["verdict"], it["coverage"], it["note"]))
    # 错题写 errors（门禁 6 关 + 自动解析知识点）
    #
    # ⚠️ 阶段22 修复：此前这里把 error_type 硬编码成 "other"（非法值）、
    # knowledge_point_id 根本不填 —— 每批改一次就造一批「非法错因 + 无知识点」的
    # 孤儿，mastery 永远聚合不到。现在改成：
    #   · error_type 写合法的 blank + error_subtype='待归因'（归因环节再补真错因）
    #   · knowledge_point_id 由 db_gate.resolve_kp 按科目/章节尝试落点
    #   · 写库前过 db_gate.validate，ERROR 直接跳过并计数
    try:
        from db_gate import validate as gate_validate, resolve_kp, \
            PLACEHOLDER_TYPE, PLACEHOLDER_SUBTYPE
    except Exception:                                        # noqa: BLE001
        gate_validate = None
        PLACEHOLDER_TYPE, PLACEHOLDER_SUBTYPE = 'blank', '待归因'

        def resolve_kp(cur, subject, chapter='', kp_text=''):
            return None

    n_new = 0
    n_blocked = 0
    blocked_detail = []
    for it in wrong:
        q = it["q"]
        dup = cur.execute(
            "SELECT id FROM errors WHERE date=? AND subject=? AND substr(error_desc,1,20)=?",
            (date, q["subj"], "第%d天第%d题" % (day, it["no"]))).fetchone()
        if dup:
            continue
        cur.execute("SELECT COALESCE(MAX(id),0)+1 FROM errors")
        nid = cur.fetchone()[0]
        desc = "第%d天第%d题（%s）：%s" % (day, it["no"], q["kind"],
                                         it["note"] or it["verdict"])
        chapter = q["subj"] + "·第%d天" % day
        kp_id = resolve_kp(cur, q["subj"], chapter, q.get("kp", ""))

        row = {'id': nid, 'date': date, 'subject': q["subj"], 'error_desc': desc[:200],
               'correct_answer': q["ans"][:200], 'error_type': PLACEHOLDER_TYPE,
               'knowledge_point_id': kp_id, 'source': "作答提交·%s" % channel,
               'error_subtype': PLACEHOLDER_SUBTYPE}
        if gate_validate is not None:
            errs, warns = gate_validate(cur, row)
            # 门禁4 已用上面的 dup 查过，这里不重复拦
            errs = [e for e in errs if not e.startswith('门禁4')]
            if errs:
                n_blocked += 1
                blocked_detail.append('第%d题：%s' % (it["no"], '; '.join(errs)[:80]))
                continue
        # ⚠️ errors 表有三个 NOT NULL 且无默认值的列：chapter / tags / resolved
        # （resolved 是计数列不是布尔，写 0）；study_round 是文本列，写 "1"
        cur.execute(
            "INSERT INTO errors(id,date,subject,chapter,knowledge_point,error_desc,"
            "correct_answer,error_type,source,severity,tags,study_round,status,"
            "resolved,created_at,updated_at,error_pattern,question_full,"
            "knowledge_point_id,error_subtype) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (nid, date, q["subj"], chapter, q.get("kp", ""),
             desc[:200], q["ans"][:200],
             PLACEHOLDER_TYPE, "作答提交·%s" % channel, "🟡", "第%d天" % day, "1",
             "active", 0,
             datetime.datetime.now().isoformat(timespec="seconds"),
             datetime.datetime.now().isoformat(timespec="seconds"),
             "（待补：错在第几步）", re.sub(r'<[^>]+>', ' ', q["stem"])[:400],
             kp_id, PLACEHOLDER_SUBTYPE))
        n_new += 1
    if blocked_detail:
        print('   ⚠️ 门禁拦下 %d 条（未入库）：' % n_blocked)
        for x in blocked_detail[:6]:
            print('      %s' % x)
    con.commit()
    con.close()
    print("  入库：submissions #%d、submission_items %d 条、errors 新增 %d 条"
          % (sid, len(items), n_new))
    return 0


if __name__ == "__main__":
    sys.exit(main())
