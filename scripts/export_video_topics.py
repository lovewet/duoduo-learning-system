# -*- coding: utf-8 -*-
"""export_video_topics.py —— 从结构化诊断 JSON 导出 topics.json（§8 视频批量引擎入口）

SKILL.md §8.1 说 topics.json「由结构化诊断 JSON 的 items[].core_terms / method_terms /
question_features 生成」，但包里原本没有任何脚本能生成它 —— 使用者第一次跑批量挂接
必然 FileNotFoundError。本脚本补上这一环：诊断 JSON 进，topics.json 出。

数据说明（本技能包不含任何学生数据）：
  * 本脚本**不含任何学生数据**，也不读写学生主库；
  * 输出只含**考点词**（subject / knowledge_point / core_terms / method_terms /
    question_features / unit / question_type / source），
    不含题干原文、得分、姓名、学校等任何个人信息；
  * 诊断 JSON 里若带学生字段，一律不往 topics.json 里搬。

输入（两种顶层形态都吃）：
  * {"items": [ {...}, ... ]}   —— 诊断主格式（references/diagnosis-schema.md）
  * [ {...}, ... ]              —— 顶层直接是数组

每条 item 的读取规则（缺字段一律容错，不崩）：
  * question_id / id          → topic_id；两个都缺时按 Q1、Q2… 顺序补齐
  * subject                   → 引擎强制要求非空，缺则跳过并计数
  * knowledge_point           → 引擎强制要求非空，缺则跳过并计数（不静默造坏 topic）
  * core_terms / method_terms → 字符串数组；给字符串时按空白/逗号拆成词表
  * question_features         → 字符串数组或字符串；给字符串时整条当一个检索词
    （专项轮要的就是「取整函数 {x}=x−[x] 小数部分 初一」这种完整短语，不能拆）
  * unit / question_type(qtype) / source → 可选字符串
  * video_needed              → false 的题不导出（SKILL.md 明令），--include-no-video 可放开

输出（与 scripts/bili_video_engine.py 的 load_topics() 完全兼容）：
  {"topics": [{"topic_id","subject","knowledge_point","core_terms","method_terms",
               "question_features","unit","question_type","source"}, ...]}

用法：
    python scripts/export_video_topics.py --diagnosis <诊断.json> --out topics.json
    python scripts/export_video_topics.py --diagnosis <诊断.json> --out topics.json --include-no-video
    python scripts/export_video_topics.py --selftest

接着交给批量引擎（dry-run 不联网，可安全自检）：
    python scripts/bili_video_engine.py --topics topics.json --out OUT_DIR --dry-run

只用标准库，无第三方依赖。
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
SKILL_ROOT = HERE.parent
ENGINE_FILE = HERE / "bili_video_engine.py"

# 跳过原因分类（导出摘要里逐类计数，便于回溯「为什么这题没进 topics」）
SKIP_NO_VIDEO = "video_needed=false"
SKIP_NO_SUBJECT = "缺学科 subject"
SKIP_NO_KP = "缺知识点 knowledge_point"
SKIP_NOT_ITEM = "item 不是对象"

# 引擎 load_topics() 强制要求非空的三个字段
REQUIRED_FIELDS = ("topic_id", "subject", "knowledge_point")

# core_terms / method_terms 给字符串时的分词分隔符（考点词之间没有空格语义）
TERM_SPLIT_RE = re.compile(r"[\s,，、/|]+")


# --------------------------------------------------------------------------- #
# 取值工具：诊断 JSON 里字段类型很杂（字符串 / 数组 / null 混着来），全部容错
# --------------------------------------------------------------------------- #
def _text(value) -> str:
    """转成干净字符串；None / 空容器返回空串。"""
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, bool):
        return ""
    if isinstance(value, (int, float)):
        return str(value)
    return ""


def _terms(value, split_ws: bool = False) -> list[str]:
    """把 core_terms / method_terms / question_features 归一成字符串数组。

    * 字符串 → 默认按整条包成单元素（引擎按数组逐个做子串命中，字符串原样传下去
      会被逐字拆成单字，等于没给检索词）；split_ws=True 时才按空白/逗号拆开。
    * 数组 → 逐项去空白、去空项、去重（保序）。
    * 数字 → 当单元素处理；布尔 / 嵌套对象与数组 → 丢弃。
    """
    if value is None:
        return []
    raw: list = []
    if isinstance(value, str):
        raw = [value]
    elif isinstance(value, (list, tuple)):
        raw = list(value)
    elif isinstance(value, (int, float)):
        raw = [value]
    else:
        return []

    out: list[str] = []
    seen: set[str] = set()
    for x in raw:
        if isinstance(x, bool) or not isinstance(x, (str, int, float)):
            continue
        s = str(x).strip()
        if not s:
            continue
        parts = TERM_SPLIT_RE.split(s) if split_ws else [s]
        for part in parts:
            part = part.strip()
            if not part or part in seen:
                continue
            seen.add(part)
            out.append(part)
    return out


def _first(item: dict, *keys: str) -> str:
    """按候选键顺序取第一个非空字符串（容错字段别名，如 question_id / id）。"""
    for k in keys:
        s = _text(item.get(k))
        if s:
            return s
    return ""


def _video_needed(item: dict) -> bool:
    """video_needed 判定：缺省视为需要视频；false / "false" / 0 视为不需要。"""
    if "video_needed" not in item:
        return True
    v = item.get("video_needed")
    if isinstance(v, str):
        return v.strip().lower() not in ("false", "0", "no", "否", "不")
    return bool(v)


# --------------------------------------------------------------------------- #
# 读取诊断 JSON
# --------------------------------------------------------------------------- #
def items_from_obj(raw) -> list[dict]:
    """从已解析的 JSON 对象取逐题条目（顶层数组或 {"items":[...]} 都吃）。

    顶层结构不对时抛 ValueError（中文信息，CLI 转成友好报错 + 退出码 2）。
    """
    if isinstance(raw, dict):
        if "items" not in raw:
            raise ValueError(
                "--diagnosis 顶层结构不对：需要 {\"items\":[...]} 或顶层直接是数组"
                f"（当前顶层键：{list(raw.keys())}）")
        items = raw.get("items")
        if not isinstance(items, list):
            raise ValueError("--diagnosis 里 items 必须是数组")
        return items
    if isinstance(raw, list):
        return raw
    raise ValueError(
        "--diagnosis 顶层结构不对：需要 {\"items\":[...]} 或顶层直接是数组"
        f"（当前类型：{type(raw).__name__}）")


def load_items(path: str) -> list[dict]:
    """读诊断 JSON 文件并取出逐题条目；出错抛 ValueError（中文，不裸 traceback）。"""
    p = Path(path)
    if not p.exists():
        raise ValueError(f"--diagnosis 文件不存在：{path}")
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise ValueError(f"--diagnosis 文件无法解析为 JSON：{e}") from e
    return items_from_obj(raw)


# --------------------------------------------------------------------------- #
# 导出
# --------------------------------------------------------------------------- #
def build_topics(items: list[dict], include_no_video: bool = False
                 ) -> tuple[list[dict], dict]:
    """把诊断条目转成 topics 列表。

    返回 (topics, stats)；stats 含总数 / 导出数 / 跳过数 / 跳过原因分类计数 /
    重复 topic_id 改名数。跳过原因必须计数 —— 少导出一条要能说清为什么。
    """
    topics: list[dict] = []
    skip_reasons: dict[str, int] = {}
    used_ids: set[str] = set()
    renamed = 0
    auto_seq = 0

    def _skip(reason: str) -> None:
        skip_reasons[reason] = skip_reasons.get(reason, 0) + 1

    for item in items:
        if not isinstance(item, dict):
            _skip(SKIP_NOT_ITEM)
            continue
        if not include_no_video and not _video_needed(item):
            _skip(SKIP_NO_VIDEO)
            continue

        subject = _first(item, "subject")
        if not subject:
            _skip(SKIP_NO_SUBJECT)
            continue
        kp = _first(item, "knowledge_point")
        if not kp:
            # 引擎 load_topics() 强制要求 knowledge_point 非空 → 跳过并计数，
            # 绝不静默产出引擎读不进去的坏 topic
            _skip(SKIP_NO_KP)
            continue

        # topic_id：优先显式字段；缺失则按 Q1、Q2… 顺序补齐（跳过已占用的号）
        tid = _first(item, "question_id", "id", "item_id")
        if not tid:
            while True:
                auto_seq += 1
                tid = f"Q{auto_seq}"
                if tid not in used_ids:
                    break
        elif tid in used_ids:
            # 重名改写：引擎按 topic_id 落盘（out/<topic_id>.json），重名会互相覆盖
            renamed += 1
            base = tid
            n = 2
            while f"{base}-{n}" in used_ids:
                n += 1
            tid = f"{base}-{n}"
        used_ids.add(tid)

        topics.append({
            "topic_id": tid,
            "subject": subject,
            "knowledge_point": kp,
            "core_terms": _terms(item.get("core_terms"), split_ws=True),
            "method_terms": _terms(item.get("method_terms"), split_ws=True),
            "question_features": _terms(item.get("question_features")),
            "unit": _first(item, "unit"),
            "question_type": _first(item, "question_type", "qtype"),
            "source": _first(item, "source"),
        })

    stats = {
        "total_items": len(items),
        "exported": len(topics),
        "skipped": sum(skip_reasons.values()),
        "skip_reasons": skip_reasons,
        "renamed_ids": renamed,
    }
    return topics, stats


def write_topics(topics: list[dict], out_path: str) -> Path:
    """写 topics.json（引擎认 {"topics":[...]} 或裸数组，这里统一用前者）。"""
    p = Path(out_path)
    if p.parent and not p.parent.exists():
        p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"topics": topics}, ensure_ascii=False, indent=2),
                 encoding="utf-8")
    return p


def print_summary(stats: dict, out_path: str | None = None) -> None:
    """导出摘要：总 item 数 / 导出 topic 数 / 跳过数（附原因分类计数）。"""
    print("=== 诊断 → topics 导出 ===")
    print(f"总 item 数：{stats['total_items']}")
    print(f"导出 topic 数：{stats['exported']}")
    print(f"跳过数：{stats['skipped']}")
    for reason, n in sorted(stats["skip_reasons"].items(), key=lambda kv: -kv[1]):
        print(f"  · {reason}：{n}")
    if stats["renamed_ids"]:
        print(f"重复 topic_id 改名：{stats['renamed_ids']}")
    if out_path:
        print(f"已写出：{out_path}")


# --------------------------------------------------------------------------- #
# 自检
# --------------------------------------------------------------------------- #
SAMPLE_DIAGNOSIS = {
    "schema_version": "1.0",
    "diagnosis_id": "DIAG-SAMPLE-0001",
    "diagnosis_type": "exam_booklet_analysis",
    "items": [
        {   # 1) 完整条目：字段齐全
            "question_id": "Q-12",
            "subject": "数学",
            "knowledge_point": "绝对值 化简",
            "core_terms": ["绝对值", "化简"],
            "method_terms": ["零点分段"],
            "question_features": ["绝对值化简"],
            "unit": "数轴与绝对值",
            "question_type": "计算",
            "video_needed": True,
            "source": "期中诊断",
        },
        {   # 2) 只给 id（不叫 question_id）
            "id": "Q-13",
            "subject": "数学",
            "knowledge_point": "数轴 动点 行程",
            "core_terms": ["数轴", "动点", "行程"],
            "method_terms": ["分段讨论"],
            "question_features": ["动点 行程"],
            "unit": "数轴与绝对值",
            "question_type": "解答题",
            "source": "期中诊断",
        },
        {   # 3) 缺 topic_id → 顺序补 Q1
            "subject": "英语",
            "knowledge_point": "一般过去时",
            "core_terms": ["一般过去时"],
            "method_terms": [],
            "question_features": ["动词过去式 变形"],
            "unit": "",
            "question_type": "语法",
            "source": "期中诊断",
        },
        {   # 4) video_needed=false → 不导出
            "question_id": "Q-14",
            "subject": "语文",
            "knowledge_point": "现代文阅读 概括",
            "core_terms": ["概括"],
            "method_terms": [],
            "question_features": [],
            "video_needed": False,
            "source": "期中诊断",
        },
        {   # 5) 缺 knowledge_point → 跳过并计数
            "question_id": "Q-15",
            "subject": "数学",
            "core_terms": ["分式"],
            "method_terms": [],
            "question_features": [],
            "source": "期中诊断",
        },
        {   # 6) 缺 subject → 跳过并计数
            "question_id": "Q-16",
            "knowledge_point": "有理数 运算",
            "core_terms": ["有理数"],
            "method_terms": [],
            "question_features": [],
            "source": "期中诊断",
        },
        {   # 7) 重复 topic_id → 改名，避免引擎落盘互相覆盖
            "question_id": "Q-12",
            "subject": "数学",
            "knowledge_point": "绝对值 最值",
            "core_terms": ["绝对值", "最值"],
            "method_terms": [],
            "question_features": [],
            "unit": "数轴与绝对值",
            "question_type": "解答题",
            "source": "期中诊断",
        },
    ],
}


def _engine_load_topics():
    """动态加载 bili_video_engine.load_topics（按文件路径加载，避开包导入副作用）。"""
    if not ENGINE_FILE.exists():
        return None
    spec = importlib.util.spec_from_file_location("_bili_engine_for_export",
                                                  ENGINE_FILE)
    if spec is None or spec.loader is None:
        return None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return getattr(mod, "load_topics", None)


def selftest() -> int:
    """离线自检：不依赖外部文件，用内置样例走完整流程并回读校验。"""
    checks: list[tuple[str, bool]] = []

    # 直接用内置样例（不经文件），保证自检不依赖外部文件
    raw = json.loads(json.dumps(SAMPLE_DIAGNOSIS, ensure_ascii=False))
    items = items_from_obj(raw)

    topics, stats = build_topics(items)

    # 1) 导出条数正确：7 条 item → 4 条导出（1 条 video_needed=false、1 条缺 kp、
    #    1 条缺 subject 被跳过）
    checks.append((f"导出条数正确（4 条，实际 {stats['exported']}）",
                   stats["exported"] == 4))
    checks.append((f"总 item 数统计正确（7，实际 {stats['total_items']}）",
                   stats["total_items"] == 7))

    # 2) video_needed=false 的被排除
    checks.append(("video_needed=false 的题被排除",
                   stats["skip_reasons"].get(SKIP_NO_VIDEO) == 1
                   and all(t["topic_id"] != "Q-14" for t in topics)))

    # 3) 缺 topic_id 的自动补齐（Q1）
    auto = [t for t in topics if t["topic_id"] == "Q1"]
    checks.append(("缺 topic_id 的自动补齐为 Q1",
                   len(auto) == 1 and auto[0]["subject"] == "英语"))

    # 4) 缺 knowledge_point 的条目被跳过并计数
    checks.append(("缺 knowledge_point 的条目被跳过并计数",
                   stats["skip_reasons"].get(SKIP_NO_KP) == 1
                   and all(t["knowledge_point"] != "有理数 运算" for t in topics)))

    # 5) 缺 subject 的条目被跳过并计数（引擎强制要求 subject 非空）
    checks.append(("缺 subject 的条目被跳过并计数",
                   stats["skip_reasons"].get(SKIP_NO_SUBJECT) == 1))

    # 6) 重复 topic_id 被改名，不互相覆盖
    ids = [t["topic_id"] for t in topics]
    checks.append(("重复 topic_id 改名且不重号",
                   len(ids) == len(set(ids)) and stats["renamed_ids"] == 1))

    # 7) 输出字段齐全 + 词表字段已归一化
    ok_fields = all(all(f in t for f in REQUIRED_FIELDS) for t in topics)
    ok_lists = all(isinstance(t.get("core_terms"), list)
                   and isinstance(t.get("method_terms"), list)
                   and isinstance(t.get("question_features"), list)
                   for t in topics)
    checks.append(("每条 topic 都带引擎必填字段", ok_fields))
    checks.append(("词表字段一律是数组（不会把字符串逐字拆开）", ok_lists))

    # 8) question_features 给字符串时按整条包成一个检索词（专项轮要完整短语）
    eng = [t for t in topics if t["subject"] == "英语"]
    checks.append(("question_features 为字符串时归一为单元素数组",
                   bool(eng) and eng[0]["question_features"] == ["动词过去式 变形"]))

    # 9) core_terms 给字符串时按空白拆成词表
    str_core, _ = build_topics([{"subject": "数学", "knowledge_point": "绝对值 化简",
                                 "core_terms": "绝对值 化简"}])
    checks.append(("core_terms 为字符串时按空白拆成词表",
                   bool(str_core) and str_core[0]["core_terms"] == ["绝对值", "化简"]))

    # 10) --include-no-video 时 video_needed=false 的题会被导出
    topics_all, stats_all = build_topics(items, include_no_video=True)
    checks.append(("--include-no-video 会导出 video_needed=false 的题",
                   stats_all["exported"] == 5
                   and any(t["topic_id"] == "Q-14" for t in topics_all)))

    # 11) 顶层数组形态同样能读，且结果一致
    topics_arr, _ = build_topics(items_from_obj(raw["items"]))
    checks.append(("顶层直接是数组时导出结果一致",
                   [t["topic_id"] for t in topics_arr] == ids))

    # 12) 输出 JSON 能被引擎 load_topics() 读回
    loader = _engine_load_topics()
    readback_ok = False
    detail = ""
    if loader is None:
        detail = "（找不到 bili_video_engine.py）"
    else:
        try:
            with tempfile.TemporaryDirectory() as td:
                f = Path(td) / "topics.json"
                write_topics(topics, str(f))
                back = loader(str(f))
                readback_ok = (len(back) == len(topics)
                               and all(str(t.get("topic_id") or "").strip()
                                       and str(t.get("subject") or "").strip()
                                       and str(t.get("knowledge_point") or "").strip()
                                       for t in back))
        except Exception as e:                        # noqa: BLE001
            detail = f"（{type(e).__name__}: {e}）"
    checks.append(("输出 JSON 能被引擎 load_topics() 读回" + detail, readback_ok))

    # 13) 文件不存在 → ValueError（中文信息，CLI 转退出码 2）
    with tempfile.TemporaryDirectory() as td:
        missing = str(Path(td) / "不存在.json")
        try:
            load_items(missing)
            code_missing = 0
        except ValueError as e:
            code_missing = 2 if "不存在" in str(e) else 1
    checks.append(("诊断文件不存在 → 中文报错且退出码 2", code_missing == 2))

    # 14) 顶层结构不对 → ValueError（中文信息）
    try:
        items_from_obj({"no_items": []})
        shape_ok = False
    except ValueError:
        shape_ok = True
    checks.append(("顶层结构不对 → 中文报错", shape_ok))

    print("=== export_video_topics 离线自检（不联网、不依赖外部文件） ===")
    for name, passed in checks:
        print(("  PASS  " if passed else "  FAIL  ") + name)
    ok_all = all(p for _, p in checks)
    print("\n结论：", "全部通过" if ok_all else "存在失败项")
    print("PASS" if ok_all else "FAIL")
    return 0 if ok_all else 1


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def run_cli() -> int:
    ap = argparse.ArgumentParser(
        description="从结构化诊断 JSON 导出 topics.json（供 bili_video_engine.py 使用）",
        epilog="示例：python scripts/export_video_topics.py "
               "--diagnosis 诊断.json --out topics.json")
    ap.add_argument("--diagnosis", help="结构化诊断 JSON 路径（{\"items\":[...]} 或顶层数组）")
    ap.add_argument("--out", help="输出 topics.json 路径")
    ap.add_argument("--include-no-video", action="store_true",
                    help="连 video_needed=false 的题也导出（默认不导出）")
    ap.add_argument("--selftest", action="store_true",
                    help="离线自检：不联网、不依赖外部文件")
    args = ap.parse_args()

    if args.selftest:
        return selftest()

    if not args.diagnosis:
        ap.error("需要 --diagnosis <诊断.json>（或用 --selftest 离线自检）")
    if not args.out:
        ap.error("需要 --out <topics.json>")

    try:
        items = load_items(args.diagnosis)
    except ValueError as e:
        ap.error(str(e))
        return 2

    topics, stats = build_topics(items, include_no_video=args.include_no_video)
    print_summary(stats)

    if not topics:
        # 空 topics.json 引擎读不进去（load_topics 拒空列表）→ 明确报错，不留坏文件
        print("错误：没有任何可导出的题目（详见上方跳过原因），未写出 topics.json",
              file=sys.stderr)
        return 2

    try:
        write_topics(topics, args.out)
    except OSError as e:
        print(f"错误：topics.json 写入失败：{e}", file=sys.stderr)
        return 2
    print(f"已写出：{args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(run_cli())
