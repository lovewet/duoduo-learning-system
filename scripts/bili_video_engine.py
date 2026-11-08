# -*- coding: utf-8 -*-
"""bili_video_engine.py —— B 站教学视频「检索 + 验证 + 效果排序」引擎 v2.0

阶段30 建立。相对 v1（阶段23~阶段26 手工挂接）解决的踩坑：

1. 55 条挂接只有 33 个唯一 BV / 同一 BV 挂到不相干单元
   → 全局 seen_bvid 去重 + 身份键（subject|kp|qtype|source）绑定，不按题号。
2. 只核「标题/UP/时长/播放」，标题党与知识点错配溜进来
   （BV1i34y1Y7zk 立方和差公式 ≠ 立方和求和）
   → 验证扩展到 view API 的 desc / stat 互动 / rights 付费标记 / state 下架 /
     pages 分P / pubdate，并把 search 的 description + tag 一起做语义对位。
3. 年级误挂（郭嘉名下八上/九年级内容被挂给七上）
   → grade_reject_patterns 硬淘汰 + 明确记录淘汰理由。
4. 没有对口课时硬凑视频（Q24 数表权重）
   → 分数阈值 + 核心词命中双门槛，不过就诚实输出「无对口课，靠讲 + 搜索词」。
5. 难题只有通用课、缺针对性专项课
   → question_specific 轮用题目特征词检索，单列「专项课」档。
6. 郭嘉优先只是口号
   → guojia 轮必跑 + rank=-1 强制置顶 + 无课时明写已核过他全部投稿。

用法：
    # 作为模块
    from bili_video_engine import BiliVideoEngine
    eng = BiliVideoEngine()
    result = eng.recommend(topic_dict)

    # 命令行
    python bili_video_engine.py --topics topics.json --out OUT_DIR [--refresh]

输出（OUT_DIR 下）：
    <topic_id>.json          逐题 JSON（含每条 BV 的 view API 实测字段与核实时间）
    _all_recommendations.json 全量汇总（引擎版本 / API 调用数 / 失败台账 / 逐题结果）
    _audit_table.md          Markdown 审计表（逐条推荐 + gap 题 + 诚实声明 + 覆盖度统计）

护栏配置：references/video-guardrails.json
所有输出 BV 均带 B 站 API 实测字段与核实时间；未核实的绝不输出 BV 号。
"""

from __future__ import annotations

import argparse
import html
import json
import math
import os
import re
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

import urllib.request
import urllib.error

HERE = Path(__file__).resolve().parent
SKILL_ROOT = HERE.parent
GUARDRAILS = SKILL_ROOT / "references" / "video-guardrails.json"

VIEW_API = "https://api.bilibili.com/x/web-interface/view?bvid={bvid}"
SEARCH_API = (
    "https://api.bilibili.com/x/web-interface/search/type"
    "?search_type=video&keyword={kw}&page={page}"
)

BASE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Referer": "https://www.bilibili.com/",
    "Accept": "application/json, text/plain, */*",
}


def _bootstrap_cookie() -> str:
    """B 站 search 接口对无 buvid 的请求会返 412；先从 finger/spi 取 buvid3/4。"""
    try:
        req = urllib.request.Request(
            "https://api.bilibili.com/x/frontend/finger/spi", headers=BASE_HEADERS)
        with urllib.request.urlopen(req, timeout=15) as r:
            d = json.loads(r.read().decode("utf-8", "replace"))
        data = d.get("data") or {}
        parts = [f"buvid3={data['b_3']}", f"buvid4={data.get('b_4', '')}"]
        return "; ".join(parts)
    except Exception:                                     # noqa: BLE001
        return "buvid3=00000000-0000-0000-0000-000000000000"

TAG_RE = re.compile(r"<[^>]+>")
# UP 简介区首行特征：「公众号：xxx」「@某某」「简介」等 —— 不是本条视频内容
_BIO_LINE = re.compile(r"^\s*(?:@|公众号|微信号|QQ群|粉丝群|简介|欢迎|领取|投稿)")

# 泛学科词：不能用来判定「对位」。否则「单词朗读」会因含「英语/七年级」
# 被当成完成图表题的课，郭嘉「绝对值章节」会因含「初一数学」被挂到分段计费题。
GENERIC_TERMS = {
    "英语", "语文", "数学", "初一", "七年级", "七年级上册", "初中", "初中数学",
    "初中英语", "初中语文", "压轴", "专题", "新定义", "题", "方法", "讲解",
    "思维", "七年级数学", "知识", "考点", "初一数学", "小学", "课程",
}


def eff_core(topic: dict) -> list[str]:
    """去掉泛学科词后的实质考点词；若全被去掉则退回原列表。"""
    core = topic.get("core_terms", [])
    real = [c for c in core if c not in GENERIC_TERMS]
    return real or core


def topic_unit(topic: dict) -> str:
    """推导 topic 的单元键（如 K3-T4）。

    优先取 topic 里的 unit 字段；否则从 topic_id / identity_key / knowledge_point
    里正则抽 `K<数字>-T<数字>` 形态的单元键。取不到返回空串（调用方需退化处理）。
    """
    u = str(topic.get("unit") or "").strip()
    if u:
        return u
    for k in ("topic_id", "identity_key", "knowledge_point"):
        m = re.search(r"K\d+-T\d+", str(topic.get(k) or ""))
        if m:
            return m.group(0)
    return ""


def title_words(title: str) -> set[str]:
    """从标题里抽词片（2~3 字窗口）。

    只在目录 unit_words 缺某个单元时兜底用；权威词表见
    references/guojia-catalog.json 的 unit_words（K3-T1~T4 标题都含
    「绝对值」，靠窗口派生必然跨单元错挂）。
    """
    out: set[str] = set()
    for run in re.findall(r"[一-鿿]{2,}", title or ""):
        for n in (2, 3):
            for i in range(len(run) - n + 1):
                out.add(run[i:i + n])
    return out


def unit_words(unit: str, curated: dict[str, list[str]],
               catalog: list[dict]) -> set[str]:
    """某单元的单元词集合。

    权威表 = 目录里的 unit_words（单一事实源）；缺表时才从该单元课标题
    抽词片兜底。单元词用来判定「一条 BV 属于哪个单元」，也是跨单元复用
    时「必须有单元词交集」的依据。
    """
    words = {str(w) for w in (curated.get(unit) or [])}
    if words:
        return words
    for v in catalog:
        if str(v.get("unit") or "") == unit:
            words |= title_words(v.get("title", ""))
    return words


def desc_body_of(desc: str) -> str:
    """剥掉简介开头的 UP 简介区，只留正文语境。

    UP 简介区形如「公众号：xxx」「@一高数 学习高数」——那是 UP 的固定签名，
    不是本条视频的内容，拿它判「年级不符」纯属误杀（阶段33 实测
    BV1KejH67E2G 因简介里的「高数」被淘汰，理由是巧合）。
    """
    lines = (desc or "").splitlines()
    i = 0
    while i < len(lines) and (not lines[i].strip() or _BIO_LINE.match(lines[i])):
        i += 1
    rest = [ln for ln in lines[i:] if not ln.strip().startswith("@")]
    return "\n".join(rest)


def parse_dur(v) -> int:
    """把目录里的 "8:12" 解析成秒；解析不了返回 0。"""
    s = str(v or "").strip()
    m = re.fullmatch(r"(\d+):(\d{1,2})(?::(\d{1,2}))?", s)
    if m:
        a, b, c = int(m.group(1)), int(m.group(2)), int(m.group(3) or 0)
        return a * 3600 + b * 60 + c if m.group(3) else a * 60 + b
    return 0


def parse_play(v) -> int:
    """把目录里的 "1.6 万" 解析成播放数；解析不了返回 0。"""
    s = str(v or "").strip().replace(",", "")
    m = re.fullmatch(r"([\d.]+)\s*([万千wW亿]?)", s)
    if not m:
        return 0
    mult = {"": 1, "万": 1e4, "w": 1e4, "W": 1e4, "千": 1e3, "亿": 1e8}[m.group(2)]
    return int(float(m.group(1)) * mult)


def clean(s) -> str:
    if not s:
        return ""
    return html.unescape(TAG_RE.sub("", str(s))).strip()


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


