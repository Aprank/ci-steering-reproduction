# CI-Steering Reproduction & Audit

对论文 **《Do LLMs Know What Is Private Internally? Probing and Steering Contextual Privacy Norms in Large Language Model Representations》**
（Haoran Wang, Li Xiong, Kai Shu — COLM 2026；arXiv:2604.00209）的**独立复现与评测审计**。

- 官方代码：https://github.com/wang2226/CI-Steering
- 本仓库：复现脚本、审计工具、结果数据、分析报告

---

## 一、本项目做了什么

1. **完整复现**论文五阶段流水线：刺激生成 → 激活提取 → 表征探针 → CI 参数分解 → steering 评测。
2. **逐条检验**论文三大发现（Finding 1/2/3），并用论文 Appendix G 的**原始方法（LDA 交叉投影）**独立验证 Finding 3。
3. **评测审计**：发现并修复原评测流程中"评委解析失败被默认判为不泄露"的缺陷，重算全部行为指标。
4. **数据与效度审查**：检查模板捷径、标签泄露、激活层语义、PCA/LDA 拟合范围。

---

## 二、主要结论（含对原报告的更正）

### 2.1 经审计修正的关键数字（Qwen2.5-7B / CONFAIDE Tier 3 / 270 场景 / α=1.0）

| 方法 | 修正后 valid-only 泄漏率 | 保守上下界 | 原报告值 |
|---|---|---|---|
| No Steering | **42.96%** | [42.96%, 42.96%] | 38.5% |
| Standard Steering | **43.70%** | [43.70%, 43.70%] | 41.1% |
| CI-Parametric (all) | **50.94%** | [50.37%, 51.48%] | 41.9% |

- **"与论文 38.5% 逐字一致"是评测缺陷造成的巧合**：原始运行有 28/270（10.4%）评委解析失败被计为"不泄露"。
- **unknown 系统性偏向泄漏样本**：19 条 unknown 复评后恢复 16 条，其中 **11 条（69%）是泄漏**。
- **CI-Parametric steering 显著增加泄漏**（+7.98pp；配对净增 20 条；保守边界与基线完全不相交）。
- 失败真因：评委模型（推理模型）的 `reasoning` 耗尽 `max_tokens`，导致 `content` 为空 ⇒ 提高 `max_tokens` 可恢复 16/19。

### 2.2 表征层结论仍然成立

| 检验 | 结果 |
|---|---|
| Finding 1：隐私线性可编码但多维 | 探针 acc 1.0；PCA-1 0.90 → PCA-3 0.9996（两模型一致） |
| Finding 3：CI 参数占据独立子空间 | LDA 交叉投影**对角 100% / 非对角 20%**，与论文 Figure 7 一致 |
| Finding 3（折内重做，更严格） | 对角 100%/100%/99.8%，非对角降至 11–18% ⇒ 结论**仍成立** |

### 2.3 重要效度威胁（概念级探针）

| 检查 | 结果 |
|---|---|
| test 模板签名出现在 train | **76/76 = 100%** |
| 一个模板签名 → 多个 label | **0 个**（label 由模板唯一决定） |
| **无模型模板查表基线对 test 的准确率** | **1.0000（200/200）** |

⇒ 概念级任务的标签可由模板文本完全决定，**"探针 acc = 1.0"不构成"模型编码隐私规范"的证据**。

### 2.4 其他更正

- 原报告"第 0 层（嵌入层）"表述有误：hook 挂在 `model.model.layers[i]` 输出，索引 0 = **第 1 个 transformer block 输出**。
- CI 分解的类别字符串（`recipient`/`info_type`）**100% 字面出现在输入文本中**，5 分类准确率可由字面内容解释。
- 原报告"所有方法都在评委噪声内"的表述**不成立**（修正后 CI 与基线边界不相交）。

---

## 三、目录结构

```
.
├── README.md
├── src/                    复现与审计代码（官方代码 + 修改 + 新增工具）
│   ├── audit_leakage.py            ★ 新增：unknown-aware 泄漏审计
│   ├── subspace_selectivity.py     ★ 新增：LDA 交叉投影（含 --nested 折内协议）
│   ├── ci_sign_determination.py    ★ 新增：CI 方向符号穷举
│   ├── evaluation/ci_eval.py       ★ 已修：unknown 处理 + valid-only + 边界
│   ├── control/ reading/ extraction/ utils/ data/
│   └── ...                        官方流水线各阶段脚本
├── data/stimuli/            刺激数据（概念 1000 / 行为 200 / CI 1500）
├── reports/                 全部分析与审计报告（md）
└── results/                 小型结果数据（JSON/JSONL/PNG，约 4.6 MB）
```

