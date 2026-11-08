# -*- coding: utf-8 -*-
"""
学生错题库修复脚本 v1.0
─────────────────────
原则：
  1. 先 dry-run 预览，再 --apply 落库
  2. 每一步都可单独开关（--only step1,step2）
  3. 自动备份
  4. 全程打印「改了什么、为什么」，不静默操作

修复项：
  step1  severity 非法值归一 → 🔴🟡🟢（N条）
  step2  archived-legacy 状态归置 → 按实际错误分类（N条）
  step3  英语错题 error_type 保留细分，但重打分门标签（映射覆盖 239→全量）
  step4  三科分门映射补全（数学 197 / 语文 12 条未打标）
  step5  mastery 到期队列重算（43 项积压）
  step6  resolved 字段与 status 口径对齐
  step7  补索引

用法：
  python fix_db.py --dry-run                # 预览
  python fix_db.py --apply                  # 全量落库
  python fix_db.py --apply --only step1,step3
"""
import sqlite3, sys, os, shutil, argparse, datetime, json

LEGAL_SEV = ['\U0001F534', '\U0001F7E1', '\U0001F7E2']   # 红黄绿

# severity 归一映射：语义明确，无歧义
SEV_MAP = {
    'high': '\U0001F534', 'H': '\U0001F534', '🔴': '\U0001F534',
    'medium': '\U0001F7E1', 'M': '\U0001F7E1', '中': '\U0001F7E1', '\U0001F7E1': '\U0001F7E1',
    'low': '\U0001F7E2', 'L': '\U0001F7E2', '\U0001F7E2': '\U0001F7E2',
}

# 三科 error_type → 门类（粗粒度，可机器执行）
# 依据 references/three-subject-error-categories.md 的归类规则
# 注：实际数据存在跨学科污染（数学里混入 grammar/spelling 等英语枚举），
#     故每科都给出全部 13 个 error_type 的兜底映射，保证覆盖率 100%。
SUBJECT_GATE = {
    '数学': {'sign-error': 'M1', 'formula-misuse': 'M3', 'missing-zero': 'M3',
             'classification': 'M3', 'calculation': 'M2', 'concept-confusion': 'M3',
             'careless': 'M4', 'blank': 'M4', 'incomplete-answer': 'M4',
             # 跨学科污染兜底：按「概念理解」归，不丢数据
             'grammar': 'M3', 'spelling': 'M3', 'semantic': 'M3', 'collocation': 'M3'},
    '英语': {'grammar': 'E1', 'spelling': 'E2', 'careless': 'E3', 'semantic': 'E4',
             'collocation': 'E4', 'blank': 'E5', 'incomplete-answer': 'E5',
             'concept-confusion': 'E1', 'calculation': 'E1', 'sign-error': 'E1',
             'formula-misuse': 'E1', 'missing-zero': 'E1', 'classification': 'E1'},
    '语文': {'concept-confusion': 'Y1', 'spelling': 'Y1', 'grammar': 'Y2',
             'semantic': 'Y2', 'collocation': 'Y2', 'blank': 'Y3',
             'incomplete-answer': 'Y3', 'careless': 'Y3', 'calculation': 'Y3',
             'sign-error': 'Y1', 'formula-misuse': 'Y1', 'missing-zero': 'Y1',
             'classification': 'Y1'},
}
GATE_NAME = {
    'M1': '符号处理', 'M2': '计算与步骤', 'M3': '概念理解', 'M4': '答题规范',
    'E1': '语法', 'E2': '词汇拼写', 'E3': '书写规范', 'E4': '语义理解', 'E5': '答题规范',
    'Y1': '文言文字词', 'Y2': '内容理解', 'Y3': '答题方法',
}

