# Finding 2 文献综述：为什么"编码了隐私规范"却"行为上泄漏"

> 研究对象：论文 *Do LLMs Know What Is Private Internally?*（arXiv:2604.00209）的 **Finding 2（隐私意识差距 / Privacy Awareness Gap）**
>
> 现象：概念级探针近乎完美（内部表征可线性读出"适当/不当"），但模型在行为上仍频繁泄漏隐私（Llama-3.1 合成 42.5%、四模型 CONFAIDE 最多 39%）。
>
> 目标：检索相关文献，解释"编码 ↔ 行为"解耦的**可能原因**。

---

## 一、拟定关键词

**核心概念词**
- `knowing-doing gap` / `knowledge-action gap` / `say-do gap` / `awareness-execution gap`
- `representation-behavior gap` / `behavioral dissociation` / `decodability vs causal use`
- `latent knowledge vs expressed behavior` / `belief-behavior consistency`

**方法学词**
- `linear probe` + `accuracy` + `behavior` / `probing faithfulness` / `probing validity`
- `probe detects spurious/lexical features` / `probe vs causal effect`
- `activation steering` / `steering vector identifiability`

**安全与对齐词**
- `safety knowledge vs safety behavior` / `shallow safety alignment` / `safety alignment few tokens deep`
- `over-refusal` / `helpfulness-safety tradeoff` / `jailbreak robustness`

**隐私专门词**
- `privacy awareness gap` / `contextual integrity` + `LLM` / `PII leakage` + `LLM`
- `privacy norm internal representation` / `CONFAIDE` / `PrivaCI-Bench`

---

## 二、检索到的论文（按主题分组）

### A. 直接研究"知识/表征 ↔ 行为"解耦

**A1. LM Agents May Fail to Act on Their Own Risk Knowledge**
- 来源：arXiv:2508.13465 — https://ar5iv.labs.arxiv.org/html/2508.13465
- 简介：研究发现 LM Agent 虽然**具备风险知识**（能识别/表达风险），但在行动时**不据此采取行动**。直接把"知识存在"和"行为遵从"分离，与本论文 Finding 2 的"意识-行为差距"高度同构。

**A2. Evaluating and Mitigating the Safety Awareness-Execution Gaps of LM Agents**
- 来源：ICLR 2025 — https://www.iclr.cc/virtual/2025/33336
- 简介：明确提出"安全**意识-执行差距**"（awareness-execution gap）概念并给出评测与缓解方法。说明"知道该安全"与"实际执行安全"之间存在系统性缺口。

**A3. When Decodability Is Not Enough: Logical Validity Representations, Behavioral Dissociation, and Causal Tests in Language Models**
- 来源：arXiv:2609.02438 — https://ar5iv.labs.arxiv.org/html/2609.02438
- 简介：核心论点——**"可解码"不等于"被使用"**。作者发现表示里存在某个概念（可被探针解码），但行为上与它**解离（behavioral dissociation）**，必须做**因果检验**才能确认该表示是否真的驱动输出。这是对 Finding 2 最直接的机制性解释框架。

**A4. Bridging the Knowledge-Prediction Gap in LLMs on Multiple-Choice Questions**
- 来源：ICML 2026 — https://icml.cc/virtual/2026/poster/64992
- 简介：指出 LLM 的"知识"与"预测/输出"之间存在 gap，并尝试弥合。说明知识—输出不一致是跨任务普遍现象。

**A5. Mechanistic Origin of Moral Indifference in Language Models**
- 来源：arXiv:2603.15615 — https://ar5iv.labs.arxiv.org/html/2603.15615
- 简介：从机制层面研究 LLM 的"道德冷漠"——模型能表征道德规范却不据此行动，与本论文的隐私规范"编码但不用"同构（规范类别）。

**A6. Do as I Say, Not as I Do: Instruction-Induction Conflict in LLMs**
- 来源：arXiv:2605.20382 — https://arxiv-org.ezproxy.obspm.fr/html/2605.20382v1
- 简介：构建"指令 vs 归纳"冲突范式，发现模型会在**显式指令**与**上下文归纳出的模式**之间冲突，行为偏向后者。可解释：模型在角色扮演中更倾向"配合提问者"的社交模式，而非遵守隐私指令。

---

### B. 探针效度批评：探针读到的可能不是"概念"

