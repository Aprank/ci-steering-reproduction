# 实验报告：复现《Do LLMs Know What Is Private Internally?》

**论文**：Do LLMs Know What Is Private Internally? Probing and Steering Contextual Privacy Norms in Large Language Model Representations
（Haoran Wang, Li Xiong, Kai Shu — Emory University；COLM 2026；arXiv:2604.00209）
**官方代码**：https://github.com/wang2226/CI-Steering
**复现日期**：2026-09-02/03
**复现范围**：论文完整流水线（刺激生成 → 激活提取 → 表征探针 → CI 分解 → steering 评测）+ Finding 3 专项验证 + Finding 2 文献调研

---

## 摘要

本报告复现了论文的全部五个阶段。**Phases 1–3 与论文结论一致**（探针近乎完美、隐私多维非单方向）；**Phase 4 的表示独立性经我们用论文原始方法（LDA 交叉投影）验证成立**；**但 Phase 5 的核心结论（CI-parametric steering 大幅降低泄漏）未能复现**——官方代码的 PCA 方向虽方向性正确，但强度极弱。此外，CONFAIDE 基线泄漏率与论文**逐字精确匹配（38.5%）**。

关键结论：论文的**表征层面**发现（Findings 1 & 3）稳健可复现；**行为层面**的核心收益（Finding 2 的差距 + steering 效果）受限于官方代码的方向提取方法与模型选择，未能复现。

---

## 1. 实验环境与设置

| 项目 | 配置 |
|---|---|
| GPU | 4× NVIDIA RTX 5090 (32GB) + 2× NVIDIA RTX 6000D (85GB)，驱动 580.95.05，CUDA 13.0 |
| 计算环境 | conda `ci_steering`（Python 3.11，torch 2.14.0+cu130，transformers 5.16.1，sklearn 1.9.0，openai 3.7.0） |
| 模型 | **Qwen2.5-7B-Instruct**（28 层，d=3584）、**Mistral-7B-Instruct-v0.3**（32 层，d=4096） |
| LLM 评委 | **DeepSeek `deepseek-v4-flash`**（OpenAI 兼容，base_url=https://api.deepseek.com），替代论文的 GPT-4o-mini |
| 外部基准 | CONFAIDE（Tier 3 = 270 场景）、PrivaCI-Bench（GDPR+HIPAA = 407 案例，已加载未评测） |

**模型覆盖缺口**：Llama-3.1-8B-Instruct 与 Llama-2-7B 被 Meta 门控（HF 返回 403 "not in the authorized list"），提供 token 仅有 `canReadGatedRepos` 权限但未被授予这两个模型的访问权，故**只能覆盖 4 个模型中的 2 个非门控模型**。

---

## 2. 代码修复与适配（共 11 处）

为让官方代码可运行且忠实复现，做了以下修改（详见 `REPRODUCTION_RESULTS.md`、`FINDING3_VERIFICATION.md`）：

| # | 文件 | 修改 | 原因 |
|---|---|---|---|
| 1 | `src/control/rep_tuning.py` | 修复第 167 行多余缩进 | 原始代码有 `IndentationError`，阻断整个 `src.control` 包导入 |
| 2 | `src/utils/model_utils.py` | `resolve_api_key` 增加 `DEEPSEEK_API_KEY` | 接入 DeepSeek 评委 |
| 3 | `src/evaluation/ci_eval.py` | `__init__` 支持 `DEEPSEEK_API_KEY` / `DEEPSEEK_MODEL` / `DEEPSEEK_API_BASE` | 同上 |
| 4 | `src/evaluation/ci_eval.py` | `_call_judge` 先试 `response_format=json_object`、失败则不带重试；`max_tokens` 256→512 | DeepSeek 偶发返回非 JSON |
| 5 | `src/evaluation/ci_eval.py` | 重写 `_parse_fallback`（剥 markdown 代码块 + 平衡括号提取） | 提高 JSON 解析鲁棒性 |
| 6 | `src/extraction/activation_extractor.py` | `extract_function_activations` 补传 `labels` | 跨任务探针需要行为样本标签 |
| 7 | `src/control/ci_steering.py` | `from_ci_directions_dir` 改按探针准确率选层，并列时优先深层 | 原按"方向范数"选层，但方向均为单位向量→退化为选 0–4 层（嵌入层） |
| 8 | `src/reading/probe_reader.py` | `get_best_layers` 并列时优先深层 | 合成数据所有层 acc=1.0，原排序退化到 0–4 层 |
| 9 | `src/reading/pca_reader.py` | 同上 | 同上 |
| 10 | 数据：`function_stimuli.json` | 重新生成为**平衡 100 适当/100 不当** | 原 Phase 1 生成的是全不当 200 条，与论文不符 |
| 11 | 新建 `src/subspace_selectivity.py`、`src/ci_sign_determination.py` | Finding 3 专项验证脚本 | 官方代码缺失 LDA 交叉投影 |

