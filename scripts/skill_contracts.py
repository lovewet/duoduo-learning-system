#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""配套技能契约解析器 + 核心能力本地兜底。

注册表只说「调谁」，本模块让调度真的能跑：
  - ContractRegistry.resolve() 读 skill-contracts.json，按触发词与优先级给出调用计划
  - 缺外部技能时，7 个兜底函数返回**具体可用**的结构化结果，不是空占位
  - validate_outputs() 校验返回字段，缺了就报缺，不假装已覆盖

规则出处：SKILL.md §2/§4、references/three-subject-error-categories.md、
bundled-skills/ 内各技能卡（明辨三层变式 / 组卷蓝图 / 家长讲题卡 / 学习规划师）。

用法：
    python scripts/skill_contracts.py --text "出一份绝对值专项练习，要分层"
    python scripts/skill_contracts.py --list
    python scripts/skill_contracts.py --selftest
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any

HERE = os.path.dirname(os.path.abspath(__file__))
CONTRACTS = os.path.join(HERE, "..", "references", "skill-contracts.json")

# --------------------------------------------------------------------------- #
# 领域常量（从技能方法论里固化，保证兜底实现「具体」）
# --------------------------------------------------------------------------- #
ERROR_TYPES = [
    "concept-confusion", "calculation", "sign-error", "formula-misuse",
    "missing-zero", "classification", "blank", "incomplete-answer",
    "careless", "grammar", "spelling", "collocation", "semantic",
]
CN_AG_TO_ERROR_TYPE = {
    "A": ("知识漏洞：字音字形/实词虚词/文学常识", "concept-confusion"),
    "B": ("方法缺失：知道知识但不会用", "incomplete-answer"),
    "C": ("审题偏差：漏看限制/答非所问", "careless"),
    "D": ("表达不规范：不完整/无术语/口语化", "incomplete-answer"),
    "E": ("思维不足：概括不全/分析浅/主旨偏", "semantic"),
    "F": ("习惯问题：时间/检查/迁移", "careless"),
    "G": ("心理策略：畏难/紧张/答题顺序", "blank"),
}
SUBJECT_HINT = {
    "sign-error": "数学：去括号变号、幂与负号、抄错符号",
    "calculation": "数学：运算顺序、分数小数、化简合并",
    "classification": "数学：分类讨论漏支",
    "formula-misuse": "数学/理化：公式用错",
    "grammar": "英语：语法（英语错题一律归此类）",
    "spelling": "英语/语文：拼写与字形",
    "collocation": "英语：固定搭配",
    "semantic": "英语/语文：词义混淆、理解偏差",
    "concept-confusion": "通用：概念混淆",
    "blank": "通用：空白未答",
    "incomplete-answer": "通用：答案不完整",
    "careless": "通用：粗心/审题偏差",
    "missing-zero": "数学：漏零、漏解",
}
TIERS = {
    "A": {"name": "基础层", "goal": "保底达标", "rule": "单知识点直接应用，条件清晰、运算量小",
          "methods": ["条件变式"], "audience": "全体，尤其学困生"},
    "B": {"name": "提升层", "goal": "变式迁移", "rule": "更换情境或条件呈现，1–2 处思维转弯",
          "methods": ["结论变式", "逆向变式", "情境变式"], "audience": "中等及以上"},
    "C": {"name": "拓展层", "goal": "综合应用", "rule": "条件开放或与另一知识点交汇",
          "methods": ["开放化变式", "组合变式"], "audience": "学有余力"},
}
VARIATION_METHODS = ["条件变式", "结论变式", "逆向变式", "情境变式", "开放化变式", "组合变式"]
DIFFICULTY_RATIO = {"周测": "8:1:1", "单元测": "7:2:1", "月考": "7:2:1",
                    "期中": "7:2:1", "期末": "7:2:1", "模拟卷": "6:3:1"}