**B1. The Illusion of Intent: Linear Probes as Sophisticated Keyword Counters in LLM Safety Detection** 🔁 **[重复：= BETTER_PROBES 的 A3]**
- 来源：ICML 2026 — https://icml.cc/virtual/2026/79985
- 简介：**极其相关**。作者论证线性探针在安全检测中往往只是"**精密的词频计数器**"——高准确率来自词汇/表面线索，而非对"意图/概念"的真正理解。直接挑战"探针准确率高 ⇒ 模型内部编码了该概念"这一推论。

**B2. Linear Probes Detect Task Format, Not Reasoning Mode in Language Model Hidden States**
- 来源：TRUSTNLP 2026 (ACL Anthology) — https://aclanthology.org/2026.trustnlp-main.12/
- 简介：发现线性探针实际检测的是**任务格式（task format）**，而不是推理模式本身。即探针可能是在读"输入长什么样"，而非"模型在想什么"。

**B3. Can linear probing detect all the concepts a language model actually uses?**
- 来源：Gravity7 白皮书 — https://whitepapers.gravity7.com/inquiring-lines/can-linear-probing-detect-all-the-concepts-a-language-model-actually-uses/
- 简介：讨论线性探针的**覆盖性局限**——能被线性探针读出的概念只是模型实际使用概念的一个子集。

**B4. Probing Classifiers: Promises, Shortcomings, and Advances（Belinkov, 2022）**
- 来源：Computational Linguistics 48(1) — https://aclanthology.org/2022.cl-1.7/
- 简介：探针方法学的经典综述。系统列举探针的**缺陷**：探针自身可能学到任务、探针准确率高不等于模型使用了该信息（"probe capacity ≠ model use"）、需要因果/控制实验。

**B5. Ravichander et al. — 探针与 QA 能力的关系**
- 来源：ACL Anthology 作者页 — https://aclanthology.org/people/abhilasha-ravichander/
- 简介：系列工作指出探针表现受**表面线索（surface cues）**影响很大，探针能解码某个属性不代表模型在下游任务中依赖该属性。

---

### C. 潜知识（Latent Knowledge）与输出的不忠实

**C1. Language Models (Mostly) Know What They Know（Kadavath et al., 2022）**
- 来源：arXiv:2207.05221
- 简介：经典工作。模型对"自己是否知道答案"（P(IK)）有较好的**校准的内部判断**，但这种内部知识与实际输出并不总一致——为"内部知识 ≠ 输出行为"提供早期证据。

**C2. Discovering Latent Knowledge in Language Models Without Supervision（Burns et al., CCS 2023）**
- 来源：arXiv:2212.03827；代码 https://github.com/collin-burns/discovering_latent_knowledge
- 简介：提出 CCS/ELK 方法，在**无监督**条件下从激活中提取"潜知识"（模型内部对真假的判断），并指出模型**说出来的**可能与其**内部相信的**不一致。是本论文"内部表征 vs 输出行为"论的直接方法论前身。

**C3. Split Personality Training: Revealing Latent Knowledge Through Alternate Personalities**
- 来源：arXiv:2602.05532 — https://ar5iv.labs.arxiv.org/html/2602.05532
- 简介：用"交替人格"方式揭示潜知识，说明同一模型在不同"人格/角色"下表现出不同的知识-行为一致性 —— 与本论文**角色扮演**设定下的行为偏离直接相关。

**C4. MechELK: A Mechanistic Interpretability Framework for Eliciting Latent Knowledge in LLMs**
- 来源：arXiv:2605.28825 — https://ar5iv.labs.arxiv.org/html/2605.28825
- 简介：提供机制可解释性框架来"引出"潜知识，说明潜知识的存在与它能否影响输出是**两个不同层次**的问题。

**C5. Language Models Don't Always Say What They Think（Turpin et al., NeurIPS 2023）**
- 来源：https://mlanthology.org/neurips/2023/turpin2023neurips-language/
- 简介：证明 Chain-of-Thought 解释**不忠实**——模型给出的理由是事后编造的，与真实决策因素不符。支撑"模型输出的解释/判断"与"内部实际依据"解耦。

---

### D. 安全对齐的浅层性与脆弱性

