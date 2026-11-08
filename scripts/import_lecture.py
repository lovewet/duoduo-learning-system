#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""把这一期讲义的数据写进学生的错题数据库（四库联动）。

分工（与 lecture-pipeline.md §8.8 一致）：
  · 讲义练习题（含答案与解析）→ `questions` 题库
  · 讲义涉及的知识点        → `knowledge_base` 知识点库
  · 7 天 × 3 科的任务       → `task_cards` 任务卡
  · 涉及知识点的掌握度画像   → `mastery`（新建的从 0 起步，已有的不动）
  · **错题 `errors` 不在这里写** —— 错题来自批改后的拍照/扫描件（§8.8 第④步）

产出：
  1. 直接写本地镜像库（skills/.../data/error_db.sqlite，duoduo_query.py 读的就是它）
  2. 同时导出增量 SQL 到 `增量入库_讲义_<日期>.sql`，供 NAS 主实例执行
     （NAS 主库对 SMB 只读，只能把 SQL 放过去等容器内执行）

用法：python import_lecture.py [--dry]
"""
import io, os, re, sys, sqlite3, datetime, html as H

import dsl_source as D

DB = r"<SKILL_DIR>\data\error_db.sqlite"
TODAY = datetime.date.today().isoformat()
WEEK_START = (datetime.date.today() -
              datetime.timedelta(days=datetime.date.today().weekday())).isoformat()

SRC_TAG = "7天攻坚讲义"


def q1(s):
    """SQL 字符串转义（单引号加倍）。"""
    return (s or "").replace("'", "''")


def plain(s):
    """HTML 片段 → 纯文本（去标签 + 反转义 + 压空白）。"""
    s = re.sub(r'<br\s*/?>', '\n', s)
    s = re.sub(r'<[^>]+>', '', s)
    s = H.unescape(s)
    return re.sub(r'[ \t]+', ' ', s).strip()


def parse_points():
    """从 DSL 的 SUB 行抽出知识点：[(科目, 知识点名, 说明)]。

    跳过「📋 测评说明」「📇 学习卡」这类非考点小节，以及带 emoji 前缀的。
    """
    out, seen = [], set()
    for d in range(1, 9):
        p = os.path.join(D.SRC_DIR, "day%d.txt" % d)
        if not os.path.exists(p):
            continue
        for ln in io.open(p, encoding="utf-8"):
            ln = ln.strip()
            if not ln.startswith("SUB|"):
                continue
            f = ln.split("|")
            name = f[1]
            note = f[3] if len(f) > 3 else ""
            if name.startswith(("📋", "📇")) or "·" not in name:
                continue
            subj, _, pname = name.partition("·")
            subj = {"数学": "数学", "语文": "语文", "英语": "英语"}.get(subj.strip(), subj.strip())
            pname = pname.strip()
            key = (subj, pname)
            if key in seen:
                continue
            seen.add(key)
            out.append((subj, pname, note))
    return out


def parse_questions():
    """逐日解析，题目带上它所属的知识点名（比 dsl_source 多记一个 point）。"""
    rows = []
    for d in range(1, 9):
        p = os.path.join(D.SRC_DIR, "day%d.txt" % d)
        if not os.path.exists(p):
            continue
        cur_pt, cur_sub = "", "数学"
        qno = 0
        for kind, pay in D.parse(io.open(p, encoding="utf-8").read()):
            if kind == "SUB":
                name = pay[0]
                if not name.startswith(("📋", "📇")) and "·" in name:
                    s, _, pn = name.partition("·")
                    cur_pt = pn.strip()
                    cur_sub = {"数学": "数学", "语文": "语文", "英语": "英语"}.get(s.strip(), s.strip())
            elif kind in D.KINDS:
                qno += 1
                if kind in ("MC", "FILL"):
                    sol, hint, a3, a4 = pay[-1], pay[-2], pay[-3], pay[-4]
                    stem = "|".join(pay[:-4])
                else:
                    sol, hint, a3 = pay[-1], pay[-2], pay[-3]
                    a4 = ""
                    stem = "|".join(pay[:-3])
                if kind == "MC":
                    try:
                        idx = int(a3)
                    except ValueError:
                        idx = 0
                    opts = a4.split("@")
                    ans = "%s．%s" % ("ABCD"[idx], plain(opts[idx] if idx < len(opts) else ""))
                    stem_full = plain(stem) + "\n" + "\n".join(
                        "%s．%s" % ("ABCD"[i], plain(o)) for i, o in enumerate(opts))
                else:
                    ans = a3
                    stem_full = plain(stem)
                rows.append({
                    "day": d, "no": qno, "kind": kind, "subj": cur_sub,
                    "point": cur_pt, "stem": stem_full, "ans": plain(ans),
                    "sol": H.unescape(sol), "hint": H.unescape(hint),
                })
    return rows


def main():
    dry = "--dry" in sys.argv
    pts = parse_points()
    qs = parse_questions()
    days = D.load_days()
    print("知识点 %d　练习题 %d　天 %d" % (len(pts), len(qs), len(days)))

    con = sqlite3.connect(DB)
    cur = con.cursor()
    sql = ["-- 增量入库：7 天攻坚讲义（%s）" % TODAY,
           "-- 生成：import_lecture.py　来源：%s" % SRC_TAG,
           "BEGIN;", ""]

    # ---------- 1. knowledge_base ----------
    pt_id = {}
    for subj, pname, note in pts:
        r = cur.execute("SELECT id FROM knowledge_base WHERE subject=? AND point_name=?",
                        (subj, pname)).fetchone()
        if r:
            pt_id[(subj, pname)] = r[0]
            continue
        cur.execute("SELECT COALESCE(MAX(id),0)+1 FROM knowledge_base")
        nid = cur.fetchone()[0]
        cur.execute(
            "INSERT INTO knowledge_base(id,subject,edition,grade,unit,unit_num,"
            "point_name,point_type,detail,parent_id,source,created_at) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            (nid, subj, "人教版", "七年级", "", 0, pname, "考点", note, None,
             SRC_TAG, TODAY))
        sql.append("INSERT INTO knowledge_base(id,subject,edition,grade,point_name,"
                   "point_type,detail,source,created_at) VALUES(%d,'%s','人教版','七年级',"
                   "'%s','考点','%s','%s','%s');"
                   % (nid, q1(subj), q1(pname), q1(note), q1(SRC_TAG), TODAY))
        pt_id[(subj, pname)] = nid

    # ---------- 2. questions ----------
    cur.execute("SELECT COALESCE(MAX(id),0) FROM questions")
    qid = cur.fetchone()[0]
    n_new = 0
    for r in qs:
        # 查重：同科目 + 同题干前 40 字
        head = r["stem"][:40]
        dup = cur.execute(
            "SELECT id FROM questions WHERE subject=? AND substr(question,1,40)=?",
            (r["subj"], head)).fetchone()
        if dup:
            continue
        qid += 1
        n_new += 1
        kp = pt_id.get((r["subj"], r["point"]))
        qt = {"MC": "选择题", "FILL": "填空题", "JUDGE": "简答题"}[r["kind"]]
        cur.execute(
            "INSERT INTO questions(id,knowledge_point_id,subject,grade,q_type,difficulty,"
            "question,answer,solution,source,source_file,source_error_id,usage_count,"
            "correct_rate,created_at,answer_status) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (qid, kp, r["subj"], "七年级", r["kind"], 3, r["stem"], r["ans"],
             r["sol"], "%s · 第%d天第%d题" % (SRC_TAG, r["day"], r["no"]),
             "_p5/day%d.txt" % r["day"], None, 0, 0.0, TODAY, "confirmed"))
        sql.append("INSERT INTO questions(id,knowledge_point_id,subject,grade,q_type,"
                   "difficulty,question,answer,solution,source,source_file,usage_count,"
                   "correct_rate,created_at,answer_status) VALUES(%d,%s,'%s','七年级','%s',3,"
                   "'%s','%s','%s','%s','%s',0,0.0,'%s','confirmed');"
                   % (qid, kp if kp else "NULL", q1(r["subj"]), r["kind"],
                      q1(r["stem"]), q1(r["ans"]), q1(r["sol"]),
                      q1("%s · 第%d天第%d题" % (SRC_TAG, r["day"], r["no"])),
                      q1("_p5/day%d.txt" % r["day"]), TODAY))

    # ---------- 3. task_cards ----------
    cur.execute("SELECT COALESCE(MAX(id),0) FROM task_cards")
    tid = cur.fetchone()[0]
    n_card = 0
    for d in days:
        titles = {}
        for r in qs:
            if r["day"] == d["n"]:
                titles.setdefault(r["subj"], []).append(r["no"])
        for subj in ("数学", "语文", "英语"):
            if subj not in titles:
                continue
            tid += 1
            n_card += 1
            content = "第%d天 %s｜%s　共 %d 题（%s）　目标：%s" % (
                d["n"], subj, d["title"], len(titles[subj]),
                "、".join("第%d题" % n for n in titles[subj]), d["goal"][:40])
            cur.execute(
                "INSERT INTO task_cards(id,week_no,week_start,day_of_week,block,content,"
                "block_type,subject,source,execution_rate,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (tid, 1, WEEK_START, d["n"], "D", content, "练习", subj,
                 SRC_TAG, 0.0, TODAY))
            sql.append("INSERT INTO task_cards(id,week_no,week_start,day_of_week,block,"
                       "content,block_type,subject,source,execution_rate,created_at) "
                       "VALUES(%d,1,'%s',%d,'D','%s','练习','%s','%s',0.0,'%s');"
                       % (tid, WEEK_START, d["n"], q1(content), subj, q1(SRC_TAG), TODAY))

    # ---------- 4. mastery（新建的从 0 起步，已存在的不动） ----------
    n_mas = 0
    for (subj, pname), kp in pt_id.items():
        r = cur.execute("SELECT knowledge_point_id FROM mastery WHERE knowledge_point_id=?",
                        (kp,)).fetchone()
        if r:
            continue
        cur.execute(
            "INSERT INTO mastery(knowledge_point_id,error_count,error_types,severity_avg,"
            "last_error_at,practice_count,correct_streak,mastery_level,next_review_at,"
            "updated_at,interval_days,difficulty) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            (kp, 0, "", 0.0, None, 0, 0, 0, TODAY, TODAY, 1, 3))
        sql.append("INSERT INTO mastery(knowledge_point_id,error_count,error_types,"
                   "severity_avg,practice_count,correct_streak,mastery_level,next_review_at,"
                   "updated_at,interval_days,difficulty) VALUES(%d,0,'',0.0,0,0,0,'%s','%s',1,3);"
                   % (kp, TODAY, TODAY))
        n_mas += 1

    sql.append("")
    sql.append("COMMIT;")

    out_sql = "增量入库_讲义_%s.sql" % TODAY.replace("-", "")
    if dry:
        con.rollback()
        print("--dry：未写入数据库")
    else:
        con.commit()
    con.close()
    io.open(out_sql, "w", encoding="utf-8", newline="\n").write("\n".join(sql))

    print("知识点 %d（新建 %d）　练习题新增 %d　任务卡 %d　掌握度新建 %d"
          % (len(pts), len(pt_id), n_new, n_card, n_mas))
    print("增量 SQL → %s（%.1f KB），供 NAS 主实例执行" % (out_sql, len("\n".join(sql)) / 1024))
    print("⚠️ 错题 errors 不在此写入 —— 等拍照/扫描批改后按 §8.8 录入")


if __name__ == "__main__":
    main()
