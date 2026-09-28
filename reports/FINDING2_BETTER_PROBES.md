# Finding 2 续：预测 LLM 破坏 CI 行为的"更优探测方法"文献调研

> **调研问题**：针对 Finding 2（CI 场景中"编码 ↔ 行为"解耦）这一现象，**是否有研究提出了比本论文探针更有效的探测方法，用于预测 LLM 破坏 CI 的行为**？
>
> **本论文探针的局限**（作为对照基线）：
> 1. **线性探针**（logistic regression）——单层、单点
> 2. **末位 token 位置**（judgment template 的最后一个 token）
> 3. **二分类**（适当/不当），与"是否真的泄漏"行为之间被 Finding 2 证明存在差距
> 4. **仅在合成数据上训练**，跨数据集靠迁移

---

## 一、拟定关键词

**方法学（更优探针）**
- `beyond linear probes` / `nonlinear probe` / `MLP probe` / `kernel probe`
- `token-selective probe` / `layer-selective probe` / `multi-layer probe` / `probe ensemble`
- `probe generalization` / `subspace selection` / `OOD deception detection`
- `sparse autoencoder (SAE)` + `safety features` / `safety neurons`

**预测时点（更早预测）**
- `before the last token` / `final-token probe failure` / `intermediate activations`
- `pre-generation prediction` / `refusal before decoding`
- `streaming moderation` / `stop early` / `safety forecasting`

**目标行为（违规预测）**
- `predicting harmful behavior` / `policy violation prediction` / `jailbreak detection`
- `context-leakage detection` / `privacy leakage prediction` / `privacy neurons`
- `latent policy guardrail` / `constitutional classifiers` / `circuit breakers`

---

## 二、检索到的论文（逐条列出）

### A. 直接主张"线性/末位探针不够、需要更优方法"

**A1. Beyond Linear Probes: Dynamic Safety Monitoring for Language Models** ⭐
- 来源：**ICLR 2026** — https://proceedings.iclr.cc/paper_files/paper/2026/hash/5a829e299ebc1c1615ddb09e98fb6ce8-Abstract-Conference.html
- 代码：https://github.com/james-oldfield/tpc
- 简介：**标题即直接回应本问题**。提出超越固定线性探针的**动态安全监控**方法（topic/contrastive probe 一类），针对"静态线性探针无法覆盖多变的违规形式"这一缺陷。与本论文"单一线性方向不足以刻画隐私"的发现方向一致，但给出了更强的探测方案。

**A2. Before the Last Token: Diagnosing Final-Token Safety Probe Failures** ⭐
- 来源：arXiv:2605.12726 — https://arxiv-org.ezproxy.obspm.fr/html/2605.12726v2
- 简介：**与本论文探针设计直接冲突**。本论文正是在**末位 token** 提取激活并训练探针；该文系统诊断"**末位 token 安全探针失效**"的原因，并证明改用其他位置/聚合方式能显著改善。是"本论文探针可被改进"的最直接证据。

**A3. The Illusion of Intent: Linear Probes as Sophisticated Keyword Counters in LLM Safety Detection** 🔁 **[重复：= LITERATURE 的 B1]**
- 来源：**ICML 2026** — https://icml.cc/virtual/2026/79985
- 简介：论证线性探针在安全检测中往往只是"**精密的词频计数器**"，高准确率来自词汇线索而非语义/意图理解。直接质疑"探针准确率高 ⇒ 模型编码了该规范"这一推论。

**A4. Why Safety Probes Catch Liars But Miss Fanatics**
- 来源：arXiv:2603.25861 — https://arxiv-org.ezproxy.obspm.fr/html/2603.25861v1
- 简介：指出安全探针能捕捉某类（蓄意欺骗）违规，却**系统性漏掉另一类**（信念驱动/极端化）。说明单一探针方法的**覆盖偏差**——与 Finding 2 中"探针读得到但不预测行为"同源。

**A5. Probe Generalization as Subspace Selection for OOD Deception Detection**
- 来源：**ICML 2026** — https://icml.cc/virtual/2026/75853
- 简介：把"探针泛化"重构为**子空间选择**问题，显著提升 OOD（分布外）欺骗检测。针对本论文"合成→真实迁移"的脆弱性给出了方法。

**A6. A BERTology View of LLM Orchestrations: Token- and Layer-Selective Probes for Efficient Single-Pass Classification**
- 来源：**ACL 2026** — https://aclanthology.org/2026.acl-long.1955/
- 简介：提出**token 选择 + 层选择**的探针，替代"固定取末位 token、固定层"。直接改进本论文的提取策略。