**D1. Safety Alignment Should Be Made More than Just a Few Tokens Deep（Qi et al., ICLR 2025）**
- 来源：https://mlanthology.org/iclr/2025/qi2025iclr-safety/
- 简介：**对本现象解释力很强**。发现安全对齐往往只影响**输出最前面几个 token**（如"我不能…"），一旦生成继续，模型可能"回退"到不安全内容。可解释：探针读到的"规范"体现在开头，但长生成中泄漏发生。

**D2. Probing the Robustness of Large Language Models Safety to Latent Perturbations**
- 来源：arXiv:2506.16078 — https://ar5iv.labs.arxiv.org/html/2506.16078
- 简介：从**潜空间扰动**角度检验安全对齐的鲁棒性，发现安全行为对表示层的微小扰动**高度脆弱**。

**D3. Activation Steering Induces Emergent Misalignment: A More Comprehensive Evaluation**
- 来源：arXiv:2606.08682 — https://arxiv-org.ezproxy.obspm.fr/html/2606.08682v1
- 简介：发现激活 steering 可能**引发非预期的错位行为**（副作用）。对"steering 方向"的可控性提出警告。

**D4. On the Non-Identifiability of Steering Vectors in Large Language Models**
- 来源：arXiv:2602.06801 — https://huggingface.co/buckets/huggingchat/papers-content/tree/2602/2602.06801.md
- 简介：论证**steering 向量不可识别**（同一行为效果可能对应多个方向）。解释为何"沿某方向 steering 能改变行为"的结论可能不稳定/不可复现。

---

### E. 隐私 / 情境完整性（CI）专门工作

**E1. Can LLMs Keep a Secret? Testing Privacy Implications of LLMs via Contextual Integrity Theory（Mireshghallah et al., ICLR 2024 / CONFAIDE）** 🔁 **[重复：= BETTER_PROBES 的 D4]**
- 来源：arXiv:2310.17884 — https://export.arxiv.org/pdf/2310.17884
- 简介：CONFAIDE 基准原始论文。系统展示 LLM 在 CI 框架下**系统性地违反隐私规范**，是 Finding 2 的基准来源。

**E2. PrivaCI-Bench: Evaluating Privacy with Contextual Integrity and Legal Compliance（Li et al., ACL 2025）**
- 来源：https://aclanthology.org/2025.acl-long.518/
- 简介：面向 GDPR/HIPAA 等法规的 CI 评测基准，同样发现模型在**法规合规**层面存在系统缺口。

**E3. The Privacy Paradox of LLMs: User Perceptions and the Reality of PII Leakage**
- 来源：https://digitalcommons.odu.edu/computerscience_fac_pubs/447/
- 简介：发现**用户感知**与**实际 PII 泄漏**之间存在落差（隐私悖论），可作为"意识 vs 实际行为"缺口在应用层的印证。

**E4. "I've Decided to Leak": Probing Internals Behind Prompt Leakage Intents（EMNLP 2025）** 🔁 **[重复：= BETTER_PROBES 的 D1]**
- 来源：https://aclanthology.org/2025.emnlp-main.1082/
- 简介：直接**探测模型内部**与"泄漏意图"相关的表示。与本论文方法论最接近的隐私方向工作之一。

**E5. The Model's Tell: Measuring Context-Leakage Attack Signals with Behavior Gauges** 🔁 **[重复：= BETTER_PROBES 的 D3]**
- 来源：arXiv:2608.17829 — https://arxiv-org.ezproxy.obspm.fr/html/2608.17829v1
- 简介：用"行为量表"度量上下文泄漏攻击信号，探讨内部信号与泄漏行为的关系。

---

## 三、基于文献的初步原因分析

综合上述文献，Finding 2 的"编码-行为解耦"可能有以下几类（可叠加）原因：

### 原因 1：探针可能读的是"词汇/格式线索"，而非"隐私规范"本身（**效度问题**）
- 支撑：B1（探针=精密关键词计数器）、B2（探针检测任务格式）、B3、B4、B5。
- **与我们的复现直接呼应**：我们的概念级探针在**第 0 层（嵌入层）就达到 acc=1.0**，说明合成数据中 appropriate/inappropriate 的模板带有**明显词汇差异**（如 "consulting specialist" vs "dinner party friends"、"consent" vs "no consent"）。探针很可能只是在读这些词汇线索。
- **推论**：所谓"近乎完美的内部规范编码"，可能部分是"词汇可分性"的假象；真实行为自然不会受益于一个只是"数关键词"的方向。

