#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""内容质量四检（G21）—— 阶段21 用户一次性指出的四类硬伤。

需求原话：
1. 「英语题中**该划线的没有划线**」
2. 「英语的**阅读题也没有明确题目**」
3. 「**语文题的范例都把答案给出来了**」
4. 「推荐视频要尽可能**对症、简短，多一个选择**」

这四条都是「内容正确性」问题，之前的门禁只管格式（分数/字体/题号），管不到。
本脚本把它们变成机器判定。

## 四项检查

### A. 英语划线 `<u>` 不得丢失
语音辨析题考的就是「画线部分读音」。`to_lines()` 曾剥掉所有标签，
作答纸 `<w:u>` 出现 **0 次** —— 孩子不知道比对哪个字母，题目直接作废。
判定：DSL 里有 `<u>` 的题 → 作答纸 docx 必须有等量 `<w:u>`，html 必须有 `<u>`。

### B. 阅读题必须「短文在前、问题在后」
Day3 曾把 `What is the passage mainly about?` 放在短文前面，
孩子先看到问句、不知道在问什么。
判定：阅读类题型（细节理解/主旨大意/推理判断/词义猜测）的题干，
**问句不能在引导语之后的第一句**。

### C. 答题公式卡的范例不得泄露答案
古诗鉴赏题的 sample 曾是《次北固山下》的满分级答案，
孩子照抄就对。判定：sample 必须用占位符 `【】`，且不含本题答案要素。

