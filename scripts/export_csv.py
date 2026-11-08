#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""导出「上云包」+ CSV 单轨化（P0-2）。

背景：此前 sqlite 与 15 张 CSV 并行写入，已发生过 resolved/status 口径打架。
现在确立单轨：
  · **sqlite = 唯一数据源**（电脑端 AI 工作用）
  · **CSV = 只读导出产物**（供 Excel 看 / 上传到资料库供手机端读取），不再回写
本脚本是唯一写 CSV 的入口；改完库统一跑一次。

用法：
  python export_csv.py                # 导出到 data/ 与 上云包/
  python export_csv.py --cloud-only   # 只刷新 上云包/
"""
import os, io, csv, json, sqlite3, datetime, shutil, sys

DATA = r"<SKILL_DIR>\data"
DB = os.path.join(DATA, "error_db.sqlite")
CLOUD = os.path.join(os.path.dirname(os.path.abspath(__file__)), "上云包")

# 要导出的表：手机端/Excel 真正会用到的
EXPORT = [
    ("errors", "errors.csv"),
    ("mastery", "mastery.csv"),
    ("knowledge_base", "knowledge_base.csv"),
    ("task_cards", "task_cards.csv"),
    ("error_category_mapping", "error_category_mapping.csv"),
]

# 手机端不需要的大字段（瘦身，省云端流量、手机上也好读）
ERRORS_COLS = ["id", "date", "subject", "knowledge_point", "error_desc", "correct_answer",
               "error_type", "severity", "status", "error_pattern", "practice_count",
               "correct_streak", "knowledge_point_id", "resolved"]


def export_table(cur, table, cols=None):
    if cols:
        q = "SELECT %s FROM %s" % (",".join(cols), table)
    else:
        q = "SELECT * FROM %s" % table
    rows = cur.execute(q).fetchall()
    names = [d[0] for d in cur.description]
    return names, rows


def write_csv(path, names, rows):
    with io.open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(names)
        w.writerows(rows)
    return os.path.getsize(path)


def main():
    cloud_only = "--cloud-only" in sys.argv
    os.makedirs(CLOUD, exist_ok=True)
    con = sqlite3.connect("file:%s?mode=ro" % DB.replace("\\", "/"), uri=True)
    cur = con.cursor()

    # ---- 1. 讲义练习题（本次 63 题）单独一份，字段瘦身 ----
    rows = cur.execute(
        "SELECT id,subject,q_type,question,answer,source FROM questions "
        "WHERE source LIKE '7天攻坚讲义%' ORDER BY id").fetchall()
    names = ["id", "subject", "q_type", "question", "answer", "source"]
    p = os.path.join(CLOUD, "题库_讲义N题.csv")
    write_csv(p, names, rows)
    print("题库_讲义N题.csv        %4d 行" % len(rows))

    # ---- 2. 核心表导出 ----
    for table, fn in EXPORT:
        cols = ERRORS_COLS if table == "errors" else None
        names, rows = export_table(cur, table, cols)
        if not cloud_only:
            write_csv(os.path.join(DATA, fn), names, rows)
        write_csv(os.path.join(CLOUD, fn), names, rows)
        print("%-28s %5d 行" % (fn, len(rows)))

    # ---- 3. 一份给手机端 AI 直接读的「学习档案摘要.md」 ----
    tot = cur.execute("SELECT COUNT(*) FROM errors").fetchone()[0]
    active = cur.execute(
        "SELECT COUNT(*) FROM errors WHERE status='active'").fetchone()[0]
    by_subj = cur.execute(
        "SELECT subject, COUNT(*) FROM errors WHERE status='active' GROUP BY subject"
    ).fetchall()
    by_type = cur.execute(
        "SELECT error_type, COUNT(*) FROM errors WHERE status='active' "
        "GROUP BY error_type ORDER BY 2 DESC LIMIT 8").fetchall()
    due = cur.execute(
        "SELECT COUNT(*) FROM mastery WHERE next_review_at IS NOT NULL "
        "AND next_review_at <= date('now')").fetchone()[0]
    recent = cur.execute(
        "SELECT date,subject,knowledge_point,substr(error_desc,1,40) FROM errors "
        "ORDER BY date DESC LIMIT 15").fetchall()

    md = ["# 学生学习档案（资料库云端副本）",
          "",
          "> 本文件由 `export_csv.py` 自动生成，是**手机端 WorkBuddy 读取学生数据的入口**。",
          "> 重建时间：%s　数据源：duoduo-learning-system 错题库" % datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
          "",
          "## 总览",
          "",
          "| 项 | 数 |", "|---|---:|",
          "| 错题总数 | %d |" % tot,
          "| 未消解（active） | %d |" % active,
          "| 今日到期复习项 | %d |" % due,
          "",
          "## 未消解错题分布（按学科）",
          "",
          "| 学科 | 数量 |", "|---|---:|"]
    for s, n in by_subj:
        md.append("| %s | %d |" % (s, n))
    md += ["", "## 高频错因 Top 8", "", "| 错因 | 次数 |", "|---|---:|"]
    for t, n in by_type:
        md.append("| %s | %d |" % (t, n))
    md += ["", "## 最近 15 条错题", "", "| 日期 | 学科 | 知识点 | 错题摘要 |", "|---|---|---|---|"]
    for d, s, k, e in recent:
        md.append("| %s | %s | %s | %s |" % (d or "", s or "", k or "", (e or "").replace("|", "/")))
    md += ["", "## 手机端怎么用", "",
           "1. 直接问：「学生的错题本里现在有多少条未消解？哪三科最弱？」",
           "2. 查单条：「学生上次数学错在哪一步？」",
           "3. 录新错题：把错的题拍给我 → 我按分类规则回写",
           "4. 看讲义：`学生_三科考点7天攻坚_vN.html` 可直接在手机浏览器打开",
           "5. 作答纸：`学生_七天作答纸合集.docx` 下载后用 Word/WPS 打开打印",
           "",
           "> ⚠️ 这里只有**数据与产物**。完整技能（出题/讲义/批改流水线）在电脑上，",
           "> 手机端 WorkBuddy 用「连接电脑」即可直接调用，功能完整。"]
    p = os.path.join(CLOUD, "学生学习档案摘要.md")
    io.open(p, "w", encoding="utf-8", newline="\n").write("\n".join(md))
    print("学生学习档案摘要.md")

    # ---- 4. 复制关键产物 ----
    # ⚠️ 只复制「数据 + 产物」，**不复制 SKILL.md**：
    #    资料库技能明确禁止把自建技能拆成文件上传来冒充跨端迁移。
    #    技能的正途是手机端 WorkBuddy「连接电脑」，直接用电脑上那套。
    root = os.path.dirname(os.path.abspath(__file__))
    for src in ["学生_三科考点7天攻坚_vN.html", "学生_七天作答纸合集.docx",
                "学生_七天题目详解与答案.docx"]:
        s = os.path.join(root, src)
        if os.path.exists(s):
            shutil.copy2(s, os.path.join(CLOUD, src))

    con.close()
    n = len(os.listdir(CLOUD))
    total = sum(os.path.getsize(os.path.join(CLOUD, f)) for f in os.listdir(CLOUD))
    print("\n上云包：%s　%d 个文件　%.0f KB" % (CLOUD, n, total / 1024))


if __name__ == "__main__":
    main()