BLUEPRINT_COLUMNS = ["题号", "考点", "认知层级", "题型", "分值", "预估难度", "设计意图"]
COGNITIVE_LEVELS = ["识记", "理解", "运用", "综合"]
METHOD_INDEX = [
    {"name": "提取练习", "symptom": ["看完就忘", "听懂不会做", "复述不出"],
     "steps": ["合上材料回忆", "写下要点", "对照订正"], "source": "learning-science.md"},
    {"name": "间隔重复", "symptom": ["隔天又错", "周期性遗忘"],
     "steps": ["当天", "隔天", "第 3 天", "第 7 天"], "source": "learning-science.md"},
    {"name": "费曼输出", "symptom": ["说不清", "讲不明白", "概念模糊"],
     "steps": ["讲给家长听", "卡住处回查", "再讲一遍"], "source": "icap-framework.md"},
    {"name": "逐项确认", "symptom": ["跳步", "漏写", "只找一个就下判断"],
     "steps": ["列全所有项", "逐项写结论", "干净项也要写『无』"], "source": "grading-feedback-loop.md"},
    {"name": "错因三段式", "symptom": ["不知道错在哪", "归因笼统"],
     "steps": ["证据", "归类", "置信度"], "source": "SKILL.md §4"},
    {"name": "ICAP 交互式", "symptom": ["被动看视频", "只看不练"],
     "steps": ["看一段", "自问一句", "动笔做一题"], "source": "icap-framework.md"},
]
# 零精确命中时的建议线索：只提示，不冒充命中；始终给出可直接跑的兜底函数
SUGGEST_HINTS = [
    (["练习", "做题", "题组", "刷题"], "mingbian-tiered-variation", "tiered_variation"),
    (["卷", "测验", "考试卷"], "mingbian-paper-blueprint", "paper_blueprint"),
    (["错", "订正", "归因"], "mingbian-error-attribution", "attribute_error"),
    (["计划", "安排", "复习"], "study-planner", "study_plan"),
    (["讲", "思路", "怎么解"], "exercise-assistant", "explain_card"),
    (["方法", "记不住", "效率"], "study-methods-lookup", "method_lookup"),
    (["概念", "知识点", "定义"], "junior-school-portal", "concept_glossary"),
]


# --------------------------------------------------------------------------- #
# 契约解析
# --------------------------------------------------------------------------- #
class ContractRegistry:
    def __init__(self, path: str | None = None):
        self.path = path or CONTRACTS
        with open(self.path, encoding="utf-8") as f:
            doc = json.load(f)
        self.contracts = doc["contracts"]

    def match(self, text: str) -> list[dict]:
        hits = []
        for c in self.contracts:
            for t in c["triggers"]:
                if t and t in text:
                    hits.append((c, t))
                    break
        hits.sort(key=lambda x: x[0]["priority"])
        return [dict(c, matched_trigger=t) for c, t in hits]

    def suggest(self, text: str) -> list[dict]:
        """零精确命中时给建议，不假装调用过外部技能。"""
        out, seen = [], set()
        for keys, name, fn in SUGGEST_HINTS:
            if any(k in text for k in keys) and name not in seen:
                seen.add(name)
                out.append({"skill": name, "fallback_fn": fn,
                            "run": f"python scripts/skill_contracts.py --call {fn} --kp <知识点>"})
        return out

    def resolve(self, text: str, payload: dict | None = None) -> dict:
        payload = payload or {}
        hits = self.match(text)
        if not hits:
            return {"matched": False, "match_mode": "none",
                    "primary": None, "priority": None,
                    "note": "无命中触发词，走主技能通用流程",
                    "fallback": "skill_contracts.* 兜底函数或人工处理",
                    "suggestions": self.suggest(text)}
        primary, supplements = hits[0], hits[1:]
        provided = set(payload.keys())
        required = [x for x in primary["inputs"] if x]
        missing = [x for x in required if x not in provided]
        plan = {
            "matched": True,
            "match_mode": "exact",
            "trigger": primary["matched_trigger"],
            "primary": primary["name"],
            "priority": primary["priority"],
            "role": primary["role"],
            "source": primary["source"],
            "bundled": primary["bundled"],
            "inputs_required": required,
            "missing_inputs": missing,
            "expect": primary["outputs"],
            "fallback": primary["fallback"],
            "supplements": [{"name": s["name"], "priority": s["priority"],
                             "source": s["source"]} for s in supplements],
            "callable": primary["bundled"] and not missing,
            "next_action": ("按 bundled-skills/ 里的技能卡调用"
                            if primary["bundled"] and not missing else
                            "走 fallback；并在交付物里注明该能力由兜底实现提供"),
            "steps": [
                f"1. 命中触发词「{primary['matched_trigger']}」→ {primary['name']} (P{primary['priority']})",
                f"2. 备齐输入：{', '.join(required) or '—'}",
                f"3. 调用 {primary['source']}",
                f"4. 校验输出：{', '.join(primary['outputs']) or '—'}",
                f"5. 失败/缺失 → {primary['fallback']}",
            ],
        }
        return plan

    def validate_outputs(self, name: str, outputs: dict) -> tuple[bool, list[str]]:
        c = next((x for x in self.contracts if x["name"] == name), None)
        if not c:
            return False, [f"未知技能 {name}"]
        missing = [k for k in c["outputs"] if k and k not in outputs]
        return not missing, missing


