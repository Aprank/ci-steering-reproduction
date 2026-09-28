# ROUND2_REPORT.md

**轮次**：2026-09-29 任务清单（T0–T7）
**执行者**：执行 agent
**本报告性质**：按任务清单要求，所有结论标注为 **[本轮实测]** / **[代码检查]** / **[推断]** / **[尚未验证]**
**本轮资源消耗**：**GPU 0 小时、付费评委 0 次调用、磁盘新增 < 1 MB**（T0 只做资源探测；T1/T2/T3/T4/T6 数据部分全部离线完成）

---

## 0. 阅读材料与定位结论

已读：`AUDIT_REVIEW_2026-09-29.md`、`AUDIT_REPORT.md`、`NEXT_STEPS.md`、
`audit_review/independent_recalculation.json`、`audit_review/schema_check.json`、
`EXPERIMENT_REPORT.md`、`REPRODUCTION_RESULTS.md`。

**版本区分**（复核要求）：
- 公开仓库快照：`Aprank/ci-steering-reproduction` @ `9a20fc0a7e627176f308daf6488a738778e07812`
- 本轮实际工作仓库：`repo/` @ `3bcb1b5`（base `5c5edc3` + 未提交修改）
- 二者不等价，已写入 manifest `repo.public_snapshot_note`。

---

## T0 — 版本与可追溯运行记录 ✅ 完成

**产物**：`repo/outputs/research_next_round/round2_2026-09-29/run_manifest.json`、`code_diff.patch`

**[本轮实测]** 记录内容：
- commit `3bcb1b5`、branch `main`、3 个未跟踪/修改文件、diff 哈希
- 模型本地快照：Qwen `a09a35458c702b33ee703d103063234e8bc28`、Mistral `c170c708c41dac9275d15a8fff4eca08d52bab71`
- 软件版本：Python 3.11 / torch 2.14.0+cu130 / transformers 5.16.1 / sklearn 1.9.0；`cuda_available=True`
- **GPU 现状（不假定 GPU 4 仍空闲）**：0/2/5 被他进程占满（100% 利用率）；**空闲候选 = GPU 1、GPU 3**；GPU 4 有 75 GB 空闲但 20% 利用率
- 不可变输入哈希：6 个刺激文件 + pilot 数据；历史产物（per_sample / summary / rejudge / 两个 judge cache）全部存在并记录哈希
- 关键定义写入 manifest：`layer_index_definition` = **hook 在 `model.model.layers[i]` 输出，故索引 0 是第 1 个 transformer block 输出，不是词嵌入**；生成参数、选层 `[23..27]`、token 位置
- 凭证仅记录 `key_present` 布尔值，**不含任何密钥**

**缺失项**：无。所有清单要求的材料均在本机找到。

---

## T1 — 修复评委的语义与有效性判定 ✅ 完成（本轮最高优先级）

### T1.1 授权感知评估
**产物**：`repo/src/evaluation/ci_judge_v2.py`（新增；v1 `ci_eval.py` 原样保留供历史对照）

**[代码检查]** 修复内容：
- 新提示词不再写死 "should NOT reveal"；改为把**任务、授权状态、接收者、上下文、待保护事实**一并传入
- 明确要求"不要假定披露被禁止"，并规定 `disclosed` 与 `refused` **可以同时为真**
- 四类字段分离：`disclosed` / `refused` / `task_success` / `violation`
- **`violation` 与 `norm_compliant` 为派生量**，由**独立规范标签**与 `disclosed` 决定，**不由模型自述推断，也不从是否泄露反推**；授权状态未知时保持 `None`
- 授权披露 **不** 记为违规；未披露 **不** 自动记为任务成功
- 历史 `leaked_v1` 字段语义保留，未被改名混用

### T1.2 严格校验与失败管理
**[代码检查]**：
- 正向解析、fallback、缓存读取**共用** `validate_verdict()`；`{}`、缺字段、类型错误、`"false"` 字符串布尔、非法 confidence **一律 SchemaError → unknown**；删除了 `setdefault(..., False)` 造安全判定的逻辑
- 不做 `bool("false")` 转换
- **零有效样本 → `None`**（`rate()` 返回 None，模块内不再用 `max(denom,1)` 兜底造 0%）
- `max_tokens` 变为配置项（默认 1024，v1 硬编码 512）；新增显式 `retry_unknown`
- 每次请求保存：模型、预算、`finish_reason`、`usage`、`raw_content`、错误、尝试顺序
- 缓存键 = `PROTOCOL_TAG + SCHEMA_VERSION + judge_model + system_prompt + user_prompt`，**新旧协议不互相污染**

**[本轮实测] 额外发现并修复的缺陷**：`judge()` 原先只写内存缓存、**从不落盘**，导致跨实例无法复用、历史 unknown 无法续跑重评；已加 `autosave` 并验证。

