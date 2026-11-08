#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""selftest_ingest.py — 摄取层 + 公式转换的一键自检（改代码后必跑）

自己造样本、跑摄取、断言关键行为，不依赖任何外部文件。

    python selftest_ingest.py

覆盖 11 件事：
  1. PDF 文本块分类（普通文字 / 含符号题干 / 纯公式）
  2. 「丢了上标」的写法被 suspect 标记（x2 → 必须复核）
  3. 含全角运算符（｜＋＜）的题干被强制标 need_vision
  4. 扫描页被切成多条带（整页一块交给模型必糊）
  5. 本地 OCR 给出文字基准（local-ocr 已部署时才查，未装则跳过）
  6. 文本层乱序按字符坐标还原（regroup_block）
  7. 矢量程序框图被识别成 diagram（且不被拆成碎块）
  8. 表格走 find_tables，且不被误判成框图
  9. docx 的 OMML 公式经 pandoc 还原成标准 LaTeX
 10. docx 表格解析出数据行（pandoc 3.x TableBody 第 4 槽的坑）
 11. 全部公式能落地成 MathML + OMML；latex_math 内置 12 例
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.stdout.reconfigure(encoding='utf-8') if hasattr(sys.stdout, 'reconfigure') else None

FAILS = []


def ok(cond, name, detail=''):
    print(('  ✅ ' if cond else '  ❌ ') + name + (('  ' + detail) if detail and not cond else ''))
    if not cond:
        FAILS.append(name)


# ==================== 造样本 ====================

def make_pdf(path):
    import pymupdf
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)

    page.insert_text((60, 80), "11. 用公式法解方程 x2 - 3x + 2 = 0。",
                     fontname="china-s", fontsize=11)
    page.insert_text((60, 140), "y = 3x", fontname="helv", fontsize=11)
    page.insert_text((104, 136), "2", fontname="helv", fontsize=7.5)   # 上标
    page.insert_text((112, 140), " - 2x + 1", fontname="helv", fontsize=11)

    # 矢量程序框图：平行四边形 + 矩形 + 菱形 + 输出 + 连线
    page.draw_polyline([(200, 230), (360, 230), (345, 262), (185, 262)],
                       color=(0.2, 0.2, 0.6), fill=(0.93, 0.94, 1.0),
                       width=1.4, closePath=True)
    page.insert_text((205, 252), "输入 x", fontname="china-s", fontsize=10)
    page.draw_rect(pymupdf.Rect(190, 285, 360, 325), color=(0.2, 0.2, 0.6),
                   fill=(1.0, 0.98, 0.9), width=1.4)
    page.insert_text((200, 310), "y = x + 1", fontname="china-s", fontsize=10)
    page.draw_polyline([(275, 350), (370, 385), (275, 420), (180, 385)],
                       color=(0.8, 0.1, 0.1), fill=(1.0, 0.95, 0.95),
                       width=1.4, closePath=True)
    page.insert_text((252, 390), "y > 0 ?", fontname="china-s", fontsize=10)
    for a, b in [((275, 262), (275, 285)), ((275, 325), (275, 350))]:
        page.draw_line(a, b, color=(0.35, 0.35, 0.45), width=1.4)

    # 表格
    for i in range(3):
        page.draw_rect(pymupdf.Rect(60, 460 + i * 26, 400, 486 + i * 26),
                       color=(0, 0, 0), width=0.8)
        page.draw_line((160, 460 + i * 26), (160, 486 + i * 26),
                       color=(0, 0, 0), width=0.8)
        page.insert_text((70, 478 + i * 26), str(i + 1), fontname="helv", fontsize=9)
        page.insert_text((170, 478 + i * 26), "row %d" % (i + 1),
                         fontname="helv", fontsize=9)

    # 中文教辅典型题干：全角运算符 + 绝对值竖线。
    # 这类块必须强制看图核对（｜ ＋ ＜ 等全角符号错一个，整题作废）。
    page.insert_text((60, 590), "12. 已知 a＜0，化简：｜a−3｜＋｜a｜",
                     fontname="china-s", fontsize=11)

    # 扫描页：只有图，无文本层。故意画 3 条横向内容带（模拟文字行），
    # 用于验证「扫描页会被切成多条带」—— 整页一块交给模型必糊。
    # ⚠️ 必须用位图而不是 draw_rect：矢量黑条会被框图聚类误判成 diagram。
    from PIL import Image as _Img, ImageDraw as _Draw
    p2 = doc.new_page(width=595, height=842)
    im = _Img.new('RGB', (595, 842), (228, 228, 228))
    dr = _Draw.Draw(im)
    for i in range(3):
        y = 80 + i * 180
        dr.rectangle([60, y, 500, y + 26], fill=(25, 25, 25))
    _scan_png = os.path.join(os.path.dirname(path), '_scanpage.png')
    im.save(_scan_png)
    p2.insert_image(pymupdf.Rect(0, 0, 595, 842), filename=_scan_png)
    doc.save(path)
    doc.close()


