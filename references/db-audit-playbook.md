# 错题库体检与批量修复 Playbook（阶段10 全库修复实战）

> ## ⚠️ 环境说明（先读这段）
>
> 本文提到的 `error_db_ingest.py`（号称「唯一门禁」）、`error_db_full_audit.py`、
> `error_db_llm_audit.py`、`error_db_weekly_check.py`、`errfix_a.py`、`errfix_n.py`
> 都是**原私有工作环境的历史脚本，不随本公开包分发**（本文是当时的实战记录）。
>
> **不要照本文直接执行那些命令，会报文件不存在。**
> 本包内对应的实际入口：
>
> | 要做的事 | 本包用哪个 |
> |:--|:--|
> | 批改结果入库 | `scripts/grade_submission.py`（直接写 `errors`，**没有 6 关门禁**）|
> | 错题聚合回画像 | `scripts/sync_mastery.py` |
> | 库体检 / 批量修复 | `scripts/fix_db.py`（幂等，带 dry-run）|
>
> 换句话说：**「唯一门禁」在本包里没有对应实现**，入库质量靠 `grade_submission.py`
> 自身的校验。本文的 6 关流程只能当**参考标准**，不是已落地的事实 ——
> 想真正用起来，把 6 关逐条实现成 `scripts/` 下的门禁脚本，或在 CI 里串起来。
>
> 文中 `<RUNTIME_DIR>` / `<SCRIPTS_DIR>` 是**占位符**，指「你自己的运行目录 / 脚本目录」。

适用：用户说「检查健康度 / 综合全面修复 / 审计错题库 / 为什么有这么多问题」时，按本文件走。
一句话流程：**先整库备份 → 同尺子量基线 → 按「轴」逐脚本修 → 复量 → 上防漂移（门禁 + 周检）**。
体检输出：健康分与知识点映射率的前后对比，具体数值以自建库为准。

---

## 1. 🔴 两把尺子（必须分清，别混报一个数）

| 尺子 | 脚本 | 量什么 | 本轮 |
|---|---|---|---|
| **确定性** | `scripts/error_db_full_audit.py`（只读） | 字段是否规范：error_type 枚举 / kp 映射 / 重复 / 状态机 / 缺答案 | 98/100 |
| **语义** | `scripts/error_db_llm_audit.py`（默认 `deepseek-flash`） | 证据是否完整：整题 / 完整作答 / 题库答案 / 复练覆盖 | 47 |

**两个数不一致是正常的，不是矛盾**：确定性高说明字段修干净了，语义低说明**历史证据欠账**（老记录题面/作答/答案缺失）还没补。向用户解释时**必须点明是哪把尺子**，否则他会以为修了个寂寞。

### LLM 审计的用法边界
- 它按「检查项清单」输出问题码 + severity，**可能照抄旧证据包**——本轮它把合法的枚举值 `classification` 报成「非法枚举 INVALID_ENUM」（读到 07:26 的旧证据包）。**只当线索，不当结论**；报出的问题码要回到库里去核实一遍。
- 交叉复核用 GLM 常 `TimeoutError`，不要因为它没出结果就阻塞交付。

## 2. 前后对比必须「同尺子」

把审计脚本指向**备份库**再跑一遍：`error_db_full_audit.py --db backups/error_db_fix_<TS>/error_db.sqlite.bak`。
- 健康分公式：`100 − 20×P0 − 8×P1 − 2×P2`。
- ⚠️ 更早的「31/100」是旧版脚本口径，**禁止当基线**。
- 🐛 坑：`score` / `ts` 必须在 `json.dump` **之前**算好，否则落盘 JSON 里没有分（本轮踩过，落盘后才发现 json 缺 score）。

## 3. 审计口径的四个假告警（全踩过）

1. **去重键**不能用 `date+subject+kp+error_desc`——历史用它**误标了 N条无关题**（例：#110 挂了 18 条数轴题）。判重只认 `dup_of` + `question_full` 归一化全等。
2. **`knowledge_base` 同名点分属不同单元是设计如此**（UNIQUE 含 unit），不是重复，别去「合并」。
3. **`kp_null` 要排除 `kp-pending` 标签的条目**——如「做题习惯」本就不是知识点，它永远不该有 kp_id。
4. **「短题干」多为假告警**：`-(-2)⁴` 这种本身就是完整计算题；另 `questions.q_type='section-header'` 的行**本就不该有答案**，不计入「缺答案」。

**通用教训**：每次改口径，都要用「已知答案的样本」反验一遍（建库时 `--db` 跑备份库对照），不要凭感觉放宽或收紧。

## 4. 修复脚本的工作模式（`errfix_a.py` … `errfix_n.py`）

- **一个脚本只修一个轴**（枚举归一 / 学科改写 / 假错因回写 / 状态机 / 重复收敛 / 悬空日志…），便于回滚与定位。
- 一律 **`dry` 先跑**（打印「将改哪几行 + 前后值」）→ 看过 → `--apply`。
- 动库前**整库备份**；`commit()` **不要放在循环里**——遇 `IntegrityError`（如 `knowledge_base` 的 `edition`/`grade` NOT NULL 未给）会整批回滚，别以为改了一半。
- 跑完立刻用**只读** sqlite 复核（`file:...?mode=ro`）。
- 脚本序号不必漂亮，**能重跑** 才是核心。

