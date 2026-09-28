# Finding 3 验证报告

目标：验证论文 **Finding 3 "Privacy Lives in a CI-Aligned Subspace"**（三个 CI 参数占据功能独立子空间）是否成立。

## 一、验证方法：论文 Appendix G 的 LDA 交叉投影

论文原文（Appendix G）：
> "For each CI parameter, we fit **Linear Discriminant Analysis (LDA)** on hidden states from the
> **75th-percentile layer** to obtain a **four-dimensional discriminant subspace** optimized for that
> parameter's five categories. We then perform **cross-projection**: for each parameter pair (i, j), we
> project parameter i's stimuli into parameter j's discriminant subspace and train a **five-class
> logistic regression classifier with 5-fold cross-validation**."

官方代码 `ci_decomposition.py` **没有实现** LDA 交叉投影，只有「余弦相似度矩阵（在 layer 0）+ 置换检验」的近似。

## 二、代码修改记录（逐次）

| # | 文件 | 修改内容 | 原因 |
|---|---|---|---|
| ① | 新建 `src/subspace_selectivity.py` | 实现 LDA 交叉投影（75% 分位层、4 维判别子空间、5 折 CV 逻辑回归）+ 同层的置换检验 | 官方代码缺失论文的核心检验 |
| ② | 同上 | 运行 Qwen2.5 → 报 `ModuleNotFoundError: No module named 'src'` | — |
| ③ | 同上 | 新增 `import sys` + `sys.path.insert(0, str(Path(__file__).resolve().parent.parent))` | 脚本位于 src/ 子目录，需把仓库根目录加入 import 路径 |
| ④ | 同上 | 删除 `LogisticRegression(..., multi_class="multinomial")` 中的 `multi_class` 参数 | sklearn 1.9 已移除该参数 |
| ⑤ | 本文件 `FINDING3_VERIFICATION.md` | 记录验证过程与结果 | 留存 |

**核心实现片段**（修改①的内容）：
```python
# 1) 每参数在 75% 分位层拟合 LDA → 4 维判别子空间
layer = sorted(acts.keys())[len(acts) * 3 // 4]          # 75% 分位层
lda = LinearDiscriminantAnalysis(n_components=4)          # 5 类 → 4 判别方向
lda.fit(X[p], y[p])

# 2) 交叉投影：把参数 i 的样本投到参数 j 的子空间，再 5 分类
proj = lda_models[pj].transform(X[pi])                    # (500, 4)
acc  = cross_val_score(LogisticRegression(max_iter=2000), proj, y[pi], cv=5).mean()
```

## 三、结果

### LDA 交叉投影选择性矩阵（对角线=自己，非对角=别人）

**Qwen2.5-7B-Instruct（layer 21）**
```
              S_info_type  S_recipient  S_trans
info_type        100%        20.8%       20.6%
recipient        20.8%       100%        21.6%
trans_princ      21.2%       20.4%       100%
```

**Mistral-7B-Instruct-v0.3（layer 24）**
```
              S_info_type  S_recipient  S_trans
info_type        100%        22.0%       20.6%
recipient        20.4%       100%        20.4%
trans_princ      23.0%       23.2%       100%
```

→ **对角 ≈100%，非对角 ≈20%（=1/5 随机水平）**，与论文 Figure 7 完全一致（论文非对角范围 19%–27%）。

### 置换检验（补充检验，同 75% 分位层，1000 次）

| 模型 | 真实 mean\|cos\| | 零分布 mean±std | p 值 | 效应量 | 论文报告 |
|---|---|---|---|---|---|
| Qwen2.5-7B | 0.9967 | 0.9986±0.0008 | 0.037 | 2.26σ | 6.1σ (p<0.001) |
| Mistral-7B | 0.9974 | 0.9982±0.0011 | 0.194 | 0.72σ | 2.1σ (p=0.05) |

## 四、结论

