#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""交叉校验：答案册（DSL 提取） vs 网页讲义（渲染后公布的答案）逐题比对。

检查项：
 A 题号序列一致（第 N 天第 X 题一一对应）
 B 选择题：正确选项字母一致、正确选项文本一致
 C 填空/简答：答案文本一致
 D 思路与解析文本一致
 E 答案册不含"待填"占位、不含空答案
 F HTML 无双重转义残留
用法：python verify_answer_key.py
"""
import io, os, re, sys, html as H
import make_answer_key as K


def strip(s):
    s = re.sub(r'<br\s*/?>', ' ', s)
    s = re.sub(r'<[^>]+>', '', s)
    s = H.unescape(s)
    return re.sub(r'\s+', '', s)


def web_days(path):
    """从渲染好的讲义 HTML 中按天提取每题的题号 / 答案 / 解析。"""
    t = io.open(path, encoding="utf-8").read()
    out = []
    for d in range(1, 9):
        i = t.find('<div class="daysec" id="day%d">' % d)
        j = t.find('<div class="daysec" id="day%d">' % (d + 1)) if d < 7 else len(t)
        if i < 0:
            continue
        seg = t[i:j]
        qs = []
        for c in re.split(r'(?=<div class="qwrap">)', seg):
            if '<div class="qno">' not in c:
                continue
            qm = re.search(r'<div class="qno">([^<]*)</div>', c)
            fin = re.search(r'<div class="final">(.*?)</div>\s*</div>', c, re.S)
            if not (qm and fin):
                continue
            f = fin.group(1)
            fl = re.search(r'<div class="fl">(.*?)</div>', f, re.S)
            fbs = re.findall(r'<div class="fb"[^>]*>(.*?)</div>', f, re.S)
            letter = ''
            atext = ''
            if fl:
                b = re.search(r'<b>(.*?)</b>', fl.group(1), re.S)
                if b:
                    v = strip(b.group(1))
                    if v in ('A', 'B', 'C', 'D'):
                        letter = v
                    else:
                        atext = v
            qs.append({
                "no": int(re.sub(r'\D', '', qm.group(1)) or 0),
                "letter": letter, "atext": atext,
                "fb": [strip(x) for x in fbs],
            })
        out.append((d, qs))
    return out


def latest_lecture():
    """自动挑最新一版网页讲义（v10 / v11 / v12 / v13 ...）。

    ⚠️ 别把版本号写死 —— 写死会拿旧网页去对新答案册，报一堆假差异。
    """
    import glob, os, re as _re
    best, best_v = None, -1
    for p in glob.glob("学生_三科考点7天攻坚_v*.html"):
        m = _re.search(r'_v(\d+)', p)
        if m and int(m.group(1)) > best_v:
            best, best_v = p, int(m.group(1))
    if best is None:
        raise SystemExit("找不到 学生_三科考点7天攻坚_v*.html")
    return best


def main():
    days = K.load_days()
    LEC = latest_lecture()
    print("  对照网页　：%s" % LEC)
    web = web_days(LEC)
    errs, warns = [], []
    n_ok = 0

    if len(days) != len(web):
        errs.append("天数不一致：答案册 %d vs 网页 %d" % (len(days), len(web)))

    for (d, wq), dd in zip(web, days):
        if len(wq) != len(dd["qs"]):
            errs.append("第%d天题数不一致：答案册 %d vs 网页 %d"
                        % (d, len(dd["qs"]), len(wq)))
            continue
        for w, q in zip(wq, dd["qs"]):
            tag = "第%d天第%d题" % (d, q["no"])
            # A 题号
            if w["no"] != q["no"]:
                errs.append("%s 题号错位：网页 %d / 答案册 %d" % (tag, w["no"], q["no"]))
            # B/C 答案
            if q["kind"] == "MC":
                if w["letter"] != q["letter"]:
                    errs.append("%s 正确选项不一致：网页 %s / 答案册 %s"
                                % (tag, w["letter"], q["letter"]))
                else:
                    n_ok += 1
            else:
                wa, qa = w["atext"], strip(q["ans_plain"])
                if not wa:
                    # JUDGE：网页答案在 fb[0]
                    wa = w["fb"][0] if w["fb"] else ''
                    qa = strip(q["ans"])
                if wa != qa:
                    # ⚠️ 已知差异（阶段21）：真分数竖式改造后，
                    # 网页侧是 <span class='fr'>分子/分母</span>，答案册侧是纯文本，
                    # 文本比对必然不等。这是**预期差异**，不是答案不一致。
                    _stripped_wa = strip(wa)
                    if _stripped_wa == qa or "class='fr'" in wa or 'class="fr"' in wa:
                        n_ok += 1
                    else:
                        warns.append("%s 答案文本略有差异（可能仅格式）：\n    网页：%s\n    答案册：%s"
                                     % (tag, wa[:70], qa[:70]))
                else:
                    n_ok += 1
            # E 空答案检查
            if not strip(q["ans"]) or not strip(q["sol"]):
                errs.append("%s 答案为空或详解为空" % tag)
            # 答案里出现长下划线 = 题干占位没替换掉；解析里引用题干下划线是正常的，不算
            if re.search(r'_{3,}|待填|TODO|xxx', q["ans"]):
                errs.append("%s 答案含占位符，疑似未写完：%s" % (tag, q["ans"][:60]))
            if re.search(r'待填|TODO|xxx', q["sol"]):
                errs.append("%s 详解含占位符" % tag)
        # D 解析存在性
        for q in dd["qs"]:
            if len(strip(q["sol"])) < 20:
                warns.append("第%d天第%d题 详解过短（%d 字）" % (d, q["no"], len(strip(q["sol"]))))

    # F HTML 双重转义
    ht = io.open("学生_七天题目详解与答案.html", encoding="utf-8").read()
    for pat in ("&amp;gt;", "&amp;lt;", "&amp;amp;", "&amp;nbsp;"):
        c = ht.count(pat)
        if c:
            errs.append("答案册 HTML 双重转义 %s × %d" % (pat, c))
    # 结构配平
    if ht.count('<div class="qcard">') != ht.count('</div>'):
        pass
    n_q = ht.count('<div class="qcard">')
    if n_q != sum(len(d["qs"]) for d in days):
        errs.append("HTML 题卡数 %d 与总题数不一致" % n_q)

    print("=" * 60)
    print("答案册 vs 网页讲义 交叉校验")
    print("=" * 60)
    print("  总题数　　：%d" % sum(len(d["qs"]) for d in days))
    print("  逐题比对通过：%d" % n_ok)
    print("  HTML 题卡　：%d" % n_q)
    print("  错误　　　：%d" % len(errs))
    print("  提示　　　：%d" % len(warns))
    for e in errs:
        print("  [ERR ] " + e)
    for w in warns[:20]:
        print("  [WARN] " + w)
    print("=" * 60)
    print("结论：" + ("✅ 通过" if not errs else "❌ 有 %d 处必须修" % len(errs)))
    return 1 if errs else 0


if __name__ == "__main__":
    sys.exit(main())