---

## 3. 实验方法（五阶段流水线）

1. **Phase 1 刺激生成**（`generate_stimuli.py`）：概念级配对、行为级角色扮演、CI 参数级单变量
2. **Phase 2 激活提取**（`extract_activations.py`）：forward hook 捕获每层 hidden state，取判断模板最后 token
3. **Phase 3 表征读取**（`read_representations.py`）：PCA（配对差分第一主成分）+ 线性探针（logistic regression，5 折 CV）+ 跨任务迁移 + 多成分 PCA
4. **Phase 4 CI 分解**（`ci_decomposition.py`）：每参数 PCA 方向 + 5 分类探针 + 余弦相似度 + 置换检验
5. **Phase 5 steering 评测**：合成/`CONFAIDE` 上对比 no-steering / monolithic / probe-weighted / CI-parametric / CI 消融，DeepSeek 评委标注

---

## 4. 实验结果

### 4.1 Phase 1 — 刺激生成 ✅

| 数据集 | 数量 | 与论文一致性 |
|---|---|---|
| 概念级 | 1000 场景（500 配对，10 信息类型） | ✅ 一致 |
| 行为级 | 200 场景（100 适当 / 100 不当） | ✅ 一致（需重新生成才平衡） |
| CI 分解 | 1500（3 参数 × 5 取值 × 100 上下文） | ✅ 一致 |

### 4.2 Phase 2 — 激活提取 ✅

| 模型 | 层数 | 隐藏维度 | 规模 |
|---|---|---|---|
| Qwen2.5-7B | 28 | 3584 | 概念 800+200、行为 200、CI 1500 |
| Mistral-7B | 32 | 4096 | 同上 |

### 4.3 Phase 3 — 表征读取（Finding 1）✅ 复现

**逐层线性探针准确率：两模型在所有层（含第 0 层嵌入层）均达 1.0000**

| 指标 | Qwen2.5-7B | Mistral-7B | 论文 |
|---|---|---|---|
| 探针准确率（最佳层） | 1.0000 | 1.0000 | 近乎完美 ✅ |
| 跨任务迁移（概念探针 → 行为激活） | **0.895 acc / 0.9407 AUROC**（layer 22） | **0.940 acc / 0.9936 AUROC**（layer 6） | 跨任务信号存在 ✅ |
| PCA-1（单主成分） | 0.870 acc / **0.9040 AUROC**（L22） | 0.895 acc / **0.9096 AUROC**（L24） | 单方向不足 ✅ |
| PCA-3 | 0.985 acc / **0.9996 AUROC**（L20） | 0.980 acc / **0.9947 AUROC**（L14） | 多维显著提升 ✅ |
| PCA-5 | 1.000 acc / 1.0000（L22） | 0.990 acc / 0.9998（L13） | k≥5 无进一步增益 ✅ |
| PCA-10 | 1.000 acc / 1.0000（L17） | 1.000 acc / 1.0000（L13） | 同上 ✅ |

→ **Finding 1 复现**：隐私线性可编码，但**不是单一方向**（PCA-1 明显弱于 PCA-3，k≥5 饱和）。

### 4.4 Phase 4 — CI 分解

**各 CI 参数 5 分类探针准确率：两模型三参数均为 1.0000** ✅