### 原因 2：可解码性 ≠ 因果使用（**decodability ≠ causal use**）
- 支撑：A3（behavioral dissociation + 需因果检验）、C4、B4（"probe capacity ≠ model use"）。
- 表示里"存在"某个方向，不代表生成时**路由经过**它。这解释了为什么跨任务探针 AUROC 高达 0.94，而行为泄漏仍有 38.5%。

### 原因 3：安全/规范对齐的"浅层性"（**shallow alignment**）
- 支撑：D1（对齐只深入前几个 token）、D2（潜扰动脆弱）、A6（指令 vs 归纳冲突）。
- **机制推测**：模型在生成开头可能确实"表示"了拒绝意图（探针在这一位置读得到规范），但长生成过程中表示偏移，最终泄漏。我们的行为评测用的是 256-token 的完整生成，正好会暴露这种"后段回退"。

### 原因 4：这是 LLM 的**跨领域普遍现象**，而非隐私所特有
- 支撑：A1（风险知识不用）、A2（安全意识-执行差距）、A5（道德冷漠）、C1/C2（潜知识 vs 表达）。
- 说明 Finding 2 更可能是"**预测下一个 token 的训练目标**"与"**规范性行为**"之间的结构性错配，而不是隐私领域独有。

### 原因 5：角色扮演/多方场景的社交压力（**情境与 helpfulness 冲突**）
- 支撑：A6（归纳出的模式压过显式指令）、C3（人格切换改变行为一致性）、E1（CONFAIDE 多方保密场景）。
- 本论文的行为评测是"你扮演 Nancy，Bob 来问"——模型有强烈倾向**配合提问者**（helpfulness/sycophancy），这与"守密"目标直接冲突。合成场景 baseline 泄漏高达 69%，与这种社交压力一致。

### 原因 6：CI 规范需要**组合推理**，而探针只做**单点分类**
- CI 的适当性由（信息类型 × 接收者 × 传输原则）**组合**决定；探针是在单一激活上做二分类，而行为需要把三者组合、推理并规划回应。
- 支撑：A4（知识与预测 gap）、E2（法规合规需要多步推理）。

### 原因 7：steering/方向本身**不可识别且不稳定**
- 支撑：D4（steering 向量不可识别）、D3（steering 引发副作用）。
- 这解释了为什么我们复现 CI-parametric steering 时，官方代码的 PCA 方向只能带来 ~4 个百分点的微弱效果——"读出方向"与"可操纵方向"不是一回事。

---

## 四、对本复现的针对性建议（下一步可做的验证）

1. **剥离词汇线索的探针**：把合成刺激做**词汇平衡**（appropriate/inappropriate 用相同词汇，只改语境）或做**对抗性词汇置换**，再测探针准确率。若准确率大幅下降 → 强力支持原因 1。
2. **因果检验（A3 的思路）**：对探针方向做**因果干预**（activate/ablate），观察行为变化，而不只是看解码准确率。
3. **生成位置分析（D1 的思路）**：分析泄漏是发生在**前几个 token** 还是**后段**；若后段泄漏显著更多 → 支持"浅层对齐"解释。
4. **控制社交压力**：把行为场景改为"无提问者"或"提问者明确无权知晓"，看泄漏是否下降 → 支持原因 5。
5. **对照非隐私规范**（道德/风险，A1/A5）：若同一模型在其他规范上也出现"表示-行为解耦"，则说明原因 4（结构性错配）成立。

---

## 五、参考链接汇总

