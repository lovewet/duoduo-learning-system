#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""一键管线 build.py：改完 DSL 之后，一条命令出全部产物。

原来要手工跑 6 步（渲染 ×7 → 拼页 → patch_head → verify_lecture → make_answer_docx
→ make_answer_key），漏一步就出事（本轮就漏过 patch_head）。现在串成一条。

    python build.py            # 全量
    python build.py --no-key   # 跳过答案册

产物：网页讲义 v*.html / 作答纸 docx+html / 答案册 docx+html
"""
import io, os, re, sys, glob, subprocess, datetime

ROOT = os.path.dirname(os.path.abspath(__file__))
SK = r"<SKILL_DIR>\scripts"
PY = sys.executable
SRC, MID = "_p5", "_p6"


def run(script, *args):
    p = os.path.join(SK, script)
    print("\n▶ %s %s" % (script, " ".join(args)))
    r = subprocess.run([PY, p] + list(args), cwd=ROOT,
                       capture_output=True, text=True, encoding="utf-8")
    out = (r.stdout or "") + (r.stderr or "")
    for ln in out.strip().splitlines():
        print("   " + ln)
    if r.returncode != 0:
        raise SystemExit("❌ %s 失败（退出码 %d）" % (script, r.returncode))
    return out


def next_version():
    """从已有产物推断下一个版本号 v14 / v15 …（避免用时间戳把目录堆满）。"""
    mx = 13
    for p in glob.glob(os.path.join(ROOT, "学生_三科考点7天攻坚_v*.html")):
        m = re.search(r'_v(\d+)\.html$', p)
        if m:
            mx = max(mx, int(m.group(1)))
    return "v%d" % (mx + 1)


def main():
    ver = next_version()
    # 1. 渲染七天
    for i in range(1, 9):
        run("lecture_dsl.py", os.path.join(SRC, "day%d.txt" % i),
            os.path.join(MID, "day%d.html" % i), "d%d" % i)
    # 2. 同步页头（print.css / print.js.html → 00_head.html）
    run("patch_head.py")
    # 3. 拼装网页
    parts = [("_p6", "00_head.html")] + [("_p6", "day%d.html" % i) for i in range(1, 9)] \
            + [("_p6", "zz_tail_seven.html")]   # 合集用带「7 天打卡表」的 tail
    h = "\n".join(io.open(os.path.join(*p), encoding="utf-8").read() for p in parts)
    out_html = os.path.join(ROOT, "学生_三科考点7天攻坚_%s.html" % ver)
    io.open(out_html, "w", encoding="utf-8", newline="\n").write(h)
    print("\n▶ 拼装网页：%s（%.0f KB）" % (os.path.basename(out_html), len(h.encode()) / 1024))
    # 4. 校验（讲义）
    run("verify_lecture.py", os.path.basename(out_html))
    # 5. 作答纸 docx + html
    run("make_answer_docx.py", "学生_七天作答纸合集.docx")
    run("make_answer_html.py", "学生_七天作答纸合集.html")
    # 6. 答案册
    if "--no-key" not in sys.argv:
        run("make_answer_key.py")
    # 7. 答案册交叉校验（自动取最新版网页）
    run("verify_answer_key.py")
    # 8. 导出 CSV + 上云包
    run("export_csv.py")
    print("\n✅ 全流程完成")
    for f in sorted(glob.glob("学生_*.docx") + [os.path.basename(out_html)]):
        print("   %-40s %.1f KB" % (f, os.path.getsize(f) / 1024))


if __name__ == "__main__":
    main()