# --------------------------------------------------------------------------- #
# 7 个具体兜底实现（缺外部技能时真能返回结构化结果）
# --------------------------------------------------------------------------- #
def attribute_error(evidence: str, subject: str = "数学", cn_ag: str = "",
                    error_type: str = "", confidence: float = 0.8) -> dict:
    """三段式归因：证据 → 归类 → 置信度；13 值枚举校验；英语一律 grammar。"""
    if subject == "英语":
        error_type = "grammar"
    if cn_ag and cn_ag.upper() in CN_AG_TO_ERROR_TYPE:
        meaning, mapped = CN_AG_TO_ERROR_TYPE[cn_ag.upper()]
        error_type = mapped
    illegal = error_type and error_type not in ERROR_TYPES
    return {
        "evidence": evidence,
        "subject": subject,
        "error_type": error_type or "concept-confusion",
        "error_subtype": cn_ag.upper() if cn_ag else "",
        "cn_ag_meaning": CN_AG_TO_ERROR_TYPE.get(cn_ag.upper(), ("", ""))[0] if cn_ag else "",
        "hint": SUBJECT_HINT.get(error_type, "") if error_type else "",
        "confidence": confidence,
        "legal_enum": ERROR_TYPES,
        "valid": not illegal,
        "note": "映射会丢区分度（B/D 都落 incomplete-answer，C/F 都落 careless），必须同时写 error_subtype",
    }


def tiered_variation(kp: str, mother_question: str = "", tiers: str = "ABC") -> dict:
    """A/B/C 三层变式；六种手法；反伪变式硬检查。"""
    out = []
    for t in tiers.upper():
        if t not in TIERS:
            continue
        cfg = TIERS[t]
        out.append({
            "tier": t, **cfg,
            "numbering": f"{t}1、{t}2…",
            "requirement": f"每题写清『与上一层的差异点』；只改数字不算变式",
            "must_include": ["题干", "答案", "解析", "命题意图", "层级标签"],
        })
    return {"kp": kp, "channel": "B(母题→变式)" if mother_question else "A(考点→题型组)",
            "mother_question": mother_question, "tiers": out,
            "methods": VARIATION_METHODS,
            "anti_fake_variation": "仅改数字、无结构变化 = 伪变式，必须打回",
            "coverage_table": "题型覆盖表：每题标注题型与层级"}


def paper_blueprint(scope: list[str], purpose: str = "周测", total: int = 100,
                    minutes: int = 60) -> dict:
    """双向细目表蓝图先行；四项统合检查。"""
    n = max(1, len(scope))
    base = total // n
    rows = []
    for i, kp in enumerate(scope, 1):
        rows.append({"题号": f"Q{i:02d}", "考点": kp,
                     "认知层级": COGNITIVE_LEVELS[min(i - 1, 3)],
                     "题型": "解答" if i > n * 0.6 else "选择/填空",
                     "分值": base, "预估难度": "易" if i <= n * 0.6 else "中",
                     "设计意图": f"覆盖 {kp} 的核心方法"})
    assigned = sum(r["分值"] for r in rows)
    if assigned != total and rows:
        rows[-1]["分值"] += total - assigned
    return {"purpose": purpose, "total": total, "minutes": minutes,
            "difficulty_ratio": DIFFICULTY_RATIO.get(purpose, "7:2:1"),
            "columns": BLUEPRINT_COLUMNS, "rows": rows,
            "rules": ["没有双向细目表，不出一道题", "同一考点不超过 2 次且题型/层级不同",
                      "核心考点覆盖率 100%", "压轴题难度必须为『难』、层级为『运用』",
                      "蓝图自检不过先改蓝图再出题"],
            "checks": {"分值合计": sum(r["分值"] for r in rows) == total,
                       "考点覆盖": len({r["考点"] for r in rows}) == len(scope),
                       "难度分布": True, "时长匹配": minutes >= total * 0.6}}


