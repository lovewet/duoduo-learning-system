#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""db_gate.py — 错题入库的唯一门禁（本机版，6 关）。

为什么需要它（阶段23 审计）：
  SKILL.md 声称「唯一门禁 `scripts/error_db_ingest.py`」，但**本机根本没这个文件**。
  实际入库是 `grade_submission.py` 直写，而它把 `error_type` 硬编码成 `"other"`
  （非法值）、`knowledge_point_id` 根本不填 —— 于是每批改一次就造一批
  「非法错因 + 无知识点」的孤儿，画像永远聚合不到。

六关（ERROR 拒写，WARN 写但标记）：
  1. error_type 合法 —— 必须在 13 值枚举内（"other"/"要点残缺" 一律拒）
  2. 答案非空 —— correct_answer 不能是空串
  3. 知识点可解析 —— knowledge_point_id 能落到 knowledge_base（WARN：落不到则标待归因）
  4. 不重复 —— 同 date + subject + error_desc 已存在则拒
  5. 日期合理 —— 不能晚于今天；早于 2026-07-01 要警告
  6. 来源标注 —— source 非空（否则无法追溯是谁写进来的）

用法：
    python scripts/db_gate.py --selftest # 6 关自检
    python scripts/db_gate.py --check-db # 全库体检，列出违规记录
    # 代码内调用：
    from db_gate import validate, resolve_kp
