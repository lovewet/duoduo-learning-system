#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""prefer_answer.py — 讲义答案优选：优先用技能/题库里的答案，别自己现算。

为什么需要它（阶段22 用户：「讲义要优选技能中的答案」）：
  讲义题目的答案一直来自 DSL 里手写的 `ans` 字段，**从来没跟题库对过**。
  而 SKILL.md 规则 5 明确写着「自出的题必须先算 —— 答案与解析不一致是本项目最高频事故」。
  自己算一遍，错了也不知道；题库里现成的答案（`errors.question_full` N条、
  `questions` N条有答案）反而没用上。

答案来源优先级（与题源优先级配套）：
  ① `errors.correct_answer`（原卷真题的官方答案，最可信）
  ② `questions.answer`（教辅库带答案的题）
  ③ 技能产出（明辨/english-exam-authoring 等算出来的）
  ④ 自己算 —— **最后手段，必须标注**

用法：
    python scripts/prefer_answer.py --audit                 # 全量审计：讲义答案 vs 原卷答案
    python scripts/prefer_answer.py --stem "题干文字" --subject 数学   # 单题查库答案
"""

from __future__ import annotations

import argparse
import difflib
import re
import sqlite3
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
DB = HERE.parent / 'data' / 'error_db.sqlite'

MATCH_THRESHOLD = 0.90      # 题干相似度到这算「同一道题」
PREFIX = ('（原卷变式）', '（变式）', '（原卷原题）', '（原卷改编）', '（新编·同型）',
          '（新编）', '（学情分析·变式1.1改编）')


def norm(s):
    """归一化题干：去来源前缀、去空白与标点、全角转半角括号不重要。"""
    s = s or ''
    for p in PREFIX:
        s = s.replace(p, '')
    s = re.sub(r'\s+', '', s)
    s = re.sub(r'[（(]\s*[）)]', '', s)          # 空括号
    s = re.sub(r'[，。；：、,.;:!?！？]', '', s)
    return s.strip()


def answer_by_source_id(cur, qid):
    """题目记录了 source_error_id → 直接拿原错题的官方答案，不用猜。

    这是**唯一可靠**的答案优选路径。实测（阶段22）：题库里 110 道讲义题
    `source_error_id` **全空**，所以只能退化到题干相似度匹配，而变式题改过题干，
    106/110 匹配不上 —— 「讲义优选技能答案」一直落不了地就是因为这个字段没人填。
    """
    r = cur.execute(
        "select e.correct_answer, e.id from questions q"
        " join errors e on e.id = q.source_error_id"
        " where q.id=? and trim(coalesce(e.correct_answer,''))!=''", (qid,)).fetchone()
    return (r[0], 'errors#%s(精确关联)' % r[1]) if r else (None, None)


def build_stem_index(cur):
    """建「归一化题干 → 答案集合」索引，用于识别模板化题干。

    阶段22 实测教训：题库的选择题**只存了题干、没存选项**（`question_items` 多为 0 条），
    于是「选出划线部分读音与其他三个不同的一项」这种模板题干会同时对应
    `look`（考 oo 长短音）和 `think`（考 th 清浊）两个**都正确**的答案。
    只看题干判定同题必然误判 —— 答案集合 >1 的一律标歧义，交人工。
    """
    idx = {}
    for qs, a in cur.execute(
            "select question, answer from questions where trim(coalesce(answer,''))!=''"):
        k = norm(qs)
        if len(k) >= 12 and a:
            idx.setdefault(k, set()).add(str(a).strip())
    return idx


def best_match(cur, stem, subject, exclude_source_like=None):
    """在 errors.question_full 和 questions.question 里找最像的题，返回
    (answer, source_desc, score) 或 (None, None, 0)。

    ① 先查原卷真题（errors.question_full），它的答案最可信。
    ② 再查教辅库（questions）。
    """
    n = norm(stem)
    if len(n) < 12:
        return None, None, 0.0

    cands = []
    for qf, ans, eid in cur.execute(
            "select question_full, correct_answer, id from errors"
            " where trim(coalesce(question_full,''))!=''"
            " and trim(coalesce(correct_answer,''))!=''"
            " and (? is null or subject=?)", (subject, subject)):
        cands.append((qf, ans, 'errors#%s' % eid))
    for qq, ans, qid in cur.execute(
            "select question, answer, id from questions"
            " where trim(coalesce(question,''))!='' and trim(coalesce(answer,''))!=''"
            " and (? is null or subject=?)", (subject, subject)):
        if exclude_source_like and exclude_source_like.lower() in (qq or '').lower():
            pass
        cands.append((qq, ans, 'questions#%s' % qid))

    best = (None, None, 0.0)
    for text, ans, tag in cands:
        m = norm(text)
        if not m:
            continue
        # 长度差太大直接跳过（省时间）
        if abs(len(m) - len(n)) > max(20, len(n) * 0.5):
            continue
        r = difflib.SequenceMatcher(None, n, m).ratio()
        if r > best[2]:
            best = (ans, tag, r)
            if r >= 0.99:
                break
    return best


def audit(cur):
    """审计：题库里「讲义」来源的题，其答案能不能被原卷答案印证/纠正。"""
    rows = cur.execute(
        "select id, subject, question, answer, source from questions"
        " where source like '%讲义%' and trim(coalesce(answer,''))!=''").fetchall()
    idx = build_stem_index(cur)
    print('=' * 68)
    print('讲义答案审计：共 %d 道有答案的讲义题' % len(rows))
    print('=' * 68)

    same = diff = none = amb = exact = 0
    diff_list = []
    amb_list = []
    for qid, subj, stem, ans, src in rows:
        # ① 有 source_error_id → 精确关联，最可信
        ea, etag = answer_by_source_id(cur, qid)
        if ea:
            exact += 1
            if norm(str(ans)) != norm(str(ea)):
                diff += 1
                diff_list.append((qid, subj, ans, ea, etag, 1.0, (stem or '')[:44]))
            else:
                same += 1
            continue
        # ② 模板化题干（同一题干多个答案）→ 无法判定是否同题，不硬比
        if len(idx.get(norm(stem), ())) > 1:
            amb += 1
            amb_list.append((qid, subj, ans, (stem or '')[:44]))
            continue
        # ③ 退化为题干相似度
        cand_ans, tag, score = best_match(cur, stem, subj)
        if not cand_ans or score < MATCH_THRESHOLD or tag == 'questions#%s' % qid:
            none += 1
            continue
        if norm(str(ans)) == norm(str(cand_ans)):
            same += 1
        else:
            diff += 1
            diff_list.append((qid, subj, ans, cand_ans, tag, score, (stem or '')[:44]))

    print('  ✅ 与原卷答案一致 : %d' % same)
    print('    其中精确关联   : %d（有 source_error_id，最可信）' % exact)
    print('  ⚠️  不一致         : %d' % diff)
    print('  ❓ 题干模板化看不清 : %d（选项没入库，无法确认是不是同一题）' % amb)
    print('  ℹ️  找不到对应原题 : %d（变式题改过题干，需自算并标注）' % none)

    if diff_list:
        print('\n  ── 不一致明细（前 20，按相似度降序）──')
        for qid, subj, a_old, a_new, tag, score, stem in sorted(
                diff_list, key=lambda x: -x[5])[:20]:
            print('  questions#%-5s [%s] 相似度 %.2f  对照 %s' % (qid, subj, score, tag))
            print('      题干: %s' % stem)
            print('      讲义答案: %r  ←→  原卷答案: %r' % (str(a_old)[:40], str(a_new)[:40]))

    if amb_list:
        print('\n  ── 题干模板化（前 8，需人工看选项）──')
        for qid, subj, ans, stem in amb_list[:8]:
            print('  questions#%-5s [%s] %s' % (qid, subj, stem))
            print('      该题答案: %r' % str(ans)[:40])
    return diff_list


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--audit', action='store_true', help='全量审计讲义答案')
    ap.add_argument('--stem', help='单题题干，查库里答案')
    ap.add_argument('--subject', help='科目（数学/语文/英语），不填则全科')
    ap.add_argument('--db', default=str(DB))
    a = ap.parse_args()

    con = sqlite3.connect(a.db)
    cur = con.cursor()

    if a.stem:
        ans, tag, score = best_match(cur, a.stem, a.subject)
        if ans and score >= MATCH_THRESHOLD:
            print('命中 %s（相似度 %.2f）\n答案：%s' % (tag, score, ans))
            print('\n→ 建议采用，并标注「答案来源：%s」' % tag)
        elif ans:
            print('最相近 %s（相似度 %.2f，低于 %.2f 阈值，不视为同题）\n答案：%s'
                  % (tag, score, MATCH_THRESHOLD, ans))
            print('\n→ 需自己算，并标注「答案来源：自算」')
        else:
            print('库里没有可对应的题 → 需自己算，并标注「答案来源：自算」')
        con.close()
        return 0

    if a.audit:
        audit(cur)
        con.close()
        return 0

    print(__doc__)
    con.close()
    return 0


if __name__ == '__main__':
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    sys.exit(main())