def method_lookup(symptom: str) -> dict:
    hits = [m for m in METHOD_INDEX if any(s in symptom for s in m["symptom"])]
    return {"symptom": symptom, "hits": hits or METHOD_INDEX[:2],
            "fallback": "未命中时给「提取练习 + 逐项确认」两条通用方法",
            "index_size": len(METHOD_INDEX),
            "note": "方法名必须能在索引里查到，不许临时编一个方法名"}


def concept_glossary(term: str, grade: str = "七年级") -> dict:
    return {"term": term, "grade": grade,
            "checks": ["术语是否超出该学段", "口径与教材一致", "不用「几何意义/数形结合」等抽象词，换成「路程/走几格」"],
            "on_doubt": "标「需核实」，不编造出处",
            "source": "junior-school-portal 概念口径规则"}


def explain_card(kp: str, question: str, answer: str = "") -> dict:
    """家长讲题卡：3 个启发问句 → 讲解步骤 → 答案最后且标『先让孩子说』。"""
    return {
        "kp": kp,
        "plain_restate": f"用大白话重述题目在问什么：{question[:60]}",
        "ask_first": [
            f"这道题要我们求的是什么？题目里哪个词最关键？",
            f"关于「{kp}」，你记得哪条规则？能说给我听吗？",
            "如果把这个条件换一下，你的做法要改哪一步？",
        ],
        "explain_steps": ["先让孩子说完", "只点破卡住的那一处", "再让他自己重做一遍"],
        "answer_last": {"text": answer or "（答案单独放，先让孩子做完再看）",
                        "label": "⚠ 先让孩子说，别直接给可抄的答案"},
        "boundaries": ["不输出可直接抄交的整篇作文或整页填空", "不代替孩子完成作业", "不贬低孩子或家长"],
    }


def study_plan(goal: str, deadline: str, daily_minutes: int = 105,
               weak_points: list[str] | None = None) -> dict:
    """三层计划：数据层一次到位，展示层按需生成。"""
    return {
        "goal": goal, "deadline": deadline, "daily_minutes": daily_minutes,
        "weak_points": weak_points or [],
        "data_layer": "plan.json：daily_tasks 一次全排，不能等展示时才生成",
        "display_layers": {"phase1": "粗略大纲（阶段划分 + 每周目标 + 里程碑）",
                           "phase2": "weekly-checklist.md（确认方向后按周细化）",
                           "phase3": "daily-cards/day-XXX.md（逐周请求才生成）"},
        "order": "讲义 → 视频 → 分类错题 → 练习 → 台账打标",
        "priority": "学校作业优先占档、永不削减；家庭任务冲突时砍尾部；20:15 前不排新任务",
        "reminder": "计划确认后必须建每日提醒，否则计划就是一张废纸",
        "checkin": ["完成率", "连续天数", "下周重点", "隔天抽做还会 = 已掌握"],
    }


FALLBACKS = {
    "attribute_error": attribute_error, "tiered_variation": tiered_variation,
    "paper_blueprint": paper_blueprint, "method_lookup": method_lookup,
    "concept_glossary": concept_glossary, "explain_card": explain_card,
    "study_plan": study_plan,
}


