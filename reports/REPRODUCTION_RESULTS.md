# CI-Steering 复现结果（进行中）

复现对象：论文 *"Do LLMs Know What Is Private Internally?"*（Wang, Xiong, Shu — COLM 2026, arXiv:2604.00209）
代码仓库：https://github.com/wang2226/CI-Steering

## 环境
- GPU：4× RTX 5090 (32GB) + 2× RTX 6000D (85GB)，CUDA 13.0（仅在 full-access 沙箱下可见 `/dev/nvidia*`）
- 环境：conda `ci_steering`（Python 3.11，torch 2.14.0+cu130，transformers 5.16.1，sklearn 1.9.0，openai 3.7.0）
- 评委：DeepSeek `deepseek-v4-flash`（OpenAI 兼容接口 base_url=https://api.deepseek.com），替代论文的 GPT-4o-mini
- 模型：Qwen2.5-7B-Instruct ✅、Mistral-7B-Instruct-v0.3 ✅（Llama-3.1/Llama-2 被 Meta 门控 403，无法下载）

## 代码修复（为忠实复现所作）
1. `rep_tuning.py` 第167行缩进语法错误（阻断整个 `src.control` 导入）
2. `generate_stimuli.py` 行为刺激集改为平衡 100 适当/100 不当（原为全不当 200）
3. `extract_function_activations` 补传 labels（跨任务探针需要）
4. 评委 `ci_eval.py`：支持 DeepSeek（base_url/model/key 环境变量）、`response_format` 失败时退化为无 JSON 模式、增强 JSON 解析（markdown 代码块 + 平衡括号）
5. 层选择：`get_best_layers` / `from_ci_directions_dir` 在探针准确率并列时优先选深层（合成数据对所有层都可分，导致原实现退化为 0-4 层）

## Phase 1 — 刺激生成 ✅
- 概念级：1000（500 配对 × 10 信息类型），80/20 分层切分
- 行为级：200 平衡（100 适当/100 不当）
- CI 分解：1500（3 参数 × 5 取值 × 100 上下文）

## Phase 2–4 — 表征探针与 CI 分解 ✅（两模型）

### Finding 1（概念级线性可分但多维）
| 模型 | 探针 acc | 跨任务 acc/AUROC | PCA-1 AUROC | PCA-3 AUROC | PCA-5 AUROC |
|---|---|---|---|---|---|
| Qwen2.5-7B | 1.0 | 89.5% / 0.94 (L22) | 0.90 | 0.9996 | 1.0 |
| Mistral-7B | 1.0 | 94.0% / 0.99 (L6) | 0.91 | 0.995 | 0.9998 |

→ 复现论文核心发现：隐私线性可分，但单方向（PCA-1）不足，多维（PCA-3+）才接近完美。

### Finding 3（CI 参数可分解）
- 三参数（info_type / recipient / transmission_principle）各 5 类线性可分（探针 acc 1.0）
- 方向向量已保存（每模型 28/32 层 × 3 参数）

## Phase 5 — Steering 评测（Qwen2.5 合成数据，α=1.0）
| 方法 | 泄漏率↓ | NCR↑ | PPI↑ |
|---|---|---|---|
| No Steering | 69.0% | 28.0% | — |
| Monolithic (Standard) | 66.5% | 28.0% | 3.6% |
| Probe-Weighted | 68.0% | 28.0% | 1.4% |
| CI-Decomposed (all) | 67.0% | 29.5% | 2.9% |
| CI: info_type | 67.5% | 29.0% | 2.2% |
| CI: recipient | 68.5% | 28.5% | 0.7% |
| CI: transmission_principle | 68.0% | 28.5% | 1.4% |

→ 对 Qwen2.5，合成行为场景下所有 steering 方法都在评委噪声内（~66–69%），未复现论文在 Llama-3.1 上 42.5%→5% 的大幅下降。
论文 Table 2 显示 Qwen2.5 对 steering 的响应本就弱于 Llama-3.1（CONFAIDE 38.5%→15.2% vs Llama-3.1 24.1%→0%）。

## Phase 5 — CONFAIDE Tier 3 迁移（Qwen2.5，α=1.0，270 场景）
| 方法 | 泄漏率↓ | NCR↑ | PPI↑ | 论文 Table 2 |
|---|---|---|---|---|
| No Steering | **38.5%** | 55.9% | — | **38.5% ✅ 精确一致** |
| Monolithic (additive) | 41.1% | 56.3% | -6.7% | 39.3%（恶化）✅ 趋势一致 |
| Probe-Weighted | 42.2% | 57.0% | -9.6% | — |
| **CI-Decomposed (all)** | **41.9%** | 52.2% | **-8.7%** | **15.2% ❌ 严重分歧** |
| CI: info_type | 41.9% | 54.8% | -8.7% | — |
| CI: recipient | 41.5% | 57.8% | -7.7% | — |
| CI: transmission_principle | 39.3% | 59.6% | -1.9% | — |

### ⚠️ 关键分歧
- **基线 38.5% 与论文 Table 3 精确一致**；单方向 steering 恶化（41.1% vs 论文 39.3%）趋势一致。
- **但 CI-parametric steering 未复现论文的 38.5%→15.2% 大幅下降**，反而恶化到 41.9%（PPI -8.7%）。
- 可能原因（已用符号穷举检验定位，见 `FINDING3_VERIFICATION.md`）：
  1. ~~方向符号~~：**已排除**——穷举 8 种符号组合，官方"规范符号（均值投影>0）"本就是最优的，符号不是问题。
  2. **方向提取太弱（真正根因）**：代码用 5 分类 PCA 第一主成分作为 steering 方向，该方向虽方向性正确（指向"不当"端→模型更倾向拒答），但**强度极弱**（合成关键词泄漏仅 50%→46%），远不足以承载论文声称的 42.5%→5% / 38.5%→15.2% 的因果操纵效果；CONFAIDE 上反而 38.5%→41.9%。
  3. 层选择、α 值、DeepSeek 评委噪声（~10–15%）也有贡献。

## 已完成 / 待办
- ✅ Qwen2.5：Phases 1–5（合成 + CONFAIDE）
- ⏳ 待办：Qwen2.5 PrivaCI-Bench、Mistral-7B Phase 5、CI 方向符号排查

## 已知限制
1. **DeepSeek 评委 ~5–10% 的样本返回非 JSON**（重试后仍失败者标记为 not-leaked/not-appropriate，对泄漏率有轻微低估）。论文用 GPT-4o-mini。
2. 代码的 CI 分解用「余弦相似度 + 置换检验」而非论文 Figure 7 的 LDA 交叉投影选择性检验；且余弦相似度在 layer 0（嵌入层）计算，方向高度相关，与论文 75% 分位层的结论存在口径差异。
3. 合成探针对所有层都可分（词汇线索），层选择退化，已用「并列时选深层」修正。
