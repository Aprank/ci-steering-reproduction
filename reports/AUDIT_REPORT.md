# 评测审计报告（步骤 1–5）

**日期**：2026-09-28
**依据**：`NEXT_STEPS.md`（2026-09-28）执行顺序第 1–5 步
**状态**：步骤 1–5 已完成；步骤 6（20 个基础场景）未开始
**标注约定**：**【实测】**= 本仓库产物计算结果；**【推断】**= 由实测支持的机制解释；**【未验证】**= 尚未检验

---

## 摘要

1. **原报告的核心行为数字是评测缺陷造成的**。【实测】No Steering 从报告的 38.5% 修正为 **42.96%**，CI-Parametric 从 41.9% 修正为 **50.94%**。
2. **"与论文 38.5% 逐字一致"是巧合**。【实测】原始运行有 28/270（10.4%）评委解析失败被计为"不泄露"，系统性低估了泄漏率。
3. **unknown 系统性偏向泄漏样本**。【实测】19 条 unknown 复评后 16 条成功，其中 **11 条（69%）是泄漏**，远高于基线 ~43%。
4. **CI-Parametric 明确使泄漏恶化**。【实测】50.94% vs 基线 42.96%（+7.98pp），配对净增 **20** 条泄漏；残留 3 条 unknown 的保守边界 [50.37%, 51.48%] 与基线**完全不相交** ⇒ 结论对未知处理稳健。
5. **概念级"完美探针"不构成"模型编码规范"的证据**。【实测】test 的模板签名 100% 出现在 train，且 label 由模板唯一决定；**不使用任何模型的模板查表基线即可达 test acc = 1.0000**。
6. **LDA 交叉投影的选择性结论在折内重做后仍成立**。【实测】对角线 100%（recipient 99.8%），非对角降至 11–18%。

---

## 1. 材料核验（步骤 1）

### 1.1 已确认存在

| 项 | 位置 / 值 | 证据 |
|---|---|---|
| 代码仓库 | `repo/`，commit `5c5edc3` | `git log` |
| 工作区改动 | 7 个已修改 + 4 个新增文件 | `git status --porcelain` |
| 计算环境 | conda `ci_steering`：torch 2.14.0+cu130 / transformers 5.16.1 / sklearn 1.9.0 | 实测导入 |
| 模型 | Qwen2.5-7B-Instruct（15G）、Mistral-7B-Instruct-v0.3（28G） | HF 缓存 |
| 激活 | 两模型各 6 类（concept_train/test、function、ci_×3） | `outputs/activations/` |
| 刺激与划分 | `concept_stimuli_{train,test}.json`、`function_stimuli_balanced.json`、`ci_decomposition_stimuli.json` | `data/stimuli/` |
| 结果与缓存 | CONFAIDE 迁移结果 + 评委缓存 623 条；合成结果 + 缓存 728 条 | `outputs/` |

### 1.2 关键缺口（原运行未持久化）

| 缺失项 | 影响 | 处置 |
|---|---|---|
| 逐样本**方法归属** | 评委缓存以 `sha256(judge prompt)` 为键，`index` 是单次评测内序号（各方法均为 0–269），无法区分方法 | 通过**确定性重生成 + 哈希命中**重建归属 |
| 完整模型回答 | 结果文件只存每方法前 3 条；缓存仅 200 字符 preview | 本次审计**重新生成并完整落盘**（810 条） |
| **解析失败样本** | 原代码失败时返回 error dict 且**不写缓存**，仅出现在未落盘的控制台日志 | 本次审计以 `status=unknown` **显式记录**并保留 `raw_content` |
| 激活提取的层语义 | 报告称"第 0 层=嵌入层" | 见 §5.3（**【实测】为第 1 个 transformer block 输出**） |

### 1.3 计算资源核验

【实测】报告中的 GPU 配置**不能直接使用**：GPU 0/2/5 已被他人占用（利用率 100%）。首次审计在 GPU 0 上因 OOM 失败。改用 **GPU 4**（RTX 6000D，74.5 GB 空闲）后成功。

---

## 2. 原报告声明审计（步骤 2）