**A7. Detecting Strategic Deception with Linear Probes（Goldowsky-Dill et al., ICML 2025）**
- 来源：https://icml.cc/virtual/2025/poster/46082
- 简介：线性探针能高准确率检测**蓄意欺骗**，但在更微妙的不忠实上**效果有限**——本论文引用的相关工作，说明"线性探针 + 行为预测"的边界。

---

### B. 在"生成前 / 生成中"预测违规（比事后评测更早）

**B1. Refusal Before Decoding: Detecting and Exploiting Refusal Signals in Intermediate LLM Activations** ⭐
- 来源：arXiv:2605.28553 — https://arxiv-org.ezproxy.obspm.fr/html/2605.28553v2
- 简介：证明**"拒绝"信号在解码前就已存在于中间层激活中**，可被检测并利用。对 CI 场景的意义：可以在**模型开口之前**预测它会不会泄漏（而非等生成完再判定）。

**B2. Stop Early, Spend Less: Hidden-State Probes as a Practical Recipe for Streaming Moderation of LLM Outputs**
- 来源：arXiv:2606.10487 — https://huggingface.co/papers/2606.10487
- 简介：用 hidden-state 探针做**流式审核**——在生成过程中早期判定，命中即停止，大幅降低开销。适合把"是否泄漏"的判定从离线评测变成**在线预测**。

**B3. Predict, Don't React: Value-Based Safety Forecasting for LLM Streaming**
- 来源：Semantic Scholar — https://www.semanticscholar.org/paper/Predict%2C-Don't-React%3A-Value-Based-Safety-for-LLM-Kavumba-Wataoka/8b6bec2da7c73f8b2e8ac62e4cffbe26ec721f78
- 简介：提出"**预测而非反应**"的流式安全框架，用价值/风险信号在生成早期预判风险。

**B4. Latent Policy Guardrail (LPG)**
- 来源：https://www.emergentmind.com/topics/latent-policy-guardrail-lpg
- 简介：在**潜空间**做策略护栏的框架概览，把策略合规判定放到内部表示层而非输出层。

**B5. Qwen3Guard-Stream（0.6B / 4B）**
- 来源：https://huggingface.co/Qwen/Qwen3Guard-Stream-0.6B
- 简介：工业界的**流式安全护栏模型**，随生成逐 token 判定风险。是"实时预测违规"的产品化方案。

---

### C. 其他探测架构 / 表示层干预

**C1. Safety Beyond the Interface: Detecting Harm via Latent States in Large Language Models**
- 来源：Semantic Scholar — https://www.semanticscholar.org/paper/Safety-Beyond-the-Interface%3A-Detecting-Harm-via-in-Khatri-Prabhu/f29c06da2da08dbb8acb3f361006113793b7ea06
- 简介：主张从**潜状态**（而非输出接口）检测有害性，与"用内部表示预测行为"直接同路。

**C2. Constitutional Classifiers++ / Cost-Effective Constitutional Classifiers via Representation Re-use（Anthropic）**
- 来源：https://ar5iv.labs.arxiv.org/html/2601.04603 ；https://alignment.anthropic.com/2025/cheap-monitors/
- 简介：用**复用采样中已计算的表示**来构建高效分类器，把"是否越界"的判定做在表示层。代表了"表示级检测"的工程化最佳实践。

**C3. Circuit Breakers / Representation Rerouting（Zou et al.）**
- 来源：相关工作见 https://ar5iv.labs.arxiv.org/html/2506.00781
- 简介：不靠外部探针，而是**在表示层直接把有害表示"改道"**，使模型自己无法沿有害方向生成。是"预测 + 干预"一体化的代表。

**C4. Sparse Autoencoder 系列：Safe-SAIL / SAFEx**
- 来源：https://aclanthology.org/2026.findings-acl.944/ ；https://ar5iv.labs.arxiv.org/html/2506.17368
- 简介：用**稀疏自编码器**把激活分解为可解释特征/专家，定位"安全关键特征"，比单一线性方向更细粒度。

**C5. Superposition of Safety-Critical Computations in LLM MLP Layers: A Grassmannian Subspace Analysis**
- 来源：https://zenodo.org/records/18903537
- 简介：用 **Grassmannian 子空间分析**刻画安全计算在 MLP 层中的**叠加结构**——与本论文"隐私是子空间而非单方向"的发现方法同源，但提供了更严格的子空间几何工具。

**C6. The Geometry of Truth（Marks & Tegmark）**
- 来源：https://browse.arxiv.org/html/2310.06824v2
- 简介：证明真假概念在表示中呈**线性结构**，是"用线性探针读出概念"的经典依据（也界定了线性方法的适用边界）。

---

### D. 隐私 / CI 专门的表示层探测

