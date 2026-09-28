# 上下文压缩快照（CONTEXT SNAPSHOT）

> 用途：以最简形式保存本次会话全部关键状态，供后续继续工作时不依赖完整对话历史。
> 生成时间：2026-09-14

---

## 1. 项目与任务

| 项 | 内容 |
|---|---|
| 论文 | *Do LLMs Know What Is Private Internally? Probing and Steering Contextual Privacy Norms in LLM Representations*（Wang, Xiong, Shu；COLM 2026；arXiv:2604.00209） |
| 代码 | https://github.com/wang2226/CI-Steering |
| 工作目录 | `/home/grx/restart/reproduction/Do LLMs Know What Is Private Internally` |
| 仓库本地路径 | `<工作目录>/repo` |
| 任务演化 | ① 按 GitHub 复现论文全部方法 → ② 分项验证 Finding 1/2/3 → ③ **方向调整**：研究 CI 场景"编码↔行为"解耦的**成因**，并据成因设计**更优编码特征** |

## 2. 环境与资源约束

| 项 | 值 |
|---|---|
| GPU | 6 块：4×RTX 5090(32GB) + 2×RTX 6000D(85GB)，驱动 580.95.05，CUDA 13.0；**GPU 3 被他人占用** |
| **沙箱约束** | `/dev/nvidia*` **仅在 `danger-full-access` 模式可见** → 所有模型/GPU 命令必须用 full-access；conda/pip 写入也需 full-access |
| conda 环境 | `ci_steering`（Python 3.11，torch 2.14.0+cu130，transformers 5.16.1，sklearn 1.9.0，openai 3.7.0，peft 0.20.0） |
| 评委 | **DeepSeek `deepseek-v4-flash`**（base_url=https://api.deepseek.com），替代论文 GPT-4o-mini |
| 模型 | Qwen2.5-7B-Instruct（28 层，d=3584）✅；Mistral-7B-Instruct-v0.3（32 层，d=4096）✅；**Llama-3.1-8B / Llama-2-7B 被 Meta 门控 403，不可用** |
| 网络 | PyPI 直连极慢 → 用清华镜像；HF 用 hf-mirror.com（AWS CDN 常超时） |
| 凭证 | `<工作目录>/secrets.env`（HF_TOKEN、DEEPSEEK_API_KEY / _BASE / _MODEL） |
| 基准数据 | CONFAIDE（Tier3=270 场景）✅；PrivaCI-Bench（GDPR+HIPAA=407 案例，**已加载未评测**） |

## 3. 代码修改清单（11 处）

| # | 文件 | 修改 |
|---|---|---|
| 1 | `src/control/rep_tuning.py` | 修复第 167 行多余缩进（原 `IndentationError` 阻断整个 `src.control` 导入） |
| 2 | `src/utils/model_utils.py` | `resolve_api_key` 增加 `DEEPSEEK_API_KEY` |
| 3 | `src/evaluation/ci_eval.py` | `__init__` 支持 `DEEPSEEK_API_KEY/_MODEL/_API_BASE` |
| 4 | 同上 | `_call_judge`：先试 `response_format=json_object`、失败则不带重试；`max_tokens` 256→512 |
| 5 | 同上 | 重写 `_parse_fallback`（剥 markdown 代码块 + 平衡括号提取 JSON） |
| 6 | `src/extraction/activation_extractor.py` | `extract_function_activations` 补传 `labels` |
| 7 | `src/control/ci_steering.py` | `from_ci_directions_dir` 改按**探针准确率**选层、并列优先**深层**（原按方向范数→退化为 0–4 层） |
| 8 | `src/reading/probe_reader.py` | `get_best_layers` 并列时优先深层 |
| 9 | `src/reading/pca_reader.py` | 同上 |
| 10 | 数据 `function_stimuli.json` | 重新生成为**平衡 100 适当/100 不当**（原为全不当 200） |
| 11 | 新增 `src/subspace_selectivity.py`、`src/ci_sign_determination.py` | Finding 3 专项验证脚本 |

## 4. 实验结果（关键数字）

### Phase 1–2（刺激与激活）
- 概念 1000（500 配对 × 10 类型）；行为 200 平衡；CI 1500（3 参数 × 500）✅ 与论文一致
- 激活：Qwen2.5 28 层×3584；Mistral 32 层×4096

### Phase 3 — Finding 1 ✅ 复现
| 指标 | Qwen2.5 | Mistral |
|---|---|---|
| 探针准确率 | 1.0000（**含第 0 层**） | 1.0000（**含第 0 层**） |
| 跨任务迁移 | 0.895 acc / 0.940 AUROC (L22) | 0.940 acc / 0.994 AUROC (L6) |
| PCA-1 AUROC | 0.904 (L22) | 0.910 (L24) |
| PCA-3 AUROC | **0.9996** (L20) | **0.9947** (L14) |
| PCA-5/10 | 1.0（饱和） | 1.0（饱和） |

### Phase 4 — CI 分解
- 三参数 5 分类探针均 **1.0**（两模型）
- 官方代码余弦相似度（layer 0）：|cos| 0.90–0.99（高度相关，与论文口径不符）
- 置换检验（layer 0）：Qwen 34.69σ / Mistral 49.13σ

### Finding 3 专项（论文 Appendix G 的 LDA 交叉投影，75% 分位层）
| 模型 | 对角 | 非对角 |
|---|---|---|
| Qwen2.5 (L21) | 100/100/100% | 20.4–21.6% |
| Mistral (L24) | 100/100/100% | 20.4–23.2% |
→ **与论文 Figure 7 一致 ⇒ 表示独立性成立** ✅
（置换检验同层：Qwen 2.26σ/p=0.037、Mistral 0.72σ/p=0.194，弱于论文 6.1σ/2.1σ）