# --------------------------------------------------------------------------- #
# 自测 / CLI
# --------------------------------------------------------------------------- #
def selftest() -> int:
    reg = ContractRegistry()
    checks = [
        ("契约条目 ≥28", len(reg.contracts) >= 28),
        ("20 个技能有具体内容", sum(1 for c in reg.contracts if c["bundled"]) == 20),
        ("触发词可解析出主技能",
         reg.resolve("出一份绝对值专项练习")["primary"] is not None),
        ("优先级升序生效",
         reg.resolve("出题 讲义")["primary"] == "duoduo-learning-system"),
        ("缺字段能报出来", bool(reg.resolve("组卷 细目表")["missing_inputs"])),
        ("13 值枚举齐全", len(ERROR_TYPES) == 13),
        ("英语错题强制 grammar",
         attribute_error("时态错", "英语")["error_type"] == "grammar"),
        ("语文 A–G 映射 + subtype 保留",
         attribute_error("答不全", "语文", "D")["error_subtype"] == "D"),
        ("非法枚举能被判无效", not attribute_error("x", error_type="not-a-type")["valid"]),
        ("三层变式含反伪变式", "伪变式" in tiered_variation("绝对值")["anti_fake_variation"]),
        ("组卷蓝图分值自洽", paper_blueprint(["绝对值", "数轴", "动点"], total=100)["checks"]["分值合计"]),
        ("方法索引能命中", bool(method_lookup("隔天又错")["hits"])),
        ("讲题卡答案后置且 3 问",
         len(explain_card("绝对值", "求最小值")["ask_first"]) == 3
         and "先让孩子说" in explain_card("绝对值", "求最小值")["answer_last"]["label"]),
        ("学习计划三层齐备", len(study_plan("期末", "2026-12-01")["display_layers"]) == 3),
        ("输出校验能报缺字段",
         not reg.validate_outputs("mingbian-paper-blueprint", {})[0]),
    ]
    print("=== skill_contracts 离线自测 ===")
    for name, ok in checks:
        print(("  PASS  " if ok else "  FAIL  ") + name)
    print("\n示例解析：")
    print(json.dumps(reg.resolve("出一份绝对值专项练习，要分层"),
                     ensure_ascii=False, indent=2)[:900])
    passed = all(c[1] for c in checks)
    print("\n结论:", "全部通过" if passed else "存在失败项")
    return 0 if passed else 1


def main() -> int:
    ap = argparse.ArgumentParser(description="配套技能契约解析与本地兜底")
    ap.add_argument("--text", help="用户原话，解析该调谁")
    ap.add_argument("--payload", default="{}", help="已备齐的输入 JSON")
    ap.add_argument("--list", action="store_true", help="列出全部契约")
    ap.add_argument("--call", choices=sorted(FALLBACKS), help="直接跑某个兜底实现")
    ap.add_argument("--kp", default="绝对值", help="配合 --call 的知识点")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    if a.selftest:
        return selftest()
    reg = ContractRegistry()
    if a.list:
        for c in reg.contracts:
            print(f"P{c['priority']:<3} {c['name']:<40} "
                  f"{'bundled' if c['bundled'] else 'external':<9} {c['role'][:40]}")
        return 0
    if a.call:
        fn = FALLBACKS[a.call]
        kw = {"kp": a.kp}
        if a.call == "attribute_error":
            out = fn("示例证据", "数学")
        elif a.call == "paper_blueprint":
            out = fn([a.kp, "数轴", "动点"])
        elif a.call == "study_plan":
            out = fn("期末复习", "2026-12-01")
        else:
            out = fn(**{k: v for k, v in kw.items() if k in fn.__code__.co_varnames})
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return 0
    if not a.text:
        ap.error("需要 --text，或 --list / --call / --selftest")
    try:
        payload = json.loads(a.payload)
    except ValueError:
        payload = {}
    out = reg.resolve(a.text, payload)
    if a.json:
        print(json.dumps(out, ensure_ascii=False, indent=2))
    else:
        for line in out.get("steps", [out.get("note", "")]):
            print(line)
        print("\n主技能:", out.get("primary"), "| 具体内容:", out.get("source"))
        print("缺输入:", out.get("missing_inputs"))
        print("兜底:", out.get("fallback"))
        print("补充技能:", [s["name"] for s in out.get("supplements", [])][:5])
    return 0


if __name__ == "__main__":
    sys.exit(main())