### 报告导航（`reports/`）

| 文件 | 内容 |
|---|---|
| `AUDIT_REPORT.md` | **评测审计报告（步骤 1–5）**，含实测/推断/未验证三级标注 |
| `EXPERIMENT_REPORT.md` | 完整复现实验报告 |
| `REPRODUCTION_RESULTS.md` | 复现结果汇总 |
| `FINDING3_VERIFICATION.md` | Finding 3 专项验证（含全部代码修改记录） |
| `FINDING2_LITERATURE.md` | "编码↔行为解耦"成因文献综述（24 篇） |
| `FINDING2_BETTER_PROBES.md` | 更优探测方法文献综述（21 篇） |
| `RESEARCH_PROGRESS_CI_DECOUPLING.md` | 研究计划：成因 → 更优编码特征 |
| `RESEARCH_PROGRESS.md`、`NEXT_STEPS.md`、`CONTEXT_SNAPSHOT.md` | 进展、后续计划、上下文快照 |

---

## 四、环境与运行

```bash
conda create -n ci_steering python=3.11 -y
conda activate ci_steering
pip install -r requirements.txt

# LLM 评委（用于行为评测）
export DEEPSEEK_API_KEY="..."        # 或 OPENAI_API_KEY
export DEEPSEEK_API_BASE="https://api.deepseek.com"
export DEEPSEEK_MODEL="deepseek-v4-flash"

# 门控模型（Llama 系列）
export HF_TOKEN="..."
```

> 注：原始实验使用 GPT-4o-mini 作评委；本复现改用 DeepSeek `deepseek-v4-flash`（OpenAI 兼容接口）。

主要流程：

```bash
# 1) 刺激生成
python src/generate_stimuli.py --num-pairs-per-type 50 --num-function-pairs 200 --num-ci-per-condition 100

# 2) 激活提取（需 GPU）
python src/extract_activations.py --model Qwen/Qwen2.5-7B-Instruct --batch-size 8

# 3) 表征读取 / CI 分解
python src/read_representations.py --activations-dir outputs/activations/Qwen2.5-7B-Instruct
python src/ci_decomposition.py --activations-dir outputs/activations/Qwen2.5-7B-Instruct

# 4) 泄漏审计（复用已有评委缓存，未知样本重评）
python src/audit_leakage.py --model Qwen/Qwen2.5-7B-Instruct --dataset confaide \
    --reader-dir outputs/reading/probe_reader --ci-dir outputs/ci_decomposition/Qwen2.5-7B-Instruct \
    --reuse-cache-from <旧 judge_cache 目录> --output-dir outputs/audit_confaide

# 5) Finding 3 验证（含折内协议）
python src/subspace_selectivity.py --activations-dir outputs/activations/Qwen2.5-7B-Instruct --nested
```

外部基准需自行 clone：

```bash
git clone https://github.com/skywalker023/confaide.git data/confaide
git clone https://github.com/HKUST-KnowComp/PrivaCI-Bench.git data/privaci_bench
```

---

## 五、数据与结果说明

- `data/stimuli/`：完整刺激集（可由 `generate_stimuli.py` 复现生成）。
- `results/`：小型结果文件（逐层曲线、审计逐样本表、选择性矩阵、热力图等）。
  **大体积张量（激活 `.pt`，约 1.2 GB）与评委缓存未包含**，可由流水线重新生成。
- 审计逐样本明细：`results/audit_confaide/confaide_Qwen2.5-7B-Instruct/per_sample.jsonl`（810 条，含方法归属、状态、原始评委内容与模型回答）。

---

## 六、已知限制

1. **模型覆盖**：论文 4 个模型中，Llama-3.1-8B 与 Llama-2-7B 因 Meta 门控无法获取，仅覆盖 Qwen2.5-7B 与 Mistral-7B。
2. **评委不同**：DeepSeek `deepseek-v4-flash` 替代 GPT-4o-mini；其失败模式为"推理耗尽 token 导致空回答"。
3. **无人工盲审**：要求的双人独立标注尚未完成。
4. **合成数据未重算**：本轮审计仅覆盖 CONFAIDE；合成场景（200 条）沿用原口径。
5. **无验证集**：原流程只有 train/test，选层按 test AUROC 报告，尚未按验证集选择超参。

---

## 七、引用

```bibtex
@inproceedings{wang2026private,
  title  = {Do LLMs Know What Is Private Internally? Probing and Steering Contextual Privacy Norms in Large Language Model Representations},
  author = {Wang, Haoran and Xiong, Li and Shu, Kai},
  booktitle = {Conference on Language Modeling (COLM)},
  year   = {2026}
}
```

原始代码遵循 MIT License（见 `LICENSE`）。
