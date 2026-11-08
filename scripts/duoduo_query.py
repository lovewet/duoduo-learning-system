#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
学生学习库查询脚本 — 随 duoduo-learning-system 技能使用
用法示例：
  python duoduo_query.py stats                 # 总体统计
  python duoduo_query.py subject               # 各科错题分布
  python duoduo_query.py weak 10               # 最薄弱 10 个知识点
  python duoduo_query.py due                   # 到期复习队列
  python duoduo_query.py search 冠词            # 按知识点/错因检索错题
  python duoduo_query.py kp 数学 有理数           # 查知识点及明细
  python duoduo_query.py unresolved --subject 数学
  python duoduo_query.py gates                   # 三科分门分布
  python duoduo_query.py dump errors 50        # 导出任意表前 N 行
"""
import sqlite3, sys, os, argparse

DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data', 'error_db.sqlite')

SEV_MAP = {'🔴': 'H', '🟡': 'M', '🟢': 'L', '中': 'M',
            'high': 'H', 'medium': 'M', 'H': 'H', 'M': 'M', 'L': 'L'}

# status 状态机（见 SKILL.md §5）
# 阶段19 优化：新增 archived —— 缺题面的历史欠账，不进待复习队列
STATUS_CN = {
    'active': '新录入 🆕', 'reviewing': '复习中 🔄', 'resolved': '已消解 ✅',
    'cleared': '已清除', 'duplicate-merged': '重复合并',
    'archived': '历史欠账归档（缺题面，不进复习队列）',
}


def conn():
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    return c


def norm_severity(rows):
    """历史遗留中英文枚举归一后统计。rows 为 (severity, count) 序列。"""
    d = {}
    for sev, n in rows:
        key = SEV_MAP.get(str(sev).strip(), 'M')
        d[key] = d.get(key, 0) + n
    return d


def cmd_stats(c):
    print('=' * 60)
    print('学生学习库 · 总体统计')
    print('=' * 60)
    t = c.execute("select count(*), min(date), max(date) from errors").fetchone()
    print(f'错题总数: {t[0]}   时间跨度: {t[1]} ~ {t[2]}')

    print('\n[按学科]')
    for r in c.execute("select subject,count(*) n from errors group by subject order by n desc"):
        print(f'  {r["subject"]:<6} {r["n"]:>5}')

    print('\n[按错因 error_type]')
    for r in c.execute("select error_type,count(*) n from errors group by error_type order by n desc"):
        print(f'  {r["error_type"]:<22} {r["n"]:>5}')

    print('\n[按严重度 · 已归一]')
    raw = c.execute("select severity,count(*) n from errors group by severity order by n desc").fetchall()
    sev = norm_severity([(r['severity'], r['n']) for r in raw])
    for k in ('H', 'M', 'L'):
        detail = ', '.join(f'{r["severity"]}={r["n"]}' for r in raw
                           if SEV_MAP.get(str(r['severity']).strip()) == k)
        print(f'  {k:<8} {sev.get(k,0):>5}   ({detail})')

    print('\n[消解状态]')
    for r in c.execute("select status,count(*) n from errors group by status order by n desc"):
        label = STATUS_CN.get(r['status'], '')
        print(f'  {r["status"]:<18} {r["n"]:>5}   {label}')

    print('\n[各表行数]')
    for tb in ['errors', 'knowledge_base', 'knowledge_detail', 'mastery',
               'questions', 'question_items', 'error_ocr_judged', 'task_cards']:
        n = c.execute(f'select count(*) from "{tb}"').fetchone()[0]
        print(f'  {tb:<22} {n:>6}')


def cmd_subject(c):
    print('学科 × 错因 交叉表')
    rows = c.execute("""
        select subject, error_type, count(*) n from errors
        group by subject, error_type order by subject, n desc
    """).fetchall()
    cur = None
    for r in rows:
        if r['subject'] != cur:
            cur = r['subject']
            print(f'\n【{cur}】')
        print(f'  {r["error_type"]:<22} {r["n"]:>5}')


def cmd_weak(c, n=10):
    print(f'最薄弱 {n} 个知识点（按错题数 + 掌握等级 + 难度）')
    rows = c.execute("""
        select m.knowledge_point_id, k.point_name, k.subject, k.unit,
               m.error_count, m.mastery_level, m.difficulty,
               m.correct_streak, m.practice_count, m.error_types, m.next_review_at
        from mastery m
        left join knowledge_base k on k.id = m.knowledge_point_id
        order by coalesce(m.mastery_level,9) asc, m.error_count desc
        limit ?
    """, (n,)).fetchall()
    if not rows:
        print('  (mastery 表为空)')
        return
    for i, r in enumerate(rows, 1):
        print(f"\n{i}. [{r['subject'] or '?'}] {r['point_name'] or '(无名称)'}  (kp#{r['knowledge_point_id']})")
        print(f"   单元: {r['unit']}   错题数: {r['error_count']}   掌握等级: {r['mastery_level']}   难度: {r['difficulty']}")
        print(f"   练习: {r['practice_count']} 次   连对: {r['correct_streak']}   到期复习: {r['next_review_at'] or '—'}")
        if r['error_types']:
            print(f"   错因分布: {r['error_types'][:160]}")


def cmd_due(c):
    today = 'now'
    rows = c.execute("""
        select m.knowledge_point_id, k.point_name, k.subject, m.next_review_at,
               m.mastery_level, m.error_count
        from mastery m
        left join knowledge_base k on k.id = m.knowledge_point_id
        where m.next_review_at is not null and m.next_review_at <= date('now','localtime')
        order by m.next_review_at
    """).fetchall()
    print(f'到期复习队列（{len(rows)} 项）')
    for r in rows:
        print(f'  {r["next_review_at"]}  [{r["subject"] or "?"}] {r["point_name"] or "?"}  '
              f'kp#{r["knowledge_point_id"]}  level={r["mastery_level"]}  错{r["error_count"]}条')


def cmd_search(c, kw):
    print(f'检索错题: 关键词 = {kw}')
    rows = c.execute("""
        select id, date, subject, chapter, knowledge_point, error_type, severity, status
        from errors
        where knowledge_point like ? or error_desc like ? or question_full like ?
           or tags like ? or error_type like ?
        order by date desc limit 50
    """, (f'%{kw}%', f'%{kw}%', f'%{kw}%', f'%{kw}%', f'%{kw}%')).fetchall()
    print(f'命中 {len(rows)} 条')
    for r in rows:
        print(f'  #{r["id"]} {r["date"]} [{r["subject"]}] {r["knowledge_point"]} | '
              f'{r["error_type"]} | {r["severity"]} | {r["status"]}')
        print(f'      {r["chapter"]}')


def cmd_kp(c, subject, name):
    print(f'知识点查询: {subject} / {name}')
    rows = c.execute("""
        select id, subject, grade, unit, point_name, point_type, detail
        from knowledge_base where subject=? and point_name like ?
    """, (subject, f'%{name}%')).fetchall()
    if not rows:
        print('  (未找到)')
        return
    for r in rows:
        print(f"\n  kp#{r['id']}  {r['point_name']}  ({r['grade']} / {r['unit']} / {r['point_type']})")
        if r['detail']:
            print(f"    {r['detail']}")
        n = c.execute("select count(*) from knowledge_detail where knowledge_point_id=?", (r['id'],)).fetchone()[0]
        print(f'    明细条目: {n}')
        for d in c.execute("select content from knowledge_detail where knowledge_point_id=? limit 8", (r['id'],)):
            print(f'      · {str(d["content"])[:120]}')


def cmd_unresolved(c, subject=None):
    sql = ("select id,date,subject,knowledge_point,error_type,severity,knowledge_point_id "
           "from errors where status='active'")
    params = ()
    if subject:
        sql += ' and subject=?'
        params = (subject,)
    sql += ' order by date desc limit 100'
    rows = c.execute(sql, params).fetchall()
    print(f'未消解错题（active）: {len(rows)} 条' + (f' · 学科={subject}' if subject else ''))
    for r in rows:
        print(f'  #{r["id"]} {r["date"]} [{r["subject"]}] {r["knowledge_point"]} | '
              f'{r["error_type"]} | {r["severity"]} | kp#{r["knowledge_point_id"]}')


def cmd_dump(c, table, n):
    if not table.isidentifier():
        print('非法表名'); return
    rows = c.execute(f'select * from "{table}" limit {int(n)}').fetchall()
    if not rows:
        print('(空表)'); return
    cols = rows[0].keys()
    print(f'## {table}  ({len(rows)} 行, {len(cols)} 列)')
    for r in rows:
        print('  ---')
        for k in cols:
            v = str(r[k]) if r[k] is not None else ''
            if len(v) > 150: v = v[:150] + '…'
            if v: print(f'   {k}: {v}')


def cmd_gates(c, subject=None):
    """三科分门分布（error_category_mapping）"""
    print('三科分门分布 · 按实际错误内容归类')
    if subject:
        rows = c.execute("""
            select m.category_id, m.category_name, count(*) n
            from error_category_mapping m join errors e on e.id = m.error_id
            where m.subject = ? group by m.category_id, m.category_name
            order by n desc""", (subject,)).fetchall()
        print(f'\n【{subject}】共 {sum(r["n"] for r in rows)} 条')
    else:
        rows = c.execute("""
            select subject, category_id, category_name, count(*) n
            from error_category_mapping group by subject, category_id, category_name
            order by subject, n desc""").fetchall()
    cur = None
    for r in rows:
        if not subject and r['subject'] != cur:
            cur = r['subject']
            print(f'\n【{cur}】')
        print(f"  {r['category_id']:<4} {r['category_name']:<26} {r['n']:>5}")

    # 覆盖度校验
    print('\n[覆盖度校验]')
    for s in ['数学', '英语', '语文']:
        tot = c.execute('select count(*) from errors where subject=?', (s,)).fetchone()[0]
        m = c.execute('select count(*) from errors e join error_category_mapping m'
                      ' on e.id=m.error_id where e.subject=?', (s,)).fetchone()[0]
        flag = 'OK' if m == tot else '!! 缺口 %d' % (tot - m)
        print(f'  {s}: {m}/{tot} = {m/tot*100:.0f}%  {flag}')


def main():
    ap = argparse.ArgumentParser(add_help=True)
    ap.add_argument('cmd')
    ap.add_argument('args', nargs='*')
    a = ap.parse_args()
    if not os.path.exists(DB):
        print(f'数据库不存在: {DB}'); sys.exit(1)
    c = conn()
    cmd = a.cmd
    if cmd == 'stats': cmd_stats(c)
    elif cmd == 'subject': cmd_subject(c)
    elif cmd == 'weak': cmd_weak(c, int(a.args[0]) if a.args else 10)
    elif cmd == 'due': cmd_due(c)
    elif cmd == 'search': cmd_search(c, a.args[0] if a.args else '')
    elif cmd == 'kp': cmd_kp(c, a.args[0] if a.args else '', a.args[1] if len(a.args) > 1 else '')
    elif cmd == 'unresolved': cmd_unresolved(c, a.args[0] if a.args else None)
    elif cmd == 'gates': cmd_gates(c, a.args[0] if a.args else None)
    elif cmd == 'dump': cmd_dump(c, a.args[0] if a.args else 'errors', a.args[1] if len(a.args) > 1 else 10)
    else:
        print(__doc__)


if __name__ == '__main__':
    main()
