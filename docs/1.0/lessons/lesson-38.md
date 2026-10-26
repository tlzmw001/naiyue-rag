# Lesson 38：阶段B·6.1 检索质量、回答质量与工程质量

> 2026-10-26。目标：沿同一个合成业务任务区分“工程链路正常”“证据适合任务”“回答正确且有依据”，知道当前实现能证明到哪一层。按既定project-learning流程学习，不开发评测平台或问答层。

## 第6章地图与本节范围

本章5节：6.1三类质量；6.2标注单位/Recall@k/固定样本；6.3失败归因/单变量对照；6.4追踪/延迟/用量边界；6.5 Debug Test完整分支与独立定位。本节建立评价对象，指标细节留6.2；调试归因方法留6.3。讲解进度从29/34至30/34，不等于用户掌握。

## 真实仓库中的合成场景

材料在examples/core-demo/knowledge/，是公开的项目合成样本，不是用户真实业务资料：

- L1_module.md：基础金额=原始单价×数量，取消优惠时基础金额不变。
- L2_previous.md：旧discount_enabled=0不折扣，=1使用0.5。
- L2_previous_测试用例.md：TC-01单价10/数量2/开关0→基础20实付20；TC-02开关1→基础20实付10。
- L2_new.md：移除开关和折扣系数，实付始终等于基础金额，基础金额计算不变。
- L2_other.md：日志按天归档，与计费折扣无关。

任务：新需求移除折扣后，需要参考哪些历史需求与用例，回归哪些保留行为？新L2提供本次任务依据，旧需求/旧用例提供历史参考，L1提供保留规则。不能只命中新L2便当作历史参考找齐，也不能直接沿用TC-02的旧预期。

## 按评价对象分层

```text
文档 → 结构/片段 → 编码/索引 → 召回/融合 → 重排 → 证据打包
          │                         │         │       │
          └ 保留内容/定位            └ 找对/排序/覆盖 ──┘
                                                     ↓
                                          未来问答/用例生成层
                                                     ↓
                                        正确性、主张支持、完整性

工程合同贯穿：配置、版本、范围、来源、错误、预算、延迟与用量
```

| 评价对象 | 要回答的问题 | 可核验材料 |
|---|---|---|
| 解析/分块 | 规则、整行用例及前置/步骤/预期是否保留，位置是否对应原文 | 保存原文、Chunk、contexts、SourceSpan |
| 检索与上下文 | 必需证据是否找到，关键证据是否排前，打包后是否仍保留 | 固定标注、各阶段ID、rank、omitted |
| 回答/生成用例 | 主张是否正确、证据是否支持、条件/版本是否适用、任务要点是否覆盖 | 问题、新需求、实际上下文、生成产物、审核准则 |
| 工程 | 配置是否接线、同版本/范围/来源是否一致、失败是否明确 | 确定性测试、原生集成、错误/追踪、实际报告 |

解析是质量前提，工程是全链路合同；检索与回答分别评价。它们不是互斥分类，也不互相替代。解析丢掉前置条件，后续再好也不能从该片段恢复它；找齐证据仍可能被生成层误用。

## 四种反例，均为课堂推演

1. 所有接口成功、引用SHA正确，但只返回日志归档：这次链路可以满足工程合同，任务相关性失败。
2. 找到历史需求/用例/L1，重排或预算后关键用例不在最终context：检索前段有证据，实际给生成层的上下文仍不足。
3. 三类证据都给到模型，生成新用例仍写“开关1、实付10”：检索可以通过，生成层误用历史条件/预期，本次任务正确性失败。
4. 回答“新功能中单价10数量2，实付20”恰好正确，但引用只有日志归档：结论对不代表给定引用支持它。若新需求已随任务输入，应区分依据来自新需求还是历史检索证据，不能把“仅依赖检索上下文”当作实际全部输入。

历史TC-02作为历史材料是真实存在的；历史材料被正确引用，不保证把它搬到当前需求仍正确。工程索引版本/SHA用于固定文本，不能自动判定业务规则的适用时间或覆盖关系。

## 当前代码到底评价了什么

`query/retrieval_pipeline.py::RetrievalPipeline.query`只有三段：search→rerank→builder.build。没有自然语言回答或最终测试用例生成。

`response/builder.py:71`按是否装入片段生成retrieved/no_evidence_fits/empty；第74行固定answerability='unknown'。retrieved描述有证据输出，不是语义相关性或可回答性判定。empty可能来自空范围/空索引等，不等于全库确实无答案；no_evidence_fits是候选存在但装不下。外部服务/存储异常另按失败合同传播，不伪装为无答案。

`validation/retrieval_smoke.py`是已存在的有界合成对照脚本，不是完整评测平台。worker第95–106行：

```text
同一hybrid候选池
  ├─ 关闭重排 → baseline hits → packed_baseline
  └─ 启用重排 → reranked hits → packed_reranked
                    各自与同一gold ID集合比较
```

