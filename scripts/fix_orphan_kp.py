#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""fix_orphan_kp.py — 给无 knowledge_point_id 的错题补映射。

背景（阶段22 审计）：
  5 条错题没有 knowledge_point_id，进不了 mastery 画像、排不进复习、
  出题时也检索不到。逐条看过 desc 之后，只有 2 条能在现有知识库里精确命中；
  另 2 条是因为**语文知识库按「教材单元」组织，缺「病句辨析」「古诗炼字」这类
  能力型知识点**（数学按知识点组织，语文按单元组织，两套混在一张表里）；
  最后 1 条是「做题习惯」，不属于学科知识点，不该硬塞。

做法：
  1. 幂等补建 2 个语文能力型知识点（已存在则复用）
  2. 映射 4 条（2 条命中现有、2 条命中新建）
  3. 「做题习惯」标 error_subtype='非学科项'，不映射

⚠️ 不臆造：拿不准的宁可留空标待人工，不硬填一个看起来像的。

用法：
    python scripts/fix_orphan_kp.py            # 预览
    python scripts/fix_orphan_kp.py --apply    # 落库（自动备份）
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

# 要补建的能力型知识点：语文按单元组织，缺这些「能力项」
NEW_KP = [
    {'subject': '语文', 'unit': '语文基础', 'unit_num': '通用', 'point_name': '病句辨析与修改',
     'point_type': 'sentence',
     'detail': '成分残缺/句式杂糅/两面对一面/重复赘余/搭配不当/否定不当/语序不当七型；'
               '判病名 + 改法 + 写出改好的完整句三步都要有'},
    {'subject': '语文', 'unit': '语文通用全册', 'unit_num': '通用', 'point_name': '古诗炼字赏析',
     'point_type': 'reading',
     'detail': '炼字题三问：手法（拟人/双关/化静为动等）→ 内容（写出什么景）→ '
               '哲理或情感（蕴含什么）。三问答全才拿满分'},
]

# 逐条人工判定（看过 desc 才定，不是算法硬配）
MAPS = [
    # (error_id, 现有 kp_id 或 None, 新建 kp 的 point_name 或 None, 依据)
    (1364, None, '病句辨析与修改', '写出病因/操作但表述不符 → 病句表述类'),
    (1365, None, '古诗炼字赏析', '炼字三问漏第③问「蕴含什么哲理」'),
    (1366, 202, None, '英语阅读主旨大意题 → 现有「主旨大意与最佳标题」'),
    (1367, 5, None, '数轴比较大小 → 现有「有理数比较大小」'),
]

NON_SUBJECT = [(531, '非学科项', '做题习惯类，不属于学科知识点，不塞进 knowledge_base')]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--apply', action='store_true')
    ap.add_argument('--db', default=str(DB))
    args = ap.parse_args()

    db = Path(args.db)
    con = sqlite3.connect(str(db))
    con.row_factory = sqlite3.Row
    cur = con.cursor()
    now = datetime.date.today().isoformat()

    print('=' * 66)
    print('fix_orphan_kp — 孤儿错题补映射%s' % ('' if args.apply else '（预览）'))
    print('=' * 66)

    before = cur.execute("select count(*) from errors where knowledge_point_id is null").fetchone()[0]
    print('  当前无 kp_id 的错题：%d 条' % before)

    # ---------- 1. 识别要新建的知识点 ----------
    todo_new, need_ids = [], {}
    for k in NEW_KP:
        row = cur.execute(
            "select id from knowledge_base where subject=? and point_name=?",
            (k['subject'], k['point_name'])).fetchone()
        if row:
            need_ids[k['point_name']] = row['id']
            print('  复用已有知识点：%s (id=%s)' % (k['point_name'], row['id']))
        else:
            todo_new.append(k)
            print('  待新建：%s（%s / %s）' % (k['point_name'], k['subject'], k['unit']))

    if args.apply:
        if todo_new:
            bak = db.with_suffix('.sqlite.bak-before-orphankp-%s'
                                 % datetime.datetime.now().strftime('%Y%m%d_%H%M%S'))
            shutil.copy2(db, bak)
            print('  已备份 → %s' % bak.name)
        for k in todo_new:
            cur.execute(
                "insert into knowledge_base(subject,edition,grade,unit,unit_num,point_name,"
                "point_type,detail,parent_id,source,created_at)"
                " values(?,?,?,?,?,?,?,?,NULL,?,?)",
                (k['subject'], '部编版', '七上', k['unit'], k['unit_num'], k['point_name'],
                 k['point_type'], k['detail'], 'audit-YYYYMMDD', now))
            need_ids[k['point_name']] = cur.lastrowid
            print('  ✅ 新建 id=%s %s' % (cur.lastrowid, k['point_name']))

    # ---------- 2. 映射 ----------
    print('\n  ── 映射计划 ──')
    n_map = 0
    for eid, kid, newname, why in MAPS:
        target = kid or need_ids.get(newname)
        cur_kp = cur.execute("select knowledge_point_id from errors where id=?", (eid,)).fetchone()
        if cur_kp and cur_kp[0]:
            print('    #%-5s 已有 kp_id=%s，跳过' % (eid, cur_kp[0]))
            continue
        lab = kid if kid else '%s(新建)' % newname
        print('    #%-5s → kp=%-4s  %s' % (eid, lab, why))
        if args.apply and target:
            cur.execute("update errors set knowledge_point_id=?, updated_at=? where id=?",
                        (target, now, eid))
        n_map += 1

    for eid, sub, why in NON_SUBJECT:
        print('    #%-5s → 不映射，标 error_subtype=%r  %s' % (eid, sub, why))
        if args.apply:
            cur.execute("update errors set error_subtype=? where id=?", (sub, eid))

    if not args.apply:
        print('\n  预览完毕。加 --apply 落库（会先自动备份）。')
        con.close()
        return 0

    con.commit()
    after = cur.execute("select count(*) from errors where knowledge_point_id is null").fetchone()[0]
    print('\n  ✅ 已落库：映射 %d 条；剩余无 kp_id 的错题 %d 条' % (n_map, after))
    con.close()
    return 0


if __name__ == '__main__':
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    sys.exit(main())