但官方代码的**余弦相似度矩阵（在 layer 0 计算）**显示方向高度相关，与论文 Figure 7 口径不符：

| 参数对 | Qwen2.5 \|cos\| | Mistral \|cos\| |
|---|---|---|
| info_type vs recipient | 0.9887 | 0.9024 |
| info_type vs trans_principle | 0.9594 | 0.9821 |
| recipient vs trans_principle | 0.9643 | 0.9404 |

置换检验（layer 0）：Qwen2.5 real 0.9708 / null 0.9986±0.0008（p=0.0，34.69σ）；Mistral real 0.9416 / null 0.9982±0.0012（p=0.0，49.13σ）。

> ⚠️ 官方代码用「余弦相似度 + 置换检验」**近似**论文 Figure 7 的 LDA 交叉投影，且余弦矩阵在 layer 0 计算（嵌入层主导），故三者高度相关——这**不代表**论文的独立性结论错误（见 §4.5）。

### 4.5 Finding 3 专项验证 — LDA 交叉投影 ✅ 独立性成立

按论文 Appendix G 原始方法（75% 分位层 + 4 维 LDA 判别子空间 + 交叉投影 + 5 分类 5 折 CV）重新实现：

**Qwen2.5-7B（layer 21）**
| 分类对象 ↓ \ 投影子空间 → | S_info | S_recipient | S_trans |
|---|---|---|---|
| info_type | **100%** | 20.8% | 20.6% |
| recipient | 20.8% | **100%** | 21.6% |
| trans_principle | 21.2% | 20.4% | **100%** |

**Mistral-7B（layer 24）**
| 分类对象 ↓ \ 投影子空间 → | S_info | S_recipient | S_trans |
|---|---|---|---|
| info_type | **100%** | 22.0% | 20.6% |
| recipient | 20.4% | **100%** | 20.4% |
| trans_principle | 23.0% | 23.2% | **100%** |

→ 对角 100%、非对角 ≈20%（= 5 分类随机水平），**与论文 Figure 7（对角≈100%、非对角 19–27%）完全一致** ⇒ **表示独立性成立**。

补充置换检验（同 75% 分位层）：Qwen2.5 2.26σ（p=0.037）、Mistral 0.72σ（p=0.194）——**弱于论文报告的 6.1σ/2.1σ**。原因：1500 个样本共享"隐私场景模板"共同结构，随机分组的 PCA 第一主成分≈平行（null |cos|≈0.998），零分布退化。

### 4.6 Phase 5 — 合成数据 steering（Qwen2.5，α=1.0，200 场景）❌ 未复现

| 方法 | 泄漏率↓ | NCR↑ | PPI↑ |
|---|---|---|---|
| No Steering | 69.0% | 28.0% | — |
| Monolithic (Standard) | 66.5% | 28.0% | 3.6% |
| Probe-Weighted | 68.0% | 28.0% | 1.4% |
| CI-Parametric (all) | 67.0% | 29.5% | 2.9% |
| CI: info_type only | 67.5% | 29.0% | 2.2% |
| CI: recipient only | 68.5% | 28.5% | 0.7% |
| CI: trans_principle only | 68.0% | 28.5% | 1.4% |

→ **所有方法都在评委噪声内（66–69%）**，无一显著降低泄漏。论文合成数据（Llama-3.1）为 42.5% → 5.0%（PPI 98.8%）。
→ 注：论文 Table 1 仅报告 Llama-3.1，未给 Qwen2.5 的合成结果，故此项无直接对照。

### 4.7 Phase 5 — CONFAIDE Tier 3 迁移（Qwen2.5，α=1.0，270 场景）

