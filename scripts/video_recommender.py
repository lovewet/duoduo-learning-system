#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""B 站学习视频推荐算法（duoduo-learning-system 配套模块 · v2.1）

把 阶段15 ~ 阶段30 期间形成的所有视频规则与踩坑收敛成一条可执行流水线：

  知识点/题目 → 关键词矩阵（含 UP 定向、难题定向）
      → 平台召回（搜索 API / 搜索页 / 412 退避）
      → 逐条 view 核实（真实标题·UP·时长·播放·分P）
      → 四维效果打分 × 质量门（讲原理优先于讲口诀）
      → 分级排序（命门课 > 首选 UP > 入门/原理/对位/专项，同级短的先看）
      → 覆盖度与对症审计 → 首选/备选 + 看哪一段 → DSL VID 行

分工：本模块是「一个知识点 / 一道难题」的即时入口；整套讲义的批量挂接走
scripts/bili_video_engine.py（--topics topics.json）。两者共用同一份护栏
references/video-guardrails.json，规则只有一处定义。

★ 铁律（完整台账见 references/video-recommendation.md）
  1. 绝不编造 BV 号；没过 view 接口核实的一律不给，只给 SEARCH: 精准词
  2. 数学优先指定 UP；他真没有，明写「暂无对应课，已核过全部投稿」，不拿别家顶替
  3. 每个考点的每个题型都要有视频；换题后必须重配；按「题型」判对症，不按题干全文
  4. 难题/压轴且无通用课的，走逐题定向检索；全站无对口课就如实说「只能靠讲」
  5. 好视频保留：★保留 / 实测有效（孩子能自己复述方法）下次直接推；淘汰要留原因
  6. 全局 BV 去重、年级不符不挂、超过 20 分钟标只看哪段、分 P 合集不猜 ?p=

只用标准库。无网络时 --selftest / --offline 可验证算法本身。

用法：
  python scripts/video_recommender.py --kp "绝对值最小值" --subject 数学 --grade 七年级
  python scripts/video_recommender.py --kp "折线数轴 变速动点" --subject 数学 --hard \
         --question "OB 段按方向变速，求停留时间" --topics "折线数轴,变速动点,双动点"
  python scripts/video_recommender.py --selftest
  python scripts/video_recommender.py --mark-effective BV1xxxxxxxxx --note "能自己复述方法"