### Phase 5 — Steering
**合成（Qwen2.5，α=1.0，200 场景）**：No Steering 69.0% → Monolithic 66.5% → Probe-Weighted 68.0% → **CI-parametric 67.0%**（CI 消融：info 67.5% / recipient 68.5% / trans 68.0%）→ 全在噪声内，**未复现**

**CONFAIDE Tier 3（Qwen2.5，α=1.0，270 场景）**：
| 方法 | 泄漏率 | 论文 |
|---|---|---|
| No Steering | **38.5%** | 38.5% ✅ **逐字一致** |
| Monolithic | 41.1% | 39.3% ✅ 趋势一致 |
| Probe-Weighted | 42.2% | — |
| **CI-parametric** | **41.9%** | **15.2%** ❌ **严重分歧** |
| CI: info / recipient / trans | 41.9 / 41.5 / 39.3% | — |

主题分布（基线）：mental health 63.3% > cheating 60.0% > belief 50.0% > sexual orientation 43.3% > infidelity 40.0% > physical discontent 33.3% > self-harm 23.3% > rare diseases 20.0% > abortion 13.3%

### 方向符号穷举（Qwen2.5，合成关键词泄漏，基线 0.500）
- **+++（官方规范符号）= 0.460（最优）**；其余 7 组合 0.480–0.540
- 单轴：recipient+ 0.490、trans+ 0.490、info_type+ 0.500；负数符号均 0.550
→ **符号无误（规范符号已最优）；真正问题是方向强度太弱**（最优仅降 4pp）

## 5. 核心结论

1. **论文表征层结论（Finding 1 & 3）稳健成立**（2 模型，含用论文原始 LDA 交叉投影验证）。
2. **论文行为层核心收益（CI steering 降泄漏）未复现**：合成仅降 ~4pp，CONFAIDE 不降反升。
3. **根因已定位**：官方代码用「5 分类 PCA 第一主成分」作 steering 方向，**符号正确但强度太弱**；且官方代码**未实现 LDA 交叉投影**、层选择在合成数据上退化。
4. **CONFAIDE 基线 38.5% 逐字一致** → 评测流水线正确，分歧集中在**方向提取方法**。
5. 已**更正**早前"方向符号反了"的错误判断（符号穷举证伪）。

## 6. 文档与产物（8 份 md + 结果数据）

| 文档 | 内容 |
|---|---|
| `RESEARCH_PROGRESS_CI_DECOUPLING.md` | **当前主文档**：新方向（成因→特征），易读版，含术语表 |
| `RESEARCH_PROGRESS.md` | 原方向研究进展（复现视角） |
| `EXPERIMENT_REPORT.md` | 完整实验报告 |
| `REPRODUCTION_RESULTS.md` | 复现总结果 |
| `FINDING3_VERIFICATION.md` | Finding 3 专项验证（含全部代码修改记录） |
| `FINDING2_LITERATURE.md` | Finding 2 成因综述（24 篇） |
| `FINDING2_BETTER_PROBES.md` | 更优探测方法综述（21 篇） |
| `CONTEXT_SNAPSHOT.md` | 本文件 |
| 结果数据 | `repo/outputs/{activations,reading,ci_decomposition,ci_steering_comparison,confaide_ci_transfer,subspace_selectivity,ci_sign_test}/` |

> 两篇 Finding 2 文档重复 4 篇（Illusion of Intent / CONFAIDE / I've Decided to Leak / The Model's Tell），去重后合计 41 篇。

## 7. 当前研究方向（新）

**路径**：先定成因 → 再据成因找更优编码特征

**RQ1 成因（6 假设）**：H1 探针只读词汇线索 / H2 可解码≠因果使用 / H3 对齐浅层性 / H4 组合推理缺口 / H5 社交压力 / H6 方向太弱或不可识别
**RQ2 特征（4 问题）**：RQ2.1 位置与层 / RQ2.2 表征粒度 / RQ2.3 预测目标（行为 vs 语义）/ RQ2.4 泛化与提前量

**工作计划**：WP1 落差基线与度量 → WP2 六病因体检 → WP3 贡献归因 → WP4 三条特征路线 → WP5 对比验证 → WP6 成文

**病因初步排序**：H1（高，依据：探针第 0 层即 1.0）、H6（高，依据：符号最优但仅 4pp）、H3/H2/H4（中）、H5（待验证）

## 8. 下一步（建议顺序）

1. **H1 词汇平衡实验**（1–2 天，成本最低、解释力最强）：改造刺激使适当/不当**用词相同、只改语境**，重跑 Phase 2–3 比探针准确率
2. H3 泄漏位置分析（1 天，复用已有生成结果）
3. WP1 落差基准 Δ（1 天）
4. H2 因果干预（2–3 天）
5. WP4 路线一（多层+多位置聚合特征，3–5 天）

**未完成扩展**：PrivaCI 迁移评测、Mistral Phase 5、权重型基线（LoRRA / Rep Tuning）、五参数消融、α 扫描/Pareto、效用评估

## 9. 常用命令模板

```bash
# 所有 GPU/模型命令需 danger-full-access 沙箱
source /home/grx/anaconda3/etc/profile.d/conda.sh && conda activate ci_steering
source "<工作目录>/secrets.env"
cd "<工作目录>/repo"
CUDA_VISIBLE_DEVICES=0 python src/<script>.py <args>
```
关键路径：激活 `outputs/activations/<model>/`；读取 `outputs/reading/`（Qwen，默认）与 `outputs/reading/Mistral-7B-Instruct-v0.3/`；CI 方向 `outputs/ci_decomposition/<model>/`