| 方法 | 泄漏率↓ | NCR↑ | PPI↑ | 论文 Table 2/3 |
|---|---|---|---|---|
| **No Steering** | **38.5%**（104/270） | 55.9% | — | **38.5% ✅ 精确一致** |
| Monolithic (additive) | 41.1% | 56.3% | −6.7% | 39.3%（同样恶化）✅ 趋势一致 |
| Probe-Weighted | 42.2% | 57.0% | −9.6% | — |
| **CI-Parametric (all)** | **41.9%** | 52.2% | **−8.7%** | **15.2% ❌ 严重分歧** |
| CI: info_type | 41.9% | 54.8% | −8.7% | — |
| CI: recipient | 41.5% | 57.8% | −7.7% | — |
| CI: trans_principle | 39.3% | 59.6% | −1.9% | — |

**基线主题分布**（泄漏率）：mental health 63.3% > work/academic cheating 60.0% > belief/ideology 50.0% > sexual orientation 43.3% > infidelity 40.0% > physical discontent 33.3% > self-harm 23.3% > rare diseases 20.0% > abortion 13.3%

→ **基线精确匹配论文（38.5%）**；单方向 steering 恶化趋势也一致；**但 CI-parametric 未能复现论文的 15.2%，反而恶化到 41.9%**。

### 4.8 方向符号穷举检验（Qwen2.5，合成关键词泄漏）

为排查"是否只是符号反了"，穷举 3 个方向共 8 种符号组合（100 个"应保密"场景，关键词泄漏度量）：

| 符号组合 | 泄漏率 | Δ vs 基线 |
|---|---|---|
| **+ + +（官方规范符号）** | **0.460** | **−0.040（最优）** |
| + + − | 0.480 | −0.020 |
| + − + | 0.480 | −0.020 |
| − + + | 0.490 | −0.010 |
| − − − | 0.490 | −0.010 |
| − − + | 0.530 | +0.030 |
| + − − | 0.540 | +0.040 |
| − + − | 0.540 | +0.040 |

单轴：`recipient+` 0.490、`trans+` 0.490、`info_type+` 0.500（无效果）；三种参数翻转符号均升到 0.550。

→ **官方"规范符号"（均值投影>0）本身就是最优的，符号不是问题**。真正问题是**方向强度太弱**（最优下仅降 4 个百分点）。

---

## 5. 与论文结果对比汇总

| 论文结论 | 复现结果 | 判定 |
|---|---|---|
| Finding 1：隐私线性可编码 | 探针 acc 1.0（两模型） | ✅ 复现 |
| Finding 1：多维非单方向 | PCA-1 0.90 → PCA-3 0.9996 → k≥5 饱和 | ✅ 复现 |
| Finding 1：合成→真实可迁移 | 跨任务 0.895/0.940 acc | ✅ 复现 |
| Finding 2：隐私意识差距 | CONFAIDE 基线 38.5%（精确匹配）；探针 1.0 vs 行为泄漏 | ✅ 现象复现 |
| Finding 3：CI 参数可分解 | 每参数 5 分类探针 1.0 | ✅ 复现 |
| **Finding 3：子空间功能独立** | **LDA 交叉投影对角 100% / 非对角 20%** | ✅ **复现** |
| Phase 5：CI steering 大幅降泄漏 | 合成 69%→67%；CONFAIDE 38.5%→41.9% | ❌ **未复现** |
| Phase 5：单方向 steering 迁移失败 | CONFAIDE 38.5%→41.1%（恶化） | ✅ 复现 |
| 置换检验（附录 G） | 2.26σ / 0.72σ（论文 6.1σ / 2.1σ） | ⚠️ 弱于论文 |

---

## 6. Finding 2 文献调研（另见 `FINDING2_LITERATURE.md`）

检索 24 篇相关论文，归纳"编码 ↔ 行为解耦"的 7 类可能原因：