def make_docx(path):
    import pypandoc
    BS = chr(92)
    src = (
        '# 公式样本\n\n'
        '行内：$' + BS + 'frac{1}{2}x^{2}+' + BS + 'sqrt{3}$ 混排。\n\n'
        '$$\n' + BS + 'begin{cases}x+y=5' + BS + BS + 'x-y=1' + BS + 'end{cases}\n$$\n\n'
        '几何：$' + BS + 'triangle ABC' + BS + 'cong' + BS + 'triangle DEF$\n\n'
        '| 序号 | 事项 | 结果 |\n|:--|:--|:--|\n'
        '| 1 | 解 $x^{2}=4$ | $x=' + BS + 'pm 2$ |\n'
        '| 2 | 求 $' + BS + 'sqrt{16}$ | $4$ |\n'
    )
    pypandoc.convert_text(src, 'docx', format='markdown', outputfile=path)


# ==================== 跑摄取 ====================

def run_ingest(src, outdir):
    subprocess.run([sys.executable, os.path.join(HERE, 'ingest_source.py'), src, '-o', outdir],
                   check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    with open(os.path.join(outdir, 'manifest.json'), encoding='utf-8') as f:
        return json.load(f)


def formulas_ok(m):
    """每个公式片段都要能落地成 MathML + OMML，且没掉进兜底。"""
    from latex_math import latex_to_mathml, latex_to_omml, find_latex
    LATEX_CMD = re.compile(r'\\[a-zA-Z]{2,}')
    total = good = 0
    for p in m['pages']:
        for b in p['blocks']:
            for f in find_latex(b.get('text', '')):
                total += 1
                ml = latex_to_mathml(f)
                om = latex_to_omml(f)
                fell = bool(
                    LATEX_CMD.search(''.join(re.findall(r'<mtext[^>]*>(.*?)</mtext>', ml, re.S)))
                    or LATEX_CMD.search(''.join(re.findall(r'<m:t[^>]*>(.*?)</m:t>', om, re.S))))
                multi = ('matrix' in f or 'cases' in f or 'aligned' in f)
                rows_ok = (not multi) or ml.count('<mtr') >= 2
                if not fell and rows_ok:
                    good += 1
    return good, total


def main():
    # 依赖预检：缺可选依赖时给一句人话，不要甩 traceback。
    # 本自检的样本要现造 PDF，必须有 PyMuPDF；它是**可选依赖**，
    # 没装不影响讲义生成与批改，只是「摄取层回归」这一项跑不了。
    try:
        import pymupdf  # noqa: F401
    except ImportError:
        print('\n⚠️ 本自检需要 PyMuPDF（PDF 摄取通道的样本生成）')
        print('   安装：pip install pymupdf')
        print('   说明：可选依赖，未安装不影响讲义生成/批改/视频推荐；')
        print('         只是「摄取层回归」这一项跑不了。\n')
        return 2
    tmp = tempfile.mkdtemp(prefix='ingest_selftest_')
    try:
        # ---------- PDF ----------
        print('\n[1] PDF 路径')
        pdf = os.path.join(tmp, 'sample.pdf')
        make_pdf(pdf)
        m = run_ingest(pdf, os.path.join(tmp, 'pdf_out'))
        st = m['stats']
        types = [b['type'] for p in m['pages'] for b in p['blocks']]

        ok(st['formula_blocks'] >= 2, '公式块 >= 2', '实际 %d' % st['formula_blocks'])
        ok(st['diagram_blocks'] >= 1, '框图块 >= 1', '实际 %d' % st['diagram_blocks'])
        ok(st['diagram_blocks'] <= 2, '框图没被拆成碎块（<=2）', '实际 %d' % st['diagram_blocks'])
        ok(st['table_blocks'] >= 1, '表格块 >= 1', '实际 %d' % st['table_blocks'])
        ok(st['scanned_pages'] >= 1, '扫描页被识别', '实际 %d' % st['scanned_pages'])

        # 扫描页必须切成多条带（整页一块 → 缩到模型输入尺寸后小字必糊）
        scanp = [p for p in m['pages'] if p['scanned']]
        ok(all(len(p['blocks']) >= 2 for p in scanp), '扫描页切成多条带',
           '块数 %s' % [len(p['blocks']) for p in scanp])

        sus = [b for p in m['pages'] for b in p['blocks'] if b.get('suspect')]
        ok(len(sus) >= 1, '「丢了上标」的 x2 被标 suspect',
           'suspect 块 %d' % len(sus))

        # 框图必须带裁剪图
        dg = [b for p in m['pages'] for b in p['blocks'] if b['type'] == 'diagram']
        ok(all(b.get('crop') for b in dg), '框图都导出了高清裁剪图')

        # 含全角运算符（｜＋＜）的题干必须强制看图 —— 真实教辅实测过：
        # 不标的话会拿着「｜a 3｜」这种残句去批改。
        op_blk = [b for p in m['pages'] for b in p['blocks']
                  if any(c in b['text'] for c in '｜＋＜＞＝−')]
        ok(bool(op_blk) and all(b['need_vision'] for b in op_blk),
           '含全角运算符的题干被强制标 need_vision',
           '%d 块，其中 %d 块未标' % (len(op_blk),
                                    sum(1 for b in op_blk if not b['need_vision'])))

        # 本地 OCR 通道：已部署就必须有产出（未部署则跳过，不算失败）
        import ingest_source as _IS
        if _IS.local_ocr_python():
            ob = [b for p in m['pages'] for b in p['blocks'] if b.get('ocr_text')]
            ok(len(ob) >= 1, '本地OCR给出文字基准',
               '实际 %d 块（stats=%s）' % (len(ob), st.get('ocr_blocks')))
            ok(all(0.0 <= b.get('ocr_conf', -1) <= 1.0 for b in ob),
               'OCR置信度在 0~1 之间')
        else:
            print('  .. 本地OCR未部署，跳过 OCR 通道检查')

        # 夸克手写通道：配置了就必须被调用（真实手写只有它能读出来）
        if _IS.quark_available():
            qp = [p for p in m['pages'] if p.get('quark')]
            ok(bool(qp), '夸克通道被调用（扫描页）', '%d 页' % len(qp))
            ok(all('degraded' in p['quark'] for p in qp),
               '夸克结果含 degraded 降级标记')
        else:
            print('  .. 夸克未配置，跳过手写通道检查')

        # 批注检测（单元级，不烧 API 额度）：有文本层但含红笔批改也要走夸克，
        # 否则老师改过的卷子会被当成「没写答案」
        import pymupdf as _pm
        adoc = _pm.open()
        ap = adoc.new_page()
        ap.insert_text((60, 80), "题目", fontname="china-s", fontsize=12)
        for y in (100, 112, 124):
            ap.draw_line((60, y), (220, y), color=(0.9, 0.1, 0.1), width=2)
        ev = _IS.annotation_signal(ap)
        ok(bool(ev), '红笔批注被检测到', str(ev))
        adoc.close()

        cdoc = _pm.open()
        cp = cdoc.new_page()
        cp.insert_text((60, 80), "干净题目", fontname="china-s", fontsize=12)
        cp.draw_line((60, 100), (200, 100), color=(0, 0, 0), width=1)
        ok(not _IS.annotation_signal(cp), '干净页不误报批注')
        cdoc.close()

        # ---------- 文本层乱序修复（单元级）----------
        print('\n[1.5] 文本层乱序修复（regroup_block）')
        import ingest_source as IS

        def _blk(lines):
            return {'lines': [{'spans': [{'size': 12.0, 'chars': [
                {'origin': (x, y), 'c': c} for x, y, c in ln]}]} for ln in lines]}

        # 同一视觉行被 PDF 拆成两个 line：｜a␣ / −b｜  ← 真实的残句形态
        fake = _blk([[(100.0, 50.0, '｜'), (112.0, 50.0, 'a'), (120.0, 50.0, ' ')],
                     [(126.0, 50.2, '−'), (133.0, 50.0, 'b'), (140.0, 50.0, '｜')]])
        fixed, rep = IS.regroup_block(fake)
        ok(fixed.strip() == '｜a−b｜', '乱序被按坐标重排还原', '得到 %r' % fixed)
        ok(rep, '重排被记为 layout_repaired')

        # 语序错乱：line 顺序是 化：｜ / 简，坐标顺序才是 化简：｜
        fake2 = _blk([[(100.0, 60.0, '化'), (124.0, 60.0, '：'), (136.0, 60.0, '｜')],
                      [(112.0, 60.0, '简')]])
        fixed2, _ = IS.regroup_block(fake2)
        ok(fixed2 == '化简：｜', '汉字被符号隔开能按坐标还原', '得到 %r' % fixed2)

        # 正常块不能被误判成乱序（否则每块都强制看图，标记失去意义）
        plain = _blk([[(100.0, 70.0, '绝'), (112.0, 70.0, '对'),
                       (124.0, 70.0, '值')]])
        t2, rep2 = IS.regroup_block(plain)
        ok(t2 == '绝对值' and not rep2, '正常文字块不误判为乱序',
           '得到 %r rep=%s' % (t2, rep2))

        # ---------- docx ----------
        print('\n[2] docx 路径（pandoc）')
        dx = os.path.join(tmp, 'sample.docx')
        make_docx(dx)
        m2 = run_ingest(dx, os.path.join(tmp, 'docx_out'))
        st2 = m2['stats']
        ok(st2['formula_blocks'] >= 2, '公式块 >= 2', '实际 %d' % st2['formula_blocks'])
        ok(st2['table_blocks'] >= 1, 'docx 表格解析出块', '实际 %d' % st2['table_blocks'])

        tbl = [b for p in m2['pages'] for b in p['blocks'] if b['type'] == 'table']
        rows = tbl[0]['rows'] if tbl else []
        ok(len(rows) >= 3, 'docx 表格含表头+数据行（>=3）', '实际 %d 行' % len(rows))

        alltxt = ' '.join(b['text'] for p in m2['pages'] for b in p['blocks'])
        ok(r'\frac{1}{2}' in alltxt, 'docx 分式保留为 LaTeX')
        ok('x^{2}' in alltxt, 'docx 上标保留为 LaTeX')

        # ---------- 公式落地 ----------
        print('\n[3] 公式落地（MathML + OMML）')
        good, total = formulas_ok(m2)
        ok(total > 0 and good == total, 'docx 公式全部落地', '%d/%d' % (good, total))

        from latex_math import self_test
        print('\n[4] latex_math 内置用例')
        import io
        buf = io.StringIO()
        old, sys.stdout = sys.stdout, buf
        passed = self_test(verbose=False)
        sys.stdout = old
        ok(passed, 'latex_math 12 例自检', buf.getvalue().splitlines()[-1] if buf.getvalue() else '')

        # ---------- 汇总 ----------
        print('\n' + '=' * 46)
        if FAILS:
            print('❌ %d 项未通过：%s' % (len(FAILS), '、'.join(FAILS)))
            return 1
        print('✅ 全部通过')
        return 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == '__main__':
    sys.exit(main())