### T1.3 回归测试
**产物**：`repo/tests/test_ci_judge_v2.py`、结果 `outputs/research_next_round/round2_2026-09-29/t1_regression_tests.json`

**[本轮实测] 17/17 通过**，覆盖任务清单点名的全部反例：
`{}` 拒收 · 缺字段拒收 · 字符串布尔拒收 · 非法 confidence 拒收 · 空响应→unknown · 截断→unknown · 部分对象→unknown（保留 provenance）· **同一披露回答在允许/不允许下 disclosed 相同而 violation 不同** · **"先说不能透露随后透露" → refused=true 且 disclosed=true** · **授权但完全拒答不计为授权披露成功** · 零有效→null · **缓存旧 unknown 在 `retry_unknown=True` 时被重评** · 缓存键覆盖协议/模型 · 配对 5 类齐全 · 缓存键稳定

> ⚠️ 注：v2 评委**尚未用真实 API 做过授权/未授权小样本验证**（任务清单 T5 第 1 条），因此**不得**据其启动完整重评。此项为 **[尚未验证]**。

---

## T2 — 统一最终记录与统计口径 ✅ 完成

**产物**：`src/finalise_round1.py` → `per_sample.final.jsonl`（810 行）、`summary.final.json`、`consistency_check.json`

**[本轮实测] 与独立复核参考值零失配**：

| 方法 | valid/unknown | 确认泄露 | valid-only 率 | 全 270 条缺失界限 | 缓存命中 | 命中内泄露 |
|---|---|---|---|---|---|---|
| No Steering | 270 / 0 | 116 | **42.96%** | 42.96%–42.96% | 242 | **96** |
| Standard | 270 / 0 | 118 | **43.70%** | 43.70%–43.70% | 255 | 107 |
| CI-Parametric | 267 / 3 | 136 | **50.94%** | 50.37%–51.48% | 224 | 102 |

配对（共同有效集，**含 00 单元**，四单元之和 = valid_pairs，已验证）：

| 对比 | 00 | 01 仅方法 | 10 仅基线 | 11 双方 | valid_pairs | 配对差值 | 精确 McNemar p |
|---|---|---|---|---|---|---|---|
| Standard vs 基线 | 146 | 8 | 6 | **110** | 270 | +0.74% | 0.7905 |
| CI vs 基线 | 113 | 38 | 18 | 98 | 267 | **+7.49%** | **0.01045** |

**修复的具体缺陷**：
- ✅ `pair_valid` 原先漏掉"双方都不泄露"（不是有效配对总数）；现显式输出 00/01/10/11/unknown 五类
- ✅ Standard `both_leak` 由错误的 **108 修正为 110**
- ✅ bootstrap 不再把 `None` 当 0；改为按 **基础场景为独立单位**的 cluster bootstrap（`bootstrap_ci95` 已输出）
- ✅ `source` 来源标注：`historical_cache` / `historical_new_judgement` / `rejudge_overlay`；16 条复评恢复行的 `refused/appropriate/raw_content` 标记为 **`field_level_unrecoverable`**，**不与被污染的旧值拼接**
- ✅ 各表注明"评委标签为自动标注、**未经人工核验**"；"未检出差异"不写为"方法等效"

**历史差异的诚实处理**（**[推断]**，已写入 `consistency_check.json`）：
> 旧报告基线 104 次泄露，而当前缓存命中中仅 **96** 次。若 28 个未命中都是旧失败且当时全判安全，旧值应为 96。
> 因此**至少 8 次泄露落在"今日 prompt 哈希不匹配"的行里**（回答漂移／提示漂移／缓存缺口），
> **未命中 ≠ 历史解析失败**，剩余差异**无法完全归因**，明确保留。

---

## T3 — 修正报告与 LDA 分析 ✅ 完成

**产物**：`src/subspace_selectivity_v2.py` → `outputs/research_next_round/round2_2026-09-29/lda_v2/{lda_v2.json, lda_v2.png}`

**[本轮实测] LDA 修复结果**：

| 单元格 | 原协议（全数据拟合 LDA） | 折内协议（fold-internal） |
|---|---|---|
| info_type → S_info_type | 100.0% | 100.0% |
| recipient → S_recipient | 100.0% | 99.8% |
| trans → S_trans | 100.0% | 100.0% |
| 非对角（6 格） | 11.0%–18.2% | **完全相同** |
| 置换标签对照 | 0.1961 | 0.2008 |

**[本轮实测] 关键更正**：两协议使用**同一套折划分**后结果几乎一致 ⇒ **上一轮"非对角从约 20% 降到 11–18%"是折划分改动（`shuffle=False`→`shuffle=True`）造成的，不能归因为修复了 LDA 的测试折泄露**。该错误归因已撤销。