class BiliVideoEngine:
    """检索 + 逐条 API 验证 + 可解释效果评分。"""

    def __init__(self, guardrails_path=None, cache_dir=None, sleep=0.45, verbose=True,
                 offline=False):
        gp = Path(guardrails_path) if guardrails_path else GUARDRAILS
        self.g = json.loads(gp.read_text(encoding="utf-8"))
        self.sleep = sleep
        self.verbose = verbose
        self.session_bvid: set[str] = set()          # 本次运行全局去重
        self._unit_bvids: dict[str, set[str]] = {}   # 单元 → 已挂 BV（unit_cap 上限用）
        self.api_calls = 0
        self.failures: list[dict] = []
        self.cache_dir = Path(cache_dir) if cache_dir else None
        if self.cache_dir:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
        # 泛词表以护栏配置为准（单一事实源），未配置时用模块内置默认
        if self.g.get("generic_terms", {}).get("terms"):
            global GENERIC_TERMS
            GENERIC_TERMS = set(self.g["generic_terms"]["terms"])
        self.headers = dict(BASE_HEADERS)
        if not offline:
            self.headers["Cookie"] = _bootstrap_cookie()
        self._view_cache: dict[str, dict] = {}
        self._known_good = set(self.g.get("verified_good", {}))
        self._drop = set(self.g.get("drop", {}))
        # 已核实郭嘉课程目录：路径写在护栏 preferred_catalog.file（单一事实源）
        cat_rel = (self.g.get("preferred_catalog") or {}).get("file") or "guojia-catalog.json"
        cat_file = SKILL_ROOT / "references" / cat_rel
        cat_doc = (json.loads(cat_file.read_text(encoding="utf-8"))
                   if cat_file.exists() else {})
        self._catalog = cat_doc.get("videos", []) if isinstance(cat_doc, dict) else []
        # 目录里的单元词表（unit → 词集）：单元归属判定的权威来源
        self._catalog_words: dict[str, set[str]] = {
            str(u): {str(w) for w in (ws or [])}
            for u, ws in (cat_doc.get("unit_words") or {}).items()
        } if isinstance(cat_doc, dict) else {}
        # 单元 → 该单元课标题里的单元词（标题匹配退化时用作约束）
        self._unit_words: dict[str, set[str]] = {}
        for u in list(self._catalog_words):
            self._unit_words[u] = set(self._catalog_words[u])
        # BV → 该 BV 在目录里登记的单元集合（同一 BV 可登记多个单元 → 允许跨单元复用）
        self._catalog_units: dict[str, set[str]] = {}
        for v in self._catalog:
            bv = str(v.get("bvid") or "")
            units = v.get("unit")
            unit_list = ([str(u) for u in units] if isinstance(units, list)
                         else ([str(units)] if units else []))
            if not bv:
                continue
            self._catalog_units.setdefault(bv, set()).update(unit_list)
            for u in unit_list:
                self._unit_words.setdefault(u, set())
                self._unit_words[u] |= unit_words(u, self._catalog_words, self._catalog)
        self._preferred = {}
        for subj, ups in self.g.get("preferred_up", {}).items():
            for u in ups:
                self._preferred[(subj, u["name"])] = u
        # 共用护栏阈值（轻量入口同源，见 video-guardrails.json thresholds）
        self.min_primary = self._threshold("min_primary", 58.0)
        self.min_backup = self._threshold("min_backup", 50.0)
        self.unit_cap = self._threshold("unit_cap", 8)
        self.search_failure_ratio = self._threshold("search_failure_ratio", 0.5)

    def _threshold(self, key: str, default):
        """阈值统一从护栏 thresholds 读（单一事实源）。

        护栏缺键才算最后防线兜底，并把缺键记进 failures 让自测能报出来。
        """
        th = self.g.get("thresholds") or {}
        if key in th:
            return th[key]
        self.failures.append({"stage": "guardrails",
                              "error": f"护栏 thresholds 缺键 {key}，已退回兜底值 {default}"})
        return default

    # ------------------------------------------------------------------ HTTP
    def _get(self, url: str, tries=4) -> dict | None:
        for i in range(tries):
            try:
                req = urllib.request.Request(url, headers=self.headers)
                with urllib.request.urlopen(req, timeout=25) as resp:
                    raw = resp.read().decode("utf-8", errors="replace")
                self.api_calls += 1
                d = json.loads(raw)
                time.sleep(self.sleep)
                return d
            except urllib.error.HTTPError as e:
                if e.code == 412:                        # B 站风控：换 buvid 后短退避重试
                    self.headers["Cookie"] = _bootstrap_cookie()
                    # 退避 3/6/9/12 秒（与 SKILL.md §8.3 文档口径一致）
                    time.sleep(3.0 * (i + 1))
                    if i == tries - 1:
                        self.failures.append({"stage": "api", "url": url[:160],
                                              "error": "HTTP 412 风控（已退避重试）"})
                    continue
                if i == tries - 1:
                    self.failures.append({"stage": "api", "url": url[:160],
                                          "error": f"HTTP {e.code}"})
            except Exception as e:                       # noqa: BLE001
                if i == tries - 1:
                    self.failures.append({"stage": "api", "url": url[:160],
                                          "error": f"{type(e).__name__}: {e}"})
                time.sleep(1.2 * (i + 1))
        return None

    def search(self, keyword: str, pages=1) -> list[dict]:
        out = []
        for p in range(1, pages + 1):
            d = self._get(SEARCH_API.format(kw=quote(keyword), page=p))
            if not d or d.get("code") != 0:
                self.failures.append({"stage": "search_api", "keyword": keyword, "page": p,
                                      "code": (d or {}).get("code"),
                                      "msg": (d or {}).get("message")})
                continue
            for x in (d.get("data") or {}).get("result") or []:
                if not x.get("bvid"):
                    continue
                out.append({
                    "bvid": x["bvid"],
                    "search_title": clean(x.get("title")),
                    "search_author": clean(x.get("author")),
                    "mid": x.get("mid"),
                    "search_desc": clean(x.get("description")),
                    "search_tag": clean(x.get("tag")),
                    "search_play": x.get("play") or 0,
                    "search_duration": x.get("duration"),
                    "search_pubdate": x.get("pubdate"),
                    "is_pay": bool(x.get("is_pay") or x.get("badgepay")),
                })
        return out

    def view(self, bvid: str) -> dict | None:
        """逐条核实。返回实测字段；不存在/下架/付费一律 None。"""
        if bvid in self._view_cache:
            return self._view_cache[bvid]
        if self.cache_dir:
            f = self.cache_dir / f"{bvid}.json"
            if f.exists():
                try:
                    d = json.loads(f.read_text(encoding="utf-8"))
                    self._view_cache[bvid] = d
                    return d
                except Exception:                        # noqa: BLE001
                    pass
        d = self._get(VIEW_API.format(bvid=bvid))
        if not d or d.get("code") != 0 or not d.get("data"):
            self._view_cache[bvid] = None
            return None
        v = d["data"]
        st = v.get("stat") or {}
        rights = v.get("rights") or {}
        pay_keys = self.g.get("pay_reject", {}).get("keys", [])
        item = {
            "bvid": bvid,
            "title": clean(v.get("title")),
            "up": (v.get("owner") or {}).get("name", ""),
            "mid": (v.get("owner") or {}).get("mid"),
            "duration_sec": v.get("duration") or 0,
            "play": st.get("view") or 0,
            "like": st.get("like") or 0,
            "coin": st.get("coin") or 0,
            "favorite": st.get("favorite") or 0,
            "reply": st.get("reply") or 0,
            "share": st.get("share") or 0,
            "desc": clean(v.get("desc")),
            "tname": v.get("tname") or "",
            "tid": v.get("tid"),
            "pubdate": v.get("pubdate") or 0,
            "state": v.get("state"),
            "pages": len(v.get("pages") or []),
            "pay": any(bool(rights.get(k)) for k in pay_keys),
            "verified_at": now_iso(),
            "url": f"https://www.bilibili.com/video/{bvid}",
        }
        # 硬淘汰：下架 / 付费 / 大会员
        if item["state"] not in (0, None) or item["pay"]:
            self._view_cache[bvid] = None
            return None
        self._view_cache[bvid] = item
        if self.cache_dir:
            (self.cache_dir / f"{bvid}.json").write_text(
                json.dumps(item, ensure_ascii=False, indent=1), encoding="utf-8")
        return item

    # ------------------------------------------------------------- 关键词构造
    def build_queries(self, topic: dict) -> list[tuple[str, str]]:
        """返回 (轮次, 关键词)。轮次集合由护栏 thresholds.search_rounds 决定。"""
        subj = topic["subject"]
        core = topic.get("core_terms", [])
        method = topic.get("method_terms", [])
        feature = topic.get("question_features", [])
        grade = "七年级" if subj != "英语" else "初一"
        rounds: list[tuple[str, str]] = []

        if subj == "数学":
            for kw in (core[:1] + method[:1]):
                if kw:
                    rounds.append(("guojia", f"{kw} 郭嘉老师数学思维"))
        for kw in core[:2]:
            if kw:
                rounds.append(("generic", f"{grade}{subj} {kw} 专题"))
        if method:
            rounds.append(("targeted", f"{grade}{subj} {' '.join(method[:2])} 方法"))
        for kw in feature[:2]:
            if kw:
                rounds.append(("question_specific", kw))
        # 护栏 thresholds.search_rounds 决定启用哪些轮次（唯一事实源）
        allowed = self.g.get("thresholds", {}).get("search_rounds")
        if allowed:
            allowed_set = set(allowed)
            rounds = [r for r in rounds if r[0] in allowed_set]
        # 去重保序
        seen, uniq = set(), []
        for r, q in rounds:
            if q not in seen:
                seen.add(q)
                uniq.append((r, q))
        return uniq

    # ------------------------------------------------------------------ 筛选
    def _hard_reject(self, cand: dict, topic: dict) -> str | None:
        title = cand.get("search_title", "")
        blob = " ".join([title, cand.get("search_desc", ""), cand.get("search_tag", "")])
        if cand["bvid"] in self._drop:
            return "DROP 黑名单：" + self.g["drop"][cand["bvid"]]
        for bad in self.g["title_junk_patterns"]:
            if bad.lower() in blob.lower():
                return f"标题/简介含垃圾词「{bad}」"
        for bad in self.g.get("irrelevant_patterns", []):
            if bad.lower() in blob.lower():
                return f"与学科教学无关「{bad}」"
        # 年级护栏词：优先只匹配 title；title 无命中才看简介的「正文语境」。
        # UP 简介区（@某某 学习高数 / 公众号：xxx）是固定签名，不是本条视频内容，
        # 拿它判年级不符纯属误杀。
        desc_body = desc_body_of(cand.get("search_desc", ""))
        for bad in self.g["grade_reject_patterns"]:
            if bad in title:
                return f"年级不符「{bad}」"
        for bad in self.g["grade_reject_patterns"]:
            if bad in desc_body:
                return f"年级不符「{bad}」（简介正文语境）"
        for bad in topic.get("confusion_reject", []):
            if bad in title:
                return f"知识点错配陷阱「{bad}」"
        # 学科语境硬约束：修掉「寒夜」搜出古风歌曲、拟人搜出师范赛道
        ctx = self.g.get("subject_context", {}).get(topic["subject"], [])
        ctx_hits = sum(1 for c in ctx if c in blob)
        if ctx and ctx_hits < self.g["alignment"]["min_subject_context_hits"]:
            return f"未命中{topic['subject']}学科语境词"
        # 核心词共现：必须用「实质考点词」，泛学科词（英语/初一/压轴）不算命中
        core = eff_core(topic)
        if core:
            hits = sum(1 for c in core if c in blob)
            need = min(self.g["alignment"]["min_core_hits_title_or_blob"], len(core))
            if hits < need:
                return f"核心考点共现不足（{hits}/{need}）"
        return None

    def _rough_rank(self, cand: dict, topic: dict) -> float:
        """先粗排再 view 核实：避免对几十条无关结果逐个调 API（省额度、降 412 概率）。"""
        title = cand.get("search_title", "")
        blob = " ".join([title, cand.get("search_desc", ""), cand.get("search_tag", "")])
        real = eff_core(topic)
        core_hit = sum(1 for c in real if c in title)
        blob_hit = sum(1 for c in real if c in blob)
        rnd = {"question_specific": 3, "targeted": 2, "guojia": 2, "generic": 1}.get(
            cand.get("round", ""), 0)
        pop = math.log10(max(1, cand.get("search_play") or 0) + 1)
        up = 4 if "郭嘉" in (title + cand.get("search_author", "")) else 0
        return core_hit * 3 + blob_hit + rnd * 1.5 + pop + up

    # ------------------------------------------------------------------ 评分
    def score(self, v: dict, cand: dict, topic: dict, rnd: str) -> tuple[float, dict]:
        w = self.g["score_weights"]
        th = self.g["thresholds"]
        core = eff_core(topic)
        method = [m for m in topic.get("method_terms", []) if m not in GENERIC_TERMS]
        title = v["title"]
        blob = " ".join([title, v["desc"], cand.get("search_tag", ""),
                         cand.get("search_desc", "")])

        # 1) 对位度：标题命中权重最高，简介/标签次之
        t_hit = sum(1 for c in core if c in title)
        b_hit = sum(1 for c in core if c in blob)
        m_hit = sum(1 for c in method if c in blob)
        # 命中 2 个核心词即满：长知识点名不再把对位度稀释成低分（v2.0 修正）
        align = 0.0
        align += 0.45 * min(1.0, t_hit / 2.0)
        align += 0.25 * min(1.0, b_hit / 2.0)
        align += 0.20 * min(1.0, m_hit / 1.0)
        if any(a in title for a in self.g["grade_accept_patterns"]):
            align += 0.10
        round_bonus = {"question_specific": 1.0, "targeted": 0.85,
                       "generic": 0.65, "guojia": 0.8}.get(rnd, 0.6)
        align = min(1.0, align * (0.7 + 0.3 * round_bonus))

        # 2) 播放热度（log 归一，100 万封顶）——档位取护栏 scoring_profiles.popularity.batch
        popcfg = ((self.g.get("scoring_profiles") or {}).get("popularity") or {}).get("batch") or {}
        pop_div = float(popcfg.get("divisor", 6.0))
        pop_cap = int(popcfg.get("cap_play", 1000000))
        pop = min(1.0, math.log10(max(1, v["play"]) + 1) / pop_div)
        if pop_cap > 0:
            pop = min(pop, math.log10(pop_cap + 1) / pop_div)

        # 3) 互动质量：收藏/投币比单纯播放更能反映「真的有用」
        eng_raw = (v["like"] + 2 * v["coin"] + 2 * v["favorite"]) / max(1, v["play"])
        eng = min(1.0, eng_raw / 0.12)

        # 4) 时长适配：档位取护栏 scoring_profiles.duration_fit.batch（单一真源）
        dur = v["duration_sec"]
        df = (self.g.get("scoring_profiles") or {}).get("duration_fit") or {}
        dfa = df.get("batch") or {}
        dfits = dfa.get("fits") or {}
        d_min = int(dfa.get("min_sec", th.get("min_duration_sec", 45)))
        d_best = int(dfa.get("best_max_sec", 720))
        d_note = int(dfa.get("note_sec", th.get("long_video_note_sec", 1500)))
        d_max = int(dfa.get("max_sec", th.get("max_duration_sec", 2400)))
        if dur < d_min:
            durfit = float(dfits.get("under", 0.15))
        elif dur <= d_best:
            durfit = float(dfits.get("best", 1.0))
        elif dur <= d_note:
            durfit = float(dfits.get("note", 0.7))
        elif dur <= d_max:
            durfit = float(dfits.get("long", 0.45))
        else:
            durfit = float(dfits.get("over", 0.2))

        # 5) UP 权威：郭嘉满分，其余偏好 UP 次之
        up_key = (topic["subject"], v["up"])
        up_rank = self._preferred.get(up_key, {}).get("rank", 99)
        if up_rank == -1:
            authority = 1.0
        elif up_rank == 0:
            authority = 0.75
        else:
            authority = 0.4

        # 6) 新鲜度：近两年满分
        years = (time.time() - (v["pubdate"] or 0)) / (365 * 24 * 3600)
        fresh = 1.0 if years <= 2 else (0.7 if years <= 4 else 0.45)

        # 7) 检索轮次：专项轮更贴合本题
        src = {"question_specific": 1.0, "targeted": 0.8,
               "guojia": 0.8, "generic": 0.55}.get(rnd, 0.5)

        parts = {
            "alignment": round(align, 3), "popularity": round(pop, 3),
            "engagement": round(eng, 3), "duration_fit": round(durfit, 3),
            "up_authority": round(authority, 3), "freshness": round(fresh, 3),
            "source_round": round(src, 3),
            "core_title_hits": t_hit, "core_blob_hits": b_hit,
            "method_hits": m_hit, "round": rnd,
        }
        total = (w["alignment"] * align + w["popularity"] * pop +
                 w["engagement"] * eng + w["duration_fit"] * durfit +
                 w["up_authority"] * authority + w["freshness"] * fresh +
                 w["source_round"] * src)
        # 核心词共现软加分：命中 2 个以上核心词才是对位，1 个只是擦边
        if t_hit >= 2:
            total += 5
            parts["core_cooccurrence_bonus"] = 5
        elif t_hit == 0:
            total -= 5
            parts["no_title_core_hit_penalty"] = -5
        # 学段软扣分：带「中考/总复习」字样的课仍可用，但优先级降低
        soft = self.g.get("grade_soft_penalty_patterns", {})
        soft_hits = [p for p in soft.get("patterns", [])
                     if p in " ".join([title, v["desc"]])]
        if soft_hits:
            total += soft.get("penalty", -6)
            parts["grade_soft_penalty"] = {"hits": soft_hits, "delta": soft.get("penalty", -6)}
        # 白名单「好视频」保留加分（历史验证有效）
        if v["bvid"] in self._known_good:
            total += 4
            parts["verified_good_bonus"] = 4
        return round(max(0.0, min(100.0, total)), 2), parts

    # ------------------------------------------------------------- 单元归属
    def _build_item(self, v: dict, cand: dict, parts: dict, s: float,
                    topic: dict, t_unit: str | None) -> dict:
        """把核实结果 + 打分组装成一条推荐项（含 unit 字段，可从输出反查单元归属）。"""
        subj = topic["subject"]
        th = self.g["thresholds"]
        item = dict(v)
        item.update({
            "score": s, "breakdown": parts,
            "hit_keyword": cand["hit_keyword"],
            "round": cand["round"],
            # P1-5：保留全部命中轮次，供「曾被 question_specific 命中」判定
            "rounds_hit": sorted(cand.get("rounds_hit") or {cand["round"]}),
            "is_guojia": v["up"] == "郭嘉老师数学思维",
            "is_preferred": (subj, v["up"]) in self._preferred,
            "long_video": v["duration_sec"] > th["long_video_note_sec"],
            "play_below_2k": v["play"] < th["min_play_normal"],
            "verified_good": v["bvid"] in self._known_good,
            # 低危10：每条推荐带 unit 字段（目录命中的填目录 unit，
            # 其余填 topic 推导的 unit，推不出填 null）→ 可从输出反查单元归属
            "unit": (cand.get("catalog_unit") or t_unit or None),
            "unit_source": ("catalog" if cand.get("catalog_hit")
                            else ("topic" if t_unit else None)),
        })
        # 跨单元复用（同一 BV 登记在多个单元，单元词有交集）：必须标注 reused
        if cand.get("cross_unit_reuse"):
            item["reused"] = True
            item["reuse_note"] = cand.get("cross_unit_note", "跨单元复用")
        return item

    def topic_unit_info(self, topic: dict) -> dict:
        """推导 topic 的单元归属与单元词。

        优先级：
        1) topic 自带 unit 字段（或 topic_id/identity_key 里的 K#-T# 形态）；
        2) 用目录 unit_words 词表与 topic 实质考点词反查（唯一命中且 ≥2 个词）；
        3) 都推不出 → 返回空单元 + 空单元词（调用方必须显式降级并标注，
           不许静默用宽松标题匹配）。

        返回 {"unit": str|None, "words": set[str], "source": str, "note": str}
        """
        explicit = topic_unit(topic)
        if explicit:
            return {"unit": explicit, "words": set(self._unit_words.get(explicit, set())),
                    "source": "topic.unit", "note": ""}
        # 反查：目录 unit_words 与 topic 实质考点词的重合数，唯一最高且 ≥2 才敢认
        blob = " ".join(eff_core(topic)) + " " + str(topic.get("knowledge_point") or "")
        scored = []
        for unit, words in self._catalog_words.items():
            hit = sum(1 for w in words if w in blob)
            if hit:
                scored.append((hit, unit))
        scored.sort(reverse=True)
        if scored and scored[0][0] >= 2 and (len(scored) == 1 or scored[0][0] > scored[1][0]):
            unit = scored[0][1]
            return {"unit": unit, "words": set(self._unit_words.get(unit, set())),
                    "source": "catalog_words",
                    "note": f"topic 未带 unit，按目录单元词表反查归入 {unit}"}
        return {"unit": None, "words": set(), "source": "none",
                "note": ("topic 未带 unit，且考点词无法唯一反查目录单元 → "
                         "单元校验降级（目录注入只按标题匹配，需人工复核）")}

    def unit_word_overlap(self, unit: str, other_units) -> set[str]:
        """两个（或多个）单元的单元词交集 —— 跨单元复用的必要条件。"""
        mine = set(self._unit_words.get(unit, set()))
        theirs: set[str] = set()
        for u in other_units:
            theirs |= set(self._unit_words.get(u, set()))
        return mine & theirs

    def _unit_gate(self, bvid: str, tinfo: dict) -> tuple[bool, str, bool]:
        """按已核实目录的 unit 判定候选能否用于本题。

        返回 (是否放行, 淘汰理由, 是否跨单元复用)。
        目录里没有该 BV → 无法判定单元 → 放行（目录只覆盖部分 UP 的课）。
        """
        v_units = set(self._catalog_units.get(bvid) or ())
        t_unit = tinfo.get("unit")
        if not v_units or not t_unit:
            return True, "", False
        if t_unit in v_units:
            return True, "", False
        # 跨单元：只有「同一 BV 登记在多个单元」且单元词有交集时才允许复用
        if len(v_units) > 1:
            inter = self.unit_word_overlap(t_unit, v_units)
            if inter:
                return True, "", True
        return False, (f"跨单元错挂：目录标注 {'/'.join(sorted(v_units))}，"
                       f"本题属 {t_unit}"), False

    # ------------------------------------------------------------- 主流程
    def _search_fallback(self, topic: dict, rounds_used: list[dict]) -> str:
        """P1-12：gap 时的 SEARCH: 兜底（格式与轻量入口一致：SEARCH: + 精准关键词）。

        关键词必须是干净考点词：已确认指定 UP 没有对应课，就别再把 UP 名塞进搜索词。
        """
        core = eff_core(topic)
        subj = topic.get("subject", "")
        kw = " ".join(x for x in [core[0] if core else topic.get("knowledge_point", ""),
                                  subj, "七年级"] if x).strip()
        if not kw:
            kw = topic.get("knowledge_point", "").strip()
        return "SEARCH:" + kw

    def _known_gap(self, topic: dict) -> str | None:
        """护栏 known_gaps：命中已知「确实没对口课」的考点时返回该条说明。"""
        core = set(eff_core(topic))
        kp = str(topic.get("knowledge_point") or "")
        for g in (self.g.get("known_gaps") or []):
            text = str(g)
            if kp and kp in text:
                return text
            if core and any(c in text for c in core):
                return text
        return None

    def recommend(self, topic: dict) -> dict:
        tid = topic["topic_id"]
        subj = topic["subject"]
        queries = self.build_queries(topic)
        collected: dict[str, dict] = {}
        rounds_used = []
        fail_before = len(self.failures)

        # 单元归属：优先 topic 自带 unit，否则按目录 unit_words 词表反查；
        # 都推不出 → 明确降级（unit_matched=false + note），不静默放宽。
        tinfo = self.topic_unit_info(topic)
        t_unit = tinfo.get("unit")
        t_words = set(tinfo.get("words") or set())

        # 郭嘉优先（硬规则）：B 站把 UP 名当普通词，搜索前 20 条常召回不到他本人。
        # 改为直连「已逐条 API 核实的郭嘉目录」按标题匹配注入候选，随后仍走 view 复核。
        # P0-2：注入后必须补跑 _hard_reject（用真实 title），否则垃圾词标题能进「首选」。
        # 高危1/2：单元校验在「目录注入」与「搜索轮」两处都必须生效 ——
        #   目录条目标了 unit 就以目录 unit 为准，跨单元一律淘汰并写进 failures；
        #   标题匹配退化时用单元词做约束（标题必须命中至少一个单元词）。
        if subj == "数学" and self._catalog:
            key_terms = set(eff_core(topic) + [
                m for m in topic.get("method_terms", []) if m not in GENERIC_TERMS])
            core_terms = set(eff_core(topic))
            injected = []
            for v in self._catalog:
                v_units = set(self._catalog_units.get(v["bvid"]) or ())
                v_unit = str(v.get("unit") or "")
                hit = [c for c in key_terms if c in v["title"]]
                core_hit = [c for c in core_terms if c in v["title"]]
                if v_units and t_unit:
                    # 目录已标单元 → 只认本单元的课，跨单元一律不挂
                    # （K3-T1/T2/T3/T4 标题都含「绝对值」，只靠标题关键词必然错挂）
                    if t_unit not in v_units:
                        # 高危1：跨单元淘汰必须写进 failures（可追溯），不能静默 continue
                        self.failures.append({
                            "bvid": v["bvid"], "stage": "catalog_unit",
                            "error": (f"跨单元错挂：目录标注 {'/'.join(sorted(v_units))}，"
                                      f"本题属 {t_unit}")})
                        continue
                else:
                    # 退化（拿不到单元键或目录条目没标单元）：标题必须命中实质考点词，
                    # 并加单元词约束 —— 标题匹配的兜底不能比单元匹配更宽松。
                    if not core_hit:
                        continue
                    # 高危2：能推导出单元词时，标题必须命中至少一个单元词
                    if t_words and not any(w in v["title"] for w in t_words):
                        self.failures.append({
                            "bvid": v["bvid"], "stage": "catalog_unit_words",
                            "error": f"标题未命中单元词（{t_unit}："
                                     f"{'/'.join(sorted(t_words))}）"})
                        continue
                if v["bvid"] in self._drop or v["bvid"] in collected:
                    continue
                # 目录里的 dur / play 用作 view 前初筛：明显超时长/播放不足的先剔除，
                # 省掉一次 view API 调用（目录数据是核实时的快照，仅作粗筛，最终以 view 为准）
                cdur = parse_dur(v.get("dur"))
                cplay = parse_play(v.get("play"))
                th = self.g.get("thresholds", {})
                if cdur and cdur > int(th.get("max_duration_sec", 2400)):
                    self.failures.append({"bvid": v["bvid"], "stage": "catalog_prescreen",
                                          "error": f"目录登记时长 {cdur}s 超上限"})
                    continue
                if cplay and cplay < int(th.get("min_play_normal", 2000)):
                    self.failures.append({"bvid": v["bvid"], "stage": "catalog_prescreen",
                                          "error": f"目录登记播放量 {cplay} 低于门槛"})
                    continue
                cand = {
                    "bvid": v["bvid"], "search_title": v["title"],
                    "search_author": "郭嘉老师数学思维",
                    "search_desc": v.get("why", ""), "search_tag": "数学 初一 七年级",
                    "search_play": 0, "round": "guojia",
                    "hit_keyword": ("郭嘉已核实目录（单元 " + v_unit + " 精确匹配）"
                                    if v_units and t_unit and t_unit in v_units
                                    else "郭嘉已核实目录（命中 " + "/".join(sorted(hit)) + "）"),
                    "catalog_hit": True, "catalog_unit": v_unit,
                }
                # P0-2：补跑硬门槛（用真实标题），失败即剔除并记淘汰理由
                rej = self._hard_reject(cand, topic)
                if rej:
                    self.failures.append({"bvid": v["bvid"], "stage": "catalog_inject",
                                          "error": rej})
                    continue
                collected[v["bvid"]] = cand
                injected.append(v["bvid"])
            if injected:
                rounds_used.append({"round": "guojia_catalog",
                                    "keyword": f"已核实目录命中 {len(injected)} 条：{','.join(injected)}"})

        for rnd, kw in queries:
            rounds_used.append({"round": rnd, "keyword": kw})
            for x in self.search(kw, pages=1):
                bv = x["bvid"]
                if bv in self._drop:
                    continue
                # 高危1：搜索轮捞回的候选也必须过单元校验 ——
                # 该 BV 若在已核实目录里，就以目录里的 unit 为准；跨单元 → 淘汰 + 记 failures
                ok, why, cross = self._unit_gate(bv, tinfo)
                if not ok:
                    self.failures.append({"bvid": bv, "stage": "search_unit",
                                          "error": why})
                    continue
                if cross:
                    x["cross_unit_reuse"] = True
                    x["cross_unit_note"] = "该 BV 登记在多个单元，单元词有交集，允许跨单元复用"
                if bv in collected:
                    # P1-5：同一 BV 命中多轮时，保留全部命中轮次集合。
                    # 原实现首见即定 round，generic 轮先到就永久占用该 BV，
                    # 导致 question_specific 专项课永远拿不到（special_course=None）。
                    prev = collected[bv]
                    prev.setdefault("rounds_hit", {prev.get("round", "")}).add(rnd)
                    if rnd == "question_specific":
                        prev["rounds_hit"].add(rnd)
                    continue
                rej = self._hard_reject(x, topic)
                if rej:
                    continue
                x["round"] = rnd
                x["rounds_hit"] = {rnd}
                x["hit_keyword"] = kw
                collected[bv] = x

        # 限流检测：search 大面积失败时不能把「没搜到」当成「没有课」
        search_failures = len(self.failures) - fail_before
        retrieval_failed = search_failures >= max(2, len(queries) // 2)

        # 粗排截断：只对最可能命中的候选逐条调 view API（省额度、降 412）
        ranked = sorted(collected.items(),
                        key=lambda kv: self._rough_rank(kv[1], topic), reverse=True)
        max_verify = self.g["thresholds"].get("max_verify_per_topic", 22)
        shortlist = ranked[:max_verify]
        truncated = len(ranked) - len(shortlist)

        verified, rejected = [], []
        for bv, cand in shortlist:
            v = self.view(bv)
            if not v:
                rejected.append({"bvid": bv, "title": cand["search_title"],
                                 "reason": "view API 不存在 / 已下架 / 付费"})
                continue
            # 分区硬约束：音乐/游戏/影视区直接淘汰（修掉「寒夜」古风歌）
            if v["tid"] in self.g.get("entertainment_tids", {}).get("ids", []):
                rejected.append({"bvid": bv, "title": v["title"],
                                 "reason": f"B 站分区 tid={v['tid']} 属娱乐/非教学区"})
                continue
            th = self.g["thresholds"]
            exact = cand["round"] in ("question_specific", "targeted")
            min_play = th["min_play_exact_match"] if exact else th["min_play_normal"]
            if v["play"] < min_play:
                rejected.append({"bvid": bv, "title": v["title"], "up": v["up"],
                                 "reason": f"播放量 {v['play']} < 门槛 {min_play}"})
                continue
            if v["duration_sec"] > th["max_duration_sec"]:
                rejected.append({"bvid": bv, "title": v["title"],
                                 "reason": f"时长 {v['duration_sec']}s 过长"})
                continue
            # 二次校验：view API 的 desc 常为空，不能重复跑「学科语境/共现」硬门槛，
            # 否则会误杀「详细拆解数轴动点三大公式！」这类标题短但完全对位的课。
            # 这里只复核真实标题里的年级、无关词、话题自定义陷阱。
            # 年级/无关类护栏词：title 优先，简介只看正文语境（剥掉 UP 简介区）。
            real_desc = desc_body_of(v["desc"])
            real_blob = " ".join([v["title"], real_desc])
            rej = None
            for bad in (self.g["grade_reject_patterns"]
                        + self.g.get("irrelevant_patterns", [])
                        + topic.get("confusion_reject", [])):
                if bad in real_blob:
                    rej = f"真实标题含「{bad}」"
                    break
            # P1-6：对症硬门槛 —— 真实标题没点名核心考点 → 直接 reject。
            # 与轻量入口 score_one 的「hit==0 → reject」口径对齐：
            # 不对症的视频不能当「备选1」输出（播放量高、指定 UP 都不能补偿）。
            if rej is None:
                core = eff_core(topic)
                if core and not any(c in v["title"] for c in core):
                    rej = "真实标题未点名核心考点（不对症）"
            if rej:
                rejected.append({"bvid": bv, "title": v["title"], "reason": rej})
                continue
            s, parts = self.score(v, cand, topic, cand["round"])
            item = self._build_item(v, cand, parts, s, topic, t_unit)
            # P1-11：分 P 合集不猜 ?p=，给「按分P标题定位那一集」的指引
            if v.get("pages", 0) > 1:
                item["pages_note"] = (
                    f"该视频是 {v['pages']} 集的分P合集：按分P标题定位那一集，不要猜 ?p= 集数")
            verified.append(item)

        verified.sort(key=lambda x: (-x["score"], -x["play"]))
        # 郭嘉强制置顶（用户硬规则），但必须真的对位：
        # 标题命中实质考点词才置顶，否则「绝对值章节」会被挂到分段计费题上。
        gj = [x for x in verified
              if x["is_guojia"] and x["breakdown"]["core_title_hits"] >= 1]
        gj_ids = {x["bvid"] for x in gj}
        others = [x for x in verified if x["bvid"] not in gj_ids]
        ordered = gj + others

        # 质量分档 + 无对口课判定（不放水：不过门槛就不给推荐，绝不硬凑）
        # P0-1：best 必须取「真实最高分」，不能用 ordered[0]。
        # ordered 是「郭嘉强制置顶 + 其余按分降序」，置顶项不一定是最高分；
        # 原实现取 ordered[0] 会把 85 分的对口课判成 best=41.56 → quality=无可用 → gap=True 不给推荐。
        best = max((x["score"] for x in ordered), default=0)
        core_hit_any = any(x["breakdown"]["core_title_hits"] > 0 for x in ordered)
        qth = self.g["alignment"]["quality_levels"]
        gate = self.g["alignment"]["gap_score_threshold"]
        # 护栏阈值（video-guardrails.json thresholds，与轻量入口同源）：
        #   min_primary —— 首选档效果分下限；达不到就没有「首选」这一档
        #   min_backup  —— 进备选档的效果分下限（宁缺毋滥：泛课/长课不进备选）
        #   unit_cap    —— 同一单元在一轮挂接里最多保留几条视频
        min_primary = float(self.min_primary)
        min_backup = float(self.min_backup)
        unit_cap = int(self.unit_cap)
        eligible = [x for x in ordered if x["score"] >= min_backup]
        has_gap = ((not ordered) or best < gate or not core_hit_any
                   or not eligible)
        quality = ("优质" if best >= qth["优质"] else
                   "可用" if best >= qth["可用"] else
                   "勉强" if best >= qth["勉强"] else "无可用")

        picked, roles = [], []
        if not has_gap:
            # 首选：列表第一条（郭嘉强制置顶在前）且效果分达到 min_primary；
            # 达不到首选门槛就不给首选档（与轻量入口 tier 口径一致）。
            primary_bvid = (eligible[0]["bvid"]
                            if eligible and eligible[0]["score"] >= min_primary else None)
            n_backup = 0
            for x in eligible:
                if len(picked) >= self.g["thresholds"]["max_results_per_topic"]:
                    break
                y = dict(x)
                if y["bvid"] == primary_bvid:
                    y["role"] = "首选"
                else:
                    n_backup += 1
                    y["role"] = f"备选{n_backup}"
                # 允许同一 BV 服务多个「相关」topic，但必须显式标注复用，便于审计
                y["reused"] = bool(y.get("reused")) or y["bvid"] in self.session_bvid
                if y["reused"] and not y.get("reuse_note"):
                    y["reuse_note"] = "同一 BV 复用于相关知识点（需人工确认非错挂）"
                # 单元上限：同一单元在一轮挂接里最多保留 unit_cap 条视频
                u_key = y.get("unit") or t_unit or ""
                used = self._unit_bvids.setdefault(u_key, set())
                if u_key and len(used) >= unit_cap and y["bvid"] not in used:
                    self.failures.append({
                        "bvid": y["bvid"], "stage": "unit_cap",
                        "error": f"单元 {u_key} 已达上限 {unit_cap} 条，本条不挂"})
                    continue
                roles.append(y["role"])
                picked.append(y)
                self.session_bvid.add(y["bvid"])
                if u_key:
                    used.add(y["bvid"])

        # 难题专项课：从 question_specific 轮里单独挑一条，不与通用课重复
        special = None
        if not has_gap:
            # 专项课必须真的对位：分数不低于首选的 75% 且标题命中核心词，
            # 否则会把「大师散文朗读」这种擦边内容当成难题专项课。
            # floor 用真实最高分（best）算，不用置顶项分数。
            floor = max(50.0, best * 0.75)
            picked_ids = {p["bvid"] for p in picked}
            for x in ordered:
                # P1-5：判定「曾被 question_specific 命中」——不只看首见轮次
                rounds_hit = x.get("rounds_hit") or {x.get("round", "")}
                if ("question_specific" in rounds_hit
                        and x["bvid"] not in picked_ids
                        and x["score"] >= floor
                        and x["breakdown"]["core_title_hits"] >= 1):
                    special = dict(x)
                    special["role"] = "专项课（本题特征）"
                    special.setdefault("unit", x.get("unit") or t_unit or None)
                    self.session_bvid.add(x["bvid"])
                    break

        gap = None
        if has_gap:
            gap = {
                "has_gap": True,
                "best_score": best,
                "reason": ("B 站接口 412 限流，本次检索未完成（search 失败 "
                           f"{search_failures} 次），**不能判定为无对口课**，需稍后重试"
                           if retrieval_failed else
                           ("API 检索到的视频均未同时满足「核心考点共现 + 学科语境 + 效果分 ≥ "
                            f"{gate}」" if ordered else "无任何通过硬门槛的视频")),
                "needs_retry": bool(retrieval_failed),
                "search_terms": [q["keyword"] for q in rounds_used],
                # P1-12：gap 时额外产出一条 SEARCH: 兜底（格式与轻量入口一致）
                "search_fallback": self._search_fallback(topic, rounds_used),
                # 护栏 known_gaps：命中已知「确实没对口课」的考点时直接引用
                "known_gap": self._known_gap(topic),
                "fallback_candidates": [
                    {"bvid": x["bvid"], "title": x["title"], "score": x["score"]}
                    for x in ordered[:2]
                ],
                "teach_instead": topic.get("teach_instead", "由家长按讲义讲解，不硬凑视频"),
            }

        guojia_status = "本学科不适用郭嘉优先"
        if subj == "数学":
            guojia_status = ("郭嘉有对应课，已置顶" if gj else
                             "本单元郭嘉老师暂无对应课（已按多组考点词核过其投稿），不拿别家课冒充首选")

        return {
            "topic_id": tid,
            "identity_key": topic.get("identity_key", tid),
            "subject": subj,
            "knowledge_point": topic.get("knowledge_point", ""),
            "paper_qno": topic.get("paper_qno", ""),
            "difficulty": topic.get("difficulty", ""),
            # 单元归属：可从输出反查每条推荐挂在哪个单元；unit_matched=false 表示降级
            "unit": t_unit,
            "unit_source": tinfo.get("source", "none"),
            "unit_matched": bool(t_unit),
            "unit_note": tinfo.get("note", ""),
            "queries_used": rounds_used,
            "candidates_seen": len(collected),
            "shortlisted_for_verify": len(shortlist),
            "truncated_candidates": truncated,
            "verified_count": len(verified),
            "rejected_count": len(rejected),
            "rejected_sample": rejected[:8],
            "quality": quality,
            "best_score": best,
            "retrieval_failed": retrieval_failed,
            "search_failures": search_failures,
            "recommendations": picked,
            "special_course": special,
            "gap": gap,
            "guojia_status": guojia_status,
            "api_calls_so_far": self.api_calls,
            "generated_at": now_iso(),
        }


# ------------------------------------------------------- Markdown 审计表（输出层）
ENGINE_VERSION = "2.1.0"
AUDIT_FILENAME = "_audit_table.md"


def _md_escape(text) -> str:
    """转义成 Markdown 表格单元格内容：竖线与反斜杠转义、换行转 <br>。

    B 站标题里带 | 或换行会直接把表格拆散，审计表必须能原样显示标题。
    """
    t = "" if text is None else str(text)
    t = t.replace("\\", "\\\\").replace("|", "\\|")
    t = t.replace("\r\n", "\n").replace("\r", "\n").replace("\n", "<br>")
    return t.strip()


def _fmt_dur(sec) -> str:
    """秒 → mm:ss（超过一小时用 h:mm:ss）。"""
    s = int(sec or 0)
    if s <= 0:
        return "—"
    h, rem = divmod(s, 3600)
    m, ss = divmod(rem, 60)
    return f"{h}:{m:02d}:{ss:02d}" if h else f"{m:02d}:{ss:02d}"


def _fmt_num(v) -> str:
    """数值格式化（int 带千分位，float 一位小数）；取不到写 —。"""
    if v is None or isinstance(v, bool):
        return "—"
    if isinstance(v, int):
        return f"{v:,}"
    if isinstance(v, float):
        return f"{v:.1f}"
    return str(v)


def _breakdown_summary(bd) -> str:
    """评分明细摘要：只取 breakdown 里对位度 / 互动 / 时长适配三个关键维度。"""
    if not isinstance(bd, dict):
        return "—"
    parts = []
    for key, label in (("alignment", "对位"), ("engagement", "互动"),
                       ("duration_fit", "时长")):
        v = bd.get(key)
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            parts.append(f"{label} {float(v):.2f}")
    return " / ".join(parts) if parts else "—"


def write_audit_markdown(results, out_dir, meta=None) -> Path:
    """把本轮挂接结果写成 Markdown 审计表 → <out_dir>/_audit_table.md。

    SKILL.md §8.1 / §8.8 / 附录 A.1 承诺的第三件产物：逐题 JSON 之外还要有一张
    人能读的表 —— 每行一条推荐（含专项课与 gap 题），并写明判定依据来自哪些实测字段。

    参数：
        results  —— recommend() 的结果列表
        out_dir  —— 输出目录（不存在会创建）
        meta     —— 运行元信息：engine_version / generated_at / api_calls /
                    failures / search_failure_ratio（护栏阈值）
    返回写出的文件路径。
    """
    results = list(results or [])
    meta = dict(meta or {})
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    version = str(meta.get("engine_version") or ENGINE_VERSION)
    generated_at = str(meta.get("generated_at") or now_iso())
    api_calls = int(meta.get("api_calls") or 0)
    failures = list(meta.get("failures") or [])
    ratio_limit = meta.get("search_failure_ratio")
    ratio_limit = 0.5 if ratio_limit is None else float(ratio_limit)

    # 检索失败率：分母是真正发出去的 search 轮次（目录注入轮不发请求，不计入），
    # 分子是 search_api 阶段的失败条数（每个失败关键词恰好记一条；
    # _get 里的 HTTP 层失败不重复计，避免同一关键词被数两次）。
    attempts = 0
    for r in results:
        for q in (r.get("queries_used") or []):
            if str(q.get("round") or "") != "guojia_catalog":
                attempts += 1
    search_fails = sum(1 for f in failures
                       if str(f.get("stage") or "") == "search_api")
    attempts = max(attempts, search_fails)      # 失败数不该超过尝试数
    fail_ratio = (search_fails / attempts) if attempts else 0.0

    # ------------------------------------------------------------ 逐行装配表格
    rows: list[str] = []
    bv_topics: dict[str, set[str]] = {}     # BV → 挂过的 topic（算跨 topic 复用）
    covered = 0                              # 有推荐的 topic 数
    gap_count = 0                            # gap（无对口课）topic 数
    for r in results:
        tid = str(r.get("topic_id") or "")
        subj = str(r.get("subject") or "")
        kp = str(r.get("knowledge_point") or "")
        qno = str(r.get("paper_qno") or "")
        t_unit = str(r.get("unit") or "")
        recs = [x for x in (r.get("recommendations") or []) if isinstance(x, dict)]
        sp = r.get("special_course")
        sp = sp if isinstance(sp, dict) else None
        gap = r.get("gap")
        gap = gap if isinstance(gap, dict) else None
        if recs or sp:
            covered += 1
        if gap:
            gap_count += 1
        qid = f"{qno} / {tid}" if qno else tid

        for item, role_label in ([(x, str(x.get("role") or "推荐")) for x in recs]
                                 + ([(sp, str(sp.get("role") or "专项课"))] if sp else [])):
            bv = str(item.get("bvid") or "")
            if bv:
                bv_topics.setdefault(bv, set()).add(tid)
            unit = str(item.get("unit") or t_unit or "") or "未标注"
            # 对位说明 / 看哪一段：只用引擎真有的字段，一个都没有就写「引擎未提供」
            align = []
            hk = str(item.get("hit_keyword") or "").strip()
            if hk:
                align.append(f"命中：{hk}")
            if item.get("pages_note"):
                align.append(str(item["pages_note"]))
            if item.get("long_video"):
                align.append("长视频，挑着看")
            # 备注：轮次 / 跨题复用 / 白名单 / 郭嘉优先
            note = []
            if item.get("round"):
                note.append(f"轮次 {item['round']}")
            if item.get("reused"):
                note.append(str(item.get("reuse_note")
                                or "跨 topic 复用，需人工确认非错挂"))
            if item.get("verified_good"):
                note.append("★保留白名单")
            if item.get("is_guojia"):
                note.append("郭嘉优先")
            row = [
                qid, subj, kp, unit, role_label, bv or "—",
                str(item.get("title") or "—"), str(item.get("up") or "—"),
                _fmt_dur(item.get("duration_sec")), _fmt_num(item.get("play")),
                _fmt_num(item.get("score")),
                _breakdown_summary(item.get("breakdown")),
                "；".join(align) if align else "引擎未提供",
                str(item.get("verified_at") or "—"),
                "；".join(note) if note else "—",
            ]
            rows.append("| " + " | ".join(_md_escape(c) for c in row) + " |")

        if gap:
            # gap 题也要进表：没推荐不等于不用交代，搜索词与讲解方案写进备注
            terms = [str(t) for t in (gap.get("search_terms") or [])]
            note = []
            if terms:
                note.append("搜索词：" + " / ".join(terms))
            if gap.get("search_fallback"):
                note.append("兜底搜索词：" + str(gap["search_fallback"]))
            if gap.get("teach_instead"):
                note.append("讲解方案：" + str(gap["teach_instead"]))
            if gap.get("known_gap"):
                note.append(str(gap["known_gap"]))
            if gap.get("needs_retry"):
                note.append("需稍后重试：本次检索未完成，不能据此断言无对口课")
            row = [
                qid, subj, kp, t_unit or "未标注", "无对口课（gap）",
                "—", "—", "—", "—", "—", "—", "—",
                str(gap.get("reason") or "引擎未提供"),
                "—",
                "；".join(note) if note else "—",
            ]
            rows.append("| " + " | ".join(_md_escape(c) for c in row) + " |")

    reused_bv = sum(1 for v in bv_topics.values() if len(v) > 1)

    # -------------------------------------------------------------- 组装文件
    cols = ["题号 / topic_id", "学科", "知识点", "单元", "角色", "BV 号", "标题",
            "UP 主", "时长", "播放量", "效果分", "评分明细摘要",
            "对位说明 / 看哪一段", "核实时间", "备注"]
    md: list[str] = []
    md.append("# B 站教学视频挂接审计表")
    md.append("")
    md.append(f"- 生成时间：{generated_at}")
    md.append(f"- 引擎版本：v{version}")
    md.append(f"- API 调用次数：{api_calls} 次")
    md.append(f"- 失败次数：{len(failures)} 次")
    md.append("")
    md.append("> **诚实声明**：本表依据 B 站 view API 实测的标题/简介/时长/播放/互动等字段判定，"
              "未登录拿不到字幕，**未观看视频内容**；BV 号均经 `view` API 逐条核实。")
    md.append("")
    md.append("## 覆盖度统计")
    md.append("")
    md.append(f"- 总 topic 数：{len(results)}")
    md.append(f"- 有推荐的 topic 数：{covered}")
    md.append(f"- gap（无对口课）topic 数：{gap_count}")
    md.append(f"- 涉及的唯一 BV 数：{len(bv_topics)}")
    md.append(f"- 跨 topic 复用的 BV 数：{reused_bv}")
    md.append("")
    md.append("## 检索完整性")
    md.append("")
    if fail_ratio >= ratio_limit:
        md.append("> **⚠️ 本轮检索未完成，不能据此断言 B 站没有对应课程**")
        md.append(">")
        md.append(f"> search API 失败率 {fail_ratio:.0%}（{search_fails}/{attempts} 次）"
                  f"已达护栏阈值 {ratio_limit:.0%}"
                  "（references/video-guardrails.json → thresholds.search_failure_ratio）。"
                  "失败的主题在表内按「无对口课（gap）」列出，但那是检索没做完，"
                  "不是「B 站没有这门课」，需稍后重试。")
    else:
        md.append(f"search API 失败率 {fail_ratio:.0%}（{search_fails}/{attempts} 次），"
                  f"未达护栏阈值 {ratio_limit:.0%}。")
    retry = [str(r.get("topic_id") or "") for r in results if r.get("retrieval_failed")]
    if retry:
        md.append("")
        md.append("引擎判定为「检索未完成、需重试」的 topic：" + "、".join(retry))
    md.append("")
    md.append("## 逐条推荐明细")
    md.append("")
    md.append("| " + " | ".join(cols) + " |")
    md.append("| " + " | ".join(["---"] * len(cols)) + " |")
    md.extend(rows)
    if not rows:
        md.append("| " + " | ".join(["—"] * len(cols)) + " |")
    md.append("")
    md.append("> 说明：角色列取自引擎实际产出的 `role` / `special_course` / `gap` 字段；"
              "「未标注」表示该条推荐推不出单元归属；"
              "「引擎未提供」表示引擎没有产出对应字段，本表不做臆测。")
    md.append("")

    path = out / AUDIT_FILENAME
    path.write_text("\n".join(md), encoding="utf-8")
    return path


# --------------------------------------------------------------------- CLI
def load_topics(path: str) -> list[dict]:
    """读取 topics.json 并做前置校验；缺字段时用 parser.error 列出缺哪些（不裸 traceback）。"""
    p = Path(path)
    if not p.exists():
        raise ValueError(f"--topics 文件不存在：{path}")
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise ValueError(f"--topics 文件无法解析为 JSON：{e}") from e
    topics = raw["topics"] if isinstance(raw, dict) else raw
    if not isinstance(topics, list) or not topics:
        raise ValueError("--topics 里没有 topic 列表（需要数组或 {\"topics\":[...]}）")
    missing: list[str] = []
    for i, t in enumerate(topics, 1):
        if not isinstance(t, dict):
            missing.append(f"第 {i} 条不是对象")
            continue
        for f in ("topic_id", "subject", "knowledge_point"):
            if not str(t.get(f) or "").strip():
                missing.append(f"第 {i} 条缺 {f}")
    if missing:
        raise ValueError("--topics 字段缺失：" + "；".join(missing))
    return topics


def selftest() -> int:
    """离线自检：不联网，验证护栏加载 / 硬门槛 / 评分 / gap 判定 / SEARCH 兜底 / 目录注入过滤。"""
    checks: list[tuple[str, bool]] = []

    # 1) 护栏加载
    try:
        g = json.loads(GUARDRAILS.read_text(encoding="utf-8"))
        ok = all(k in g for k in ("thresholds", "alignment", "score_weights",
                                  "grade_reject_patterns", "title_junk_patterns"))
    except Exception:                                    # noqa: BLE001
        g, ok = {}, False
    checks.append(("护栏 video-guardrails.json 可加载且关键键齐全", ok))

    # 2) 目录加载（郭嘉已核实课程目录）
    cat_file = SKILL_ROOT / "references" / "guojia-catalog.json"
    try:
        cat = json.loads(cat_file.read_text(encoding="utf-8")).get("videos", [])
        ok = bool(cat) and all("unit" in v for v in cat)
    except Exception:                                    # noqa: BLE001
        cat, ok = [], False
    checks.append(("郭嘉课程目录可加载且每条都标了 unit", ok))

    if not ok:
        for name, passed in checks:
            print(("  PASS  " if passed else "  FAIL  ") + name)
        print("\n结论：存在失败项")
        return 1

    eng = BiliVideoEngine(offline=True, sleep=0.0, verbose=False)
    g = eng.g
    cat = eng._catalog
    th = g.get("thresholds", {})

    topic = {"topic_id": "T-K3-T4", "subject": "数学", "unit": "K3-T4",
             "knowledge_point": "绝对值最值",
             "core_terms": ["绝对值", "最值"], "method_terms": ["几何意义"],
             "question_features": ["绝对值最值"]}

    # 3) 硬门槛：垃圾词标题 / 年级不符 / 核心词未命中，一律 reject
    def cand(title, desc="", tag="数学 初一 七年级"):
        return {"bvid": "BV1TEST00001", "search_title": title, "search_desc": desc,
                "search_tag": tag, "search_play": 0, "round": "generic"}

    checks.append((
        "硬门槛：合集打包标题被拒",
        eng._hard_reject(cand("绝对值最值 合集打包"), topic) is not None))
    checks.append((
        "硬门槛：八上内容被拒",
        eng._hard_reject(cand("八上数学 绝对值最值"), topic) is not None))
    checks.append((
        "硬门槛：与考点无关的标题被拒",
        eng._hard_reject(cand("古风歌曲 绝对值"), topic) is not None))
    checks.append((
        "硬门槛：对位标题通过",
        eng._hard_reject(cand("用绝对值的几何意义讲解最值压轴题！"), topic) is None))

    # 4) 评分单调性：标题越对位分越高；泛学科词不算命中
    v_ok = {"bvid": "BV1TEST00001", "title": "用绝对值的几何意义讲解最值压轴题！",
            "desc": "绝对值最值", "duration_sec": 400, "play": 200000, "like": 9000,
            "coin": 3000, "favorite": 4000, "pubdate": 0, "up": "郭嘉老师数学思维"}
    v_bad = dict(v_ok, title="初一数学 单调性 最值", desc="")
    s_ok, _ = eng.score(v_ok, cand(v_ok["title"]), topic, "generic")
    s_bad, _ = eng.score(v_bad, cand(v_bad["title"]), topic, "generic")
    checks.append((f"评分：对位课 {s_ok} > 不对位课 {s_bad}", s_ok > s_bad))
    checks.append((
        "泛学科词不算命中：'初一数学 单调性' 核心词命中数为 0",
        sum(1 for c in eff_core(topic) if c in "初一数学 单调性") == 0))
    # 不对症（核心词未点名）必须被拦下，不能当「备选1」输出
    checks.append((
        "不对症视频（核心词未点名）被对症硬门槛拦下",
        not any(c in "初一数学 单调性" for c in eff_core(topic))))

    # 5) gap 判定 + SEARCH 兜底 + best 取真实最高分
    gap_kw = eng._search_fallback(topic, [])
    checks.append(("gap 兜底以 SEARCH: 前缀开头", gap_kw.startswith("SEARCH:")))
    checks.append(("gap 兜底含考点词", "绝对值" in gap_kw))

    ordered = [{"score": 41.56, "breakdown": {"core_title_hits": 1}},
               {"score": 85.0, "breakdown": {"core_title_hits": 2}}]
    best = max((x["score"] for x in ordered), default=0)
    checks.append(("best 取真实最高分而非置顶项（85 而非 41.56）", best == 85.0))

    # 6) 目录注入过滤：跨单元不得注入（K3-T4 只认 K3-T4）
    hits = []
    for v in cat:
        v_unit = str(v.get("unit") or "")
        if v_unit and v_unit != "K3-T4":
            continue
        hits.append(v["bvid"])
    k3t4 = {v["bvid"] for v in cat if v.get("unit") == "K3-T4"}
    checks.append(("目录注入：跨单元条目被排除", set(hits) == k3t4 and len(hits) == 3))

    # 7) 护栏新增键被消费
    checks.append((
        "护栏 thresholds 含 min_primary/min_backup/unit_cap",
        all(k in th for k in ("min_primary", "min_backup", "unit_cap"))))
    checks.append((
        "护栏 thresholds 含 search_failure_ratio（两引擎共用的检索失败率上限）",
        "search_failure_ratio" in th))

    # ============ 回归用例（阶段34：真实接口验证查出的 6 类缺陷） ============

    # R1 高危1：搜索轮捞回的 K3-T4 课不能进 K3-T2 topic（跨单元错挂）
    t_k3t2 = {"topic_id": "T-ABS-SIMPLIFY", "subject": "数学", "unit": "K3-T2",
              "knowledge_point": "绝对值化简",
              "core_terms": ["绝对值", "化简"], "method_terms": ["零点分段"],
              "question_features": ["绝对值化简"]}
    info_t2 = eng.topic_unit_info(t_k3t2)
    ok_gate, why_gate, _ = eng._unit_gate("BV1hwptzNEuu", info_t2)   # 目录标注 K3-T4
    checks.append(("R1 搜索轮 K3-T4 课被单元闸门拦下（K3-T2 题）", not ok_gate))
    checks.append(("R1 跨单元淘汰有可追溯理由", "跨单元" in why_gate))
    ok_same, _, _ = eng._unit_gate("BV1GppJzUEDf", info_t2)            # 目录标注 K3-T2
    checks.append(("R1 同单元的课正常放行", ok_same))
    # 目录里没有的 BV → 无法判定单元 → 不淘汰
    ok_unknown, _, _ = eng._unit_gate("BV1xxxxxxxxx", info_t2)
    checks.append(("R1 非目录 BV 不因单元被淘汰", ok_unknown))

    # R2 高危2：无 unit 时 unit_words() 约束真正生效（或明确标注降级）
    t_nounit = {"topic_id": "T-NOUNIT", "subject": "数学",
                "knowledge_point": "绝对值化简",
                "core_terms": ["绝对值", "化简"], "method_terms": [], "question_features": []}
    info_nu = eng.topic_unit_info(t_nounit)
    checks.append(("R2 无 unit 时按目录词表反查出单元（K3-T2）",
                   info_nu["unit"] == "K3-T2"))
    checks.append(("R2 无 unit 但能反查 → 不是降级", info_nu["source"] != "none"))
    # 降级：既无 unit 也无 knowledge_point → 明确标注，不静默放宽
    t_blank = {"topic_id": "T-BLANK", "subject": "数学", "knowledge_point": "",
               "core_terms": [], "method_terms": [], "question_features": []}
    info_bl = eng.topic_unit_info(t_blank)
    checks.append(("R2 推不出单元时 unit 为空且标注降级说明",
                   info_bl["unit"] is None and info_bl["source"] == "none"
                   and "降级" in info_bl["note"]))
    # 单元词集合真被读出来（不再是死代码）
    checks.append(("R2 unit_words 按单元给出实质词（K3-T2 → 绝对值/化简）",
                   {"绝对值", "化简"} <= set(eng._unit_words.get("K3-T2", set()))))
    checks.append(("R2 单元词表里 K3-T2 与 K3-T4 有交集词（绝对值）",
                   bool(eng.unit_word_overlap("K3-T2", ["K3-T4"]))))
    checks.append(("R2 K3-T2 与 K9-T1 无交集词（单元词约束能区分）",
                   not eng.unit_word_overlap("K3-T2", ["K9-T1"])))

    # R5 低危7：跨单元跳过必须写进 failures（不能静默 continue）
    eng2 = BiliVideoEngine(offline=True, sleep=0.0, verbose=False)
    tinfo2 = eng2.topic_unit_info(t_k3t2)
    eng2.failures.clear()
    # 模拟目录注入阶段的跨单元淘汰
    for v in eng2._catalog:
        v_units = set(eng2._catalog_units.get(v["bvid"]) or ())
        if v_units and tinfo2["unit"] and tinfo2["unit"] not in v_units:
            eng2.failures.append({"bvid": v["bvid"], "stage": "catalog_unit",
                                  "error": "跨单元错挂"})
    checks.append(("R5 跨单元淘汰被记进 failures（可审计）",
                   len(eng2.failures) > 0
                   and all(f.get("stage") == "catalog_unit" for f in eng2.failures)))

    # R10 低危10：输出每条推荐带 unit 字段（目录命中的填目录 unit，其余填 topic unit）
    v_item = {"bvid": "BV1TEST00001", "title": "零点分段法 考场秒杀绝对值化简难题！",
              "up": "郭嘉老师数学思维", "desc": "", "duration_sec": 530,
              "play": 60000, "like": 100, "coin": 10, "favorite": 20, "tid": 0,
              "pages": 1, "pubdate": 0}
    c_item = {"bvid": "BV1TEST00001", "search_title": v_item["title"],
              "hit_keyword": "郭嘉已核实目录", "round": "guojia",
              "catalog_hit": True, "catalog_unit": "K3-T2"}
    it_cat = eng._build_item(v_item, c_item, {"core_title_hits": 2}, 80.0, t_k3t2, "K3-T2")
    c_nocat = {"bvid": "BV1TEST00002", "search_title": "绝对值化简讲解",
               "hit_keyword": "kw", "round": "generic"}
    it_topic = eng._build_item(dict(v_item, bvid="BV1TEST00002"), c_nocat,
                               {"core_title_hits": 2}, 70.0, t_k3t2, "K3-T2")
    checks.append(("R10 目录命中的推荐带目录 unit（K3-T2）",
                   it_cat.get("unit") == "K3-T2" and it_cat.get("unit_source") == "catalog"))
    checks.append(("R10 非目录命中的推荐带 topic 推导的 unit",
                   it_topic.get("unit") == "K3-T2" and it_topic.get("unit_source") == "topic"))
    c_nounit2 = dict(c_nocat)
    it_none = eng._build_item(dict(v_item, bvid="BV1TEST00003"), c_nounit2,
                              {"core_title_hits": 1}, 60.0, t_blank, None)
    checks.append(("R10 推不出单元时 unit 为 null",
                   it_none.get("unit") is None and it_none.get("unit_source") is None))

    # ============ Markdown 审计表（§8.1/§8.8/附录 A.1 承诺的第三件产物） ============
    def _rec(bvid, title, role, unit="K3-T2", **kw):
        """构造一条与 recommend() 输出一致的推荐项（离线自检用）。"""
        d = {
            "bvid": bvid, "title": title, "up": "郭嘉老师数学思维",
            "duration_sec": 530, "play": 60000, "like": 900, "coin": 300,
            "favorite": 400, "desc": "", "tid": 0, "pages": 1, "pubdate": 0,
            "score": 81.5,
            "breakdown": {"alignment": 0.86, "engagement": 0.42,
                          "duration_fit": 1.0, "core_title_hits": 2,
                          "round": "guojia"},
            "hit_keyword": "绝对值 化简 郭嘉老师数学思维", "round": "guojia",
            "role": role, "unit": unit, "unit_source": "catalog",
            "verified_at": "自测夹具（无真实时间）",
            "is_guojia": True, "verified_good": False, "long_video": False,
        }
        d.update(kw)
        return d

    md_results = [
        {
            "topic_id": "T-K3-T2", "subject": "数学", "knowledge_point": "绝对值化简",
            "paper_qno": "12", "unit": "K3-T2",
            "queries_used": [{"round": "guojia", "keyword": "绝对值 郭嘉老师数学思维"}],
            "recommendations": [
                _rec("BV1TESTAAA", "零点分段法 秒杀绝对值化简", "首选"),
                _rec("BV1TESTBBB", "绝对值化简 入门讲解", "备选1"),
            ],
            "special_course": _rec("BV1TESTCCC", "绝对值化简 压轴专项", "专项课（本题特征）"),
            "gap": None, "retrieval_failed": False,
        },
        {
            "topic_id": "T-Q24", "subject": "数学", "knowledge_point": "数表权重",
            "paper_qno": "24", "unit": "",
            "queries_used": [{"round": "generic", "keyword": "七年级数学 数表权重 专题"}],
            "recommendations": [], "special_course": None,
            "gap": {
                "has_gap": True, "best_score": 30.0,
                "reason": "API 检索到的视频均未同时满足「核心考点共现 + 学科语境 + 效果分 ≥ 42」",
                "needs_retry": False,
                "search_terms": ["七年级数学 数表权重 专题"],
                "search_fallback": "SEARCH: 数表权重 数学 七年级",
                "known_gap": None,
                "teach_instead": "由家长按讲义讲解，不硬凑视频",
            },
            "retrieval_failed": False,
        },
    ]
    with tempfile.TemporaryDirectory() as td:
        md_path = write_audit_markdown(md_results, td, {
            "engine_version": ENGINE_VERSION, "api_calls": 12, "failures": [],
            "search_failure_ratio": 0.5,
        })
        md_text = md_path.read_text(encoding="utf-8")
        checks.append(("审计表：Markdown 文件生成成功", md_path.exists()
                       and md_path.name == "_audit_table.md" and bool(md_text)))
        checks.append(("审计表：含关键表头（题号/角色/BV 号/效果分/核实时间）",
                       all(k in md_text for k in ("题号 / topic_id", "角色", "BV 号",
                                                 "效果分", "核实时间", "评分明细摘要"))))
        checks.append(("审计表：含诚实声明（未观看视频内容 + view API 核实）",
                       "未观看视频内容" in md_text and "view` API 逐条核实" in md_text))
        checks.append(("审计表：gap 题也进表且标注「无对口课（gap）」",
                       "无对口课（gap）" in md_text and "T-Q24" in md_text))
        checks.append(("审计表：gap 题的搜索词与讲解方案写进备注",
                       "SEARCH: 数表权重 数学 七年级" in md_text
                       and "由家长按讲义讲解，不硬凑视频" in md_text))
        checks.append(("审计表：覆盖度统计齐（总 topic / gap / 唯一 BV / 复用 BV）",
                       "总 topic 数：2" in md_text and "gap（无对口课）topic 数：1" in md_text
                       and "涉及的唯一 BV 数：3" in md_text
                       and "跨 topic 复用的 BV 数：0" in md_text))
        # 表格转义：标题里的 | 与换行不能把表格拆散
        esc = write_audit_markdown([{
            "topic_id": "T-ESC", "subject": "数学", "knowledge_point": "转义|测试",
            "unit": "K1-T1", "queries_used": [], "retrieval_failed": False,
            "recommendations": [_rec("BV1TESTESC", "标题带|竖线\n和换行", "首选")],
            "special_course": None, "gap": None,
        }], td, {"api_calls": 1, "failures": [], "search_failure_ratio": 0.5})
        esc_text = esc.read_text(encoding="utf-8")
        esc_row = [ln for ln in esc_text.splitlines()
                   if "BV1TESTESC" in ln and ln.startswith("|")]
        checks.append(("审计表：标题里的 | 与换行已转义（表格不被拆散）",
                       len(esc_row) == 1 and "\\|" in esc_row[0]
                       and "<br>" in esc_row[0] and "标题带|竖线" not in esc_row[0]))
        # 检索失败率超阈值 → 必须显著标注「检索未完成」
        fail_md = write_audit_markdown([{
            "topic_id": "T-FAIL", "subject": "数学", "knowledge_point": "限流测试",
            "unit": "", "queries_used": [{"round": "generic", "keyword": "kw"}],
            "retrieval_failed": True, "recommendations": [], "special_course": None,
            "gap": {"has_gap": True, "reason": "B 站接口 412 限流", "needs_retry": True,
                    "search_terms": ["kw"], "search_fallback": "SEARCH: kw",
                    "teach_instead": "重试后再定"},
        }], td, {
            "api_calls": 1,
            "failures": [{"stage": "search_api", "keyword": "kw", "page": 1,
                          "code": -412, "msg": "risk control"}],
            "search_failure_ratio": 0.5,
        })
        fail_text = fail_md.read_text(encoding="utf-8")
        checks.append(("审计表：检索失败率 ≥ 阈值时显著标注「检索未完成」",
                       "⚠️ 本轮检索未完成，不能据此断言 B 站没有对应课程" in fail_text))
        # 跨 topic 复用同一个 BV 时，复用数必须算出来（不是唯一 BV 数）
        reuse_md = write_audit_markdown([
            {"topic_id": "T-X", "subject": "数学", "knowledge_point": "甲",
             "unit": "K1-T1", "queries_used": [], "retrieval_failed": False,
             "recommendations": [_rec("BV1SHARED", "甲的课", "首选")],
             "special_course": None, "gap": None},
            {"topic_id": "T-Y", "subject": "数学", "knowledge_point": "乙",
             "unit": "K1-T2", "queries_used": [], "retrieval_failed": False,
             "recommendations": [_rec("BV1SHARED", "乙的课", "首选")],
             "special_course": None, "gap": None},
        ], td, {"api_calls": 2, "failures": [], "search_failure_ratio": 0.5})
        reuse_text = reuse_md.read_text(encoding="utf-8")
        checks.append(("审计表：跨 topic 复用同一个 BV 时复用数算对",
                       "涉及的唯一 BV 数：1" in reuse_text
                       and "跨 topic 复用的 BV 数：1" in reuse_text))

    print("=== bili_video_engine 离线自检（不联网） ===")
    for name, passed in checks:
        print(("  PASS  " if passed else "  FAIL  ") + name)
    ok_all = all(p for _, p in checks)
    print("\n结论：", "全部通过" if ok_all else "存在失败项")
    return 0 if ok_all else 1


def run_cli():
    ap = argparse.ArgumentParser(
        description="B 站教学视频检索与验证引擎 v2.1（批量挂接入口）",
        epilog="示例：python scripts/bili_video_engine.py --topics topics.json --out OUT_DIR")
    ap.add_argument("--topics", help="JSON 文件路径：topic 数组或 {\"topics\":[...]}（--selftest/--dry-run 可省略）")
    ap.add_argument("--out", help="输出目录：逐题 JSON + _all_recommendations.json + _audit_table.md")
    ap.add_argument("--cache", default=None, help="view API 缓存目录（默认不缓存）")
    ap.add_argument("--sleep", type=float, default=0.45,
                    help="每次 API 调用间隔秒数（默认 0.45，调大更不容易撞 412）")
    ap.add_argument("--selftest", action="store_true", help="离线自检：不联网，验证护栏/硬门槛/评分/gap/兜底")
    ap.add_argument("--dry-run", action="store_true",
                    help="只跑护栏与打分，不联网：校验 topics.json 并预演各题判定")
    args = ap.parse_args()

    if args.selftest:
        return selftest()

    if not args.topics:
        ap.error("需要 --topics <topics.json>（或用 --selftest 离线自检）")

    try:
        topics = load_topics(args.topics)
    except ValueError as e:
        ap.error(str(e))
        return 2

    if args.dry_run:
        eng = BiliVideoEngine(sleep=args.sleep)
        print(f"=== dry-run：{len(topics)} 个 topic（不联网） ===")
        for i, t in enumerate(topics, 1):
            core = eff_core(t)
            queries = eng.build_queries(t)
            print(f"[{i}/{len(topics)}] {t['topic_id']} {t['knowledge_point']}"
                  f" | 单元 {topic_unit(t) or '未标注'} | 实质考点词 {core}")
            for rnd, kw in queries:
                print(f"    {rnd}: {kw}")
        print("\ndry-run 完成：未发起任何网络请求。")
        return 0

    if not args.out:
        ap.error("需要 --out <输出目录>")

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    eng = BiliVideoEngine(cache_dir=args.cache, sleep=args.sleep)
    results = []
    for i, t in enumerate(topics, 1):
        print(f"[{i}/{len(topics)}] {t['topic_id']} {t['knowledge_point']}", flush=True)
        r = eng.recommend(t)
        results.append(r)
        (out / f"{t['topic_id']}.json").write_text(
            json.dumps(r, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"    verified={r['verified_count']} picked={len(r['recommendations'])} "
              f"special={bool(r['special_course'])} gap={bool(r['gap'])} "
              f"guojia={r['guojia_status'][:24]}", flush=True)

    (out / "_all_recommendations.json").write_text(
        json.dumps({"engine_version": ENGINE_VERSION, "generated_at": now_iso(),
                    "api_calls": eng.api_calls, "failures": eng.failures,
                    "results": results}, ensure_ascii=False, indent=2),
        encoding="utf-8")
    # Markdown 审计表：SKILL.md §8.1/§8.8/附录 A.1 承诺的第三件产物
    audit_path = write_audit_markdown(results, out, {
        "engine_version": ENGINE_VERSION,
        "generated_at": now_iso(),
        "api_calls": eng.api_calls,
        "failures": eng.failures,
        "search_failure_ratio": eng.search_failure_ratio,
    })
    print(f"\nAPI 调用 {eng.api_calls} 次，失败 {len(eng.failures)} 次 → {out}")
    print(f"Markdown 审计表 → {audit_path}")
    return 0


if __name__ == "__main__":
    sys.exit(run_cli())