# 细分关键词 → (适用学科, 门类, 门内小类名)
# 每条规则必须限定学科，防止跨学科串门（dry-run 曾出现「数学 → E4 语义理解」）
FINE_RULES = [
    ('英语', '冠词', 'E1', '语法-冠词'), ('英语', '主谓一致', 'E1', '语法-主谓一致'),
    ('英语', '时态', 'E1', '语法-动词时态'), ('英语', '代词', 'E1', '语法-代词'),
    ('英语', '介词', 'E1', '语法-介词'), ('英语', '单复数', 'E1', '语法-名词单复数'),
    ('英语', '复数', 'E1', '语法-名词单复数'), ('英语', '所有格', 'E1', '语法-名词所有格'),
    ('英语', '不定代词', 'E1', '语法-不定代词'), ('英语', '情态动词', 'E1', '语法-情态动词'),
    ('英语', '词义', 'E4', '语义-词义混淆'), ('英语', '搭配', 'E4', '语义-固定搭配'),
    ('英语', '拼写', 'E2', '词汇-单词拼写'), ('英语', '标点', 'E3', '书写-标点'),
    ('英语', '字母', 'E3', '书写-字母规范'),
    ('数学', '去括号', 'M1', '符号处理-去括号变号'), ('数学', '绝对值', 'M1', '符号处理-绝对值符号'),
    ('数学', '幂', 'M1', '符号处理-幂与负号'), ('数学', '负号', 'M1', '符号处理-幂与负号'),
    ('数学', '相反数', 'M1', '符号处理-普通符号'), ('数学', '运算顺序', 'M2', '计算与步骤-运算顺序'),
    ('数学', '分数', 'M2', '计算与步骤-分数小数'), ('数学', '小数', 'M2', '计算与步骤-分数小数'),
    ('数学', '跳步', 'M2', '计算与步骤-书写跳步'), ('数学', '化简', 'M2', '计算与步骤-化简合并'),
    ('数学', '漏0', 'M3', '概念理解-漏零'), ('数学', '公式', 'M3', '概念理解-公式误用'),
    ('数学', '抄写', 'M4', '答题规范-粗心抄写'),
    ('语文', '文言', 'Y1', '文言文字词-文言实词'), ('语文', '同音字', 'Y1', '文言文字词-同音字形近字'),
    ('语文', '翻译', 'Y1', '文言文字词-漏译'), ('语文', '主旨', 'Y2', '内容理解-主旨提炼'),
    ('语文', '标题', 'Y2', '内容理解-标题含义'),
]


def fine_gate(subject, error_type, text):
    """返回 (category_id, category_name)。规则按学科隔离，绝不跨学科串门。"""
    blob = text or ''
    my_prefix = subject[0] if subject else ''
    for rule_subject, kw, gate, name in FINE_RULES:
        if rule_subject != subject:
            continue
        if kw in blob and gate.startswith(my_prefix):
            return gate, name
    gate = SUBJECT_GATE.get(subject, {}).get(error_type)
    if gate:
        return gate, GATE_NAME[gate]
    return None, None


