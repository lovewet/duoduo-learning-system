#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
DSL 渲染器：把每日任务的紧凑 DSL 展开成 HTML。
DSL 用 | 和 @ 作分隔符，避免中英文引号冲突。

指令：
  DAY|日号|科目标题|css类|今日目标
  LEC<<<  ...讲义HTML...  >>>            （多行块）
  VID|BV号|标题|UP主|时长|推荐理由
  MC|题干|A@B@C@D|正确索引|思路提示|完整解析
  FILL|题干|输入框占位|正确答案|思路提示|完整解析
  JUDGE|题干|参考答案要点|思路提示|完整解析
  ENDDAY
"""
import io, re, sys, html as H

try:
    import bingju_card as _BJC
except Exception:
    _BJC = None
try:
    import answer_formula as _AF
except Exception:
    _AF = None
try:
    import frac_render as _FR
except Exception:
    _FR = None

def esc(s):
    return H.escape(s, quote=False)

def _md(s):
    """清掉 markdown 星号残留（阶段21 实测踩坑：DSL 手写 **加粗** 会印到讲义上）。"""
    import re as _re
    return _re.sub(r"\*\*(.+?)\*\*", lambda m: m.group(1), s)

def rich(s):
    """选项文本的有限富文本放行：<u> / <b> / 真分数 <span class="fr">。

    ⚠️ 分数必须放行（阶段21）：<span class="fr"> 是**真分数竖式**，
    转义掉就退回斜杠 3/2，与 §5A.14 规范第①条冲突。
    """
    # 先把分数整块抠出来占位，避免被后面的转义逻辑打散
    frs = []

    def _st(m):
        frs.append(m.group(0))
        return "\x00FR%d\x00" % (len(frs) - 1)
    s = re.sub(_FR.FR_BLOCK_RE, _st, s)   # FR_BLOCK_RE 已含 re.S
    o = esc(s)
    for t in ("u", "b"):
        o = o.replace("&lt;%s&gt;" % t, "<%s>" % t).replace("&lt;/%s&gt;" % t, "</%s>" % t)
    o = re.sub(r"\x00FR(\d+)\x00", lambda m: frs[int(m.group(1))], o)
    return o

def _opts_block(qid, opts, phase, hint_text=""):
    """phase: 'try1' or 'try2'"""
    out = []
    for i, o in enumerate(opts):
        v = 'ok' if i == 0 else 'no'   # 占位，调用方会重建
        out.append('')
    return out

def split_qtype(stem):
    """把题干里的题型/语病标签抽出来，返回 (题型, [语病...], 干净题干)。

    ⚠️ 同时清掉 markdown 星号残留（阶段21 实测踩坑）：
    DSL 里手写 `**加粗**` 会原样印到讲义上，教辅不该有星号。
    """
    import re as _re
    stem = _re.sub(r"\*\*(.+?)\*\*", lambda m: m.group(1), stem)
    bj = []
    qtype = ""
    m = _re.search(r'<b class="qt">【题型】([^<]+)</b>', stem)
    if m:
        qtype = m.group(1).strip()
        stem = stem.replace(m.group(0), "", 1)
    m = _re.search(r'<b class="qb">【语病清单】([^<]+)</b>', stem)
    if m:
        bj = [x.strip() for x in m.group(1).split("｜") if x.strip()]
        stem = stem.replace(m.group(0), "", 1)
    stem = _re.sub(r'^[　\s]+', '', stem)
    return qtype, bj, stem


def bjtab_block(rows, qid):
    """病句题「逐句语病定性」答题区：每句都要写出病名 + 改正，不是只选选项。"""
    trs = []
    for i, r in enumerate(rows):
        trs.append(
            f'<tr><td class="bjno">{r["no"]}</td>'
            f'<td class="bjsent">{r["sent"]}</td>'
            f'<td class="bjans"><input type="text" name="{qid}_bj{i}_t" placeholder="语病类型"></td>'
            f'<td class="bjans"><input type="text" name="{qid}_bj{i}_f" placeholder="怎么改（写出改后的句子）"></td></tr>')
    sol_rows = "".join(
        f'<tr><td class="bjno">{r["no"]}</td><td class="bjsent">{r["sent"]}</td>'
        f'<td class="bjans"><b>{r["typ"]}</b></td><td class="bjans">{r["fix"]}</td></tr>'
        for r in rows)
    # 顶部：7 型速查卡（列全所有语病类型 + 识别信号），答题时对照用
    card = ""
    if _BJC is not None:
        card = ('<div class="bjcardbox"><div class="bjcardlab">📇 语病 7 型速查卡'
                '<span>七种全列 · 逐句判病时对照这张卡；<b>不是</b>只能从这七种里挑，'
                '先看信号再定名字</span></div>' + _BJC.cards_html("web") + '</div>')
    return card + f'''<div class="bjtab">
  <div class="bjlab">🖊 <b>逐句定性（本题的正式答案，不只是选选项）</b>
    <span>下面每句话都要单独写出：① 是什么语病　② 怎么改</span></div>
  <table class="bjtable">
    <thead><tr><th>句</th><th>这句话</th><th>语病类型（自己写）</th><th>改正（写出改好的句子）</th></tr></thead>
    <tbody>{''.join(trs)}</tbody>
  </table>
  <details class="bjsol"><summary>✅ 看标准答案（先自己写完再打开）</summary>
    <table class="bjtable sol">
      <thead><tr><th>句</th><th>这句话</th><th>语病类型</th><th>改正</th></tr></thead>
      <tbody>{sol_rows}</tbody>
    </table>
  </details>
</div>'''


def mc(qid, stem, opts, ans, hint, sol):
    """选择题：两段式。第一段选错 → 只给思路 + 给第二次机会；第一段就对或第二段任意 → 给答案"""
    def rows(phase):
        r = []
        for i, o in enumerate(opts):
            r.append(f'<label class="opt"><input type="radio" name="{qid}_{phase}" value="{"ok" if i==ans else "no"}">'
                     f'<span class="mk">{"ABCD"[i]}</span><span class="ot">{rich(o)}</span></label>')
        return "".join(r)
    ca = "ABCD"[ans]
    return f'''<div class="qt" id="{qid}">
  <div class="stem">{stem}</div>
  <div class="phase try1">
    <div class="plab">🖊 第一次作答　<span>选出你认为对的选项</span></div>
    <div class="opts">{rows("a")}</div>
  </div>
  <div class="hint1">
    <div class="hh">💡 还不对，先看思路（这里不给答案）</div>
    <div class="hb">{_md(hint)}</div>
  </div>
  <div class="phase try2">
    <div class="plab">🔁 再试一次　<span>用上面的思路重新判断</span></div>
    <div class="opts">{rows("b")}</div>
  </div>
  <div class="final">
    <div class="fl">🔑 正确答案：<b>{ca}</b>　<span class="fnote fok">你第一次就答对了，很稳！</span><span class="fnote fagain">第二次找到感觉了，这题要标记一下。</span></div>
    <div class="fb">{sol}</div>
  </div>
</div>'''

# ------------------------------------------------------------------
# 网页练习题下方是否保留「演算区」输入框（阶段19 v14 起默认关闭）
# 用户原话：「你的演算区 把网页版的这个写法去掉」
#           「答题纸要把全部题目纳入进去，全部都要在答题纸上写」
# → 写的地方只有一处：**作答纸**。网页只负责讲解 + 自评 + 对答案，
#   再留一个网页输入框会让孩子不知道到底该写在哪。
# 想恢复就把它改回 True。
# ------------------------------------------------------------------
WORKAREA = False

def waptr(kind):
    """网页练习题下方的「写在纸上」提示。

    ⚠️ `data-kind` 是给 print.js.html 用的：网页端收集作答纸时要知道该题
    是填空（5 行）还是简答（6 行）。别改成纯 CSS class，JS 要读它。
    """
    return ('<div class="waptr" data-kind="%s" style="margin:10px 0;padding:8px 12px;'
            'border-left:3px solid #cbd5e1;background:#f8fafc;border-radius:6px;'
            'font-size:12.6px;color:#64748b;">'
            '✎ 这题<b>写在作答纸上</b>（题号与此处一致），写完再回来对照答案</div>' % kind)


def fill(qid, stem, ph, ans, hint, sol):
    """填空/计算题：两段式自评"""
    ca = esc(ans)
    wa = ('<div class="workarea"><div class="wl">✎ 演算区（写清每一步，考场上也要写）</div>'
          '<textarea class="wr" placeholder="在这里写下你的计算过程……"></textarea></div>'
          if WORKAREA else waptr("fill"))
    return f'''<div class="qt" id="{qid}">
  <div class="stem">{stem}</div>
  {wa}
  <div class="phase try1">
    <div class="plab">🖊 第一次作答　<span>填完后对照答案位置：<b>{esc(ph)}</b></span></div>
    <div class="opts row2">
      <label class="opt"><input type="radio" name="{qid}_a" value="ok"><span class="mk">✓</span><span class="ot">我做对了</span></label>
      <label class="opt"><input type="radio" name="{qid}_a" value="no"><span class="mk">✗</span><span class="ot">我做错了 / 不确定</span></label>
    </div>
  </div>
  <div class="hint1">
    <div class="hh">💡 还不对，先看思路（这里不给答案）</div>
    <div class="hb">{_md(hint)}</div>
  </div>
  <div class="phase try2">
    <div class="plab">🔁 再试一次　<span>按上面的思路重算一遍，再判断</span></div>
    <div class="opts row2">
      <label class="opt"><input type="radio" name="{qid}_b" value="ok"><span class="mk">✓</span><span class="ot">这次算对了</span></label>
      <label class="opt"><input type="radio" name="{qid}_b" value="no"><span class="mk">✗</span><span class="ot">还是不对</span></label>
    </div>
  </div>
  <div class="final">
    <div class="fl">🔑 正确答案：<b>{ca}</b>　<span class="fnote fok">第一次就对了，很稳！</span><span class="fnote fagain">第二次找到感觉了，标记一下。</span></div>
    <div class="fb">{sol}</div>
  </div>
</div>'''

def judge(qid, stem, keys, hint, sol):
    wa = ('<div class="workarea"><div class="wl">✎ 作答区（分条写，一条一层）</div>'
          '<textarea class="wr" style="min-height:110px;" placeholder="在这里写下你的答案……"></textarea></div>'
          if WORKAREA else waptr("judge"))
    return f'''<div class="qt" id="{qid}">
  <div class="stem">{stem}</div>
  {wa}
  <div class="phase try1">
    <div class="plab">🖊 自评　<span>写完对照下面的要点，看自己覆盖了几条</span></div>
    <div class="opts row2">
      <label class="opt"><input type="radio" name="{qid}_a" value="ok"><span class="mk">✓</span><span class="ot">要点都写到了</span></label>
      <label class="opt"><input type="radio" name="{qid}_a" value="no"><span class="mk">✗</span><span class="ot">漏了 / 写不出来</span></label>
    </div>
  </div>
  <div class="hint1">
    <div class="hh">💡 漏在哪一层？先自己想想</div>
    <div class="hb">{_md(hint)}</div>
  </div>
  <div class="phase try2">
    <div class="plab">🔁 再试一次　<span>补上漏掉的那一层，重新写一遍</span></div>
    <div class="opts row2">
      <label class="opt"><input type="radio" name="{qid}_b" value="ok"><span class="mk">✓</span><span class="ot">这次补全了</span></label>
      <label class="opt"><input type="radio" name="{qid}_b" value="no"><span class="mk">✗</span><span class="ot">还是写不全</span></label>
    </div>
  </div>
  <div class="final">
    <div class="fl">🔑 参考答案要点</div>
    <div class="fb">{keys}</div>
    <div class="fb" style="margin-top:8px;border-top:1px dashed #a7f3d0;padding-top:8px;">{sol}</div>
  </div>
</div>'''

def parse(text):
    lines = text.split("\n")
    blocks = []
    i = 0
    while i < len(lines):
        ln = lines[i].rstrip("\r")
        if not ln.strip():
            i += 1; continue
        if ln.startswith("LOGIC<<<"):
            buf = []
            i += 1
            while i < len(lines) and not lines[i].rstrip("\r").startswith(">>>"):
                buf.append(lines[i].rstrip("\r")); i += 1
            blocks.append(("LOGIC", "\n".join(buf)))
            i += 1; continue
        if ln.startswith("LEC<<<"):
            buf = []
            i += 1
            while i < len(lines) and not lines[i].rstrip("\r").startswith(">>>"):
                buf.append(lines[i].rstrip("\r")); i += 1
            blocks.append(("LEC", "\n".join(buf)))
            i += 1; continue
        if ln.startswith("BJ<<<"):
            buf = []
            i += 1
            while i < len(lines) and not lines[i].rstrip("\r").startswith(">>>"):
                buf.append(lines[i].rstrip("\r")); i += 1
            blocks.append(("BJ", "\n".join(buf)))
            i += 1; continue
        parts = ln.split("|")
        blocks.append((parts[0], parts[1:]))
        i += 1
    return blocks

def render(text, qprefix):
    out = []
    qi = 0
    dq = 0   # 当天题号
    day_open = False
    sub_open = False
    logic_cls = ""   # LOGIC 块配色跟随所属 SUB 的科目（m/c/e）
    pending_q = ""   # 题块缓冲：遇到紧随其后的 BJ<<<>>> 时还要追加内容，故先不收口

    def _flush():
        nonlocal pending_q
        if pending_q:
            out.append(pending_q)
            pending_q = ""

    for kind, payload in parse(text):
        if kind == "DAY":
            _flush()
            if sub_open: out.append("</div>")
            if day_open: out.append("</div></div>")
            d, ttl, cls, goal = payload[0], payload[1], payload[2], payload[3]
            out.append(f'<div class="daysec" id="day{d}">'
                       f'<div class="dayhead {cls}"><div class="dnum">DAY {d}</div>'
                       f'<div class="dttl">{ttl}</div><div class="dgoal">🎯 {goal}</div></div>'
                       f'<div class="daybody">')
            day_open = True; sub_open = False; dq = 0
        elif kind == "SUB":
            # 🔴 必须先 _flush() 再收口上一个 subsec（阶段22 修）：
            # 题块是缓冲的（等 BJ<<<>>> 追加逐句病名表），换 SUB 时若不先 flush，
            # 上一节的**最后一道题**会被挤到下一节的标题后面 ——
            # 孩子看到的是「语文」标题下面挂着一道数学绝对值题。
            _flush()
            if sub_open: out.append("</div>")
            name, cls, goal = payload[0], payload[1], payload[2]
            out.append(f'<div class="subsec"><div class="subhead {cls}">'
                       f'<span class="sname">{name}</span><span class="sgoal">{goal}</span></div>')
            sub_open = True
            logic_cls = cls
        elif kind == "LOGIC":
            _flush()
            # 按所属科目切换配色：数学紫(.logic) / 语文红(.logic.c) / 英语青(.logic.e)
            out.append(f'<div class="logic {logic_cls}">{payload}</div>')
        elif kind == "LEC":
            _flush()
            out.append(f'<div class="lec">{payload}</div>')
        elif kind == "BJ":
            # 逐句语病定性表：追加进上一道题的 qwrap（题块先缓冲，遇到 BJ 才收口）
            rows = []
            for ln2 in payload.split("\n"):
                ln2 = ln2.strip()
                if not ln2:
                    continue
                c = ln2.split("|")
                if len(c) < 4:
                    continue
                rows.append(dict(no=c[0].strip(), sent=c[1].strip(),
                                 typ=c[2].strip(), fix=c[3].strip()))
            if rows and pending_q:
                pending_q = pending_q[:-len("</div>")] + bjtab_block(rows, "b%d_%d" % (qi, dq)) + "</div>"
        elif kind == "VID":
            _flush()
            bv, ttl, up, dur = payload[0], payload[1], payload[2], payload[3]
            why = "|".join(payload[4:])
            # ⚠️ 支持「搜索词」型推荐（阶段21）：BV 写成 `SEARCH:关键词` 时，
            # 不硬编一个可能失效/错误的 BV 号，而是**跳到 B 站搜索结果**，
            # 让用户自己按「时长」挑最短的。
            # 为什么需要：备选视频我核实不到真实 BV 时，**编一个假的比不给更糟**——
            # 点开是错的视频，等于白浪费孩子时间。
            if bv.upper().startswith("SEARCH:"):
                from urllib.parse import quote as _q
                kw = bv.split(":", 1)[1]
                url = "https://search.bilibili.com/all?keyword=%s" % _q(kw)
                btn, tag = "去搜索", "🔍 搜索这条"
            else:
                url = "https://www.bilibili.com/video/%s" % bv
                btn, tag = "观看", "🎬 今天看这条"
            out.append(f'<div class="vid"><span class="vtag">{tag}</span>'
                       f'<div class="vinfo"><a href="{url}" target="_blank" class="vt">{ttl}</a>'
                       f'<div class="vm">{up}　·　{dur}</div><div class="vw">{why}</div></div>'
                       f'<a class="vbtn" href="{url}" target="_blank">{btn}</a></div>')
        elif kind == "FIG":
            _flush()
            ttl, src = payload[0], payload[1]
            try:
                svg = io.open(src, encoding="utf-8").read()
            except Exception as e:
                svg = f'<div style="padding:12px;color:#b91c1c;">图形未找到：{src}</div>'
            out.append(f'<div class="fig"><div class="fc m">{ttl}</div>'
                       f'<div class="fb">{svg}</div></div>')
        elif kind in ("MC", "FILL", "JUDGE"):
            _flush()
            # 从右往左取字段，避免题干里的绝对值竖线 | 冲突
            qi += 1
            dq += 1
            qid = f"{qprefix}{qi}"
            # ⚠ 必须先剥离题型标签再渲染题干，否则标签会混进 stem
            if kind == "MC":
                sol, hint, ans, opts = payload[-1], payload[-2], payload[-3], payload[-4]
                stem = "|".join(payload[:-4])
            elif kind == "FILL":
                sol, hint, ans, ph = payload[-1], payload[-2], payload[-3], payload[-4]
                stem = "|".join(payload[:-4])
            else:
                sol, hint, keys = payload[-1], payload[-2], payload[-3]
                stem = "|".join(payload[:-3])

            qtype, bj, stem = split_qtype(stem)
            if kind == "MC":
                body = mc(qid, stem, opts.split("@"), int(ans), hint, sol)
            elif kind == "FILL":
                body = fill(qid, stem, ph, ans, hint, sol)
            else:
                body = judge(qid, stem, keys, hint, sol)

            btag = ('<span class="qtag bq">语病：%s</span>' % "｜".join(bj)) if bj else ""
            qtag = ('<span class="qtag qt2">%s</span>' % qtype) if qtype else ""
            # G14 答题公式卡：只在主观题（JUDGE）且题型已注册公式时挂，客观题不挂
            afcard = ""
            if kind == "JUDGE" and qtype and _AF is not None and _AF.get(qtype):
                afcard = _AF.card_html(qtype, kind="plain")
            # 病句题：题干里必须明确「逐句写病名」是正式作答内容
            req = ""
            if bj:
                req = ('<div class="bjreq">📌 <b>本题答题要求</b>：① 选出没有语病的一句（选字母）'
                       '　② <b>下面表格里每个句子都要单独写出「语病类型」和「怎么改」</b>'
                       '——这两栏和选项一样是要判分的，不能只选完就放过。</div>')
            pending_q = ('<div class="qwrap"><div class="qno">第 %d 题</div>%s%s%s%s%s</div>'
                         % (dq, qtag, btag, afcard, req, body))
        elif kind == "ENDDAY":
            _flush()
            if sub_open: out.append("</div>")
            if day_open: out.append("</div></div>")
            day_open = False; sub_open = False
    _flush()
    if sub_open: out.append("</div>")
    if day_open: out.append("</div></div>")
    return "".join(out)

if __name__ == "__main__":
    src, dst, pre = sys.argv[1], sys.argv[2], sys.argv[3]
    text = io.open(src, encoding="utf-8").read()
    html = render(text, pre)
    io.open(dst, "w", encoding="utf-8", newline="\n").write(html)
    print(f"{src} -> {dst}  {len(html)} chars")