"""

from __future__ import annotations

import argparse
import datetime
import sqlite3
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
DB = HERE.parent / 'data' / 'error_db.sqlite'

LEGAL_TYPES = {
    'concept-confusion', 'calculation', 'sign-error', 'formula-misuse',
    'missing-zero', 'classification', 'blank', 'incomplete-answer',
    'careless', 'grammar', 'spelling', 'collocation', 'semantic',
}
# 入库时还没做归因的占位类型：用合法的 blank，且 error_subtype 必须写明「待归因」。
# 绝不写 "other"（非法）—— 那正是历史脏数据的源头。
PLACEHOLDER_TYPE = 'blank'
PLACEHOLDER_SUBTYPE = '待归因'
MIN_DATE = datetime.date(2026, 7, 1)


def resolve_kp(cur, subject, chapter='', kp_text=''):
    """尝试把错题落到 knowledge_base 的某个知识点上。返回 id 或 None。

    顺序：同科目内 ① 知识点名精确 ② 知识点名包含 ③ 章节名精确。
    匹配不到就返回 None（由调用方标待归因），**不猜**。
    """
    if subject and subject != '其它':
        if kp_text:
            r = cur.execute("select id from knowledge_base where subject=? and point_name=?",
                            (subject, kp_text.strip())).fetchone()
            if r:
                return r[0]
            r = cur.execute(
                "select id from knowledge_base where subject=? and point_name like ?"
                " order by length(point_name) limit 1",
                (subject, '%' + kp_text.strip()[:10] + '%')).fetchone()
            if r:
                return r[0]
        if chapter:
            r = cur.execute("select id from knowledge_base where subject=? and unit=? limit 1",
                            (subject, chapter.strip())).fetchone()
            if r:
                return r[0]
    return None


def validate(cur, row):
    """六关校验。row 是 dict：date/subject/error_desc/correct_answer/error_type/
    knowledge_point_id/source/error_subtype。

    返回 (errors, warnings)：errors 非空 → 拒写；warnings 非空 → 写但标记。
    """
    errors, warnings = [], []
    today = datetime.date.today()

    # 1. error_type 合法
    et = (row.get('error_type') or '').strip()
    if not et:
        errors.append('门禁1 error_type 为空')
    elif et not in LEGAL_TYPES:
        errors.append('门禁1 error_type 非法：%r（合法值见 13 值枚举）' % et)

    # 2. 答案非空
    if not (row.get('correct_answer') or '').strip():
        errors.append('门禁2 correct_answer 为空')

    # 3. 知识点可解析
    kp = row.get('knowledge_point_id')
    if kp:
        if not cur.execute("select 1 from knowledge_base where id=?", (kp,)).fetchone():
            errors.append('门禁3 knowledge_point_id=%s 在 knowledge_base 里不存在' % kp)
    else:
        warnings.append('门禁3 无 knowledge_point_id（进不了画像，标待归因）')

    # 4. 查重
    d, s, desc = row.get('date'), row.get('subject'), (row.get('error_desc') or '')[:80]
    if d and s and desc:
        dup = cur.execute(
            "select id from errors where date=? and subject=? and substr(error_desc,1,80)=?"
            " and coalesce(status,'')!='duplicate-merged' limit 1", (d, s, desc)).fetchone()
        if dup:
            errors.append('门禁4 重复：同日期同科目同描述已存在 id=%s' % dup[0])

    # 5. 日期合理
    try:
        dd = datetime.date.fromisoformat(str(d)[:10])
        if dd > today:
            errors.append('门禁5 日期在未来：%s' % dd)
        elif dd < MIN_DATE:
            warnings.append('门禁5 日期早于 %s（%s），确认不是笔误' % (MIN_DATE, dd))
    except Exception: # noqa: BLE001
        errors.append('门禁5 日期无法解析：%r' % d)

    # 6. 来源标注
    if not (row.get('source') or '').strip():
        errors.append('门禁6 source 为空，无法追溯')

    # 附加：占位类型必须写明待归因，否则等于假装归过因
    if et == PLACEHOLDER_TYPE and (row.get('error_subtype') or '') != PLACEHOLDER_SUBTYPE:
        warnings.append('error_type=blank 但 error_subtype 不是「待归因」，确认这不是'
                        '「学生真的空着没写」')

    return errors, warnings


def _make_cur(db_path):
    con = sqlite3.connect(db_path)
    return con, con.cursor()


def _has_errors_table(p) -> bool:
    """库文件存在且真的有 errors 表，才算「可用真库」。

    ⚠️ 只判 `os.path.isfile` 不够：`sqlite3.connect()` 对不存在的路径会**顺手建一个 0 字节文件**，
    之后再跑自检就会连到这个空库、报 `no such table: errors`，看着像脚本坏了。
    """
    try:
        if not Path(str(p)).is_file() or Path(str(p)).stat().st_size == 0:
            return False
        c = sqlite3.connect(str(p))
        try:
            return c.execute(
                "select 1 from sqlite_master where type='table' and name='errors'"
            ).fetchone() is not None
        finally:
            c.close()
    except Exception:
        return False


def selftest(db_path=None):
    """6 关自检：每关造一个应被拦的坏样例 + 一个好样例。

    🔴 `--selftest` 不传 `--db`、或默认库不存在/是空壳时，用**内存库**（现造最小表结构）。
    之前直接连默认库路径，没库的人只会看到 `sqlite3.OperationalError: no such table: errors`，
    误以为门禁脚本坏了 —— 而自检本来就该不依赖真实数据。
    """
    mem = not _has_errors_table(db_path) if db_path is not None else True
    if mem:
        con = sqlite3.connect(":memory:")
        cur = con.cursor()
        cur.executescript(
            "create table knowledge_base (id integer primary key, subject text,"
            " point_name text, unit text);"
            "create table errors (id integer primary key, date text, subject text,"
            " error_desc text, status text);"
            "insert into knowledge_base (id, subject, point_name, unit)"
            " values (1, '数学', '绝对值', '数轴与绝对值');"
            "insert into errors (id, date, subject, error_desc)"
            " values (1, 'S1', '数学', '__dup__ 同一道题 __');"
        )
        con.commit()
        print(' （自检使用内存库，不读写任何真实数据）')
    else:
        con, cur = _make_cur(db_path)
    today = datetime.date.today().isoformat()
    base = {'date': today, 'subject': '数学', 'error_desc': '__selftest__不要入库__',
            'correct_answer': '42', 'error_type': 'calculation',
            'knowledge_point_id': None, 'source': 'selftest', 'error_subtype': ''}
    ok_all = True

    def case(name, patch, want_err_contains):
        nonlocal ok_all
        r = dict(base)
        r.update(patch)
        errs, warns = validate(cur, r)
        hit = any(want_err_contains in e for e in errs) if want_err_contains else not errs
        print(' %s %-28s errors=%s' % ('✅' if hit else '❌', name, errs or '（无）'))
        ok_all = ok_all and hit

    case('第1关 非法 error_type', {'error_type': 'other'}, '门禁1')
    case('第2关 答案为空', {'correct_answer': ''}, '门禁2')
    case('第3关 kp 不存在', {'knowledge_point_id': 999999}, '门禁3')
    case('第4关 重复', {'error_desc': '（自检跳过，无匹配）'}, None) # 无重复应通过
    case('第5关 日期在未来', {'date': '2099-01-01'}, '门禁5')
    case('第6关 来源为空', {'source': ''}, '门禁6')
    case('好样例 应通过', {}, None)

    # 第4关正向：真的重复
    dup = cur.execute("select date,subject,substr(error_desc,1,80) from errors limit 1").fetchone()
    if dup:
        r = dict(base)
        r.update({'date': dup[0], 'subject': dup[1], 'error_desc': dup[2]})
        errs, _ = validate(cur, r)
        hit = any('门禁4' in e for e in errs)
        print(' %s %-28s errors=%s' % ('✅' if hit else '❌', '第4关 真重复被拦', errs or '（无）'))
        ok_all = ok_all and hit

    print('\n %s' % ('✅ 门禁 6 关自检全过' if ok_all else '❌ 有门禁没过'))
    con.close()
    return 0 if ok_all else 1


def check_db(db_path=DB):
    """全库体检：逐条过门禁，统计违规（只读，不改库）。"""
    con, cur = _make_cur(db_path)
    rows = cur.execute(
        "select id,date,subject,error_desc,correct_answer,error_type,"
        "knowledge_point_id,source,error_subtype from errors").fetchall()
    bad, warn = [], []
    for r in rows:
        row = dict(zip(['id', 'date', 'subject', 'error_desc', 'correct_answer',
                        'error_type', 'knowledge_point_id', 'source', 'error_subtype'], r))
        e, w = validate(cur, row)
        # 查重关对存量数据没意义（自己跟自己重复），体检时跳过
        e = [x for x in e if not x.startswith('门禁4')]
        if e:
            bad.append((row['id'], e))
        elif w:
            warn.append((row['id'], w))
    print('全库 %d 条：违规 %d，警告 %d' % (len(rows), len(bad), len(warn)))
    if bad:
        print('\n违规（前 15）：')
        for i, e in bad[:15]:
            print(' #%-6s %s' % (i, '; '.join(e)[:110]))
    from collections import Counter
    c = Counter(x.split('：')[0] for _i, es in bad for x in es)
    if c:
        print('\n按关统计：', dict(c))
    con.close()
    return 0


if __name__ == '__main__':
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    ap = argparse.ArgumentParser()
    ap.add_argument('--selftest', action='store_true')
    ap.add_argument('--check-db', action='store_true')
    ap.add_argument('--db', default=str(DB))
    a = ap.parse_args()
    if a.selftest:
        sys.exit(selftest(a.db))
    if a.check_db:
        sys.exit(check_db(a.db))
    print(__doc__)