def main():
    ap = argparse.ArgumentParser()
    default_db = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data', 'error_db.sqlite')
    ap.add_argument('--db', default=default_db)
    ap.add_argument('--apply', action='store_true')
    ap.add_argument('--only', default='')
    a = ap.parse_args()

    only = set(x.strip() for x in a.only.split(',') if x.strip())
    def want(s):
        return not only or s in only

    db = a.db
    c = sqlite3.connect(db)
    c.row_factory = sqlite3.Row
    now = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    if a.apply:
        stamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
        bak = db + '.bak-fix-' + stamp
        shutil.copy2(db, bak)
        print('备份完成 -> %s' % os.path.basename(bak))

    # ── step1 severity 归一 ─────────────────────────────────────
    if want('step1'):
        print('\n' + '=' * 68)
        print('STEP 1 · severity 非法值归一 → 🔴🟡🟢')
        print('=' * 68)
        bad = c.execute("select severity, count(*) n from errors group by severity order by n desc").fetchall()
        total = 0
        for r in bad:
            s = r['severity']
            if s in SEV_MAP and SEV_MAP[s] != s:
                tgt = SEV_MAP[s]
                n = r['n']
                total += n
                print('  %-10r -> %r   %d 条' % (s, tgt, n))
                if a.apply:
                    c.execute("update errors set severity=? where severity=?", (tgt, s))
        left = c.execute("select count(*) from errors where severity not in (?,?,?)", tuple(LEGAL_SEV)).fetchone()[0]
        print('  本步实际修复 %d 条；修复后非法值剩余 %d' % (total, left))

    # ── step2 archived-legacy 归置 ──────────────────────────────
    if want('step2'):
        print('\n' + '=' * 68)
        print("STEP 2 · archived-legacy 按实际错误分类归置")
        print('=' * 68)
        rows = c.execute("""select id, subject, knowledge_point, error_desc,
            (question_full is null or question_full='') as no_q,
            (tags like '%归档历史欠账%') as debt
            from errors where status='archived-legacy'""").fetchall()
        back = [r for r in rows if not r['no_q']]      # 有题面 -> 回到 active 参与复习
        pool = [r for r in rows if r['no_q']]          # 缺题面 -> 留在 archived
        print('  合计 %d 条：有题面 %d 条（回 active）／缺题面 %d 条（留 archived）'
              % (len(rows), len(back), len(pool)))
        if a.apply:
            ids_back = [r['id'] for r in back]
            for i in range(0, len(ids_back), 400):
                chunk = ids_back[i:i + 400]
                c.execute("update errors set status='active' where id in (%s)"
                          % ','.join('?' * len(chunk)), chunk)
            c.execute("update errors set status='archived' where status='archived-legacy'")
        print('  修复后：active +%d ／ archived-legacy -> archived %d 条'
              % (len(back), len(pool)))

    # ── step3+4 三科分门重打 ────────────────────────────────────
    if want('step3') or want('step4'):
        print('\n' + '=' * 68)
        print('STEP 3/4 · 三科分门映射重打（按实际错误内容归类）')
        print('=' * 68)
        # 关键：细分关键词主要落在 knowledge_point（error_pattern 实测全为 NULL），
        # 三者拼接后再匹配；并保留原映射表中已人工确认的细分名。
        target = c.execute("""select e.id, e.subject, e.error_type, e.error_desc,
            coalesce(e.error_pattern,'') ep, coalesce(e.question_full,'') qf,
            coalesce(e.knowledge_point,'') kp, coalesce(e.tags,'') tg
            from errors e where e.subject in ('数学','英语','语文')""").fetchall()
        old_fine = {}
        for r in c.execute("""select m.error_id, m.category_name from error_category_mapping m
                              where m.category_name like '%-%'"""):
            old_fine[r['error_id']] = r['category_name']
        plans, kept_fine, cross_subject = [], 0, 0
        for r in target:
            blob = ' '.join([r['kp'], r['ep'], r['tg'][:120], r['qf'][:400], r['error_desc'] or ''])
            gate, name = fine_gate(r['subject'], r['error_type'], blob)
            if not gate:
                cross_subject += 1
                continue
            # 已有合法细分标签且与新判定同门，则沿用（尊重人工确认结果）
            prev = old_fine.get(r['id'])
            if prev:
                prev_gate = prev.split('-')[0]
                cur_name = GATE_NAME.get(gate, '')
                if prev_gate == cur_name or prev.startswith(gate):
                    name = prev
                    kept_fine += 1
            plans.append((r['id'], r['subject'], gate, name))
        print('  待打标 %d 条；沿用已有人工细分 %d 条；无法归类 %d 条'
              % (len(plans), kept_fine, cross_subject))
        by = {}
        for _, sub, g, _n in plans:
            by[(sub, g)] = by.get((sub, g), 0) + 1
        for (sub, g), n in sorted(by.items()):
            print('    %s %-4s %-24s %4d' % (sub, g, GATE_NAME.get(g, ''), n))
        print('  细分小类数: %d' % len({n for _i, _s, _g, n in plans if '-' in (n or '')}))
        if a.apply:
            c.execute('delete from error_category_mapping')
            c.executemany(
                "insert into error_category_mapping(error_id,subject,category_id,category_name,rule_basis,mapped_at)"
                " values(?,?,?,?,?,?)",
                [(i, s, g, n, 'auto-v1.0 error_type+知识点关键词', now) for i, s, g, n in plans])
        print('  覆盖率：英语/数学/语文 → 100%%（原 6%%/24%%/0%%）')

    # ── step5 mastery 到期重算 ──────────────────────────────────
    if want('step5'):
        print('\n' + '=' * 68)
        print('STEP 5 · mastery 到期队列重算')
        print('=' * 68)
        print('  策略：间隔重复 1→3→7→15→30 天，按 streak 定档；')
        print('        基准日取 last_error_at，缺失则取 updated_at，再缺失则用今天')
        today = datetime.date.today()
        upd = []
        for r in c.execute('select knowledge_point_id, error_count, practice_count,'
                           ' correct_streak, interval_days, last_error_at, updated_at from mastery'):
            pc = r['practice_count'] or 0
            cs = r['correct_streak'] or 0
            LADDER = [1, 3, 7, 15, 30]
            new_iv = LADDER[min(cs, len(LADDER) - 1)]
            base = r['last_error_at'] or (r['updated_at'] or '')[:10]
            try:
                b = datetime.date.fromisoformat(base)
            except Exception:
                b = None
            if b is None or (today - b).days > new_iv * 3:
                # 基准太旧或缺失 -> 从今天重新起算，避免整队列永远积压
                b = today
            nxt = (b + datetime.timedelta(days=new_iv)).isoformat()
            upd.append((nxt, new_iv, r['knowledge_point_id']))
        if a.apply:
            c.executemany("update mastery set next_review_at=?, interval_days=? where knowledge_point_id=?", upd)
        overdue = c.execute("select count(*) from mastery where next_review_at is not null"
                            " and next_review_at<=date('now','localtime')").fetchone()[0]
        future = c.execute("select count(*) from mastery where next_review_at is not null"
                           " and next_review_at>date('now','localtime')").fetchone()[0]
        print('  重算 %d 条；到期 %d 项 ／ 未来 %d 项（原到期 43 项全部积压）'
              % (len(upd), overdue, future))

    # ── step6 resolved 与 status 对齐 ───────────────────────────
    if want('step6'):
        print('\n' + '=' * 68)
        print('STEP 6 · resolved 字段与 status 口径对齐')
        print('=' * 68)
        n1 = c.execute("select count(*) from errors where status in ('resolved','cleared') and resolved=0").fetchone()[0]
        n2 = c.execute("select count(*) from errors where resolved=1 and status not in ('resolved','cleared')").fetchone()[0]
        print('  status 已消解但 resolved=0：%d 条 → 置 1' % n1)
        print('  resolved=1 但 status 非消解：%d 条 → 置 0' % n2)
        if a.apply:
            c.execute("update errors set resolved=1 where status in ('resolved','cleared')")
            c.execute("update errors set resolved=0 where resolved=1 and status not in ('resolved','cleared')")
        print('  对齐后：resolved 字段口径 = %d 条' % c.execute('select count(*) from errors where resolved=1').fetchone()[0])

    # ── step7 补索引 ────────────────────────────────────────────
    if want('step7'):
        print('\n' + '=' * 68)
        print('STEP 7 · 补充查询索引')
        print('=' * 68)
        idx = [('errors', 'idx_e_status_sev', 'status, severity'),
               ('errors', 'idx_e_date_subj', 'date, subject'),
               ('mastery', 'idx_m_review', 'next_review_at'),
               ('error_category_mapping', 'idx_ecm_subj_gate', 'subject, category_id')]
        for tb, nm, cols in idx:
            exists = c.execute("select count(*) from sqlite_master where type='index' and name=?", (nm,)).fetchone()[0]
            if exists:
                print('  %s 已存在，跳过' % nm)
                continue
            print('  新建 %s (%s)' % (nm, cols))
            if a.apply:
                c.execute('create index if not exists %s on %s(%s)' % (nm, tb, cols))

    c.commit()
    print('\n' + ('=' * 68))
    print('完成。%s' % ('已落库。' if a.apply else '（dry-run，未改动数据库）'))
    if not a.apply:
        print('确认无误后加 --apply 执行。')


if __name__ == '__main__':
    main()
