# -*- coding: utf-8 -*-
"""盘点「学情分析原卷题」的可用量，为替换「新编」题做准备。

阶段21 用户：「语文数学英语都要尽量使用学情分析中的题目」

## 现状问题
讲义 78 题里 **「新编」占 42 道（54%）**，真正来自原卷/学情分析只有 16 道。
自己编的题，真实性、难度梯度、命题角度都不如原卷题。

## 可用题源（本次盘点）
| 来源 | 量 | 说明 |
|:--|--:|:--|
| errors 表原卷错题 | 437 | **最正宗的「学情分析」**：学校卷子上的真题 |
| 启东作业本七上数学北师 | 433 | 教材同步，数轴/有理数题密集 |
| 教辅练习册 | 627 | 计算类 |
| 星火英语语法全练 | 2275 | 语法类 |
| 7年级阅读理解（上/下） | 118 | 英语阅读全文+题 |
| questions 语文 | ? | 古诗/病句等 |
"""
import sqlite3
from collections import Counter

DB = r"<SKILL_DIR>\data\error_db.sqlite"
c = sqlite3.connect(DB)


def q(sql, args=()):
    return list(c.execute(sql, args))


print("=" * 68)
print("可用题源盘点")
print("=" * 68)

# ── errors 原卷错题 ──
n_err = q("SELECT COUNT(*) FROM errors WHERE length(question_full)>20")[0][0]
print("\n【errors 原卷错题】%d 条（学情分析的正宗来源）" % n_err)
for sub, n in q("""SELECT subject, COUNT(*) FROM errors
                   WHERE length(question_full)>20 GROUP BY subject
                   ORDER BY 2 DESC"""):
    print("   %-6s %d" % (sub, n))

print("\n   数轴/相反数/绝对值/分类 相关：")
KP = ("数轴", "相反数", "绝对值", "分类", "比较大小")
rows = q("""SELECT id, knowledge_point, question_full FROM errors
            WHERE length(question_full)>20 ORDER BY id DESC""")
hit = []
for rid, kp, qf in rows:
    blob = (kp or "") + " " + (qf or "")
    if any(k in blob for k in KP):
        hit.append((rid, kp, qf))
print("   共 %d 条" % len(hit))
for rid, kp, qf in hit[:8]:
    txt = " ".join(str(qf).split())[:70]
    print("     #%-5s [%-10s] %s" % (rid, str(kp)[:10], txt))

# ── questions 教辅题库 ──
print("\n【教辅题库】按来源：")
for src, n in q("""SELECT source, COUNT(*) FROM questions
                   GROUP BY source ORDER BY 2 DESC LIMIT 8"""):
    print("   %-28s %d" % (str(src)[:26], n))

print("\n【按学科】questions 表：")
for sub, n in q("SELECT subject, COUNT(*) FROM questions GROUP BY subject ORDER BY 2 DESC"):
    print("   %-6s %d" % (sub, n))

# ── 英语阅读（真实短文）──
print("\n【英语阅读理解】按文件：")
for f, n in q("""SELECT source_file, COUNT(*) FROM questions
                 WHERE source_file LIKE '%阅读%' GROUP BY source_file"""):
    print("   %-34s %d" % (str(f)[:32], n))

# ── 语文可用题 ──
print("\n【语文】questions 表按来源：")
for src, n in q("""SELECT COALESCE(source,'(无)'), COUNT(*) FROM questions
                   WHERE subject='语文' GROUP BY source ORDER BY 2 DESC LIMIT 6"""):
    print("   %-28s %d" % (str(src)[:26], n))

print("\n【语文】errors 原卷错题按知识点：")
for kp, n in q("""SELECT COALESCE(knowledge_point,'(空)'), COUNT(*) FROM errors
                  WHERE subject='语文' AND length(question_full)>20
                  GROUP BY knowledge_point ORDER BY 2 DESC LIMIT 8"""):
    print("   %-24s %d" % (str(kp)[:22], n))

c.close()