| # | 原报告表述 | 审计结论 |
|---|---|---|
| 1 | No Steering 38.5% 与论文"**精确一致**" | ❌ **不成立**。修正后为 **42.96%**；一致性源于未知样本被计为"不泄露" |
| 2 | "所有 steering 方法都在**评委噪声内**" | ❌ **不成立**。修正后 CI 与基线**边界不相交**；且原报告无重复标注或人工对照，无权声称噪声内 |
| 3 | 非 JSON 比例"5–10%"（复现报告）与"10–15%"（实验报告） | ❌ **矛盾且均未从日志重算**。**【实测】**原始 CONFAIDE No Steering 失败率 28/270 = **10.4%** |
| 4 | "第 0 层（嵌入层）" | ⚠️ **表述错误**。hook 挂在 `model.model.layers[i]` 的**输出**上 ⇒ 索引 0 = 第 1 个 transformer block 输出 |
| 5 | "方向太弱是**真正根因**" | ⚠️ **过度归因**。符号穷举仅覆盖固定模型/数据/层/强度/指标，不足以锁定唯一根因 |
| 6 | LDA 交叉投影 ⇒ 独立性 | ⚠️ 仅支持该设置下的**判别选择性**，不等于功能或因果独立（原文已注，此处重申） |

---

## 3. 评测流程修复（步骤 3）

### 3.1 代码变更

| 文件 | 变更 | 目的 |
|---|---|---|
| `src/evaluation/ci_eval.py` `_call_judge` | 最终失败返回 `status="unknown"`、`leaked/refused/appropriate=None`，保存 `raw_content`/`error_detail`，**并将失败写入缓存** | 不再默认判为"不泄露"；unknown 可复现 |
| `src/evaluation/ci_eval.py` `evaluate_privacy_leakage` | 新增 `n_valid`/`n_unknown`/`unknown_rate`/`leakage_rate_lower_bound`/`leakage_rate_upper_bound`；`overall_leakage_rate` 改为 **valid-only**；保留 `legacy_leakage_rate_unknown_as_not_leaked` 仅供对照 | 主指标不再把 unknown 当安全 |
| `src/evaluation/ci_eval.py` `compute_ppi` | 新增 `ppi_worst_case`/`ppi_best_case`/`ppi_sign_is_robust` | 效应方向对未知处理的稳健性 |
| `src/audit_leakage.py`（新增） | 确定性重生成 → 哈希命中旧缓存 → 未命中重评 → 落盘逐样本 JSONL | 复用已有评委结果，重建方法归属 |
| `src/subspace_selectivity.py` | 新增 `--nested`：折内重拟合 LDA | 修正全数据拟合导致的乐观偏差 |

### 3.2 缓存复用有效性

【实测】哈希命中率：No Steering 242/270、Standard 255/270、CI 224/270（82–94%）⇒ **确定性重生成成功复现原始回答**，旧评委判定得以零成本复用。

### 3.3 失败模式的真实原因

【实测】19 条 unknown 中 18 条 `raw_content` 为**空字符串**（非 JSON 格式错误）。
【推断+实测验证】将 `max_tokens` 从 512 提升到 2048 后，**16/19 恢复**，3 条仍为空 ⇒ 失败机制是**推理内容耗尽 token 预算，导致 `content` 被截断为空**，而非解析逻辑缺陷。

---

## 4. 修正后结果（步骤 4）

### 4.1 主结果（Qwen2.5-7B / CONFAIDE Tier 3 / 270 场景 / α=1.0）

【实测】

| 方法 | N | valid | unknown | 确认泄漏 | **valid-only 泄漏率** | 保守上下界 |
|---|---|---|---|---|---|---|
| No Steering | 270 | 270 | 0 | 116 | **42.96%** | [42.96%, 42.96%] |
| Standard Steering | 270 | 270 | 0 | 118 | **43.70%** | [43.70%, 43.70%] |
| **CI-Parametric (all)** | 270 | 267 | 3 | 136 | **50.94%** | **[50.37%, 51.48%]** |

*（unknown 经 `max_tokens=2048` 复评恢复：No Steering 3 条→含 1 泄漏；Standard 2 条→含 1 泄漏；CI 11 条→含 9 泄漏）*

### 4.2 与原报告及论文的对比

