#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""sync_mastery.py — 把错题聚合回掌握度画像（补「批改→画像」断掉的那一段）。

为什么需要它（阶段22 审计发现）：
  `import_lecture.py` 建 mastery 时「已存在的不动」，`fix_db.py` 只重算到期日 ——
  两者都不做「新增错题 → 更新已有画像」。结果 mastery 的 updated_at 长期停在
  阶段19，之后每次批改对「哪科薄弱、该练什么」都没影响。

规则（取自 references/four-library-design.md）：
  error_count = 0                    → level 0（未知）
  error_count ≥ 3 或 correct_streak<2 → level 1（薄弱）
  practice ≥ 3 且 correct_streak ≥ 2  → level 2（巩固）
  correct_streak ≥ 5 且 practice ≥ 8  → level 3（掌握）

间隔重复：1→3→7→15→30 天，按 correct_streak 定档（与 fix_db.py step5 一致）。

用法：
    python scripts/sync_mastery.py             # 预览，不改库
    python scripts/sync_mastery.py --apply     # 落库（自动备份）
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

# 算作「未消解」的状态。其余（archived / cleared / resolved / duplicate-merged）不计入薄弱度。
UNRESOLVED = ('active', 'reviewing')
# 历史上出现过的不规范状态值 → 规范值
STATUS_FIX = {'未掌握': 'active', '': 'active'}

LADDER = [1, 3, 7, 15, 30]


def level_of(error_count, practice, streak):
    """按 four-library-design.md 的四档规则算掌握度。

    ⚠️ 阶段22 修正：原规则表里 level 2 的判据（practice≥3 且 streak≥2）
    没有和 level 1 的判据（error_count≥3）排先后，导致「54 道错题但练过 3 次」
    会被判成「巩固」。这里补上 `error_count < 3` 的前提 —— 手上还堆着 3 道以上
    未消解错题，就不可能算巩固。
    """
    if streak >= 5 and practice >= 8:
        return 3
    if practice >= 3 and streak >= 2 and error_count < 3:
        return 2
    if error_count >= 3 or streak < 2:
        return 1
    return 0


def next_review(base_date, streak):
    iv = LADDER[min(max(streak, 0), len(LADDER) - 1)]
    today = datetime.date.today()
    b = base_date
    if b is None or (today - b).days > iv * 3:
        b = today                     # 基准太旧就从今天重起，避免队列永久积压
    return (b + datetime.timedelta(days=iv)).isoformat(), iv