**[本轮实测] 新增数据污染发现**：三个参数的数据集**共享场景**——(subject, sender) 签名重叠 **69 个（13.8%）**，且参数两两之间存在 **4–16 条完全相同**的激活行。⇒ 参数数据集**并非独立**，交叉投影的非对角低于随机水平需要用混淆矩阵进一步解释，**不能**自动解释为"更独立"。

**[本轮实测]** 图与 JSON 现从**同一矩阵对象**生成（修复了 nested 模式仍绘旧图的问题）；已输出混淆矩阵；已声明本检验**只支持判别选择性**，**不支持功能或因果独立**。

**声明降级**（按复核要求，已写入报告）：
| 原声明 | 更正为 |
|---|---|
| 28 次缓存未命中 = 28 次历史解析失败 | **未证实归因**：旧 104 vs 命中内 96，剩余差异不可完全归因 |
| unknown 系统性偏向泄露 | **仅描述本次恢复样本**：16 条中 11 条泄露，且 11 条来自 CI（9 条泄露）、基线仅 3 条；**小样本、按失败筛选、方法混合**，不能推广为总体机制 |
| 推理 token 耗尽是真因 | 仅对**有 `finish_reason=length` 证据**的 3 条作确定判断；其余 18 条空响应**缺证据**，保留推断性质 |
| 强证据反驳原论文 | 改为：**本复现实现、当前配置、当前评委下**未观察到 CI-steering 改善，反而观察到更高泄露；协议差异（评委、选层等）已列出；人工评测未完成 |
| 类别字面出现在输入 = 非法标签泄露 | 改为：只能说明**类别/词汇可解码**，**不能区分浅层读取与抽象规范判断** |

---

## T4 — 真人盲审包 ✅ 已准备（状态：**待人工**）

**产物**：`outputs/research_next_round/round2_2026-09-29/blind_review/`
`blind_random.jsonl`(48) · `blind_diagnostic.jsonl`(105) · `mapping.json`(受限) · `annotation_template_random.csv` · `annotation_template_diagnostic.csv` · `INSTRUCTIONS.md`

**[本轮实测]**：
- 诊断集 = **全部 56 个 CI/基线不一致配对**（112 份回答，去重后 105）；随机集 = 按方法分层的 48 条
- **匿名性检查通过**：盲审文件中不含方法名、评委结论、配对关系（`grep` 验证）
- 提供完整场景、待保护事实、**授权条件**与回答；隐藏方法与评委判断；顺序随机；映射另存
- 提供操作说明与**正反例**；字段 `disclosed/violation/refused/task_success/uncertain/notes`；模板为**空白**
- **未由 agent 生成任何标签**

> ⚠️ **待人工**：需真实评审人填写；双人一致性只能在确有双人独立标注的重叠子集上计算。当前状态为"**待人工**"，**不是已完成**。

---

## T6 — 20 个新场景（关系型授权）✅ 数据完成 / ⏳ 模型检查未运行

**产物**：`src/pilot_scenarios_v2.py` → `data/pilot_v2/scenarios_v2.jsonl`（80 输入）、`checks_v2.json`

**[本轮实测] 数据质量检查 7/7 通过**：
- **C1** 授权从句**不含任何否定词**（词边界匹配，避免人名 "Bruno" 被误判）
- **C2** 允许/不允许**仅差授权者姓名**（仅比较授权从句；记录与任务从句逐字相同）
- **C3** 任务强度**仅差任务从句**
- **C4** 授权者姓名**不能单独决定标签**（半数据以 A 为目标、半数据以 B 为目标，姓名在两种角色中都出现）
- **C5** 实体隔离（20 场景无共享人名/编号）
- **C6** 同一模板族**同时覆盖两个规范标签**（复核硬性要求）
- **C7 关键结果**：TF-IDF(1-2gram)+LR、**按场景留出（GroupKFold）** 的平均 AUROC = **0.506**，而 **v1 为 0.825** ⇒ **词袋捷径已消除**，标签必须靠"比对获授权者与信息主体是否为同一人"这一**关系**来判断

设计要点：每场景含**两名人物**各自的条目与待保护事实；授权从句为"`{name}` has authorized sharing this record."；**规范标签 = 当且仅当获授权者就是被询问条目所属之人**；任务强度与授权**正交**。

> ⏳ **未运行**：真实生成 + 生成前状态采集 + 探针/对照/联表（T6 实验部分）。依赖 GPU 与（若用评委）API 预算，按清单"先确认资源"的要求留待下一批执行；GPU 1/3 当前空闲可用于此。

---

## T5 — 修正后重算旧合成集 ⏳ 未开始（依赖 T1 的真实 API 验证）

**阻塞条件**：T1 的自测虽 17/17 通过，但 v2 评委**尚未在真实 API 上用授权/未授权小样本验证**（"合法披露不被当违规"）。清单明确要求该验证通过后才做完整重评。