| 方法 | 原报告 | 修正后 | 变化 | 论文 Table 2/3 |
|---|---|---|---|---|
| No Steering | 38.5% | **42.96%** | **+4.46pp** | 38.5% ⇒ **不再一致** |
| Standard | 41.1% | 43.70% | +2.6pp | 39.3%（趋势仍为"恶化"） |
| CI-Parametric | 41.9% | **50.94%** | **+9.04pp** | 15.2% ⇒ **分歧进一步扩大** |

### 4.3 配对分析（按场景配对，剔除任一方为 unknown 的对）

【实测】

| 对比 | both 泄漏 | 仅基线泄漏 | 仅该方法泄漏 | 净增泄漏 |
|---|---|---|---|---|
| Standard vs No Steering | 108 | 6 | 8 | **+2** |
| CI vs No Steering | 98 | 18 | 38 | **+20** |

（未恢复 unknown 前的原始口径：Standard +2、CI +14；恢复后 CI 增至 +20 ⇒ unknown 确实偏向泄漏）

### 4.4 结论（步骤 4）

【实测，稳健】在修正评测缺陷后：
- 基线泄漏率为 **42.96%**，**不再与论文 38.5% 一致**；
- **CI-Parametric steering 使泄漏显著恶化**（+7.98pp；配对净增 20；保守边界与基线不相交）；
- **Standard steering 与基线无可检出差异**（+0.74pp，配对净 +2）；
- 论文声称的"CI 把 Qwen2.5 CONFAIDE 泄漏降到 15.2%"**被强证据反驳**。

---

## 5. 数据与拟合范围审查（步骤 5）

### 5.1 模板捷径与标签泄露【实测，严重】

| 检查 | 结果 |
|---|---|
| test 模板签名是否出现在 train | **76/76 = 100%** |
| train 中"一个签名 → 多个 label" | **0 个**（label 由模板唯一决定） |
| test 中"一个签名 → 多个 label" | **0 个** |
| test 样本其签名在 train 已被固定 label | **200/200** |
| **无模型模板查表基线（train 签名→label）对 test 的准确率** | **1.0000（200/200）** |

⇒ **概念级任务的 label 可由模板文本完全决定，且 train/test 共享全部模板**。
**因此"探针 acc = 1.0"对该任务而言不构成"模型编码隐私规范"的证据**：任何查表法都能满分。这是 Finding 1 的**效度威胁**，也是"编码-行为差距"中"编码"一侧可能被高估的直接原因。

### 5.2 CI 参数分类的字面泄露【实测】

| 参数 | `varied_value` 字面出现在输入文本中的比例 |
|---|---|
| recipient | **500/500 = 100%**（如 "a stranger" 原文出现） |
| info_type | **500/500 = 100%** |
| transmission_principle | 0%（键名未出现，但**对应取值句字面出现**，如 "has not given permission"） |

⇒ 5 分类探针的 1.0 准确率可由输入字面内容解释，**不足以证明"该 CI 参数被编码为独立表示"**。

### 5.3 激活位置与层语义【实测（代码级）】

- `ModelHelper.register_hooks` 挂在 `model.model.layers[idx]` 的 **forward 输出**上 ⇒ **索引 0 = 第 1 个 transformer block 的输出**，**不是词嵌入**。
- token 位置：`padding_side="left"` + `hidden[:, -1, :]` ⇒ 取**最后一个真实 token**（判断模板末尾 "this practice is"）。
- 影响：原报告"第 0 层（嵌入层）就 acc=1.0"的表述**不准确**，但**削弱了**"纯词汇捷径"的强解释——第 1 个 block 输出已含注意力混合。故 H1 仍需 §5.1 的词汇平衡实验来定论。
- 【未验证】尚未用同一输入的"纯 embedding vs layer-0 激活"做逐元素比对。

### 5.4 标签来源

| 数据集 | 标签来源 | 是否与模板/字面绑定 |
|---|---|---|
| 概念级 | 生成时所用模板（appropriate / inappropriate 两套） | **是**（见 §5.1） |
| CI 分解 | `varied_value`（5 个类别） | **是**（见 §5.2） |
| 行为级 | `is_appropriate` / `expected_behavior` | 两类使用**不同模板族与不同 system prompt**（不当："…in a natural conversational tone. Only give X's direct reply."；适当："You are X. Respond in character as X would."）⇒ **亦有表面差异** |

### 5.5 拟合范围

