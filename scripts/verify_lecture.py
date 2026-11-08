#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""讲义出厂校验：符号 / 选项 / 答案 / 结构 四类检查。
用法：python verify.py 讲义.html
"""
import io, re, sys, html

def load(p):
    return io.open(p, encoding="utf-8", newline="").read()

def main(path):
    t = load(path)
    errs, warns = [], []

    # ---------- 1. 双重转义 ----------
    for bad, label in [("&amp;gt;", ">"), ("&amp;lt;", "<"), ("&amp;amp;", "&"), ("&amp;nbsp;", "空格")]:
        n = t.count(bad)
        if n:
            errs.append(f"[符号] 双重转义 {bad} ×{n}（应显示为 {label}，现在会显示成 &amp;{label[1:]}）")

    # ---------- 2. 全是实体的怪写法 ----------
    n = len(re.findall(r"&gt;\s*\?", t))
    if n: errs.append(f"[符号] 「&gt; ?」异常 {n} 处")

    # ---------- 3. 逐题检查 ----------
    qts = re.findall(r'<div class="qt" id="([^"]+)">(.*?)\n</div>', t, re.S)
    if not qts:
        qts = [(f"q{i}", b) for i, b in enumerate(re.findall(r'<div class="qt" id="([^"]+)">(.*?)</div>\s*</div>', t, re.S))]
    mc_cnt = choice_cnt = 0
    for qid, body in qts:
        stem = re.search(r'<div class="stem">(.*?)</div>', body, re.S)
        stem_txt = html.unescape(re.sub(r"<[^>]+>", "", stem.group(1))).strip() if stem else ""
        if not stem_txt:
            errs.append(f"[题目] {qid} 题干为空")
            continue
        if re.search(r"&amp;(gt|lt|amp);", stem_txt):
            errs.append(f"[符号] {qid} 题干含双重转义")

        # 只有 "opts"（不带 row2）才是真正的选择题选项；row2 是填空/简答的自评按钮
        opts = re.findall(r'<div class="opts">(.*?)</div>', body, re.S)
        if opts:
            choice_cnt += 1
            opts = re.findall(r'<span class="ot">(.*?)</span>', "".join(opts), re.S)
            allt = [html.unescape(re.sub(r"<[^>]+>", "", o)).strip() for o in opts]
            # 两段式判分：try1 与 try2 各渲染一遍选项，正常是 2 的倍数
            if len(allt) % 2 == 0:
                half = len(allt) // 2
                first, second = allt[:half], allt[half:]
                if first != second:
                    errs.append(f"[选项] {qid} 第一次/第二次作答的选项不一致")
                texts = first
            else:
                texts = allt
                errs.append(f"[选项] {qid} 选项数量异常（{len(allt)} 个，不应为奇数）")
            if len(texts) not in (3, 4):
                errs.append(f"[选项] {qid} 选项数 {len(texts)} 个（应为 3 或 4）")
            for i, x in enumerate(texts):
                if not x:
                    errs.append(f"[选项] {qid} 第 {'ABCD'[i]} 项为空")
                if re.search(r"&amp;(gt|lt|amp);", x):
                    errs.append(f"[符号] {qid} 选项 {'ABCD'[i]} 含双重转义：{x[:30]}")
                if re.search(r"&(gt|lt);", x) and "&amp;" not in x:
                    warns.append(f"[符号] {qid} 选项 {'ABCD'[i]} 含裸实体：{x[:30]}")
            if len(set(texts)) != len(texts):
                dup = [x for x in set(texts) if texts.count(x) > 1]
                errs.append(f"[选项] {qid} 有重复选项：{dup}")

            # 【G13 划线一致性】语音题的「划线部分」必须四个选项划在**同一音素**上。
            # 反例（阶段20 实测踩坑）：Day1 第8题考 th 清浊，却把线划在 i/a/i/e 上；
            # Day2 第7题考 ur，surprised 却划在 i 上 —— 孩子即使做对也说不清为什么。
            if "划线" in body or "画线" in body:
                # 注意 texts 是**已剥标签**的纯文本，<u> 必须从未剥的 opts 取
                raw = opts[:len(texts)]
                us = [(re.findall(r"<u>(.*?)</u>", x) or [""]) for x in raw]
                got = [u[0] if u else "" for u in us]
                if not all(got):
                    errs.append(f"[划线] {qid} 语音题有选项缺划线：{[ ( 'ABCD'[i], g) for i,g in enumerate(got) if not g]}")
                elif len(set(got)) > 1:
                    errs.append(f"[划线] {qid} 语音题四个选项划线不一致：{got} —— "
                                f"必须全部划在同一个音素上（如 th / ch / ur）")

            ans = re.search(r'正确答案：<b>([A-D])</b>', body)
            if ans:
                mc_cnt += 1
                letter = ans.group(1)
                idx = "ABCD".index(letter)
                if idx >= len(texts):
                    errs.append(f"[答案] {qid} 答案 {letter} 超出选项范围")

        # 答案/解析非空
        if 'class="final"' in body:
            fb = re.search(r'<div class="fb">(.*?)</div>', body, re.S)
            if not fb or len(re.sub(r"<[^>]+>", "", fb.group(1)).strip()) < 5:
                errs.append(f"[解析] {qid} 解析为空或过短")

    # ---------- 4. SVG 检查 ----------
    svgs = re.findall(r"<svg\b.*?</svg>", t, re.S)
    for i, s in enumerate(svgs, 1):
        if "&amp;" in s:
            errs.append(f"[框图] 第 {i} 张 SVG 内含 &amp;（双重转义）")
        if "<text" in s and "y &" in s and "&amp;" in s:
            errs.append(f"[框图] 第 {i} 张 SVG 的判条件转义异常")

    # ---------- 5. 结构 ----------
    body = re.sub(r"<style.*?</style>", "", t, flags=re.S)
    body = re.sub(r"<script.*?</script>", "", body, flags=re.S)
    d = 0
    for m in re.finditer(r"<div\b[^>]*>|</div>", body):
        d += -1 if m.group(0).startswith("</") else 1
    if d != 0:
        errs.append(f"[结构] div 未配平（深度 {d:+d}）")
    for tag in ["table", "tr", "td", "th", "aside", "main", "header", "footer",
                "textarea", "label", "u", "b", "strong", "span", "svg", "script", "style"]:
        o = len(re.findall(r"<%s\b" % tag, body))
        c = len(re.findall(r"</%s>" % tag, body))
        if o != c:
            errs.append(f"[结构] <{tag}> 开 {o} / 闭 {c}")
    ids = re.findall(r'\sid="([^"]+)"', body)
    dup = sorted({x for x in ids if ids.count(x) > 1})
    if dup:
        errs.append(f"[结构] 重复 id：{dup}")
    miss = [h for h in set(re.findall(r'href="#([^"]+)"', t)) if ('id="%s"' % h) not in t]
    if miss:
        errs.append(f"[结构] 死链锚点：{miss}")

    # ---------- 6. 敏感表述 ----------
    for kw in ["0 分三连", "每次都失", "你 0 分", "薄弱点"]:
        n = t.count(kw)
        if n:
            warns.append(f"[措辞] 仍含「{kw}」×{n}")

    # ---------- 报告 ----------
    print("=" * 64)
    print(f"讲义校验 · {path}")
    print("=" * 64)
    print(f"题目 {len(qts)} 道（选择题 {choice_cnt}，带答案 {mc_cnt}）｜SVG {len(svgs)} 张｜文件 {len(t)/1024:.0f} KB")
    print()
    if errs:
        print(f"❌ 发现 {len(errs)} 个必须修复的问题：")
        for e in errs: print("   " + e)
    else:
        print("✅ 未发现必须修复的问题")
    if warns:
        print(f"\n⚠️  {len(warns)} 个提示（不阻断，但建议查看）：")
        for w in warns[:15]: print("   " + w)
        if len(warns) > 15: print(f"   …… 另有 {len(warns)-15} 条")
    print()
    return 1 if errs else 0

if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "学生_三科考点7天攻坚_vN.html"))