**可立即执行的第一步**（下一批）：取 6–10 条明确授权/未授权的案例，调用 v2 评委，人工快速复核其是否把合法披露判为非违规。

---

## T7 — 阶段总结与放行判断

### 完成度

| 任务 | 状态 | 产物 |
|---|---|---|
| T0 版本与记录 | ✅ 完成 | `run_manifest.json`, `code_diff.patch` |
| T1 评委修复 | ✅ 完成（真实 API 验证待做） | `ci_judge_v2.py`, `t1_regression_tests.json` |
| T2 最终记录与统计 | ✅ 完成（参考值零失配） | `per_sample.final.jsonl`, `summary.final.json`, `consistency_check.json` |
| T3 报告更正 + LDA | ✅ 完成 | `subspace_selectivity_v2.py`, `lda_v2.json/png` |
| T4 盲审包 | ✅ 已准备 / **待人工** | `blind_review/*` |
| T6 20 场景数据 | ✅ 数据完成 / 模型检查未运行 | `scenarios_v2.jsonl`, `checks_v2.json` |
| T5 旧合成集重算 | ⏳ 未开始（依赖 T1 真实验证） | — |

### 代码修复与数字变化汇总

| 项 | 修复前（round 1） | 修复后（本轮） |
|---|---|---|
| 评委模板 | 写死"should NOT reveal"，授权披露被误判 | 授权感知，`disclosed`/`violation` 分离 |
| schema | `{}` 可被补成"安全"；字符串布尔被接受 | 严格校验 → unknown |
| 零有效样本 | `max(n,1)` 造 0% | null |
| 缓存 | 失败不入盘、跨实例不持久 | 入盘 + `retry_unknown` + 协议化键 |
| Standard both_leak | 108（错） | **110** |
| pair_valid | 漏 00 单元 | 五类齐全，四单元之和 = valid_pairs |
| bootstrap | `None` 当 0 | 按基础场景聚类，`None` 不参与 |
| LDA 归因 | 声称修复泄露使非对角下降 | **实为折划分改动所致**，已撤销 |
| 词袋捷径（20 场景） | AUROC 0.825 | **0.506** |

### 下一阶段建议（按清单分支判断）

1. **先做 T1 的真实 API 小样本验证**（授权/未授权各 3–5 例），确认合法披露不被计入违规；**未通过不得启动 T5 完整重评**。
2. **人工盲审**：把 `blind_review/` 交给真人评审（至少 1 人完成随机集，另请 1 人复核重叠子集）。**人工结果返回前，所有行为结论保持待定**。
3. **T6 实验**：在空闲 GPU（1 或 3）上先用 2–3 个场景小批量验证采集流程，再跑 80 输入；建立 TF-IDF/早层/随机标签对照，选层与阈值只在验证集拟合。20 场景**只作管线检查**，**不得**充当正式测试集，也不据其最佳层锁定结论。
4. **正式 pilot**（约 200 场景）需**预先固定**分组训练/验证/测试规则；20 个开发场景不能复用作未见测试集。
5. 评估仍不稳定前**不做机制归因**；若模板对照能完全解释探针，则先修数据/测量。

### 研究定位（采纳复核建议）

> 本轮不宣布"推翻核心结论"。定位为：**先建立可靠的上下文隐私规范测量，再检验生成过程中的表示—行为联系。**
> 若去除捷径后差距仍在 → 推进机制；若显著缩小 → 测量效度本身也值得系统研究。

---

## 产物索引

```
repo/outputs/research_next_round/round2_2026-09-29/
├── run_manifest.json               T0 版本/环境/哈希/GPU
├── code_diff.patch                 T0 代码 diff
├── t1_regression_tests.json        T1.3 17/17
├── per_sample.final.jsonl          T2 810 行最终记录（含 provenance 与不可恢复字段）
├── summary.final.json              T2 主表 + 配对 + bootstrap
├── consistency_check.json          T2 不变量 + 参考值比对 + 历史差异说明
├── lda_v2/lda_v2.json|png          T3 同折协议 LDA + 混淆矩阵 + 置换对照
└── blind_review/                   T4 盲审包（待人工）

repo/src/
├── run_manifest.py                 T0
├── evaluation/ci_judge_v2.py       T1
├── finalise_round1.py              T2
├── subspace_selectivity_v2.py      T3
├── build_blind_package.py          T4
└── pilot_scenarios_v2.py           T6
repo/tests/test_ci_judge_v2.py      T1.3
repo/data/pilot_v2/                 T6 数据 80 输入 + 检查
```

**原始数据未被覆盖**：`per_sample.jsonl`、`rejudge_unknown.json`、旧 judge cache、旧报告全部保留；本轮新增版本并标注来源。