"""
from __future__ import annotations

import argparse
import html
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

# --------------------------------------------------------------------------- #
# 平台接口与默认偏好
# --------------------------------------------------------------------------- #
SEARCH_API = ("https://api.bilibili.com/x/web-interface/search/type"
              "?search_type=video&keyword={kw}&page={page}")
SEARCH_PAGE = "https://search.bilibili.com/all?keyword={kw}"
VIEW_API = "https://api.bilibili.com/x/web-interface/view?bvid={bvid}"
WATCH_URL = "https://www.bilibili.com/video/{bvid}"
HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"),
    "Referer": "https://www.bilibili.com/",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "zh-CN,zh;q=0.9",
}
# 护栏「单一来源」：references/video-guardrails.json
# 汇总 阶段23 ~ 阶段30 全部 B 站要求与踩坑（全局 BV 去重、年级硬淘汰、
# 学科语境词、付费/下架/娱乐分区、★保留与 DROP 名单、各科指定 UP）。
# 本模块与批量引擎 scripts/bili_video_engine.py 共用这一份，避免两套规则打架。
GUARDRAILS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               "..", "references", "video-guardrails.json")


def load_guardrails(path: str | None = None) -> dict:
    try:
        with open(path or GUARDRAILS_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


GUARD = load_guardrails()

# 已核实课程目录（references/guojia-catalog.json）：B 站把 UP 名当普通词，
# 搜索前 20 条常召回不到 UP 本人 → 轻量入口也必须直连目录匹配，再逐条 view 复核。
# 路径写在护栏 preferred_catalog.file（单一事实源），与批量引擎 bili_video_engine.py 同源。
CATALOG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "..", "references",
                            (GUARD.get("preferred_catalog") or {}).get("file")
                            or "guojia-catalog.json")


def load_catalog(path: str | None = None) -> list[dict]:
    """读取已核实课程目录；读不到就返回空列表（不编造 BV 号）。"""
    try:
        with open(path or CATALOG_FILE, encoding="utf-8") as f:
            return json.load(f).get("videos") or []
    except (OSError, ValueError):
        return []


CATALOG: list[dict] = load_catalog()

REQUEST_INTERVAL = 1.3          # 秒；B 站 412 风控，宁慢勿错
RETRY = 4
# 阈值统一从护栏读（与批量引擎 bili_video_engine.py 同源，见 video-guardrails.json）
THRESHOLDS = GUARD.get("thresholds") or {}
# 护栏缺键 → 记下来 + 退回最后防线兜底值（自测会据此报错，不让兜底静默生效）
MISSING_THRESHOLDS: list[str] = []


def _threshold(key: str, default):
    """从护栏 thresholds 取阈值。

    单一事实源：护栏里有就用护栏的；缺键才退回兜底，并把缺键记进
    MISSING_THRESHOLDS（自测据此 FAIL，避免两套规则悄悄打架）。
    """
    if key in THRESHOLDS:
        return THRESHOLDS[key]
    MISSING_THRESHOLDS.append(key)
    return default


MAX_VERIFY = int(_threshold("max_verify_per_topic", 14))
UNIT_CAP = int(_threshold("unit_cap", 8))      # 单元视频上限，超出挤掉最弱的
MIN_PRIMARY = float(_threshold("min_primary", 58.0))
MIN_BACKUP = float(_threshold("min_backup", 50.0))  # 宁缺毋滥：泛课/长课不进备选
# 检索失败率上限：超过此比例判定「检索未完成」，不得当作「B 站真没这门课」
SEARCH_FAILURE_RATIO = float(_threshold("search_failure_ratio", 0.5))
ENTERTAINMENT_TIDS = set((GUARD.get("entertainment_tids") or {}).get("ids", []))
PAY_KEYS = (GUARD.get("pay_reject") or {}).get("keys", ["pay", "ugc_pay", "movie", "bp"])

# 各科指定 UP：护栏里每个学科可能有多个 UP（英语盖老师/平行世界、语文邵鑫/梓墨/豆伴匠）。
# 保留完整列表，评分时按 rank 最高者给首选加权 —— 原实现只取 lst[0]，其余全丢。
PREFERRED_UP_LIST: dict[str, list[dict]] = {
    s: list(ups or []) for s, ups in (GUARD.get("preferred_up") or {}).items()
}
PREFERRED_UP = {s: (ups[0].get("name", "") if ups else "")
                for s, ups in PREFERRED_UP_LIST.items()}
DEFAULT_UP = PREFERRED_UP.get("数学", "郭嘉老师数学思维")
PREFS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          "..", "data", "video_prefs.json")

V_RANK = {"首选UP": -1, "入门": 0, "原理": 1, "对位": 2, "专项": 3}
PRINCIPLE_WORDS = ("原理", "为什么", "推导", "理解", "几何意义", "本质", "思路",
                   "模型", "怎么来的", "讲透", "可视化", "动画", "由来", "证明")
ROTE_WORDS = ("口诀", "秒杀", "速记", "大招", "背会", "万能", "套路", "一招", "克星")
GENERIC_WORDS = ("全章", "串讲", "总复习", "合集", "完整版", "全套", "知识点汇总",
                 "一轮复习", "整本书", "大全", "一遍过", "最全")
INTRO_WORDS = ("套路", "三步", "基础", "入门", "必备", "概念", "怎么想", "地基")
SPECIAL_WORDS = ("串讲", "大全", "总复习", "合集", "全解析", "一遍过", "最全")
# 泛学科词（护栏单一事实源）：判定「对位」时不能算命中。
# 否则 kp="初一数学 绝对值" 对标题"初一数学 单调性 最值"会算出 kp_hit=4（全是泛词命中），
# 把不对症的课当首选输出。§8.7-9 明令要修。
GENERIC_TERMS = set((GUARD.get("generic_terms") or {}).get("terms") or ())
# 泛学科词派生的 2-gram 也必须过滤（阶段33 实测漏「一数/中数/中英/七年/年级/新定/定义」）。
# 例：kp="初一数学 绝对值" 里的「初一数学」被剔除后，它的 2-gram「一数」还在，
# 导致标题「初一数学 单调性 最值」被误判为对症（kp_hit=1）。
GENERIC_2GRAMS: set[str] = set()
for _g in GENERIC_TERMS:
    for _i in range(len(_g) - 1):
        _bg = _g[_i:_i + 2]
        if _bg not in GENERIC_TERMS:
            GENERIC_2GRAMS.add(_bg)
# 年级不符的内容不挂（防误捡）：命中即淘汰（与批量引擎口径一致）。
# 以护栏为准 —— 阶段30 修正：「中考」对七上语文阅读课同样适用，已改为软扣分而非硬淘汰。
OFF_GRADE_WORDS = tuple(GUARD.get("grade_reject_patterns") or (
    "八上", "八下", "九年级", "高考", "因式分解", "全等",
    "勾股", "将军饮马", "胡不归", "婆罗摩笈多", "不等式含参"))
SUBJECT_CONTEXT = GUARD.get("subject_context") or {}
TITLE_JUNK = tuple(GUARD.get("title_junk_patterns") or ())
IRRELEVANT = tuple(GUARD.get("irrelevant_patterns") or ())
GRADE_SOFT = ((GUARD.get("grade_soft_penalty_patterns") or {}).get("patterns") or ())
GRADE_SOFT_PENALTY = float((GUARD.get("grade_soft_penalty_patterns") or {}).get("penalty", -6))
# 互动维度权重：与批量引擎对齐（护栏 score_weights.engagement = 12）
ENGAGEMENT_WEIGHT = float((GUARD.get("score_weights") or {}).get("engagement", 12))
# 指定 UP 加权：rank 最高者给满权重，其余按 rank 递减（护栏 preferred_up.rank）
PREFERRED_UP_WEIGHTS = {-1: 8.0, 0: 6.0}
# 对症门禁 G21-D：当天不存在这些题型时，视频标题里不该出现
OFFTOPIC_WORDS = {
    "找规律": ["找规律", "数列"],
    "自然拼读": ["自然拼读", "Digraph", "phonics"],
    "病句": ["病句"],
}
MATH_NOISE = ("的", "与", "和", "及", "中", "了", "求", "题", "型")

# UP 简介区首行特征：「公众号：xxx」「@某某」「简介」等 —— 是 UP 的固定签名，
# 不是本条视频的内容，不能拿来判「年级不符」（见 _desc_body）。
_BIO_LINE = re.compile(r"^\s*(?:@|公众号|微信号|QQ群|粉丝群|简介|欢迎|领取|投稿)")


def _desc_body(desc: str) -> str:
    """剥掉简介开头的 UP 简介区，只留正文语境。

    UP 简介区形如「公众号：一数儿，免费分享学习资料~」「@一高数 学习高数」——
    那是 UP 主自己写的固定签名，跟本条视频讲什么无关。阶段33 实测 BV1KejH67E2G
    「2026初高衔接第一课！因式分解！方法串讲！」就是被简介里的「高数」误杀的
    （淘汰结果碰巧对，理由是巧合）。
    """
    lines = (desc or "").splitlines()
    i = 0
    while i < len(lines) and (not lines[i].strip() or _BIO_LINE.match(lines[i])):
        i += 1
    rest = [ln for ln in lines[i:] if not ln.strip().startswith("@")]
    return "\n".join(rest)


# 离线样例：仅用于验证打分/排序/兜底逻辑，不代表推荐结论
# like/coin/favorite 为离线互动样例（真实值只从 view API 取，这里用于自测互动维度）
SAMPLES = [
    {"bvid": "SAMPLE_A", "title": "绝对值最小值：几何意义与为什么取中点（讲透原理）",
     "author": DEFAULT_UP, "duration": "12:18", "play": 513000, "pages": 1,
     "like": 12000, "coin": 3400, "favorite": 5600,
     "desc": "从数轴距离讲清楚为什么是中间点取最小"},
    {"bvid": "SAMPLE_B", "title": "【初一】绝对值加和最小值，一次吃透全部题型",
     "author": "示例UP主B", "duration": "30:11", "play": 86000, "pages": 1,
     "like": 900, "coin": 180, "favorite": 700, "desc": "题型大全"},
    {"bvid": "SAMPLE_C", "title": "绝对值最小值 秒杀口诀 一招搞定",
     "author": "示例UP主C", "duration": "2:05", "play": 1200000, "pages": 1,
     "like": 3000, "coin": 600, "favorite": 900, "desc": "背口诀"},
    {"bvid": "SAMPLE_D", "title": "利用绝对值的几何意义，快速求最小值",
     "author": "示例UP主D", "duration": "14:53", "play": 272000, "pages": 1,
     "like": 4200, "coin": 900, "favorite": 1800, "desc": "几何意义推导"},
]


# --------------------------------------------------------------------------- #
# 偏好持久化：★保留 / 实测有效 / 淘汰留痕 / 命门课 / 指定 UP
# --------------------------------------------------------------------------- #
class Prefs:
    """本地偏好（不随仓库分发）。结构：
    {"preferred_up": {"数学": "..."}, "star": [], "verified": {bv: 一句效果},
     "drop": {bv: 原因}, "pin": {单元: [bv]}, "skip_title": {标题: 原因}}
    """

    def __init__(self, path: str | None = None, data: dict | None = None):
        self.path = path or PREFS_FILE
        self.data = data if data is not None else self._load()
        self.guard = GUARD
        self._apply_guard()

    def _apply_guard(self) -> None:
        """护栏里的全局名单无条件生效：DROP / ★保留 / 各科指定 UP。
        与个人偏好文件分开 —— 个人偏好可覆盖不了「已判错的 BV」。
        """
        self.data.setdefault("drop", {}).update(self.guard.get("drop") or {})
        star = self.data.setdefault("star", [])
        for bv in (self.guard.get("verified_good") or {}):
            if bv not in star:
                star.append(bv)
        # P1-3：保留该学科的完整指定 UP 列表（护栏 preferred_up）。
        # 原实现只取 lst[0]，英语「盖老师/平行世界」、语文「邵鑫/梓墨/豆伴匠」全丢。
        self.preferred_ups: dict[str, list[dict]] = {
            subj: [dict(u) for u in (lst or []) if u.get("name")]
            for subj, lst in (self.guard.get("preferred_up") or {}).items()
        }
        ups = self.data.setdefault("preferred_up", {})
        for subj, lst in self.preferred_ups.items():
            if lst and subj not in ups:
                ups[subj] = lst[0]["name"]

    def _load(self) -> dict:
        base = {"preferred_up": dict(PREFERRED_UP), "star": [], "verified": {},
                "drop": {}, "pin": {}, "skip_title": {}}
        try:
            with open(self.path, encoding="utf-8") as f:
                base.update(json.load(f))
        except (OSError, ValueError):
            pass
        return base

    def save(self) -> None:
        os.makedirs(os.path.dirname(os.path.abspath(self.path)), exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(self.data, f, ensure_ascii=False, indent=2)

    def up_for(self, subject: str) -> str:
        return self.data.get("preferred_up", {}).get(subject, "")

    def preferred_match(self, author: str, subject: str) -> str:
        """该作者是否属于本学科的指定 UP 列表；是则返回命中的 UP 名，否则空串。"""
        a = (author or "").strip()
        if not a:
            return ""
        # 本地偏好里显式指定的 UP 优先（--up 覆盖）
        local = self.up_for(subject)
        if local and a == local.strip():
            return local
        for u in self.preferred_ups.get(subject, []):
            if a == (u.get("name") or "").strip():
                return u["name"]
        return ""

    def preferred_weight(self, subject: str) -> float:
        """首选 UP 加权：按本学科 rank 最高者取值（rank -1 最高），与护栏一致。

        本地偏好里显式改掉的 UP（--up 覆盖）视作 rank=-1 的最高优先；
        与护栏首选相同的那只是自动补的默认值，不额外提权。
        """
        ranks = [int(u.get("rank", 99)) for u in self.preferred_ups.get(subject, [])]
        local = self.up_for(subject).strip()
        guard_first = next((u["name"] for u in self.preferred_ups.get(subject, [])
                            if u.get("name")), "")
        if local and local != guard_first:
            ranks.append(-1)
        if not ranks:
            return PREFERRED_UP_WEIGHTS.get(0, 6.0)
        best = min(ranks)
        return PREFERRED_UP_WEIGHTS.get(best, 4.0)

    def is_preferred(self, author: str, subject: str) -> bool:
        return bool(self.preferred_match(author, subject))

    def dropped(self, bvid: str) -> str | None:
        return self.data.get("drop", {}).get(bvid)

    def pinned(self, unit: str) -> list[str]:
        return self.data.get("pin", {}).get(unit, [])


# --------------------------------------------------------------------------- #
# 基础工具
# --------------------------------------------------------------------------- #
def _get(url: str, as_json: bool = True, timeout: float = 20.0, tries: int = RETRY):
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers=HEADERS, method="GET")
            with urllib.request.urlopen(req, timeout=timeout) as r:
                raw = r.read()
            text = raw.decode("utf-8", errors="replace")
            return json.loads(text) if as_json else text
        except Exception as e:  # noqa: BLE001
            last = e
            code = getattr(e, "code", None)
            time.sleep((3.0 * (i + 1)) if code in (412, 429) else 2.0)
    raise RuntimeError(f"GET 失败 {type(last).__name__}: {str(last)[:100]}")


def _clean(s: Any) -> str:
    t = "" if s is None else str(s)
    return html.unescape(re.sub(r"<[^>]+>", "", t)).strip()


def _to_int(v: Any) -> int:
    if isinstance(v, (int, float)):
        return int(v)
    m = re.match(r"([\d.]+)\s*([万千wW亿]?)", str(v or "").strip().replace(",", ""))
    if not m:
        return 0
    return int(float(m.group(1)) * {"": 1, "万": 1e4, "w": 1e4, "W": 1e4,
                                    "千": 1e3, "亿": 1e8}[m.group(2)])


def _duration_sec(v: Any) -> int:
    if isinstance(v, (int, float)):
        return int(v)
    t = str(v or "").strip()
    if t.isdigit():
        return int(t)
    m = re.fullmatch(r"(\d+):(\d{1,2})(?::(\d{1,2}))?", t)
    if m:
        a, b, c = int(m.group(1)), int(m.group(2)), int(m.group(3) or 0)
        return a * 3600 + b * 60 + c if m.group(3) else a * 60 + b
    m = re.match(r"(?:(\d+)分)?(?:(\d+)秒)?", t)
    if m and (m.group(1) or m.group(2)):
        return int(m.group(1) or 0) * 60 + int(m.group(2) or 0)
    return 0


def _mmss(sec: int) -> str:
    sec = max(0, int(sec))
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def _clean_kp(kp: str) -> str:
    """净化知识点输入：去纯符号、限长 40 字。

    纯符号（!!!、***、??? 等）会让检索词变成噪音，长知识点名则会把
    对位度稀释成低分。超长直接截断前 40 字。
    """
    s = str(kp or "").strip()
    # 去掉不含任何实义字符的符号片段
    s = re.sub(r"[^\w一-鿿]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s[:40]


def _kp_tokens(kp: str) -> set[str]:
    """把知识点拆成可命中的实质词。

    P1-2：剔除护栏 generic_terms.terms（英语/语文/数学/初一/七年级/压轴/专题…）。
    泛学科词不能算「命中」——否则 kp="初一数学 绝对值" 对标题"初一数学 单调性 最值"
    会命中 4 个泛词，把不对症的课当首选输出。

    阶段33 补漏（阶段33 实测）：泛学科词被剔除后，它的 2-gram 仍在漏 ——
    「初一数学」漏出「一数」、「初中英语」漏出「中英」、「七年级」漏出「七年/年级」、
    「新定义」漏出「新定/定义」。于是 kp="初一数学 绝对值" 对标题
    "初一数学 单调性 最值" 会算出 kp_hit=1（token=「一数」），不对症课通过硬门槛。
    修法：泛学科词派生的所有 2-gram 一并过滤（一数/中数/中英/七年/年级/新定/定义
    都不会再成为命中 token）。
    """
    parts = re.split(r"[\s,，、/｜|()（）:：]+", _clean_kp(kp))
    out: set[str] = set()
    for p in parts:
        if len(p) >= 2 and p not in GENERIC_TERMS:
            out.add(p)
        if len(p) > 2:
            for i in range(len(p) - 1):
                bg = p[i:i + 2]
                if all(c in MATH_NOISE for c in bg):
                    continue
                if bg in GENERIC_TERMS or bg in GENERIC_2GRAMS:
                    continue
                out.add(bg)
    return {t for t in out if len(t) >= 2 and t not in GENERIC_TERMS
            and t not in GENERIC_2GRAMS}


# --------------------------------------------------------------------------- #
# ① 关键词矩阵：常规 / UP 定向 / 难题定向
# --------------------------------------------------------------------------- #
def build_keywords(kp: str, subject: str = "", grade: str = "",
                   error_type: str = "", extra: str = "",
                   hard: bool = False, question: str = "",
                   preferred_up: str = "") -> list[str]:
    base = " ".join(x for x in (_clean_kp(kp), subject.strip()) if x)
    g = grade.strip() or "初中"
    kp = _clean_kp(kp)
    words: list[str] = []

    # 首选 UP 定向：18 个考点词 ×2 页复查过全部投稿的教训 → 先查他有没有
    if preferred_up:
        words.append(f"{preferred_up} {kp}")
        words.append(f"{preferred_up} {kp} {g}")

    words += [f"{base} {g} 讲解",
              f"{base} 原理 为什么",
              f"{kp} 专项 {g} 15分钟"]
    if error_type:
        words.append(f"{kp} {error_type} 易错 讲解")
    if extra:
        words.append(f"{kp} {extra.strip()}")

    # 难题/压轴且没有通用课：用「核心方法 + 真题定位 + 专讲」找针对性课程
    if hard:
        core = re.sub(r"[\d\s,，。；;：:、（）()]+", " ", question or kp).strip()[:28]
        words += [f"{kp} 压轴 专讲",
                  f"{kp} 真题 精讲 {g}",
                  f"{core} 讲解" if core else f"{kp} 方法 拆解"]
    out, seen = [], set()
    for w in words:
        w = re.sub(r"\s+", " ", w).strip()
        if w and w not in seen:
            seen.add(w)
            out.append(w)
    return out[:8]


# --------------------------------------------------------------------------- #
# ② 平台召回：搜索 API → 搜索页（WebFetch 思路）→ 412 退避
# --------------------------------------------------------------------------- #
def _search_api(kw: str, page: int = 1) -> list[dict]:
    d = _get(SEARCH_API.format(kw=urllib.parse.quote(kw), page=page))
    if d.get("code") != 0:
        raise RuntimeError(f"search code={d.get('code')} {d.get('message')}")
    rows = []
    for it in (d.get("data") or {}).get("result") or []:
        if not it.get("bvid"):
            continue
        rows.append({"bvid": it["bvid"], "title": _clean(it.get("title")),
                     "author": _clean(it.get("author")),
                     "duration": it.get("duration"), "play": it.get("play"),
                     "keyword": kw})
    return rows


def _walk(obj: Any, found: list[dict], depth: int = 0) -> None:
    if depth > 12 or len(found) >= 40:
        return
    if isinstance(obj, dict):
        bv = obj.get("bvid") or obj.get("bv_id")
        if isinstance(bv, str) and re.fullmatch(r"BV[0-9A-Za-z]{10}", bv):
            stat = obj.get("stat") if isinstance(obj.get("stat"), dict) else {}
            owner = obj.get("owner") if isinstance(obj.get("owner"), dict) else {}
            found.append({"bvid": bv, "title": _clean(obj.get("title") or obj.get("name")),
                          "author": _clean(obj.get("author") or obj.get("upname") or owner.get("name")),
                          "duration": obj.get("duration") or obj.get("length") or 0,
                          "play": obj.get("play") or obj.get("view") or stat.get("view") or 0})
        for v in obj.values():
            _walk(v, found, depth + 1)
    elif isinstance(obj, list):
        for v in obj[:60]:
            _walk(v, found, depth + 1)


def _search_page(kw: str) -> list[dict]:
    """WebSearch 只返回专栏文章（cv 号），必须直接打开平台搜索页。"""
    page = _get(SEARCH_PAGE.format(kw=urllib.parse.quote(kw)), as_json=False)
    found: list[dict] = []
    for marker in ("__INITIAL_STATE__", "__NEXT_DATA__", "__pinia"):
        m = re.search(re.escape(marker) + r"\s*=\s*", page)
        if not m:
            continue
        start = page.find("{", m.end())
        if start < 0:
            continue
        try:
            obj, _ = json.JSONDecoder().raw_decode(page[start:])
            _walk(obj, found)
        except (ValueError, TypeError):
            pass
    if not found:
        for bv in dict.fromkeys(re.findall(r"BV[0-9A-Za-z]{10}", page)):
            found.append({"bvid": bv, "title": "", "author": "", "duration": 0, "play": 0})
    return [dict(r, keyword=kw) for r in found]


def catalog_recall(kp: str, subject: str = "") -> list[dict]:
    """从已核实课程目录里按 kp 的实质词捞候选（仍要过 view API 逐条核实）。

    阶段34 实测：轻量入口只靠 B 站搜索时，8 组召回词全部搜不到郭嘉的
    「详细拆解数轴动点三大公式！」（BV1rQC9BbE5d）——B 站把 UP 名当普通词。
    所以轻量入口也必须直连 references/guojia-catalog.json（护栏 preferred_catalog.file
    指定路径），按 kp 的实质词与目录条目的 title 匹配，命中就把该 BV 作为候选注入。

    注入的候选**只是候选**：仍要过 view API 核实、仍要过对症硬门槛与学段硬淘汰，
    核实不过就丢弃。目录里没命中的课不许凭空出现。
    """
    if not CATALOG:
        return []
    cat_subject = (GUARD.get("preferred_catalog") or {}).get("subject", "数学")
    if subject and cat_subject and subject != cat_subject:
        return []
    toks = _kp_tokens(kp) - GENERIC_TERMS - GENERIC_2GRAMS
    if not toks:
        return []
    out: list[dict] = []
    for v in CATALOG:
        title = v.get("title") or ""
        hit = sorted(t for t in toks if t in title)
        if not hit:
            continue
        out.append({
            "bvid": v["bvid"], "title": title,
            "author": "郭嘉老师数学思维",
            "duration": v.get("dur"), "play": v.get("play"),
            "keyword": f"已核实目录命中（{'/'.join(hit)}）",
            "catalog_unit": v.get("unit", ""),
        })
    return out


def recall(keywords: list[str], preferred_up: str = "",
           verbose: bool = False) -> tuple[list[dict], int, int]:
    """召回候选。

    P0-4：返回 (候选, 尝试次数, 失败次数)。
    原来失败被静默吞掉，只在 --verbose 打印，最后统一输出「没核实到对口视频」——
    把限流谎报成「B 站真没这门课」。失败次数必须统计出来给上层判定。
    """
    pool: dict[str, dict] = {}
    attempts = 0
    failures = 0
    for i, kw in enumerate(keywords):
        if i:
            time.sleep(REQUEST_INTERVAL)
        rows: list[dict] = []
        for fetch in (_search_api, _search_page):
            attempts += 1
            try:
                rows = fetch(kw)
                if rows:
                    break
            except Exception as e:  # noqa: BLE001
                failures += 1
                if verbose:
                    print(f"  [recall] {fetch.__name__}: {type(e).__name__} {str(e)[:70]}",
                          file=sys.stderr)
        # UP 定向词：只留作者精确匹配（别家视频不能混进「郭嘉有没有」的判断里）
        if preferred_up and kw.startswith(preferred_up):
            rows = [r for r in rows
                    if (r.get("author") or "").strip() == preferred_up.strip()]
        for r in rows:
            bv = r.get("bvid", "")
            if re.fullmatch(r"BV[0-9A-Za-z]{10}", bv) and bv not in pool:
                pool[bv] = r
        if len(pool) >= MAX_VERIFY * 2:
            break
    return list(pool.values()), attempts, failures


# --------------------------------------------------------------------------- #
# ③ 逐条核实（红线：没核实过的不给；标题/时长/播放只从 API 取）
# --------------------------------------------------------------------------- #
def verify(bvid: str, cache: dict | None = None, verbose: bool = False) -> dict | None:
    if cache is not None and bvid in cache:
        return cache[bvid]
    try:
        d = _get(VIEW_API.format(bvid=bvid), tries=3)
    except Exception as e:  # noqa: BLE001
        if verbose:
            print(f"  [verify] {bvid}: {type(e).__name__}", file=sys.stderr)
        return None
    if d.get("code") != 0:
        return None
    v = d.get("data") or {}
    if not v.get("bvid") or not v.get("duration"):
        return None
    # 阶段30 护栏：下架 / 需大会员 / 娱乐分区一律不进候选（用户踩过「点开要大会员」）
    try:
        state = int(v.get("state") or 0)
    except (TypeError, ValueError):
        state = 0
    if state < 0:
        return None
    rights = v.get("rights") or {}
    if any(rights.get(k) in (1, True) for k in PAY_KEYS):
        return None
    try:
        tid = int(v.get("tid") or 0)
    except (TypeError, ValueError):
        tid = 0
    if tid and ENTERTAINMENT_TIDS and tid in ENTERTAINMENT_TIDS:
        return None
    owner = v.get("owner") or {}
    stat = v.get("stat") or {}
    # P1-4：采集互动数据（收藏+投币比单纯播放更能反映「真的有用」），
    # 与批量引擎的 engagement 维度对齐（护栏 score_weights.engagement）。
    out = {"bvid": v.get("bvid", bvid), "title": _clean(v.get("title")),
           "author": _clean(owner.get("name")), "duration_sec": int(v["duration"]),
           "play": _to_int(stat.get("view")), "desc": _clean(v.get("desc"))[:300],
           "like": _to_int(stat.get("like")), "coin": _to_int(stat.get("coin")),
           "favorite": _to_int(stat.get("favorite")),
           "reply": _to_int(stat.get("reply")), "share": _to_int(stat.get("share")),
           "pages": len(v.get("pages") or []), "verified": True,
           "tid": tid, "state": state, "pubdate": int(v.get("pubdate") or 0)}
    if cache is not None:
        cache[bvid] = out
    return out


# --------------------------------------------------------------------------- #
# ④ 效果打分：四维 × 质量门（讲原理优先，讲口诀降档）
# --------------------------------------------------------------------------- #
def score_one(item: dict, kp: str, subject: str = "", grade: str = "",
              prefs: Prefs | None = None) -> dict:
    title, desc = item.get("title", ""), item.get("desc", "")
    blob = title + " " + desc
    tokens = _kp_tokens(kp)
    hit = sum(1 for t in tokens if t in title)
    ratio = hit / len(tokens) if tokens else 0.0
    ctx = SUBJECT_CONTEXT.get(subject, []) if isinstance(SUBJECT_CONTEXT, dict) else []
    ctx_missing = bool(ctx) and not any(w in blob for w in ctx)
    play = _to_int(item.get("play"))

    # (a) 对口度 0-40
    rel = 40 * (0.10 + 0.90 * ratio)
    if subject and subject in title:
        rel += 3
    if grade and grade in title:
        rel += 2
    for w in GENERIC_WORDS:
        if w in title:
            rel -= 6
    if tokens and hit == 0:
        rel -= 12
    if ctx_missing:                    # 学科语境词只软扣分，见下方硬门槛说明
        rel -= 6
    rel = _clamp(rel, 0, 40)

    # (b) 时长 0-25 —— 档位取护栏 scoring_profiles.duration_fit.light（单一真源）
    dfcfg = ((GUARD.get("scoring_profiles") or {}).get("duration_fit") or {}).get("light") or {}
    dfp = dfcfg.get("points") or {}
    dfd = dfcfg.get("decay") or {}
    d_best_min = int(dfcfg.get("best_min_sec", 600))
    d_best_max = int(dfcfg.get("best_max_sec", 900))
    d_short = int(dfcfg.get("short_min_sec", 360))
    d_long = int(dfcfg.get("long_sec", 1200))
    d_decay_start = int(dfd.get("start_sec", d_long))
    d_decay_step = float(dfd.get("step", 0.35))
    d_decay_floor = float(dfd.get("floor", 4))
    dur_sec = item.get("duration_sec", 0)
    minutes = dur_sec / 60
    if d_best_min <= dur_sec <= d_best_max:
        dur_s, hint = float(dfp.get("best", 25)), "整段看完即可（10–15 分钟）"
    elif d_short <= dur_sec < d_best_min:
        dur_s, hint = float(dfp.get("short", 21)), "很短，看完立刻做题"
    elif d_best_max < dur_sec <= d_long:
        dur_s, hint = float(dfp.get("long", 18)), "整段看完，别跳"
    elif dur_sec > d_decay_start:
        dur_s = max(d_decay_floor, d_decay_floor + (14 - d_decay_floor)
                    - (minutes - d_decay_start / 60) * d_decay_step)
        hint = (f"偏长（{_mmss(dur_sec)}）：先拖进度条定位该知识点，"
                "只看对应片段，并写清那段讲什么")
    else:
        dur_s, hint = float(dfp.get("under", 8)), "不到 6 分钟，只适合当提示，讲不透原理"
    if item.get("pages", 0) > 1:
        hint += "；分 P 合集按分 P 标题定位那一集，不要猜 ?p= 集数"

    # (c) 播放热度 0-20 —— 档位取护栏 scoring_profiles.popularity.light（单一真源）
    pop_tiers = (((GUARD.get("scoring_profiles") or {}).get("popularity") or {})
                  .get("light") or {}).get("tiers") or []
    pop = 2.0
    for tier in pop_tiers:
        if play >= int(tier.get("min_play", 0)):
            pop = float(tier.get("points", 2))
            break

    # (c2) 互动质量 0-12：收藏+投币比单纯播放更能反映「真的有用」。
    # 公式与批量引擎一致；权重取护栏 score_weights.engagement（=12）。
    eng_raw = (item.get("like", 0) + 2 * item.get("coin", 0)
               + 2 * item.get("favorite", 0)) / max(1, play)
    eng = ENGAGEMENT_WEIGHT * min(1.0, eng_raw / 0.12)

    # (d) 讲法 0-15（最终作为乘性质量门，不可被播放量补偿）
    principle = sum(1 for w in PRINCIPLE_WORDS if w in blob)
    rote = sum(1 for w in ROTE_WORDS if w in blob)
    ped = _clamp(8 + 2.5 * min(2, principle) - 4.0 * min(2, rote), 0, 15)

    base = rel + dur_s + pop + eng                  # 0-97
    quality = 0.5 + 0.5 * (ped / 15)              # 0.5-1.0：口诀类直接砍半
    total = 100 * (base / 97) * quality

    # 偏好加权：★保留 / 实测有效 / 指定 UP（效果优先，不是人气优先）
    tags = []
    if prefs:
        bv = item.get("bvid", "")
        # P1-3：指定 UP 用完整列表判定，权重按该学科 rank 最高者
        pref_name = prefs.preferred_match(item.get("author", ""), subject)
        if pref_name:
            total += prefs.preferred_weight(subject)
            tags.append(f"{pref_name}·首选")
        if bv in prefs.data.get("star", []):
            total += 6
            tags.append("★保留")
        if bv in prefs.data.get("verified", {}):
            total += 10
            tags.append("✔ 实测有效")
    # P1-1：学段软惩罚（中考/总复习/冲刺/竞赛）——护栏读了但从没用过，命中即扣分
    soft_hits = [p for p in GRADE_SOFT if p in blob]
    if soft_hits:
        total += GRADE_SOFT_PENALTY
    total = round(_clamp(total, 0, 100), 1)

    reasons = []
    if hit:
        reasons.append(f"标题点名「{kp}」")
    if principle:
        reasons.append("讲原理")
    if rote:
        reasons.append("偏口诀（质量门降档）")
    reasons.append(f"{_mmss(item.get('duration_sec', 0))} / 播放 {play:,}")
    # 🔴 对症硬门槛：标题完全没点名该知识点，一律不给。
    # 播放量再高、是不是指定 UP 都不能补偿 —— 历史上「Day6 考《十五夜望月》
    # 却配《次北固山下》」「数轴动点配找规律」都是这么来的。
    # 阶段30 补三层护栏：非授课标题 / 娱乐与跨赛道污染 / 缺本学科语境词
    # （「寒夜」搜出古风歌、「拟人」搜出师范赛道与小学微课，均由此挡住）。
    why_reject = []
    if hit == 0:
        why_reject.append("标题未点名该知识点（不对症）")
    if TITLE_JUNK and any(w in title for w in TITLE_JUNK):
        why_reject.append("非授课类标题（专场/回放/课件/PPT 等）")
    if IRRELEVANT and any(w in blob for w in IRRELEVANT):
        why_reject.append("与学科教学无关（歌曲/游戏/师范赛道等）")
    # P0-5：学段硬淘汰 —— 与批量引擎口径一致。
    # 原实现只 -8 分，八上内容照样能以 80 分被标「首选」输出给七上学生。
    # 阶段34 修：年级/语境类护栏词**优先只匹配 title**；title 无命中时，才看简介的
    # 「正文语境」（剥掉 UP 简介区）。UP 主简介区的「@一高数 学习高数」是固定签名，
    # 不是本条视频内容 —— 实测 BV1KejH67E2G「2026初高衔接第一课！因式分解！」就是
    # 被简介里的「高数」误杀的（淘汰结果碰巧对，理由是巧合）。
    grade_bad = next((w for w in OFF_GRADE_WORDS if w in title), None)
    if grade_bad is None:
        body = _desc_body(desc)
        if body:
            grade_bad = next((w for w in OFF_GRADE_WORDS if w in body), None)
    if grade_bad:
        why_reject.append(f"年级不符（{grade_bad}）")
    # 播放量门槛：与批量引擎同一份护栏（min_play_exact_match）。
    # 播放量 0 的视频没有观看数据佐证，绝不能进「首选」。
    min_play = float(THRESHOLDS.get("min_play_exact_match", 500))
    if play < min_play:
        why_reject.append(f"播放量 {play} < 门槛 {min_play}")
    # 🔴 阶段30 实测教训：`desc` 常为空，短标题好课（如「三步法包教包会绝对值化简！」、
    # 「详细拆解数轴动点三大公式！」）不含任何学科语境词，一刀切硬淘汰会误杀指定 UP 的好课。
    # 因此标题已点名考点时只软扣 6 分；只有完全不对症时，才拿语境词作额外拦截。
    if ctx_missing and hit == 0:
        why_reject.append("缺本学科语境词")
    reject = "；".join(why_reject) or None
    return {**item, "score": total, "quality_gate": round(quality, 2),
            "kp_hit": hit, "reject": reject,
            "breakdown": {"对口度": round(rel, 1), "时长": round(dur_s, 1),
                          "口碑": round(pop, 1), "互动": round(eng, 1),
                          "讲法": round(ped, 1)},
            "grade_soft_hits": soft_hits,
            "watch_hint": hint, "reason": "；".join(reasons), "tags": tags,
            "duration": _mmss(item.get("duration_sec", 0)),
            "url": WATCH_URL.format(bvid=item.get("bvid", ""))}


def grade_video(item: dict, subject: str, prefs: Prefs) -> str:
    """看片次序：指定 UP → 入门 → 原理 → 对位 → 专项。"""
    if prefs.is_preferred(item.get("author", ""), subject):
        return "首选UP"
    t = item.get("title", "") + " " + item.get("desc", "")
    if any(k in t for k in PRINCIPLE_WORDS):
        return "原理"
    if any(k in t for k in SPECIAL_WORDS):
        return "专项"
    if any(k in t for k in INTRO_WORDS):
        return "入门"
    return "对位"


# --------------------------------------------------------------------------- #
# ⑤ 排序 / 去重 / 覆盖度审计
# --------------------------------------------------------------------------- #
def rank(items: list[dict], kp: str, subject: str, grade: str,
         prefs: Prefs, unit: str = "", limit: int = 3) -> list[dict]:
    scored = [score_one(x, kp, subject, grade, prefs) for x in items]
    return rank_scored(scored, subject, prefs, unit, limit)


def rank_scored(scored: list[dict], subject: str, prefs: Prefs,
                unit: str = "", limit: int = 3) -> list[dict]:
    """对已打分的候选做去重 / 排序 / 上限截断。

    与 rank() 分开是为了让「打分」只跑一次 —— 上层要用同一份打分结果判定
    「指定 UP 到底有没有对症课」（阶段34 修：原来用未过滤的 verified 判定，
    0 条可推荐时也报「UP 命中」）。
    """
    scored = [x for x in scored if not x["reject"] and x["score"] >= MIN_BACKUP]

    # 全局唯一 BV 去重（55 条挂接只有 33 个唯一 BV 的教训）
    uniq: dict[str, dict] = {}
    for x in scored:
        if x["bvid"] not in uniq or x["score"] > uniq[x["bvid"]]["score"]:
            uniq[x["bvid"]] = x
    arr = list(uniq.values())
    for x in arr:
        x["grade"] = grade_video(x, subject, prefs)

    pins = prefs.pinned(unit)
    arr.sort(key=lambda x: (
        (0, pins.index(x["bvid"])) if x["bvid"] in pins
        else (1, V_RANK[x["grade"]], x["duration_sec"], -x["score"])
    ))

    # 单元上限：挤掉最弱的，但指定 UP / ★ / 实测有效 / 命门课永不挤掉
    protected = lambda x: (x["bvid"] in pins or "★保留" in x["tags"]
                           or "✔ 实测有效" in x["tags"]
                           or any("首选" in t for t in x["tags"]))
    if len(arr) > UNIT_CAP:
        keep, rest = [x for x in arr if protected(x)], [x for x in arr if not protected(x)]
        arr = (keep + rest)[:UNIT_CAP]

    picked = arr[:limit]
    # 「首选」给综合效果分最高的那条；「order」是看片次序（短的先看、入门在原理前）。
    # 两者刻意分开：效果最好 ≠ 最先看，历史上 21 分钟命门课也不能被短课挤掉。
    best = max(picked, key=lambda x: x["score"]) if picked else None
    for i, x in enumerate(picked):
        x["order"] = i + 1
        x["tier"] = "首选" if x is best and x["score"] >= MIN_PRIMARY else "备选"
    return picked


def coverage_audit(topics: list[str], items: list[dict], verbose: bool = False) -> dict:
    """G21-D：每个题型至少 1 条；标题不得指向当天不存在的题型。"""
    blob = " ".join(x.get("title", "") for x in items)
    missing, offtopic = [], []
    for t in topics:
        t = t.strip()
        if not t:
            continue
        if not any(k in blob for k in _kp_tokens(t)):
            missing.append(t)
    for topic, banned in OFFTOPIC_WORDS.items():
        if topic not in topics and any(w in blob for w in banned):
            offtopic.append(topic)
    return {"topics": topics, "covered": len(topics) - len(missing),
            "missing": missing, "offtopic": offtopic,
            "pass": not missing and not offtopic,
            "note": "按题型判断，不按题干全文；全文匹配实测误报过半"}


def _method_steps(text: str) -> list[str]:
    """从题干/考点词推出「核心方法拆解」的步骤骨架（规则驱动，不联网、不猜视频内容）。

    阶段34 修：难题模式原来只输出判定档位 + 依据说明，没有给方法拆解；
    产品口径要求「全站无对口课时，要给出核心方法拆解，不硬凑泛课」。
    这里的步骤是**通法骨架**（怎么设未知数、怎么转化、怎么检验），
    只依据题干里出现的数学特征词推导，不声称看过任何视频内容。
    """
    t = str(text or "")
    steps: list[str] = []
    if "动点" in t or "行程" in t or "数轴" in t:
        steps.append("建系设点：在数轴上表示动点位置，把线段长（带符号）写成含动点位置的式子")
    if "绝对值" in t:
        steps.append("去绝对值：先找零点分段（或用零点分段法），逐段按符号去绝对值再化简")
    if "最值" in t or "最大" in t or "最小" in t:
        steps.append("转化最值：把目标量（距离/差/和）写成函数或几何意义，转成区间上的最值问题")
    if "方程" in t or "未知数" in t:
        steps.append("设元列式：设未知数表示动点位置或所求量，按题目条件列出方程/方程组")
    if "分类" in t or "讨论" in t:
        steps.append("分类讨论：按零点、动点所处区间或符号分情况，逐类求解后合并同类解")
    if "相似" in t or "全等" in t or "三角形" in t or "几何" in t:
        steps.append("几何转化：找相似/全等/勾股等判定关系，把几何量转成边长或角度的代数式")
    if "周期" in t or "循环" in t:
        steps.append("找周期：按最小重复单元确定周期长度，用余数把所求项定位到周期内的位置")
    if "整除" in t or "余数" in t:
        steps.append("整除建模：写成被除数=除数×商+余数，用余数范围反推商的取值")
    if "不等式" in t:
        steps.append("解不等式：注意变号条件与端点取舍，最终答案要带范围")
    if not steps:
        steps.append("拆解题干：把已知量、待求量、隐藏条件逐条列出，判断题型归属")
        steps.append("选方法：在方程/不等式/几何转化/分类讨论中选出主攻方向")
    steps.append("检验回代：把结果代回原题条件（含范围、舍去增根）再作答")
    return steps


def hard_question_audit(question: str, items: list[dict], kp: str) -> dict:
    """难题逐题匹配三档：够 / 勉强 / 不够。全站无对口课就如实说只能靠讲。

    阶段34 修：hard_question 里补 method_breakdown（核心方法拆解）。
    判「不够」时必须给出（没有对口课就靠讲，得告诉家长怎么讲）；
    判「勉强」时额外给「缺哪一环」的补充说明。
    """
    breakdown = _method_steps(f"{question} {kp}")
    if not items:
        return {"verdict": "不够", "reason": "全站无对口课",
                "advice": "如实告知「没有对口视频，只能靠讲」，并给出核心方法拆解，不硬凑",
                "method_breakdown": breakdown,
                "method_note": "按上面的方法拆解讲；每步都要写清式子，不要只讲思路",
                "question": question[:80], "kp": kp}
    best = max(x["score"] for x in items)
    if best >= 65:
        verdict, reason = "够", "标题明确对上核心方法"
    elif best >= 48:
        verdict, reason = "勉强", "有主方法但缺一环，需补一句讲解"
    else:
        verdict, reason = "不够", "核心方法没有任何一条覆盖"
    out = {"verdict": verdict, "reason": reason,
           "advice": ("判定依据只有标题/时长/播放/单元归属，B 站未登录拿不到字幕，"
                      "「够」不等于内容一定讲对" if verdict != "不够"
                      else "如实说无对口课，只能靠讲，不给搜索词当借口"),
           "question": question[:80], "kp": kp,
           "method_breakdown": breakdown}
    if verdict == "勉强":
        out["method_note"] = ("这节课只覆盖主干方法，缺上面拆解里的最后一环（检验回代/范围取舍），"
                              "看完要自己补做一遍，别直接抄答案")
    elif verdict == "不够":
        out["method_note"] = "没有对口视频，按上面的方法拆解讲；每步都要写清式子，不要只讲思路"
    else:
        out["method_note"] = "视频方法与上面拆解一致，可直接照着讲"
    return out


# --------------------------------------------------------------------------- #
# ⑥ 主编排
# --------------------------------------------------------------------------- #
def recommend(kp: str, subject: str = "", grade: str = "", error_type: str = "",
              extra: str = "", limit: int = 3, unit: str = "", topics: list[str] | None = None,
              hard: bool = False, question: str = "", preferred_up: str = "",
              offline: bool = False, prefs: Prefs | None = None,
              verbose: bool = False) -> dict:
    prefs = prefs or Prefs(data={"preferred_up": dict(PREFERRED_UP), "star": [],
                                 "verified": {}, "drop": {}, "pin": {}, "skip_title": {}})
    if preferred_up:
        prefs.data.setdefault("preferred_up", {})[subject or "数学"] = preferred_up
    up = prefs.up_for(subject)
    keywords = build_keywords(kp, subject, grade, error_type, extra,
                              hard, question, up)

    if offline:
        raw = [dict(x, duration_sec=_duration_sec(x.get("duration")),
                    play=_to_int(x.get("play")), verified=True, keyword=keywords[0])
               for x in SAMPLES]
        verified = []
        for bv, v in [(x["bvid"], x) for x in raw]:
            if prefs.dropped(bv):
                continue
            verified.append(v)
        search_attempts = search_failures = 0
    else:
        raw, search_attempts, search_failures = recall(keywords, up, verbose)
        # 阶段34：直连已核实目录补候选（B 站把 UP 名当普通词，搜不到他本人）。
        # 目录候选与搜索候选走同一条核实/对症/学段流水线，核实不过就丢弃。
        # 目录候选排在前面 —— 它是指定 UP 已核实的对口课，不能被搜索结果挤出
        # MAX_VERIFY 的核实额度（实测：搜 48 条时它排在末尾就永远轮不到核实）。
        seen_bv = {r.get("bvid") for r in raw}
        cat_rows = [c for c in catalog_recall(kp, subject) if c["bvid"] not in seen_bv]
        raw = cat_rows + raw
        cache: dict[str, dict | None] = {}
        verified = []
        for i, c in enumerate(raw[:MAX_VERIFY]):
            if i:
                time.sleep(REQUEST_INTERVAL)
            drop = prefs.dropped(c["bvid"])
            if drop:
                if verbose:
                    print(f"  [drop] {c['bvid']}: {drop}", file=sys.stderr)
                continue
            v = verify(c["bvid"], cache, verbose)
            if v:
                v["keyword"] = c.get("keyword", "")
                # 目录候选带上单元归属（可从输出反查这节课属于哪个单元）
                if c.get("catalog_unit"):
                    v["catalog_unit"] = c["catalog_unit"]
                    v["catalog_hit"] = True
                verified.append(v)

    scored = [score_one(x, kp, subject, grade, prefs) for x in verified]
    picked = rank_scored(scored, subject, prefs, unit, limit)
    # P0-4：检索失败率超阈值 → 本次检索未完成，不能当成「B 站真没这门课」。
    # 失败比例达阈值时：禁止给「无对口课」结论、禁止给 SEARCH 兜底（搜索都没成功，
    # 兜底词同样不可靠），改为「检索未完成，需稍后重试」。
    failure_ratio = (search_failures / search_attempts) if search_attempts else 0.0
    retrieval_failed = (search_attempts > 0
                        and failure_ratio >= SEARCH_FAILURE_RATIO)
    # 「有没有对应课」= 核实通过 + 对症 + 未被 reject 的候选集合。
    # 阶段34 修：原来只看「核实通过」就算 UP 命中（0 条可推荐时也报命中），
    # 现在必须是对症且过了硬门槛的候选才算。
    toks = _kp_tokens(kp)
    qualified = [x for x in scored
                 if not x.get("reject")
                 and x.get("kp_hit", 0) > 0]
    has_up = any(prefs.is_preferred(x.get("author", ""), subject) for x in qualified)
    # 诚实声明的前提：目录 + 搜索都确认没有对症课时才敢说「暂无对应课」。
    # 目录里有对口课但没通过核实/对症门槛 → 不能说「暂无对应课」，只能说没通过门槛。
    cat_hits = catalog_recall(kp, subject)
    cat_bvids = {c["bvid"] for c in cat_hits}
    cat_qualified = [x for x in qualified if x.get("bvid") in cat_bvids]
    honesty = None
    if up and not has_up:
        if cat_hits and not cat_qualified:
            honesty = (f"{up} 目录里有本题相关课（"
                       + "、".join(c["bvid"] for c in cat_hits)
                       + "），但本次没通过核实/对症门槛，暂不挂；"
                       "按下面次序看，不拿别家课充作首选")
        else:
            honesty = (f"本单元 {up} 暂无对应课，已核过其全部投稿；"
                       "按下面次序看，不拿别家课充作首选")

    cov = coverage_audit(topics or [], picked) if topics else None
    hqa = hard_question_audit(question or kp, picked, kp) if hard else None

    fallback = None
    retry_note = None
    if retrieval_failed:
        # 检索没完成 → 只说「未完成，需重试」，不给「无对口课」结论，也不给 SEARCH 兜底
        retry_note = (f"检索未完成：{search_failures}/{search_attempts} 次搜索失败"
                      f"（失败率 {failure_ratio:.0%}，多为 B 站 412 限流）。"
                      "本次**不能判定为无对口课**，请稍后重试")
    elif not picked:
        # 兜底词必须是干净的考点词：已确认指定 UP 没有对应课，就别再把 UP 名塞进搜索词
        kw = next((k for k in keywords if not (up and k.startswith(up))),
                  f"{kp} {grade} 专项 15分钟".strip())
        note = ("没核实到对口视频：给精准搜索词 + 挑 15 分钟以内 + 标题点名考点，"
                "绝不编造 BV 号")
        if hard:
            note += "；难题优先加「真题出处 / 核心方法词」找针对性课程，别用全章串讲顶替"
        fallback = {"type": "SEARCH", "keyword": kw,
                    "url": SEARCH_PAGE.format(kw=urllib.parse.quote(kw)),
                    "note": note}
        # 护栏 known_gaps：命中已知的「确实没对口课」考点时直接引用，别再重复搜索
        for g in (GUARD.get("known_gaps") or []):
            if any(t and t in str(g) for t in _kp_tokens(kp)):
                fallback["known_gap"] = g
                break

    dsl = []
    for x in picked:
        tag = ("".join(f"[{t}]" for t in x["tags"])) or ""
        why = f"<b>{x['tier']}</b>{tag}：{x['reason']}。{x['watch_hint']}"
        dsl.append("|".join(["VID", x["bvid"], x["title"], x["author"],
                             x["duration"], why]))
    if fallback:
        dsl.append("|".join(["VID", "SEARCH:" + fallback["keyword"],
                             "（备选）在 B 站按精准关键词自行挑选", "自选", "≤15 分钟",
                             "<b>备选</b>：点「去搜索」，挑 15 分钟以内、标题点名考点的那条"]))

    return {
        "query": {"kp": kp, "subject": subject, "grade": grade, "unit": unit,
                  "hard": hard, "question": question[:80], "preferred_up": up},
        "keywords": keywords,
        "recalled": len(raw), "verified": len(verified),
        "thresholds": {"primary": MIN_PRIMARY, "backup": MIN_BACKUP,
                       "rank": V_RANK, "unit_cap": UNIT_CAP},
        "guardrails": {"version": GUARD.get("version", "builtin"),
                       "updated": GUARD.get("updated", ""),
                       "source": GUARD.get("source", ""),
                       "hard_rules": len(GUARD.get("hard_rules") or []),
                       "drop": len(GUARD.get("drop") or {}),
                       "verified_good": len(GUARD.get("verified_good") or {}),
                       "user_verified": GUARD.get("user_verified", {}),
                       "known_gaps": GUARD.get("known_gaps", [])},
        "items": picked,
        "preferred_up_hit": has_up,
        "honesty_note": honesty,
        # 目录注入轨迹（可审计：目录命中了什么、哪些过了核实与对症门槛）
        "catalog": {"file": os.path.basename(CATALOG_FILE),
                    "hits": [{"bvid": c["bvid"], "title": c["title"],
                              "unit": c.get("catalog_unit", "")} for c in cat_hits],
                    "qualified": [x["bvid"] for x in cat_qualified]},
        "coverage": cov,
        "hard_question": hqa,
        "fallback": fallback,
        # P0-4：检索未完成的显式信号（调用方据此提示重试，而不是当成「没这门课」）
        "needs_retry": bool(retrieval_failed),
        "retry_note": retry_note,
        "search_stats": {"attempts": search_attempts, "failures": search_failures,
                         "failure_ratio": round(failure_ratio, 4)},
        "dsl": dsl,
        "disclaimer": "所有 BV 均经 view 接口核实；未核实通过、被 DROP、年级不符的一律不给。",
    }


# --------------------------------------------------------------------------- #
# ⑦ 离线自测 & CLI
# --------------------------------------------------------------------------- #
def _cli_exit_code(args: list[str]) -> int:
    """跑一次本脚本 CLI，返回退出码（用于自测参数校验）。不联网。"""
    import subprocess
    here = os.path.abspath(__file__)
    try:
        r = subprocess.run([sys.executable, here] + args,
                           capture_output=True, timeout=60)
        return r.returncode
    except Exception:                                    # noqa: BLE001
        return -1


def selftest() -> int:
    p = Prefs(data={"preferred_up": {"数学": DEFAULT_UP}, "star": [], "verified": {},
                    "drop": {}, "pin": {}, "skip_title": {}})
    res = recommend("绝对值最小值", subject="数学", grade="七年级", offline=True,
                    prefs=p, limit=3)
    ids = [x["bvid"] for x in res["items"]]
    long_one = score_one(dict(SAMPLES[1], duration_sec=_duration_sec(SAMPLES[1]["duration"]),
                              play=_to_int(SAMPLES[1]["play"]), verified=True),
                         "绝对值最小值", "数学", "七年级", p)
    checks = [
        ("至少产出 2 条候选", len(res["items"]) >= 2),
        ("指定 UP 的讲原理课排第一", bool(ids) and ids[0] == "SAMPLE_A"),
        ("秒杀口诀课被质量门挡下", "SAMPLE_C" not in ids),
        ("偏好标签打上「首选」", any("首选" in t for x in res["items"] for t in x["tags"])),
        (">20 分钟给出只看片段指引", "先拖进度条" in long_one["watch_hint"]),
        ("DSL 行为 VID| 且 ≥6 段",
         all(x.startswith("VID|") and len(x.split("|")) >= 6 for x in res["dsl"])),
        ("四维分解齐全",
         all({"对口度", "时长", "口碑", "讲法"} <= set(x["breakdown"]) for x in res["items"])),
        ("覆盖度审计能报出缺失题型",
         coverage_audit(["绝对值", "病句"], res["items"])["missing"] == ["病句"]),
        ("不对症题型能被 G21-D 抓出",
         "找规律" in coverage_audit(["绝对值"], [{"title": "初一找规律七大数列"}])["offtopic"]),
        ("难题三档审计可用",
         hard_question_audit("数表权重分析", [], "数表")["verdict"] == "不够"),
        ("不对症视频被硬门槛挡下（播放量高也不行）",
         not recommend("折线数轴 变速动点", subject="数学", offline=True,
                       prefs=p)["items"]),
        ("不对症时不误报「指定 UP 有对应课」",
         recommend("折线数轴 变速动点", subject="数学", offline=True,
                   prefs=p)["preferred_up_hit"] is False),
        # 阶段30 护栏整合（与批量引擎共用 video-guardrails.json）
        ("护栏 DROP 名单生效",
         all(p.dropped(bv) for bv in (GUARD.get("drop") or {}))),
        ("护栏 ★保留名单生效",
         all(bv in p.data.get("star", []) for bv in (GUARD.get("verified_good") or {}))),
        ("学科语境词 + 娱乐污染硬门槛生效",
         score_one({"bvid": "X1", "title": "古风翻唱 寒夜", "desc": "",
                    "duration_sec": 300, "play": 999999, "author": "某UP", "pages": 1},
                   "寒夜", "语文", "七年级", p)["reject"] is not None),
        ("非授课标题被挡下",
         score_one({"bvid": "X2", "title": "绝对值 PPT 课件下载", "desc": "初中数学",
                    "duration_sec": 600, "play": 500000, "author": "某UP", "pages": 1},
                   "绝对值", "数学", "七年级", p)["reject"] is not None),
        # 阶段30 回归：desc 为空的短标题好课不能被学科语境词一刀切杀掉
        ("短标题指定 UP 好课不被学科语境词误杀",
         score_one({"bvid": "X3", "title": "三步法包教包会绝对值化简！", "desc": "",
                    "duration_sec": 252, "play": 24324, "author": DEFAULT_UP, "pages": 1},
                   "绝对值 化简", "数学", "七年级", p)["reject"] is None),
    ]

    # ---------------- 回归用例（补原自测盲区） ----------------
    # P0-5：八上/九年级内容在轻量入口必须硬淘汰，不能只 -8 分还标「首选」
    grade_bad = score_one({"bvid": "G1", "title": "八上数学 绝对值最小值 一次讲透",
                           "desc": "", "duration_sec": 600, "play": 500000,
                           "author": "某UP", "pages": 1},
                          "绝对值最小值", "数学", "七年级", p)
    checks.append(("P0-5 八上内容被硬淘汰（reject 非空，不是首选）",
                   grade_bad["reject"] is not None
                   and "年级不符" in (grade_bad["reject"] or "")))
    nine_bad = score_one({"bvid": "G2", "title": "九年级 绝对值方程 压轴题讲解",
                           "desc": "", "duration_sec": 600, "play": 500000,
                           "author": "某UP", "pages": 1},
                          "绝对值方程", "数学", "七年级", p)
    checks.append(("P0-5 九年级内容被硬淘汰（reject 非空）",
                   nine_bad["reject"] is not None))

    # P1-2：泛学科词标题不算命中 —— kp="绝对值" 对标题"初一数学 单调性 最值"
    generic_hit = score_one({"bvid": "G3", "title": "初一数学 单调性 最值", "desc": "",
                              "duration_sec": 600, "play": 500000,
                              "author": "某UP", "pages": 1},
                             "绝对值", "数学", "七年级", p)
    checks.append(("P1-2 泛学科词标题不算命中（kp_hit=0 且被拒）",
                   generic_hit["kp_hit"] == 0 and generic_hit["reject"] is not None))

    # P1-1：中考/总复习软惩罚真的扣分（同款视频差 ≈6 分）
    soft_base = {"bvid": "G4", "title": "初一数学 绝对值最小值 一次讲透", "desc": "",
                 "duration_sec": 600, "play": 50000, "author": "某UP", "pages": 1}
    s_nosoft = score_one(dict(soft_base), "绝对值最小值", "数学", "七年级", p)
    s_soft = score_one(dict(soft_base, title="初一数学 中考 绝对值最小值 一次讲透"),
                       "绝对值最小值", "数学", "七年级", p)
    checks.append((f"P1-1 中考软惩罚真的扣分（差 {round(s_nosoft['score'] - s_soft['score'], 1)} 分）",
                   abs((s_nosoft["score"] - s_soft["score"]) - (-GRADE_SOFT_PENALTY)) < 0.05
                   and s_soft["grade_soft_hits"] != []))

    # 播放量 0 的视频不能进首选
    zero_play = {"bvid": "G5", "title": "绝对值最小值 一次讲透原理", "desc": "",
                 "duration_sec": 600, "play": 0, "author": "某UP", "pages": 1}
    zero_scored = score_one(zero_play, "绝对值最小值", "数学", "七年级", p)
    checks.append(("播放量 0 的视频不能进首选",
                   zero_scored["reject"] is not None or zero_scored["score"] < MIN_PRIMARY))

    # P1-3：偏好 UP 完整列表（英语盖老师/平行世界、语文邵鑫/梓墨/豆伴匠不能丢）
    en_prefs = Prefs(data={"preferred_up": {}, "star": [], "verified": {},
                           "drop": {}, "pin": {}, "skip_title": {}})
    en_names = {u["name"] for u in en_prefs.preferred_ups.get("英语", [])}
    zh_names = {u["name"] for u in en_prefs.preferred_ups.get("语文", [])}
    checks.append(("P1-3 护栏指定 UP 完整列表保留（英语/语文）",
                   {"盖老师", "平行世界"} <= en_names
                   and {"邵鑫", "梓墨", "豆伴匠"} <= zh_names))
    # 非首选 UP（如平行世界）也要能拿到首选加权
    en_item = score_one({"bvid": "G6", "title": "初一英语 单词朗读 词根记忆",
                         "desc": "", "duration_sec": 600, "play": 50000,
                         "author": "平行世界", "pages": 1},
                        "英语单词", "英语", "七年级", en_prefs)
    checks.append(("P1-3 非首位偏好 UP 也享受首选加权",
                   any("首选" in t for t in en_item["tags"])))

    # P0-4：搜索 API 全抛异常 → 报「检索未完成」而不是「没核实到对口视频」
    saved_api, saved_page = _search_api, _search_page

    def _boom(*_a, **_kw):
        raise RuntimeError("simulated 412 rate-limit")

    try:
        globals()["_search_api"] = _boom
        globals()["_search_page"] = _boom
        retry_res = recommend("绝对值最小值", subject="数学", grade="七年级",
                              prefs=p, verbose=False)
    finally:
        globals()["_search_api"] = saved_api
        globals()["_search_page"] = saved_page
    checks.append(("P0-4 搜索全失败 → needs_retry=True 且不给 SEARCH 兜底",
                   retry_res["needs_retry"] is True
                   and retry_res["fallback"] is None
                   and "检索未完成" in (retry_res["retry_note"] or "")
                   and "没核实到对口视频" not in json.dumps(retry_res, ensure_ascii=False)))

    # P1-7 / P1-8：CLI 参数校验（退出码非 0）
    checks.append(("P1-7 --hard 无 --question 时报错退出（退出码非 0）",
                   _cli_exit_code(["--hard", "--kp", "绝对值最小值"]) != 0))
    checks.append(("P1-8 --mark-effective 传非法 BV 时报错退出（退出码非 0）",
                   _cli_exit_code(["--mark-effective", "NOT_A_BV"]) != 0))

    # P2：阈值与 kp 净化
    checks.append(("P2 阈值从护栏读（min_primary/min_backup/unit_cap）",
                   all(k in (GUARD.get("thresholds") or {})
                       for k in ("min_primary", "min_backup", "unit_cap"))))
    checks.append(("P2 护栏阈值无缺键（四个新键都被读到）",
                   not MISSING_THRESHOLDS
                   and "search_failure_ratio" in (GUARD.get("thresholds") or {})))
    checks.append(("P2 kp 长度上限 40 字 + 纯符号净化",
                   len(_clean_kp("绝对值" * 40)) <= 40
                   and _clean_kp("!!! ???") == ""))

    # ============ 阶段34 回归用例（真实接口验证查出的 6 类缺陷） ============

    # R3 高危6：泛学科词 2-gram 泄漏 —— kp="初一数学 绝对值" 对标题
    # 「初一数学 单调性 最值」必须 kp_hit=0 且被拒（原来漏 token「一数」→ 误命中）
    leak = score_one({"bvid": "L1", "title": "初一数学 单调性 最值", "desc": "",
                      "duration_sec": 600, "play": 500000, "author": "某UP", "pages": 1},
                     "初一数学 绝对值", "数学", "七年级", p)
    checks.append(("R3 泛学科词 2-gram 不泄漏（kp_hit=0 且被拒）",
                   leak["kp_hit"] == 0 and leak["reject"] is not None))
    checks.append(("R3 「一数/中数/中英/七年/年级/新定/定义」都不是命中 token",
                   not ({"一数", "中数", "中英", "七年", "年级", "新定", "定义"}
                        & (_kp_tokens("初一数学 初中英语 七年级 新定义")
                           | _kp_tokens("初中数学")))))
    checks.append(("R3 泛学科词派生的 2-gram 已被过滤",
                   "一数" not in _kp_tokens("初一数学")
                   and "定义" not in _kp_tokens("新定义")))

    # R4 低危8：年级护栏词只在标题匹配，UP 简介区的「高数」不误杀
    bio_desc = ("公众号：一数儿，免费分享学习资料~ \n\n"
                "@一物儿 学习物理\n@一化儿  学习化学\n@一高数 学习高数\n"
                "@学过石油的语文老师 学习语文\n\n愿这份友谊长存！")
    bio_item = score_one({"bvid": "B1", "title": "2026初高衔接第一课！因式分解！方法串讲！",
                          "desc": bio_desc, "duration_sec": 1654, "play": 1366144,
                          "author": "一数", "pages": 1},
                         "因式分解", "数学", "七年级", p)
    checks.append(("R4 UP 简介区的「高数」不再触发年级护栏词",
                   "高数" not in (bio_item["reject"] or "")))
    title_grade = score_one({"bvid": "B2", "title": "八上数学 绝对值最小值 一次讲透",
                              "desc": "", "duration_sec": 600, "play": 500000,
                              "author": "某UP", "pages": 1},
                             "绝对值最小值", "数学", "七年级", p)
    checks.append(("R4 标题里的年级护栏词仍然硬淘汰",
                   title_grade["reject"] is not None
                   and "年级不符" in (title_grade["reject"] or "")))

    # R5 低危9：难题模式必须产出核心方法拆解（不够时也要给）
    hq = hard_question_audit("动点从 A 到 B 运动，求经过时间", [], "数轴 动点 行程")
    checks.append(("R5 难题无对口课时给出核心方法拆解",
                   bool(hq.get("method_breakdown"))
                   and any("数轴" in s or "动点" in s for s in hq["method_breakdown"])))
    hq_ok = hard_question_audit("绝对值最小值", [
        {"bvid": "H1", "title": "绝对值最小值 几何意义", "score": 90.0}], "绝对值最小值")
    checks.append(("R5 难题够用时也带方法拆解", bool(hq_ok.get("method_breakdown"))))
    hq_mid = hard_question_audit("绝对值最小值", [
        {"bvid": "H2", "title": "绝对值最小值", "score": 50.0}], "绝对值最小值")
    checks.append(("R5 难题勉强时给补充说明",
                   hq_mid["verdict"] == "勉强" and bool(hq_mid.get("method_note"))))

    # R6 高危3：轻量入口能从目录注入郭嘉的对口课
    cat_hits = catalog_recall("数轴 动点 行程", "数学")
    checks.append(("R6 目录能按 kp 实质词捞出郭嘉的对口课",
                   any(c["bvid"] == "BV1rQC9BbE5d" for c in cat_hits)))
    checks.append(("R6 目录候选不匹配的课不会被捞出",
                   all("绝对值" not in c["title"] for c in cat_hits)))
    checks.append(("R6 目录注入的候选仍要过对症硬门槛（对不上的被拒）",
                   score_one({"bvid": "BV1rQC9BbE5d",
                              "title": "详细拆解数轴动点三大公式！", "desc": "",
                              "duration_sec": 492, "play": 17218,
                              "author": DEFAULT_UP, "pages": 1},
                             "数轴 动点 行程", "数学", "七年级", p)["reject"] is None
                   and score_one({"bvid": "BV1hwptzNEuu",
                                  "title": "奇点偶段法 绝对值压轴题的克星！", "desc": "",
                                  "duration_sec": 522, "play": 63584,
                                  "author": DEFAULT_UP, "pages": 1},
                                 "数轴 动点 行程", "数学", "七年级", p)["reject"] is not None))

    # R7 中危4：preferred_up_hit 必须基于「核实通过 + 对症 + 未被 reject」的候选
    saved2 = SAMPLES[:]
    try:
        SAMPLES.clear()
        # 模拟：目录有对口课，但核实后被硬门槛淘汰 → 0 条可推荐 → 不得报 UP 命中
        saved_v = globals()["verify"]
        globals()["verify"] = lambda bvid, cache=None, verbose=False: {
            "bvid": bvid, "title": "八上数学 绝对值最值 一次讲透", "author": DEFAULT_UP,
            "duration_sec": 600, "play": 500000, "desc": "", "like": 100, "coin": 10,
            "favorite": 20, "reply": 0, "share": 0, "pages": 1, "tid": 0,
            "state": 0, "pubdate": 0, "verified": True}
        globals()["_search_api"] = lambda kw, page=1: []
        globals()["_search_page"] = lambda kw: []
        zero_res = recommend("数轴 动点 行程", subject="数学", grade="七年级",
                             prefs=p, verbose=False)
    finally:
        globals()["verify"] = saved_v
        globals()["_search_api"] = saved_api
        globals()["_search_page"] = saved_page
        SAMPLES.extend(saved2)
    checks.append(("R7 0 条可推荐时 preferred_up_hit 为 false",
                   zero_res["preferred_up_hit"] is False
                   and not zero_res["items"]))
    checks.append(("R7 0 条可推荐时输出诚实声明",
                   bool(zero_res["honesty_note"])
                   and "暂无对应课" not in zero_res["honesty_note"]))

    saved = SAMPLES[:]
    try:
        SAMPLES.clear()
        fb = recommend("冷门考点", subject="数学", offline=True, prefs=p)["fallback"]
        checks.append(("零召回 → SEARCH 兜底，不编 BV", bool(fb and fb["type"] == "SEARCH")))
        checks.append(("无首选 UP 课时给出诚实声明",
                       bool(recommend("冷门考点", subject="数学", offline=True,
                                      prefs=p)["honesty_note"])))
    finally:
        SAMPLES.extend(saved)

    print("=== video_recommender v2 离线自测（不联网） ===")
    for name, passed in checks:
        print(("  PASS  " if passed else "  FAIL  ") + name)
    print("\n排序结果：")
    for x in res["items"]:
        print(f"  {x['score']:>5}  {x['tier']}  {x['grade']:<5} {x['duration']:>6}  "
              f"{''.join(x['tags']):<16} {x['title'][:34]}")
    ok = all(c[1] for c in checks)
    print("\n结论:", "全部通过" if ok else "存在失败项")
    return 0 if ok else 1


def _print_human(r: dict) -> None:
    q = r["query"]
    print(f"知识点：{q['kp']}  |  学科：{q['subject'] or '-'}  |  学段：{q['grade'] or '-'}  "
          f"|  难题模式：{'是' if q['hard'] else '否'}")
    print(f"召回 {r['recalled']} / 核实通过 {r['verified']}  |  指定 UP：{q['preferred_up'] or '-'}"
          f"  |  命中：{'是' if r['preferred_up_hit'] else '否'}")
    print("关键词：" + " / ".join(r["keywords"]))
    if r["honesty_note"]:
        print("⚠ " + r["honesty_note"])
    print()
    for x in r["items"]:
        print(f"[{x['tier']}] {x['score']} 分 / {x['grade']}  {''.join(x['tags'])}  {x['title']}")
        print(f"       {x['author']} · {x['duration']} · 播放 {x['play']:,} · {x['url']}")
        print(f"       四维 {x['breakdown']} · 质量门 {x['quality_gate']}")
        print(f"       理由 {x['reason']}")
        print(f"       看哪段 {x['watch_hint']}")
    if r["coverage"]:
        c = r["coverage"]
        print(f"\n覆盖度：{c['covered']}/{len(c['topics'])}  {'PASS' if c['pass'] else 'FAIL'}"
              f"  缺={c['missing']}  不对症={c['offtopic']}")
    if r["hard_question"]:
        h = r["hard_question"]
        print(f"难题逐题审计：{h['verdict']} — {h['reason']}；{h['advice']}")
        if h.get("method_breakdown"):
            print("核心方法拆解：")
            for i, s in enumerate(h["method_breakdown"], 1):
                print(f"  {i}. {s}")
            if h.get("method_note"):
                print(f"  注：{h['method_note']}")
    if r["fallback"]:
        f = r["fallback"]
        print(f"\n[兜底] {f['note']}\n       关键词：{f['keyword']}\n       {f['url']}")
    print("\n--- DSL VID 行（可直接进讲义 DSL 源） ---")
    for line in r["dsl"]:
        print(line)


def main() -> int:
    ap = argparse.ArgumentParser(description="B 站学习视频推荐算法 v2")
    ap.add_argument("--kp", help="知识点，如「绝对值最小值」")
    ap.add_argument("--subject", default="", help="学科（数学会启用指定 UP 优先）")
    ap.add_argument("--grade", default="", help="学段，如「七年级」")
    ap.add_argument("--error-type", default="", help="错因/题型，补一路搜索词")
    ap.add_argument("--extra", default="", help="补充限定词")
    ap.add_argument("--unit", default="", help="单元键，用于命门课置顶")
    ap.add_argument("--topics", default="", help="当天题型清单，逗号分隔，用于覆盖度审计")
    ap.add_argument("--hard", action="store_true", help="难题/压轴模式：逐题定向检索 + 三档审计")
    ap.add_argument("--question", default="", help="难题题干，用于构造针对性关键词")
    ap.add_argument("--up", default="", help="覆盖默认首选 UP 主名")
    ap.add_argument("--limit", type=int, default=3)
    ap.add_argument("--offline", action="store_true", help="内置样例跑算法，不联网")
    ap.add_argument("--json", action="store_true", help="只输出 JSON")
    ap.add_argument("--verbose", action="store_true")
    ap.add_argument("--selftest", action="store_true", help="离线自测")
    ap.add_argument("--mark-effective", metavar="BV", help="登记「实测有效」到本地偏好")
    ap.add_argument("--note", default="", help="配合 --mark-effective 的效果说明")
    a = ap.parse_args()

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    if a.selftest:
        return selftest()
    if a.mark_effective:
        # P1-8：BV 号格式必须合法，否则会往本地偏好里写垃圾键还白送 +10 分
        if not re.fullmatch(r"BV[0-9A-Za-z]{10}", a.mark_effective):
            ap.error(f"--mark-effective 需要合法的 BV 号（形如 BV1xxxxxxxxx），"
                     f"收到：{a.mark_effective!r}")
        p = Prefs()
        p.data.setdefault("verified", {})[a.mark_effective] = a.note or "孩子看完能自己复述方法"
        p.save()
        print(f"已登记实测有效：{a.mark_effective} → {p.path}")
        return 0
    if not a.kp:
        ap.error("需要 --kp，或用 --selftest")
    # P1-7：难题定向检索必须有题干，否则「难题专项检索」名存实亡
    if a.hard and not a.question.strip():
        ap.error("--hard（难题/压轴模式）必须同时提供 --question 题干："
                 "没有题干就无法做逐题定向检索")

    prefs = Prefs()
    if a.up:
        prefs.data.setdefault("preferred_up", {})[a.subject or "数学"] = a.up
    try:
        res = recommend(a.kp, a.subject, a.grade, a.error_type, a.extra, a.limit,
                        a.unit, [t for t in a.topics.split(",") if t.strip()],
                        a.hard, a.question, a.up, a.offline, prefs, a.verbose)
    except Exception as e:  # noqa: BLE001
        print(f"推荐失败：{type(e).__name__}: {e}", file=sys.stderr)
        return 2
    if a.json:
        print(json.dumps(res, ensure_ascii=False, indent=2))
    else:
        _print_human(res)
    return 0


if __name__ == "__main__":
    sys.exit(main())