### 🔴 库被锁（database is locked）的绕行（阶段16 实测）

陈旧连接（cron/常驻脚本持有句柄）会让 `sqlite3.connect` 连写都报 `database is locked`。**绕行=副本改+原子替换**，但有一个硬条件容易漏：

```python
import shutil, os, sqlite3
tmp = db.replace('error_db.sqlite', 'error_db_new.sqlite') # 🔴 副本必须与 DB 同目录
shutil.copy(db, tmp) # ❌ 不能放 /tmp：os.replace 跨文件系统直接报
con = sqlite3.connect(tmp) # OSError 18 Invalid cross-device link（已实测）
# ... 改完 con.commit() + PRAGMA integrity_check=='ok' ...
con.close()
shutil.copy(db, f'{bakdir}/error_db.sqlite.bak-{ts}-pre-<action>') # 先备份
os.replace(tmp, db) # 同文件系统才是原子 rename
```

另注：mastery 表写入还有两个结构坑（kp_id 是 INTEGER 引用 knowledge_base(id)、mastery_level 是 0-3 INTEGER 档位、禁写文本档）——见 SKILL.md「mastery 手动更新两坑」节，本文件不重复。

## 5. 同题再犯的合并口径（不删行、留痕）

实测收敛 6 组。规则：
- canonical = `student_steps` 最长者（tie 取最早日期）
- 其余 → `status='duplicate-merged'` + `dup_of=<canonical id>` + `resolved=1`
- `canonical.error_desc` 追加「**【再犯 YYYY-MM-DD】**」
- `practice_log` 该题行迁移到 canonical

配合铁律：**已消解/已合并的历史错题一律不物理删除**，只改状态留痕。

## 6. 🔴 老记录「没存的题面」是怎么回事（阶段10 查清，用户问过）

**结论先说：不是数据丢了，是那时候表里压根没有这两列。**

- `question_full` / `student_steps` 是 **阶段9 才新建的列**；7–8 月入库时表里只有 `error_desc`（错因摘要），题干**无处可放**。
- 当时的工作方式是**摘要式录入**：只记「哪题错了 / 错在哪 / 什么知识点」。看 source 名就知道——`手动录入`、`Kimi分析-错误单词记录`、`图4第4题` 这种一条一条的，本来就没记题面。
- **反证**：9/10 那批 OCR 批量入库（`source=ocr_judged`，N条）题面覆盖 **649/649 = 100%** → 说明通道是好的，缺题面纯属**历史欠账**。
- **规模**：N条无题面（7月 205 / 8月 188 / 9月 2），全库覆盖 题面 66%、作答 61%；这些已标 `q_status='missing-nosource'` **禁入出题池**。

### 回收路径（按性价比排序）
1. **`error_fulltext` 旁表 N条完整题面**（当初从 Kimi 分享快照逐题挖出来的）——**`linked_error_id` 全空，一条都还没挂回主库**，这是现成的池子。
2. **可回填约 N条**：日期能与池对上（7/29 N条、8/1 65、7/30 49、8/13 43…）→ 按「日期 + 学科 + 题号/知识点」**互相印证才挂**。
   - 🔴 **宁缺勿滥**：对不上就留空，绝不硬配——硬配会把 A 题的题面印到 B 题卡上，比没有更糟。落库前必须**先出对照清单给用户过目**。
3. **剩 ~N条**：早期原图缓存已清（`cache/images` 现 0 张），只能等该题**下次再犯时重拍补录**；**不发起全量翻拍**。

⚠️ 语义健康分（那把 LLM 尺子）上不去，主要就是这一轴撑的——**别把它误判成「字段还没修好」**。

## 7. 防漂移（修完必须上，否则必复发）

- **入口**：唯一门禁 `scripts/error_db_ingest.py`（6 关，`--selftest` 6/6）。禁止任何脚本自拼 `INSERT INTO errors`。
- **事后**：周检看门狗 `scripts/error_db_weekly_check.py`（周一 07:00 → 微信，**仅 P0/P1 告警，无问题静默**，带存量阈值 `kp_null>3` / `duplicates>10`，避免老债天天报警）。
  - 🐛 **cron 坑**：`cronjob` 的 `script` 字段必须写 **`~/.hermes/scripts/` 下的相对文件名**；脚本实体在 `<SCRIPTS_DIR>/` 时要 symlink 过去（`<RUNTIME_DIR>/home/.hermes/scripts/`，另 `<RUNTIME_DIR>/cron/scripts/` 也放一份）。首次建成后要核 `cron/jobs.json` 有没有留僵尸条目。

## 8. 交付口径

- 给用户报**前后对比**（同尺子），不要报「已经很干净了」这种没有锚点的话。
- 明确说清**能不能回收 / 怎么回收 / 要不要现在做**，并给一个「下一步最高性价比动作」+ 是否等他点头。
- 凭据（key/token）**一律不出现在报告、日志、回复里**。