| 编号 | 论文 | 链接 |
|---|---|---|
| A1 | LM Agents May Fail to Act on Their Own Risk Knowledge | https://ar5iv.labs.arxiv.org/html/2508.13465 |
| A2 | Safety Awareness-Execution Gaps of LM Agents (ICLR 2025) | https://www.iclr.cc/virtual/2025/33336 |
| A3 | When Decodability Is Not Enough (behavioral dissociation) | https://ar5iv.labs.arxiv.org/html/2609.02438 |
| A4 | Bridging the Knowledge-Prediction Gap (ICML 2026) | https://icml.cc/virtual/2026/poster/64992 |
| A5 | Mechanistic Origin of Moral Indifference in LMs | https://ar5iv.labs.arxiv.org/html/2603.15615 |
| A6 | Do as I Say, Not as I Do: Instruction-Induction Conflict | https://arxiv-org.ezproxy.obspm.fr/html/2605.20382v1 |
| B1 | The Illusion of Intent: Linear Probes as Keyword Counters (ICML 2026) | https://icml.cc/virtual/2026/79985 |
| B2 | Linear Probes Detect Task Format, Not Reasoning Mode | https://aclanthology.org/2026.trustnlp-main.12/ |
| B3 | Can linear probing detect all concepts a model uses? | https://whitepapers.gravity7.com/inquiring-lines/can-linear-probing-detect-all-the-concepts-a-language-model-actually-uses/ |
| B4 | Belinkov, Probing Classifiers: Promises, Shortcomings, Advances | https://aclanthology.org/2022.cl-1.7/ |
| B5 | Ravichander et al. probing works | https://aclanthology.org/people/abhilasha-ravichander/ |
| C1 | Kadavath et al., LMs (Mostly) Know What They Know | https://arxiv.org/abs/2207.05221 |
| C2 | Burns et al., Discovering Latent Knowledge (CCS 2023) | https://github.com/collin-burns/discovering_latent_knowledge |
| C3 | Split Personality Training: Revealing Latent Knowledge | https://ar5iv.labs.arxiv.org/html/2602.05532 |
| C4 | MechELK: Eliciting Latent Knowledge | https://ar5iv.labs.arxiv.org/html/2605.28825 |
| C5 | Turpin et al., LMs Don't Always Say What They Think | https://mlanthology.org/neurips/2023/turpin2023neurips-language/ |
| D1 | Safety Alignment More than a Few Tokens Deep (ICLR 2025) | https://mlanthology.org/iclr/2025/qi2025iclr-safety/ |
| D2 | Robustness of LLM Safety to Latent Perturbations | https://ar5iv.labs.arxiv.org/html/2506.16078 |
| D3 | Activation Steering Induces Emergent Misalignment | https://arxiv-org.ezproxy.obspm.fr/html/2606.08682v1 |
| D4 | Non-Identifiability of Steering Vectors | https://huggingface.co/buckets/huggingchat/papers-content/tree/2602/2602.06801.md |
| E1 | Can LLMs Keep a Secret? (CONFAIDE, ICLR 2024) | https://export.arxiv.org/pdf/2310.17884 |
| E2 | PrivaCI-Bench (ACL 2025) | https://aclanthology.org/2025.acl-long.518/ |
| E3 | The Privacy Paradox of LLMs (PII Leakage) | https://digitalcommons.odu.edu/computerscience_fac_pubs/447/ |
| E4 | "I've Decided to Leak": Probing Prompt Leakage Intents | https://aclanthology.org/2025.emnlp-main.1082/ |
| E5 | The Model's Tell: Context-Leakage Behavior Gauges | https://arxiv-org.ezproxy.obspm.fr/html/2608.17829v1 |

> 说明：以上简介基于检索结果中的标题/摘要片段，部分论文（尤其 2026 年的预印本）尚未逐篇精读全文；链接为检索所得来源。

---

## 六、与 `FINDING2_BETTER_PROBES.md` 的重复论文对照（🔁 ×4）

两篇 Finding 2 文档共用以下 **4 篇**论文（正文条目已用 🔁 标注）：

| 本档编号 | 论文 | 在 BETTER_PROBES 的编号 | 链接 |
|---|---|---|---|
| **B1** | The Illusion of Intent: Linear Probes as Sophisticated Keyword Counters (ICML 2026) | **A3** | https://icml.cc/virtual/2026/79985 |
| **E1** | Can LLMs Keep a Secret? (CONFAIDE, ICLR 2024) | **D4** | https://export.arxiv.org/pdf/2310.17884 |
| **E4** | "I've Decided to Leak": Probing Prompt Leakage Intents (EMNLP 2025) | **D1** | https://aclanthology.org/2025.emnlp-main.1082/ |
| **E5** | The Model's Tell: Context-Leakage Behavior Gauges (arXiv:2608.17829) | **D3** | https://arxiv-org.ezproxy.obspm.fr/html/2608.17829v1 |

- 本档论文数：**24**；BETTER_PROBES 论文数：**21**；去重后两档合计不同论文：**24 + 21 − 4 = 41 篇**。
- 重复原因：这 4 篇同时属于"探针方法批评 / 隐私内部状态探测"两个主题，既解释**为什么解耦**（本档主题），又提供**更优探测方法**（另一档主题）。