def parse_date(s):
    if not s:
        return None
    try:
        return datetime.date.fromisoformat(str(s)[:10])
    except Exception:                                     # noqa: BLE001
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--apply', action='store_true', help='落库（默认只预览）')
    ap.add_argument('--db', default=str(DB))
    args = ap.parse_args()

    db = Path(args.db)
    if not db.exists():
        raise SystemExit('数据库不存在：%s' % db)
    con = sqlite3.connect(str(db))
    con.row_factory = sqlite3.Row
    cur = con.cursor()

    today = datetime.date.today().isoformat()

    # ---------- 1. 规范状态值（历史脏数据） ----------
    status_fixed = 0
    for bad, good in STATUS_FIX.items():
        n = cur.execute("select count(*) from errors where status=?", (bad,)).fetchone()[0]
        if n:
            status_fixed += n
            if args.apply:
                cur.execute("update errors set status=?, updated_at=? where status=?",
                            (good, today, bad))

    # ---------- 2. 按知识点聚合未消解错题 ----------
    ph = ','.join('?' * len(UNRESOLVED))
    agg = {}
    for r in cur.execute(
            "select knowledge_point_id as kp, count(*) n, group_concat(distinct error_type) types,"
            " avg(coalesce(severity,0)) sev, max(date) last_at"
            " from errors where knowledge_point_id is not null and status in (%s)"
            " group by knowledge_point_id" % ph, UNRESOLVED):
        agg[r['kp']] = r
    orphans = cur.execute(
        "select count(*) from errors where knowledge_point_id is null and status in (%s)" % ph,
        UNRESOLVED).fetchone()[0]

    # ---------- 3. 算每行的新值 ----------
    existing = {r['knowledge_point_id']: r for r in
                cur.execute("select * from mastery")}
    plans, created = [], 0
    for kp, r in agg.items():
        old = existing.get(kp)
        practice = (old['practice_count'] if old else 0) or 0
        streak = (old['correct_streak'] if old else 0) or 0
        if old is None:
            # 新建的按规则算（没有历史判断可以破坏）
            lvl = level_of(r['n'], practice, streak)
        elif (old['mastery_level'] or 0) == 0 and r['n'] >= 3:
            # 0 = 「未知」，不是「已掌握」。手上堆着 ≥3 道未消解错题还标「未知」，
            # 那是信息缺失，不是判断。允许 0 → 1（更明确），但不许 1/2/3 之间乱动。
            lvl = level_of(r['n'], practice, streak)
        else:
            # ⚠️ 已有画像**不覆盖等级**。原因：practice_log 只有 28 行、
            # 绝大多数 kp 的 practice_count/correct_streak 都是 0，
            # 按规则算会把 127 个知识点全部压成 level 1（薄弱），
            # 等于用「没练过」去否定已有的判断。等级该由练习结果推动，
            # 不该由「错题聚合」单方面改写。
            # 这里只刷新事实字段（错题数/错因/最近错日/复习到期），等级留给练习环节。
            lvl = old['mastery_level']
        last = parse_date(r['last_at']) or parse_date(old['last_error_at'] if old else None)
        nxt, iv = next_review(last, streak)
        plans.append({
            'kp': kp, 'error_count': r['n'], 'error_types': r['types'] or '',
            'severity_avg': round(r['sev'] or 0, 2), 'last_error_at': r['last_at'],
            'mastery_level': lvl, 'next_review_at': nxt, 'interval_days': iv,
            'old_level': old['mastery_level'] if old else None,
            'old_count': old['error_count'] if old else None,
            'is_new': old is None,
        })
        if old is None:
            created += 1

    # ---------- 4. 摘要 ----------
    changed = [p for p in plans if not p['is_new'] and
               (p['mastery_level'] != p['old_level'] or p['error_count'] != p['old_count'])]

    print('=' * 66)
    print('sync_mastery — 错题聚合回掌握度画像%s' % ('' if args.apply else '（预览，不落库）'))
    print('=' * 66)
    print('  规范状态值      : %d 条（未掌握/空 → active）' % status_fixed)
    print('  未消解错题      : 涉 %d 个知识点（active+reviewing）' % len(agg))
    print('  无 kp 的孤儿错题: %d 条（不参与画像）' % orphans)
    print('  mastery 新建     : %d 个知识点' % created)
    print('  mastery 有变化   : %d 个知识点' % len(changed))

    if changed:
        print('\n  ── 等级或错题数变化（前 12）──')
        for p in changed[:12]:
            print('    kp=%-4s 错题 %s→%s  level %s→%s'
                  % (p['kp'], p['old_count'], p['error_count'],
                     p['old_level'], p['mastery_level']))

    lv = {}
    for p in plans:
        lv[p['mastery_level']] = lv.get(p['mastery_level'], 0) + 1
    print('\n  ── 本次涉及知识点的等级分布 ──')
    for k in sorted(lv):
        print('    level %d : %d 个' % (k, lv[k]))

    if not args.apply:
        print('\n  预览完毕。加 --apply 落库（会先自动备份）。')
        con.close()
        return 0

    # ---------- 5. 落库（先备份） ----------
    bak = db.with_suffix('.sqlite.bak-before-sync-mastery-%s'
                         % datetime.datetime.now().strftime('%Y%m%d_%H%M%S'))
    shutil.copy2(db, bak)
    print('\n  已备份 → %s' % bak.name)

    for p in plans:
        if p['is_new']:
            cur.execute(
                "insert into mastery(knowledge_point_id,error_count,error_types,severity_avg,"
                "last_error_at,practice_count,correct_streak,mastery_level,next_review_at,"
                "updated_at,interval_days) values(?,?,?,?,?,0,0,?,?,?,?)",
                (p['kp'], p['error_count'], p['error_types'], p['severity_avg'],
                 p['last_error_at'], p['mastery_level'], p['next_review_at'], today,
                 p['interval_days']))
        else:
            cur.execute(
                "update mastery set error_count=?, error_types=?, severity_avg=?,"
                " last_error_at=?, mastery_level=?, next_review_at=?, interval_days=?,"
                " updated_at=? where knowledge_point_id=?",
                (p['error_count'], p['error_types'], p['severity_avg'], p['last_error_at'],
                 p['mastery_level'], p['next_review_at'], p['interval_days'], today, p['kp']))
    con.commit()

    n = cur.execute("select count(*) from mastery").fetchone()[0]
    last = cur.execute("select max(updated_at) from mastery").fetchone()[0]
    print('  ✅ 已落库：mastery 共 %d 行，最新 updated_at = %s' % (n, last))
    con.close()
    return 0


if __name__ == '__main__':
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    sys.exit(main())