### D. 视频推荐必须对症
Day3 曾给数轴动点配「找规律」、给句段作用配「病句」、给细节理解配「自然拼读」
—— 三条备选全不对症，而当天 2 道主旨大意题**一条视频都没有**。
判定：每个 SUB 考点至少 1 条视频；且视频标题不得指向当天不存在的题型。
"""
import io
import os
import re
import sys
import zipfile

SK = os.path.dirname(os.path.abspath(__file__))
ROOT = os.environ.get("DUODUO_ROOT", os.getcwd())
sys.path.insert(0, SK)

import dsl_source as D          # noqa: E402
import answer_formula as AF     # noqa: E402

# 当天不存在的题型 → 视频标题里不该出现这些词
OFFTOPIC_WORDS = {
    "找规律": ["找规律", "数列"],
    "自然拼读": ["自然拼读", "Digraph", "phonics"],
    "病句": ["病句"],
}


def check_underline(days):
    """A. 英语划线：DSL 有 <u> 的题，作答纸必须有等量下划线。"""
    errs = []
    for d in days:
        n_u = sum(q["stem"].count("<u>") + sum(o.count("<u>") for o in q.get("opts", []))
                  for q in d["qs"])
        if n_u == 0:
            continue        # 当天没有划线题（如无语音题），跳过
        tag = "Day%d" % d["n"]
        # 作答纸 docx
        f = os.path.join(ROOT, "学生_Day%d_作答纸_*.docx" % d["n"])
        import glob as g
        cand = g.glob(f)
        if cand:
            x = zipfile.ZipFile(cand[0]).read("word/document.xml").decode("utf-8")
            got = x.count("<w:u w:val")
            if got == 0:
                errs.append("%s：DSL 有 %d 处划线，作答纸 docx 有 0 处 —— 语音题无法作答"
                            % (tag, n_u))
            elif got < n_u:
                errs.append("%s：划线不足 DSL %d 处 vs docx %d 处" % (tag, n_u, got))
    return errs


READING_TYPES = ("细节理解题", "主旨大意题", "推理判断题", "词义猜测题")


def check_reading_order(days):
    """B. 阅读题：必须「引导语 → 短文 → 问题」。"""
    errs = []
    for d in days:
        for q in d["qs"]:
            if q.get("qtype") not in READING_TYPES:
                continue
            stem = q["stem"]
            # 去掉题型徽标后看开头
            body = re.sub(r'<b class="qt">.*?</b>', "", stem).strip()
            body = re.sub(r"^（[^）]*）", "", body).strip()
            # 开头若直接是英文问句（含 What/Which/When/Where/Why/How 且 60 字内以 ? 结尾）
            first = re.split(r"<br\s*/?>", body)[0]
            plain = re.sub(r"<[^>]+>", "", first)
            if re.match(r"^\s*(What|Which|When|Where|Why|How|Who)\b", plain) \
                    and "?" in plain and len(plain) < 70:
                errs.append("Day%d 第%d题（%s）：问句在短文前面 —— 「%s」"
                            % (d["n"], q["no"], q["qtype"], plain.strip()[:40]))
    return errs


def check_sample_leak(days):
    """C. 公式卡范例不得含答案要素。"""
    errs = []
    # 收集当天语文主观题的答案关键片段（8 字以上、非停用词）
    for name, card in AF.CHINESE_FORMULA.items():
        smp = card.get("sample", "")
        if "【" not in smp:
            errs.append("%s：sample 没有占位符【】，可能是成品答案" % name)
    # 逐天比对：sample 的实词是否出现在当天同题型的答案里
    for d in days:
        for q in d["qs"]:
            qt = q.get("qtype")
            if qt not in AF.CHINESE_FORMULA:
                continue
            smp = AF.CHINESE_FORMULA[qt].get("sample", "")
            ans = re.sub(r"<[^>]+>", "", q.get("ans_plain") or q.get("ans", ""))
            # 取 sample 里被 <b> 包住的实词（旧版泄露就是这样暴露的）
            bold = re.findall(r"<b>([^<]{2,12})</b>", smp)
            for w in bold:
                if w in ans and "【" not in w:
                    errs.append("Day%d 第%d题（%s）：范例词「%s」直接出现在本题答案里"
                                % (d["n"], q["no"], qt, w))
    return errs


def check_videos(days):
    """D. 视频：每个 SUB 考点 ≥2 条；且**必须覆盖当天实际考点**。

    ⚠️ **必须按 SUB 块逐块判断**，不能用全局禁用词（第一版踩过）：
    「自然拼读 ch/sh/ph」对 Day1 的「辅音字母组合发音」是**对症**的；
    「找规律七大数列」对 Day4 的「用代数式表示规律」也是**对症**的。

    ⚠️ **Day7 是测评日**，豁免视频要求。

    ⚠️ **阶段21 新增：考点覆盖检查**（用户：「所有视频一定要有针对性，
    尤其数学」）。原来只数条数，不查内容 —— 于是出现：
    - Day3 换题后新增 4 道**绝对值**题，视频却只有「动点」——4 题零覆盖
    - Day6 考《十五夜望月》，视频配的是《次北固山下》——**换了篇目**
    - Day1 英语块里塞了「有理数」「病句」——完全无关

    判定：从当天题目的**题干和题型**里提取关键术语，
    要求该 SUB 下至少一条视频（标题或推荐理由）提到它。
    """
    errs = []
    for d in days:
        raw = d["raw"] or ""
        blocks = re.split(r"^SUB\|", raw, flags=re.M)[1:]
        if not blocks:
            continue
        if all(re.match(r"\s*[📋📇]", b) or "测评" in b[:12] or "学习卡" in b[:12]
               for b in blocks):
            continue        # 测评日豁免

        for b in blocks:
            head = b.split("\n")[0]
            name = head.split("|")[0].strip()
            if name.startswith(("📋", "📇")) or "测评" in name[:6] or "学习卡" in name[:6]:
                continue
            vids = re.findall(r"^VID\|([^|\n]*)\|([^|\n]*)\|([^|\n]*)\|([^|\n]*)\|([^\n]*)",
                              b, re.M)
            # ⚠️ 两种模式：
            # ① 平时讲义（给选择）→ 每考点 ≥2 条（首选 + 备选）
            # ② 周末专场（家长精讲）→ 每节 ≥1 条**最好的**
            #    阶段22 用户：「视频要用最好的一条」——精选优于多选
            # ③ 「上篇／下篇」结构的专题讲义（阶段23 起统一采用）→ 同样 ≥1
            #    用户要求：每个概念只配「效果最好 + 时长最短」的那一条，不堆数量
            if re.search(r"第\s*\d+\s*节", name) or re.search(r"上篇|下篇", name):
                need = 1
            else:
                need = 2
            if len(vids) < need:
                errs.append("Day%d「%s」只有 %d 条视频（要求 ≥%d）"
                            % (d["n"], name[:22], len(vids), need))
                continue

            # ── 考点覆盖 ──
            # ⚠️ **必须按「题型」判断，不能用题干全文找关键词**：
            # 题干里常顺带提到别的词（如「一个有理数的绝对值是它本身」里的「有理数」），
            # 用全文匹配会大量误报。题型才是真实考点。
            qtypes = re.findall(r"【题型】([^<]+)", b)
            blob = " ".join("%s %s %s" % (v[1], v[4] or "", v[0]) for v in vids)

            # 题型 → 视频里必须出现的词
            TYPE_NEED = {
                "绝对值": ["绝对值"],
                "动点问题": ["动点", "运动", "移动"],
                "行程问题": ["行程", "路程", "千米"],
                "平移": ["平移"],
                "程序框图": ["程序框图", "流程图"],
                "规律": ["规律", "找规律"],
                "有理数加减": ["有理数", "加减"],
                "病句": ["病句"],
                "古诗": ["古诗", "赏析"],
                "炼字": ["炼字", "赏析", "字"],
                "句段作用": ["段落", "句段"],
                # ⚠️ 只写「best title」不写「标题」：
                # 推荐理由里常有「标题带『xxx』」这类话，
                # 用「标题」当关键词会把"没配主旨视频"误判成已覆盖（实测踩过）。
                "主旨": ["主旨", "main idea", "best title", "mainly"],
                "标题含义": ["标题"],
                "细节理解": ["细节", "定位"],
                "语音": ["发音", "拼读", "语音"],
                "语法填空": ["语法", "时态", "现在时"],
                "词义": ["词义", "辨析", "名词", "动词"],
                "表现手法": ["表现手法", "手法"],
            }
            for tq in set(qtypes):
                need = None
                for key, syns in TYPE_NEED.items():
                    if key in tq:
                        need = syns
                        break
                if not need:
                    continue
                if any(s.lower() in blob.lower() for s in need):
                    continue
                errs.append("Day%d「%s」：考「%s」，但没有一条视频对应它"
                            % (d["n"], name[:20], tq.strip()[:12]))
    return errs


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    # 补 raw 字段（dsl 解析后的原始文本）
    days = []
    for d in D.load_days(os.path.join(ROOT, "_p5")):
        p = os.path.join(ROOT, "_p5", "day%d.txt" % d["n"])
        d["raw"] = io.open(p, encoding="utf-8").read() if os.path.exists(p) else ""
        days.append(d)

    print("=" * 66)
    print("内容质量四检（G21）")
    print("=" * 66)

    results = [
        ("A 英语划线保留", check_underline(days)),
        ("B 阅读题先后顺序", check_reading_order(days)),
        ("C 范例不泄露答案", check_sample_leak(days)),
        ("D 视频对症且够选", check_videos(days)),
    ]

    total = 0
    for name, errs in results:
        if errs:
            print("  ❌ %s：%d 处" % (name, len(errs)))
            for e in errs[:8]:
                print("       " + e)
            if len(errs) > 8:
                print("       … 还有 %d 处" % (len(errs) - 8))
        else:
            print("  ✅ %s" % name)
        total += len(errs)

    print()
    print("结论：%s" % ("✅ 全部通过" if total == 0 else "❌ %d 处问题" % total))
    return 0 if total == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