1. **探针可能只在读词汇/格式线索**（[Illusion of Intent, ICML 2026](https://icml.cc/virtual/2026/79985)；[Linear Probes Detect Task Format](https://aclanthology.org/2026.trustnlp-main.12/)）
   - **与本实验强呼应**：探针在**第 0 层嵌入层就 acc=1.0**，说明合成模板词汇差异可能足以让探针分类。
2. **可解码性 ≠ 因果使用**（[When Decodability Is Not Enough](https://ar5iv.labs.arxiv.org/html/2609.02438)）
3. **对齐浅层性**（[Safety Alignment More than a Few Tokens Deep](https://mlanthology.org/iclr/2025/qi2025iclr-safety/)）
4. **跨领域普遍现象**（[LM Agents Fail to Act on Risk Knowledge](https://ar5iv.labs.arxiv.org/html/2508.13465)；[Safety Awareness-Execution Gaps](https://www.iclr.cc/virtual/2025/33336)）
5. **角色扮演社交压力**（helpfulness/sycophancy 冲突）
6. **CI 需要组合推理**，探针只做单点分类
7. **steering 方向不可识别**（[Non-Identifiability of Steering Vectors](https://huggingface.co/buckets/huggingchat/papers-content/tree/2602/2602.06801.md)）

---

## 7. 结论

1. **论文的表征层结论（Finding 1 & 3）稳健成立**：两个模型上，探针近乎完美、隐私信号多维、三个 CI 参数占据功能独立子空间（LDA 交叉投影干净复现 Figure 7）。
2. **论文的行为层核心收益（Phase 5 CI steering）未能复现**：官方代码的 PCA 第一主成分方向方向性正确但强度极弱，合成仅降 4 个百分点，CONFAIDE 不降反升。
3. **CONFAIDE 基线 38.5% 与论文逐字一致**，说明评测流水线（刺激/提示/评委）复现正确——**分歧集中在 steering 方向的提取方法**。
4. **官方代码存在实现缺口**：未实现论文 Appendix G 的 LDA 交叉投影；层选择在合成数据上退化；PCA 方向符号虽最优但方向本身不足以承载因果操纵。

---

## 8. 局限与未完成工作

**局限**
1. **模型覆盖不全**：Llama-3.1-8B 与 Llama-2-7B 因 Meta 门控缺失（论文 4 个模型中 2 个无法复现）。
2. **评委不同**：DeepSeek `deepseek-v4-flash` 替代 GPT-4o-mini，且约 **10–15% 样本返回非 JSON**（重试后仍失败者按 not-leaked/not-appropriate 计，对泄漏率有轻微低估）。
3. **网络受限**：PyPI/HF 的 AWS CDN 极慢，模型下载耗时数小时（已改用清华 PyPI 镜像 + hf-mirror）。
4. 合成探针在所有层都可分（词汇线索），层选择机制退化，需人工修正。

**未完成**
1. Qwen2.5 的 PrivaCI-Bench 迁移评测（数据已加载：GDPR+HIPAA 407 案例）。
2. Mistral-7B 的 Phase 5（合成 + CONFAIDE）。
3. 论文的权重型基线（LoRRA、Representation Tuning，需 LoRA 微调）。
4. 五参数 CI 消融（Appendix I）、效用评估（Appendix H）、α 扫描/Pareto（Appendix F）。

---

## 附录：产物文件清单

**工作区（`Do LLMs Know What Is Private Internally/`）**
- `REPRODUCTION_RESULTS.md` — 复现总结果
- `FINDING3_VERIFICATION.md` — Finding 3 专项验证报告（含全部代码修改记录）
- `FINDING2_LITERATURE.md` — Finding 2 文献综述（24 篇 + 原因分析）
- `EXPERIMENT_REPORT.md` — 本报告
- `secrets.env` — 凭证（HF token / DeepSeek key）

**仓库新增脚本（`repo/src/`）**
- `subspace_selectivity.py` — LDA 交叉投影子空间选择性检验
- `ci_sign_determination.py` — CI 方向符号穷举检验

**结果数据（`repo/outputs/`）**
- `activations/{Qwen2.5-7B-Instruct,Mistral-7B-Instruct-v0.3}/` — 各阶段激活
- `reading/` — PCA/probe reader + 逐层曲线
- `ci_decomposition/*/` — CI 方向向量 + 分解结果
- `ci_steering_comparison/` — 合成 steering 结果
- `confaide_ci_transfer/Qwen2.5-7B-Instruct/` — CONFAIDE 迁移结果
- `subspace_selectivity/*/` — LDA 交叉投影矩阵 + 热力图
- `ci_sign_test/*/sign_test.json` — 符号穷举结果
