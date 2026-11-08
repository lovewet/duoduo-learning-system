# 三科错题库分类体系（分别列门）阶段3

## 机制
`errors` 表的 `error_type` 是旧的扁平通用枚举。阶段3 起引入**按学科分门**的分类，落两张表：
- `error_category_config`：三科各自的分类门类（权威配置，PRIMARY KEY(subject,category_id)）
- `error_category_mapping`：每条 active 错题 → 所属门类（error_id + subject + category_id + category_name + rule_basis + mapped_at）

查询某门类错题：
```sql
SELECT e.* FROM errors e JOIN error_category_mapping m ON e.id=m.error_id
WHERE e.status='active' AND m.subject=? AND m.category_id=?
```

## 🔴 用户硬性偏好
- **英语错题一律归类为 grammar（语法）**——用户原话"注意错题库应该把这些英语错误归类为语法"。录入英文错题时 error_type 用 grammar，归 E1 门。
- **三科错题库按实际错误分别列门**——分类依据真实错误内容逐条提炼，不是空泛概念。用户会检查分类是否符合实际错误。

## 三科门类清单（与 error_category_config 一致）
### 数学（M1-M4）
- **M1 符号处理**：M1-1去括号变号 M1-2幂与负号 M1-3绝对值符号 M1-5普通符号
- **M2 计算与步骤**：M2-1运算顺序 M2-2分数小数 M2-3化简合并 M2-4书写跳步
- **M3 概念理解**：M3-1概念混淆 M3-2公式误用 M3-3漏零
- **M4 答题规范**：M4-1空白 M4-2粗心抄写 M4-3答案不完整
### 英语（E1-E5）
- **E1 语法**：E1-1主谓一致 E1-2冠词 E1-3单复数 E1-4动词时态 E1-5代词 E1-6介词
- **E2 词汇拼写**：E2-1单词拼写
- **E3 书写规范**：E3-2标点 E3-3字母
- **E4 语义理解**：E4-1词义混淆 E4-2固定搭配
- **E5 答题规范**：E5-1空白 E5-2答案不完整
### 语文（Y1-Y3）
- **Y1 文言文字词**：Y1-1漏译 Y1-3关键词不理解 同音字/形近字
- **Y2 内容理解**：主旨提炼/标题含义
- **Y3 答题方法**：答题模型缺失

## 归类规则（机器可执行）
按 subject + error_type + error_pattern + 正文关键词判定）优先
2. error_type（数学: sign-error→M1 / calculation→M2 / blank→M4；英语: grammar→E1 / spelling→E2 / careless→E3 / semantic→E4；）语文: concept-confusion→Y1或Y2 / spelling→Y2 / blank→Y3）
3. 正文关键词细分（数学: 括号/去括号→M1-1, 幂/负号→M1-2, 绝对值→M1-3；英语: 主谓一致/冠词/介词/单复数/代词分 E1-x）

## ⚠️ 踩坑
- **category_id 的 split bug**：`cat.split('-',1)` 会把 `"M1-1符号处理-去括号变号"` 拆成 `M1` + `1符号处理-去括号变号`（序号错位，category_id 变裸 M1）。正确做法：category_id 只存 `M1`，category_name 存 `符号处理-去括号变号`（**去掉序号前缀**）。若已存脏，用 `name_fix` 字典批量修正 name，id 按大类对齐（语文 Y3-1→Y3 / Y4→Y3）。
- 首次打标需分类器试跑统计（`Counter`）再人工核对样本；英语/语文的 `concept-confusion` 需依正文细分（"主谓一致"or"冠词"or"复数"），不能一刀切全归一个。
- 已打 `error_pattern` 的错题优先按 pattern 归，pattern 与 error_type 冲突时以 pattern 为准。

## 溯源
- 千问分享(阶段3《初一数学易错点梳理》)：学生计算卡壳根源=「符号+步骤」习惯，非知识不会 → 印证数学符号类错题最多。
- Kimi 分享(阶段3 图像题目答案分析)：录入 3 条英语不定代词错题，全部 error_type=grammar，并入 kb#107 不定代词 mastery。数学 10 题全对不录入。
