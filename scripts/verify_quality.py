#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""题目完整性审计（G22）—— 逐题查「能不能做」。

阶段21 用户：「除了第一二天的，其他都要检查完善」

内容四检（G21）管的是四类已知硬伤（划线/阅读顺序/范例泄露/视频）。
本脚本管**更基础的一件事：每道题是否具备可作答的最小条件**。

## 七项判定

| # | 判什么 | 为什么 |
|:--|:--|:--|
| 1 | 题干非空且 ≥8 字 | 空题干 = 废题 |
| 2 | 选择题恰好 4 个选项 | 少一个就没法四选一 |
| 3 | 选项长度相近（最长 ≤ 最短×4） | 长短悬殊 = 一眼看穿的假选项 |
| 4 | 答案索引 0–3 有效 | 索引越界 = 答案错位 |
| 5 | 答案非空 | 没答案无法批改 |
| 6 | 解析非空且 ≥20 字 | 没解析等于没讲 |
| 7 | 阅读类题必须有 30 字以上短文 | 「问主旨」却没短文，无法作答 |

> 只输出**明确的缺陷**，不做风格评价 —— 少报不误报。
"""
import io
import os
import re
import sys

SK = os.path.dirname(os.path.abspath(__file__))
ROOT = os.environ.get("DUODUO_ROOT", os.getcwd())
sys.path.insert(0, SK)
import dsl_source as D  # noqa: E402

READING = ("细节理解题", "主旨大意题", "推理判断题", "词义猜测题", "词义辨析题")

# 题库抽取时的**残留标记**，绝不能出现在孩子看的题面上。
# 阶段22 实测：Day3 第12/13 题短文开头带着「试题篮子」——
# 那是题库的版面标签，混进了题干。
DIRTY = ["试题篮子", "【答案】", "【解析】", "目录 CONTENTS", "出题人说",
         "试题来源", "第 X 页", "配图及选项OCR缺失"]


def plain(s):
    """去标签 + 反转义。

    ⚠️ 只能用 `<(字母或斜杠)` 识别真标签 —— 不能用 `<[^>]+>`。
    数学选项里有 `b < a < −a` 这类**未转义的比较号**，
    用 `<[^>]+>` 会把 `< a < −a ...` 当标签吃掉，选项长度算错
    （实测：Day2 第 2 题报「最短 2 字」的假警报）。
    """
    s = re.sub(r"<[a-zA-Z/][^>]*>", "", s or "")
    import html as H
    return H.unescape(s).strip()


def audit(days, only=None):
    errs = []
    for d in days:
        if only and d["n"] not in only:
            continue
        for q in d["qs"]:
            tag = "Day%d 第%d题（%s）" % (d["n"], q["no"], q.get("qtype") or q["kind"])
            stem = plain(q["stem"])
            opts = q.get("opts") or []
            ans = plain(q.get("ans_plain") or q.get("ans") or "")
            sol = plain(q.get("sol") or "")

            # 1 题干
            if len(stem) < 8:
                errs.append("%s：题干过短「%s」" % (tag, stem[:16]))
            # 2/3 选项
            if q["kind"] == "MC":
                if len(opts) != 4:
                    errs.append("%s：选项 %d 个（应 4 个）" % (tag, len(opts)))
                elif all(opts):
                    lens = [len(plain(o)) for o in opts]
                    lo, hi = min(lens), max(lens)
                    # ⚠️ 数学题的选项本来就是短数字（`-3` vs `-3.5`），
                    # 长短悬殊是正常的。**若最长选项 ≤6 字就跳过**，
                    # 否则会误报一堆正常数学题（实测 Day2/Day6 各报 1 处假警报）。
                    if hi > 6 and lo and hi > lo * 4:
                        errs.append("%s：选项长短悬殊（最短 %d / 最长 %d 字）"
                                    % (tag, lo, hi))
                # 4 答案索引
                idx = q.get("idx")
                if idx is not None and not (0 <= idx < len(opts)):
                    errs.append("%s：答案索引 %s 越界（选项 %d 个）"
                                % (tag, idx, len(opts)))
            # 5 答案
            if not ans:
                errs.append("%s：答案为空" % tag)
            # 6 解析
            if len(sol) < 20:
                errs.append("%s：解析过短（%d 字）「%s」" % (tag, len(sol), sol[:20]))
            # 7 题库残留标记（脏数据）
            for w in DIRTY:
                if w in q["stem"] or any(w in o for o in (q.get("opts") or [])):
                    errs.append("%s：题干/选项含题库残留「%s」" % (tag, w))

            # 8 阅读题必须有短文
            if q.get("qtype") in READING:
                # 短文 = 题干里第一个问句之前的部分
                body = re.sub(r'<b class="qt">.*?</b>', "", q["stem"])
                first_q = re.search(r"<b>\s*(?:What|Which|When|Where|Why|How|Who)\b",
                                    body)
                passage = plain(body[:first_q.start()] if first_q else body)
                passage = passage.replace("阅读下面短文，回答问题。", "")
                passage = re.sub(r"^（[^）]*）", "", passage).strip()
                if len(passage) < 30:
                    errs.append("%s：阅读类题但没有短文（正文仅 %d 字）"
                                % (tag, len(passage)))
    return errs


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    days = D.load_days(os.path.join(ROOT, "_p5"))
    print("=" * 66)
    print("题目完整性审计（G22）")
    print("=" * 66)
    for d in days:
        n = len(d["qs"])
        e = audit([d])
        print("  Day%d  %2d 题　%s" % (d["n"], n, "✅" if not e else "❌ %d 处" % len(e)))
        for x in e[:6]:
            print("       " + x)
        if len(e) > 6:
            print("       … 还有 %d 处" % (len(e) - 6))
    all_e = audit(days)
    print()
    print("结论：%s" % ("✅ 全部可作答" if not all_e else "❌ %d 处缺陷" % len(all_e)))
    return 0 if not all_e else 1


if __name__ == "__main__":
    sys.exit(main())