pool是fusion_top_k后的Hybrid候选，不等于Dense/Sparse全部召回并集。pool缺证据还需查看两路和融合，不能仅凭这项就归因向量模型。pool里有而reranked没有，检查重排选择；reranked有但packed没有，检查预算排除。各阶段名称相同的recall对象不同，必须指明检查哪个集合。

脚本score_ids以唯一所需片段ID为分母，重复返回同一ID不增加命中，无gold时recall=None。这里存在的算法测试只证明集合运算/边界实现，不证明标注充分或真实检索质量。公式/粒度/跨方案标注比较下一节展开。

当前questions.json明确label_source=assistant_constructed、review_status=not_reviewed_by_user；source_path+正文anchor唯一解析当前Chunk。不是人工审核金标准。Q4实时汇率无gold且标为unanswerable；脚本记录answerability仍unknown，不声称已经识别无答案。脚本没有生成答案或做主张支持判定。本课不重跑真实模型或历史服务实验。

## 从哪里观察各层

| 观察位置 | 当前数据 | 能支持的结论 |
|---|---|---|
| 原文与Chunk/contexts | 前置、步骤、预期、正文切片 | 内容/结构/来源是否保留 |
| hybrid.dense_hits/sparse_hits/hits | 两路候选与融合输出 | 证据在哪一步出现/消失 |
| ranked.hits | 片段ID、rank、score | 重排后保留了谁，分数不是正确率 |
| response.evidence/context_text/omitted | 最终正文与预算排除 | 下游实际拿到什么 |
| 未来生成结果 | 当前核心未生成 | 本课无回答正确性实测结论 |

测试通过依赖其断言/材料/替身；真实服务请求成功证明接入，不自动证明业务效果。固定样本对照还需要适当标注，真实资料和生产规模需各自验证。这里未提出新通过阈值，也未把演示数据当实测评分。

## 两个Debug Test入口

### 来源合同：不是相关性打分

`tests/test_evidence_response.py::test_all_sources_citations_and_actual_spans`（无参数ID），Test Explorer→Debug Test。测试21行调用builder.build；可F5到builder.py:71，在build帧看len(selected)、len(omitted)、len(ranked.hits)。第74–76行执行后output才产生，看output['status']、output['answerability']。

返回测试帧，第29行执行后chunk/span/doc产生；在31行比较e['body']与doc.text[span['start_char']:span['end_char']]，32行核SHA。通过证明引用/正文对应已保存来源，断言未检查该正文是否足够回答业务问题。

### 工程空态：不冒充无答案判断

`tests/test_evidence_response.py::test_empty_states_do_not_invent_answerability`（无参数ID）。测试68行显式scope_document_ids=[]，69行走关闭重排及builder；观察empty.prepared.status，返回测试帧看result['status']='empty'、result['answerability']='unknown'、result['observations']['embedding'] is None。当前分支无异常，正常返回空结果。不能据此宣布全库无相关材料。

以上使用既有job编码/Chroma替身；native_query虽名字含native，实际是FakeClient上的余弦查询替身，Backend按候选枚举序号给合成分。实际Bundle/BM25/SQLite与来源/预算检查执行，不能当真实Embedding/LLM相关性验证。WATCH只读已产生字段，不重跑query/build。

其他本次覆盖：context预算不切行与omitted分支；RetrievalPipeline实质调用search/rerank/build且编码一次；score_ids的去重、零命中、空gold边界。没有新增或修改测试。

## 本次实际验证

```sh
.venv/bin/python -m pytest -q \
  tests/test_evidence_response.py::test_all_sources_citations_and_actual_spans \
  tests/test_evidence_response.py::test_empty_states_do_not_invent_answerability \
  tests/test_evidence_response.py::test_context_budget_counts_rendering_and_does_not_cut_rows \
  tests/test_evidence_response.py::test_pipeline_is_real_consumer_and_encodes_once \
  tests/test_retrieval_smoke.py::test_recall_uses_gold_count_and_deduplicated_ids
# 5 passed in 5.07s
```

L1：独立查询、Builder和有界合成对照入口存在；L2：来源核验、状态/预算和ID集合计分是真实实现；L3：本次确定性测试覆盖Pipeline消费者、实际保存正文及计分边界，smoke各阶段消费者另由当前源码核对，未实际运行服务worker。没有新增回答评分能力或真实资料质量结论。

只维护学习文档；产品代码/真实.env/运行配置/依赖/原索引不改。构建不适用，未跑全量、真实模型与真实业务评测。文档检查为git diff --check及git diff --cached --check，退出0。

## 学习证据与唯一下一步

6.1已讲解；用户理解待反馈，独立调试/实现/面试追问能力未评估。讲解覆盖30/34节，余第6章4节。唯一下一步：6.2标注单位、Recall@k与固定样本对照。
