#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""过程指标 metrics.py：把「学得怎么样」变成能看的数。

原有指标全是**质量指标**（63/63 对齐、页利用率、零答案），
这里补的是**过程指标**——错题有没有在收敛、作答有没有在完成。

用法：python metrics.py [天数=30]
"""
import os, sqlite3, sys, datetime

DB = r"<SKILL_DIR>\data\error_db.sqlite"


def q(cur, sql, args=()):
    try:
        return cur.execute(sql, args).fetchone()[0]
    except Exception:
        return None


def main():
    days = int(sys.argv[1]) if len(sys.argv) > 1 else 30
    con = sqlite3.connect("file:%s?mode=ro" % DB.replace("\\", "/"), uri=True)
    c = con.cursor()
    since = (datetime.date.today() - datetime.timedelta(days=days)).isoformat()

    print("=" * 58)
    print("学生学习过程指标（近 %d 天）" % days)
    print("=" * 58)

    tot = q(c, "SELECT COUNT(*) FROM errors")
    act = q(c, "SELECT COUNT(*) FROM errors WHERE status='active'")
    # ⚠️ 口径坑：**不能**用「非 active」当已消解。
    #    resolved=真消解；cleared=代码里的真值；archived=缺题面的历史欠账（不算吃透）；
    #    duplicate-merged=重复合并（不算吃透）；reviewing=在复习中。
    #    早先一版指标把 tot-act 直接当消解率，虚高到 35%，已修正。
    res = q(c, "SELECT COUNT(*) FROM errors WHERE status IN ('resolved','cleared')")
    dup = q(c, "SELECT COUNT(*) FROM errors WHERE status='duplicate-merged'")
    arc = q(c, "SELECT COUNT(*) FROM errors WHERE status='archived'")
    rev = q(c, "SELECT COUNT(*) FROM errors WHERE status='reviewing'")
    print("\n【错题存量】")
    print("  总错题 %s　未消解(active) %s　真消解 %s　消解率 %.0f%%"
          % (tot, act, res, (res or 0) / float(tot or 1) * 100))
    print("  另：复习中 %s　重复合并 %s　历史欠账(archived) %s —— 这三类**不算吃透**"
          % (rev, dup, arc))

    new_n = q(c, "SELECT COUNT(*) FROM errors WHERE date>=?", (since,))
    print("\n【新增与收敛】")
    print("  近 %d 天新增错题 %s 条（%.1f 条/天）" % (days, new_n, (new_n or 0) / days))
    row = c.execute(
        "SELECT substr(date,1,7) m, COUNT(*) FROM errors WHERE date>=? "
        "GROUP BY m ORDER BY m", (since,)).fetchall()
    if row:
        print("  按月：" + "　".join("%s %d 条" % r for r in row))

    # 错题收敛率：真消解 / 该科总数，按学科
    print("\n【分科消解率】（低 = 该科没吃透；只算 resolved+cleared）")
    for s, n, r in c.execute(
            "SELECT subject, COUNT(*), SUM(CASE WHEN status IN ('resolved','cleared') "
            "THEN 1 ELSE 0 END) FROM errors GROUP BY subject ORDER BY 2 DESC").fetchall():
        print("  %-6s %4d 条　已消解 %3d　%.0f%%" % (s, n, r or 0, (r or 0) / float(n) * 100))

    # 高频错因 Top5（这是下一期出题的靶子）
    print("\n【高频错因 Top5】")
    for t, n in c.execute(
            "SELECT error_type, COUNT(*) FROM errors WHERE status='active' "
            "GROUP BY error_type ORDER BY 2 DESC LIMIT 5").fetchall():
        print("  %-14s %3d" % (t, n))

    # 作答完成情况（若有提交）
    has = c.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table' "
                    "AND name='submissions'").fetchone()[0]
    print("\n【作答提交】")
    if not has:
        print("  还没有提交记录（做完一天题提交后这里会亮起来）")
    else:
        n_sub = q(c, "SELECT COUNT(*) FROM submissions")
        avg = q(c, "SELECT ROUND(AVG(score),1) FROM submissions")
        blank = q(c, "SELECT SUM(blank) FROM submissions")
        total = q(c, "SELECT SUM(total) FROM submissions")
        print("  提交 %s 次　平均得分 %s　未作答 %s/%s（完成率 %.0f%%）"
              % (n_sub, avg, blank, total, (1 - (blank or 0) / float(total or 1)) * 100))
        for d, sc, ch in c.execute(
                "SELECT day, score, channel FROM submissions ORDER BY id DESC LIMIT 5").fetchall():
            print("    第%s天 %s 分（%s）" % (d, sc, ch))

    # 复习到期
    due = q(c, "SELECT COUNT(*) FROM mastery WHERE next_review_at IS NOT NULL "
               "AND next_review_at <= date('now')")
    print("\n【复习队列】")
    print("  今日到期 %s 项　总画像 %s 条" % (due, q(c, "SELECT COUNT(*) FROM mastery")))
    con.close()


if __name__ == "__main__":
    main()