| 环节 | 原协议 | 问题 | 处置 |
|---|---|---|---|
| PCA/探针 | 在 train 拟合、test 评估；pair_id 不跨 split（【实测】train 400 / test 100，交集 0） | **无验证集**；报告排序按 **test AUROC** 选最佳层 | 【未修复】需引入验证集选层 |
| **LDA 交叉投影** | 在**全 500 样本**拟合 LDA，再对投影做 5 折 CV | **对角线乐观偏差**（LDA 见过 CV 测试折） | ✅ 已实现 `--nested` 折内重做 |
| LDA 折内重做结果 | — | — | 【实测】对角 **100% / 100% / 99.8%**，非对角 **11.0–18.2%** ⇒ 选择性结论**仍成立** |

---

## 6. 结论与不确定性声明

### 6.1 经实测确立（可复核）

1. 原报告 38.5% 为评测缺陷产物；修正后基线 **42.96%**。
2. unknown **系统性偏向泄漏**（恢复样本泄漏率 69% vs 基线 43%）。
3. **CI-Parametric steering 在本设置下显著增加泄漏**（50.94%；配对净 +20；保守边界与基线不相交）。
4. **Standard steering 与基线无可检出差异**。
5. 概念级任务的 label **可由模板文本完全决定**，train/test **共享全部模板**，无模型基线可达 1.0 ⇒ 该探针结果**不能**作为"模型编码规范"的证据。
6. LDA 交叉投影的选择性**在折内协议下仍成立**（对角 ≈100%、非对角低于随机）。

### 6.2 仅为推断（有证据但未确证）

- 评委失败机制 = 推理 token 耗尽（16/19 恢复支持，但未直接读取 API 的 `finish_reason` 全量分布）。
- CI steering 增加泄漏的**机制**未知（方向强度/层选择/α 均未系统排查）。

### 6.3 尚未验证

- 激活位置（纯 embedding vs layer-0）的逐元素比对。
- 模板捷径对"模型内部是否编码规范"的最终裁决 —— 需**词汇平衡/模板留出**实验（步骤 6–7）。
- 论文 Llama-3.1 结果（门控，无法访问）。
- 人工盲审（未做）。
- 合成数据（200 场景）的同样修正（本轮只审计了 CONFAIDE）。

### 6.4 与原报告的差异性质

本报告**不是**"原协议复现"，而是**修正评测缺陷后的再分析**。两套口径均保留：
- 原协议（unknown 当不泄露）：`legacy_leakage_rate_unknown_as_not_leaked`
- 修正协议（valid-only + 边界）：主指标

---

## 7. 产物清单

| 文件 | 内容 |
|---|---|
| `repo/src/audit_leakage.py` | 审计脚本（新增） |
| `repo/outputs/audit_confaide/confaide_Qwen2.5-7B-Instruct/per_sample.jsonl` | **810 条**逐样本记录（method/i/status/leaked/response/scenario/raw_content…） |
| 同上 `summary.json` | valid-only、unknown 率、上下界、配对差值 |
| 同上 `rejudge_unknown.json` | 19 条 unknown 的 `max_tokens=2048` 复评结果 |
| 同上 `judge_cache/gpt_judge_cache.json` | 缓存副本（原始 342311 B **未被修改**） |
| `repo/outputs/subspace_selectivity_nested/` | 折内 LDA 交叉投影结果 |
| `repo/src/evaluation/ci_eval.py` | unknown 处理与边界指标 |

---

## 8. 下一步（对应 NEXT_STEPS 步骤 6）

按 `NEXT_STEPS.md` §2 构建 **20 个基础场景**，每个含：固定虚构敏感事实、固定任务、固定接收者；**允许/不允许 × 普通/强调完整性** 共 4 个变体（强化任务要求**不得改变披露授权**）。

本轮已确立的设计约束（来自步骤 5 的实测教训）：
1. **模板与实体必须按场景隔离**，训练/验证/测试按基础场景划分（100/40/60），同一场景的 4 个变体归入同一集合；
2. 标签**不得与模板文本一一对应**——同一措辞需同时出现在允许与不允许条件下；
3. 需设置**词袋/TF-IDF 与早层表示对照**，若对照同样能分类，则不得声称存在规范专用计算；
4. 层、阈值、超参**只在验证集选择**。
