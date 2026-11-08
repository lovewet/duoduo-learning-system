#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""fix_error_subtype.py — 治理 error_type 脏数据 + 新增 error_subtype 字段。

背景（阶段22 审计）：
  `errors` 里混进 4 条非法 error_type（要点残缺 / 概念不清（提示后改对）/
  以偏概全 / other），另有 22 条 error_desc 根本是「智学网报告：本题得 9.0/12.0」
  这种分数记录，不是错因。语文错题还缺 A–G 七类明细。

做法：
  1. `ALTER TABLE errors ADD COLUMN error_subtype TEXT`（幂等，已有就跳过）
  2. 4 条非法值 → 按 §4.4 映射到合法 13 值，原值存进 error_subtype 留痕（`原值:xxx`）
  3. 22 条伪错因 → error_subtype='待归因'（desc 原文不动，只加标记，不臆造错因）
  4. 语文其余 → 按 error_type 粗推 A–G，存成 `A(inferred)`，标明是推断非人工确认

⚠️ 原则：**不臆造。** 推不出来的就标「待归因」，不硬填一个看起来像的答案。

用法：
    python scripts/fix_error_subtype.py            # 预览
    python scripts/fix_error_subtype.py --apply    # 落库（自动备份）
"""

from __future__ import annotations

import argparse
import datetime
import shutil
import sqlite3
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
DB = HERE.parent / 'data' / 'error_db.sqlite'

LEGAL = {'concept-confusion', 'calculation', 'sign-error', 'formula-misuse',
         'missing-zero', 'classification', 'blank', 'incomplete-answer',
         'careless', 'grammar', 'spelling', 'collocation', 'semantic'}

# 4 条非法值的人工判定（逐条看过 error_desc 才定的，不是通用规则硬套）
ILLEGAL_MAP = {
    '要点残缺': ('incomplete-answer', '答题要点不全，缺采分点'),
    '概念不清（提示后改对）': ('concept-confusion', '概念本身没建立，提示后才对'),
    '以偏概全': ('incomplete-answer', '概括只覆盖部分，漏其余要点'),
    'other': ('blank', '错因无法判定，按未作答处理'),
}

# 伪错因特征：desc 写的是分数/得分率，不是错因
FAKE_PAT = ('学情报告', '得分率', '本题得', '智学网', '班级平均')

# 语文：error_type → A–G 的粗推（标 inferred，等人工确认）
ZH_INFER = {
    'spelling': 'A', 'grammar': 'A', 'concept-confusion': 'A',
    'semantic': 'E', 'incomplete-answer': 'D', 'careless': 'C',
}

SUB_NAMES = {
    'A': '知识漏洞', 'B': '方法缺失', 'C': '审题偏差', 'D': '表达不规范',
    'E': '思维不足', 'F': '习惯问题', 'G': '心理策略',
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--apply', action='store_true')
    ap.add_argument('--db', default=str(DB))
    args = ap.parse_args()

    db = Path(args.db)
    con = sqlite3.connect(str(db))
    con.row_factory = sqlite3.Row
    cur = con.cursor()

    cols = [r[1] for r in cur.execute("PRAGMA table_info(errors)")]
    has_col = 'error_subtype' in cols

    print('=' * 66)
    print('fix_error_subtype — 错因脏数据治理%s' % ('' if args.apply else '（预览）'))
    print('=' * 66)
    print('  error_subtype 字段 : %s' % ('已存在' if has_col else '待新增'))

    if not has_col:
        if args.apply:
            cur.execute("ALTER TABLE errors ADD COLUMN error_subtype TEXT")
            con.commit()
            print('  已新增字段 error_subtype TEXT')
        else:
            print('  （预览不动表结构，--apply 时新增）')

    ph = ','.join('?' * len(LEGAL))
    plan = []

    # ---------- 1. 非法 error_type ----------
    for r in cur.execute(
            "select id, subject, error_type, substr(coalesce(error_desc,''),1,40) d"
            " from errors where trim(coalesce(error_type,'')) not in (%s)" % ph,
            tuple(LEGAL)):
        raw = (r['error_type'] or '').strip()
        if raw not in ILLEGAL_MAP:
            plan.append((r['id'], 'MANUAL', raw, '未收录的非法值，保留待人工'))
            continue
        new, why = ILLEGAL_MAP[raw]
        plan.append((r['id'], new, '原值:%s' % raw, '%s → %s（%s）' % (raw, new, why)))

    # ---------- 2. 伪错因 ----------
    where = ' or '.join("error_desc like ?" for _ in FAKE_PAT)
    fargs = tuple('%%%s%%' % p for p in FAKE_PAT)
    fake_ids = [r[0] for r in cur.execute(
        "select id from errors where " + where, fargs)]
    for i in fake_ids:
        plan.append((i, None, '待归因', 'desc 是分数记录，不是错因'))

    # ---------- 3. 语文粗推 A–G（跳过已在上面处理过的） ----------
    done = {p[0] for p in plan}
    inferred = 0
    for r in cur.execute(
            "select id, error_type from errors where subject='语文'"
            " and trim(coalesce(error_type,'')) in (%s)" % ph, tuple(LEGAL)):
        if r['id'] in done:
            continue
        letter = ZH_INFER.get(r['error_type'])
        if not letter:
            continue
        plan.append((r['id'], None, '%s(inferred)' % letter,
                     '%s 推断为 %s %s' % (r['error_type'], letter, SUB_NAMES[letter])))
        inferred += 1

    # ---------- 摘要 ----------
    n_illegal = sum(1 for p in plan if str(p[2] or '').startswith('原值:'))
    print('  非法值改写    : %d 条' % n_illegal)
    print('  伪错因标记    : %d 条（→ 待归因）' % len(fake_ids))
    print('  语文 A–G 推断 : %d 条（标 inferred）' % inferred)
    print('  无法判定      : %d 条（保留待人工）' % sum(1 for p in plan if p[1] == 'MANUAL'))

    print('\n  ── 明细（前 20）──')
    for i, new, sub, why in plan[:20]:
        print('    #%-6s %-22s %s' % (i, (new or '（不改 type）'),
                                      '%s ← %s' % (sub, why[:44])))

    if not args.apply:
        print('\n  预览完毕。加 --apply 落库（会先自动备份）。')
        con.close()
        return 0

    bak = db.with_suffix('.sqlite.bak-before-subtype-%s'
                         % datetime.datetime.now().strftime('%Y%m%d_%H%M%S'))
    shutil.copy2(db, bak)
    print('\n  已备份 → %s' % bak.name)

    now = datetime.date.today().isoformat()
    n = 0
    for i, new, sub, _why in plan:
        if new == 'MANUAL':
            cur.execute("update errors set error_subtype=? where id=?", (sub, i))
        elif new:
            cur.execute("update errors set error_type=?, error_subtype=?, updated_at=? where id=?",
                        (new, sub, now, i))
        else:
            cur.execute("update errors set error_subtype=? where id=?", (sub, i))
        n += 1
    con.commit()

    left = cur.execute("select count(*) from errors where trim(coalesce(error_type,''))"
                       " not in (%s)" % ph, tuple(LEGAL)).fetchone()[0]
    print('  ✅ 已处理 %d 条；剩余非法 error_type %d 条' % (n, left))
    con.close()
    return 0


if __name__ == '__main__':
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    sys.exit(main())