1. **Finding 3 的核心命题「三个 CI 参数占据功能独立子空间」成立**——LDA 交叉投影在 Qwen2.5 与 Mistral 两个模型上都得到干净的对角结构（100% / ~20%），与论文 Figure 7 一致。

2. **置换检验方向一致但更弱**（Qwen 显著 p=0.037、Mistral 不显著 p=0.194；均弱于论文的 6.1σ/2.1σ）。原因：置换检验的零分布退化——1500 个样本共享"隐私场景模板"的共同结构，随机分组的 PCA 第一主成分都≈平行于该共同结构（null |cos|≈0.9986≈1），导致真实与零分布差异极小。LDA 因利用类别标签找**判别**方向，避开了这个退化，因此是更可靠的检验。

3. **功能性验证（§5.4 steering 消融）**：官方代码的 steering 方向**符号错误**（PCA 方向用"均值投影>0"任意定号，指向 `no_consent/no_need` 违规端），故"单轴 steering 增漏、三轴降漏"的功能性证据在当前代码下无法复现——这是 Finding 3 的**功能半边**尚未验证的部分（表示独立性半边已确认）。

## 五、功能半边验证：符号穷举 + steering

为验证 §5.4 的「功能独立性」，新增 `src/ci_sign_determination.py`（修改⑥），在合成行为数据（100 个"应保密"场景）上穷举 3 个方向共 8 种符号组合，用关键词泄漏（secret_keywords）快速度量（修改⑦）。

**结果（Qwen2.5-7B，α=1.0，关键词泄漏）**：
- 无 steering 基线：0.500
- 8 种符号组合（info_type/recipient/transmission_principle 三轴一起）：
```
 + + +  0.460  Δ=-0.040   ← 最优（= 官方代码的"规范符号"）
 + + -  0.480  Δ=-0.020
 + - +  0.480  Δ=-0.020
 - + +  0.490  Δ=-0.010
 - - -  0.490  Δ=-0.010
 - - +  0.530  Δ=+0.030
 + - -  0.540  Δ=+0.040
 - + -  0.540  Δ=+0.040
```
- 单轴 steering（±两种符号）：
```
info_type+          0.500  Δ=0.000
info_type-          0.550  Δ=+0.050
recipient+          0.490  Δ=-0.010
recipient-          0.550  Δ=+0.050
transmission_principle+  0.490  Δ=-0.010
transmission_principle-  0.550  Δ=+0.050
```

### 重要更正
- **官方代码的"规范符号"（均值投影>0）已经是 8 种组合里最优的**，不是符号反了。
- 我之前根据「transmission_principle 方向指向 no_consent/no_need」推断"符号错误"是**错的**——实际含义是：该方向指向"不当传输原则"（no_consent/no_need），steering `+α·v` 让模型更倾向把情境判为"不当"→拒答→泄漏下降。这正是隐私保护的正确方向。
- **真正的问题不是符号，而是方向本身太弱**：最优符号下关键词泄漏只降 4 个百分点（0.50→0.46），远不及论文合成数据的 42.5%→5%（PPI 98.8%）。

### 功能半边结论
1. 官方代码的 PCA 第一主成分方向，在合成数据上**方向性正确**（规范符号最优、单轴 receiver/trans 也轻微降漏），但**强度极弱**（~4 个百分点）。
2. 在 CONFAIDE（OOD）上则**不降反升**（41.9% vs 38.5%），未能复现论文 15.2%。
3. 因此论文 §5.4 的功能性证据（单轴增漏、三轴降漏 89%）**在官方代码的 PCA 方向下无法复现**，根因是方向提取（PCA 第一主成分）不足以刻画"隐私保护"这一行为方向，而非符号问题。

## 六、最终结论一句话

> Finding 3 的「**表示独立性**」结论是**正确的**（LDA 交叉投影在两个模型上干净复现 Figure 7 的对角结构）；但「**功能独立性**」（steering 降泄漏）在官方代码的 PCA 方向下**无法复现**——方向符号已是最优，问题是方向本身太弱/提取不当，无法承载论文声称的因果操纵效果。