**D1. "I've Decided to Leak": Probing Internals Behind Prompt Leakage Intents（EMNLP 2025）** ⭐ 🔁 **[重复：= LITERATURE 的 E4]**
- 来源：https://aclanthology.org/2025.emnlp-main.1082/
- 简介：**最贴近本问题**——直接探测模型内部与"泄漏意图"相关的表示，试图在输出前预测泄漏意图。是隐私领域"内部状态 → 泄漏行为预测"的代表工作。

**D2. Understanding and Mitigating Cross-lingual Privacy Leakage via Language-specific and Universal Privacy Neurons**
- 来源：arXiv:2506.00759 — https://ar5iv.labs.arxiv.org/html/2506.00759v1
- 简介：定位并利用**"隐私神经元"**（language-specific + universal），用**神经元级别**（比线性方向更细）刻画隐私机制，并据此缓解泄漏。

**D3. The Model's Tell: Measuring Context-Leakage Attack Signals with Behavior Gauges** 🔁 **[重复：= LITERATURE 的 E5]**
- 来源：arXiv:2608.17829 — https://arxiv-org.ezproxy.obspm.fr/html/2608.17829v1
- 简介：用"**行为量表（behavior gauges）**"度量上下文泄漏攻击信号，探索内部信号与泄漏行为之间的定量关系。

**D4. Can LLMs Keep a Secret?（CONFAIDE, ICLR 2024）** 🔁 **[重复：= LITERATURE 的 E1]**
- 来源：https://export.arxiv.org/pdf/2310.17884
- 简介：CI 违规行为的基准来源；其评测是**输出后判定**（post-hoc），本论文 Finding 2 说明需要**输出前预测**。

---

## 三、小结：是否有"比本论文探针更有效"的方法？

**结论：有，而且相当集中。**

| 本论文探针的局限 | 对应的更优方法 | 代表论文 |
|---|---|---|
| 线性分类器容量不足 | 非线性/动态/topic 探针、子空间选择 | A1, A5 |
| **只取末位 token** | 中间层/多 token/流式位置 | **A2**, A6, B1 |
| 单层提取 | 层选择 / 多层集成 | A6, C5 |
| 只做语义二分类 | 直接预测**行为**（拒绝/泄漏） | B1, B2, D1 |
| 事后评测 | **生成前/生成中**预警 | B1–B5 |
| 单一线性方向 | 神经元级 / SAE 特征级 / 子空间级 | C4, D2, C5 |
| 合成→真实迁移脆弱 | OOD 泛化的子空间选择 | A5 |
| 只读不干预 | 表示重路由（circuit breakers） | C3 |

**三条最值得直接借鉴的路线**：
1. **改提取位置与层**（A2「Before the Last Token」+ A6「token/layer-selective」）——最低成本、最直接针对本论文的末位 token 设计。
2. **直接预测行为而非语义**（B1「Refusal Before Decoding」+ D1「I've Decided to Leak」）——绕开"语义分类 ≠ 行为"的鸿沟。
3. **细粒度表示分解**（C4 SAE / D2 隐私神经元 / C5 Grassmannian 子空间）——用特征/神经元/子空间替代单一线性方向。

> 说明：以上简介基于检索结果中的标题与摘要片段整理，部分 2026 年预印本尚未逐篇精读全文；链接均为检索所得来源。

---

## 四、与 `FINDING2_LITERATURE.md` 的重复论文对照（🔁 ×4）

两篇 Finding 2 文档共用以下 **4 篇**论文（正文条目已用 🔁 标注）：

| 本档编号 | 论文 | 在 LITERATURE 的编号 | 链接 |
|---|---|---|---|
| **A3** | The Illusion of Intent: Linear Probes as Sophisticated Keyword Counters (ICML 2026) | **B1** | https://icml.cc/virtual/2026/79985 |
| **D1** | "I've Decided to Leak": Probing Prompt Leakage Intents (EMNLP 2025) | **E4** | https://aclanthology.org/2025.emnlp-main.1082/ |
| **D3** | The Model's Tell: Context-Leakage Behavior Gauges (arXiv:2608.17829) | **E5** | https://arxiv-org.ezproxy.obspm.fr/html/2608.17829v1 |
| **D4** | Can LLMs Keep a Secret? (CONFAIDE, ICLR 2024) | **E1** | https://export.arxiv.org/pdf/2310.17884 |

- 本档论文数：**21**；LITERATURE 论文数：**24**；去重后两档合计不同论文：**24 + 21 − 4 = 41 篇**。
- 重复原因：这 4 篇同时落在"探针方法批评"与"隐私内部状态探测"的交叉地带，既解释**为什么解耦**（LITERATURE 主题），又提供**更优探测方法**（本档主题）。
