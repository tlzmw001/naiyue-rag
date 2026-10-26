# Lesson 40：阶段B·6.3 失败归因与单变量实验

> 2026-10-26。目标：目标证据未出现在最终上下文时，沿实际数据检查第一次丢失的位置，再提出可证伪假设。复用当前实现和测试，不新增诊断框架或调参功能。

## 一个任务与一条目标证据

沿前两节合成折扣任务，假设人工审核后确认历史用例C是必要参考。最终evidence不含C时，先保存问题、标签来源/完整性、原文/活动版本、scope/exclude、各层k和预算。这里业务C为课堂示意；本课实际探针用测试夹具中第一条重排候选作target，未声称该条经业务审核。

先区分两类现象：成功返回但缺证据，是质量/范围/预算等诊断；QueryJobError/RerankError/EvidenceError等显式异常，是执行失败。不得把失败异常伪装成empty或普通零分后解释为不相关。

## 第一次丢失的位置

```text
正确的本版本原文确有目标内容？
 → Bundle的Chunk/contexts保留目标必需信息？
 → PreparedQuery范围内允许候选包含它？
 → Dense/Sparse两路返回它？
 → Hybrid融合截取后还在？
 → Rerank截取后还在？
 → 最终evidence/context_text还在？
 → 未来生成层是否正确使用？
```

| 首个不满足的位置 | 看什么 | 可以提出的下一假设 |
|---|---|---|
| 当前原文无此规则 | 来源SHA、版本、标注出处、资料是否缺失 | 资料/标注错或版本不一致，不先改检索算法 |
| 原文有、片段/上下文不完整 | chunk.text、contexts、body_span | 切分/结构保留问题；先核完整单位，不能只看ID |
| 文档/片段不在准备范围 | prepared.document_ids/chunk_ids、scope/exclude | 请求范围排除，非排名问题 |
| 在范围内，两路均未返回 | 两路top_k、query_terms/文档词项、向量/身份/分数 | 某路候选截断、关键词表达/表示等；尚不能直接判Embedding差 |
| 两路至少一路有，融合后无 | dense_hits/sparse_hits与hybrid.hits、rrf_k/fusion_top_k | 融合排序或截取阶段，继续核名次 |
| 融合后有，重排后无 | ranked.scores/hits、top_k、实际候选文本 | 模型评分或重排截取；两者还需区分 |
| 重排后有，最终无 | omitted的ID/reason、上下文预算、实际渲染长度 | 打包预算；JSON超限则另为整次异常 |
| 最终证据完整、生成仍错 | 未来生成输入/输出与新需求、历史条件 | 生成使用/业务适用性；当前核心未生成答案 |

“首个丢失位置”缩小调查范围，不自动给出最终根因。例如范围排除可能来自调用方意图错误；候选里没有可能是k、表示或词项匹配。需要下一步最小验证。不能仅看最终低Recall就跳到换模型。

## 当前源码的三处边界

1. query/hybrid_search.py:77–82：消费两路真实结果，RRFFusion按fusion_top_k截取；HybridResult同时保留dense_hits/sparse_hits/hits。trace只有阶段计数不够定位某个ID，需内存结果或经授权的合成调试产物。正式安全追踪不擅自加原始敏感正文/查询。
2. reranking/core.py:25–35：只把hybrid.hits组装为candidates，后端只评分现有passage_id，验证完整ID后按top_k输出。core/rerank_results.py:9–12排序并截取；它不能扩大候选池或搜索缺失证据。分数低和top_k小都可能使目标不入选，不能统称模型失败。
3. response/builder.py:67–70：渲染完整证据，超过剩余字符预算记{chunk_id,reason:'context_budget'}并继续；候选和重排名单不因此修改。异常evidence_source_mismatch或evidence_response_limit按错误分支处理，不等同预算省略。

同一prepared绑定版本；不能用旧gold ID对新版产物找“第一次丢失”。改分块的业务证据映射问题沿Lesson39。

## 一个最小假设与验证

现象：目标在ranked.hits但不在evidence，且omitted对应context_budget。

假设：本次打包预算不足，使目标未返回。

控制条件：保留同一RerankResult、同一版本、候选、分数、顺序、top_k与JSON上限；只在内存替换max_context_characters。直接builder.build，不再次search或rerank。

预期：预算足够时目标恢复；若仍未恢复，则该假设未充分解释本次现象，应读实际输出与其他限制。不是连续调大所有参数。

本课合成临时探针复用test_document_manager.prepared、test_query_preparation.job、native_query夹具和test_evidence_response.build，调用正式Builder。临时目录Path.resolve，socket连接禁用，测试结束撤销monkeypatch。编码/Chroma/评分为既有替身；真实Bundle/BM25/SQLite与来源/预算路径执行。

实际输出：

| 同一份3条重排结果 | 预算字符 | 最终数量 | target在最终结果 | target省略原因 |
|---|---:|---:|---|---|
| 小预算 | 1 | 0，no_evidence_fits | 否 | context_budget |
| 恢复到完整渲染长度 | 174 | 3，retrieved | 是 | 无 |

输入RerankResult序列化前后相同，两次输出active相同；初次准备Dense/Sparse各调用1次，预算对照新增编码0次、真实模型请求0。174是本次夹具渲染长度，不是默认值、业务建议或生产性能结果。结论仅支持当前合成调用的预算解释，不证明真实资料召回/排序最优。

## 其他位置怎样设计单变量实验

| 定位到的位置 | 先固定 | 只改变 | 观察 |
|---|---|---|---|
| 范围 | 同一资料/问题/配置 | scope或exclude中的一个因素 | 目标是否进入eligible；新准备可能重新编码，需记录版本/输出 |
| Sparse词项 | 同一文档版本/检索参数 | 一处查询表达或分词策略 | 词项→得分/候选变化；改查询实验不等于纯分词实验 |
| 某路候选截断 | 同一prepared/索引与其他参数 | 该路top_k | 原缺失目标是否出现、融合及成本的后续影响 |
| 融合截取 | 同一已得两路候选 | fusion_top_k | 目标是否因截断进入；无需重编码 |
| 重排截取 | 同一hybrid及已得scores | 重排top_k | 排名不变时是否仅因截断遗漏 |
| 评分机制 | 同一hybrid/目标/预算 | 评分后端或策略 | 目标名次与固定k覆盖；随机输出需重复并记录波动 |

这些是实验设计，不是本课全部运行，也不表示新增缓存/评分重放API。检索后端扩大top_k可能改变近似搜索结果，需记录实际候选，不承诺旧结果必为新结果前缀。改Embedding需文档/查询一致重建，不允许只换查询模型后与旧索引比较。

“单一自变量”允许重建派生产物：例如只改分块策略，会连带改变Chunk、编码与索引；这些是该因素的下游影响，但必须固定原文与业务标签、核实际接线。一起换分块、Embedding、k和重排，无法把增益归因到某个因素。

预算上调后通过只是局部机制验证；选择长期值还需固定样本整体覆盖、噪声、延迟/成本和保留样本验证。未测费用仍未知，不从字符或耗时推算真实账单。

## Debug Test：正常缺证据与执行失败

### 预算排除与恢复

`tests/test_evidence_response.py::test_context_budget_counts_rendering_and_does_not_cut_rows`（无参数ID），Test Explorer→Debug Test。测试41行产生builder/ranked/full；42行只替换当前测试对象预算，44行设为1，45行调用build。可F5到builder.py:68，选build帧观察cfg.max_context_characters、characters、needed和uid；67行后rendered/needed已产生。69行记省略，返回测试帧46–47行看none的status/evidence/omitted。

没有在此处抛异常：这是合法预算选择。测试还核完整预算恰好可装入，以及较小预算下保留项不截断。课堂探针另以同一ranked实测1→174恢复；不是声称已有测试中存在该打印或固定数值。WATCH不重跑search/rerank/build。

### 后端异常不是相关性零命中

`tests/test_reranking.py::test_whole_failure_never_falls_back_or_leaks[raise]`。测试83–84行把backend.score替成抛OSError的函数；86行调用CoreReranker.rerank。断点core.py:31，F11进入替身抛错；core.py:38–40捕获并包装RerankError('rerank_invalid_output')，测试86行pytest.raises捕获。选测试帧87行后观察error.code、error.report['status']、hasattr(error,'hits')。当前合同整次报错，没有退回未重排候选冒充成功，不能把此题当作合法empty。

### 来源不一致

`test_stored_source_audit_rejects_valid_but_changed_chunk`在候选metadata加入测试标记但不改变保存原件；Builder50–51行实质核验失败，83行捕获evidence_source_mismatch。不是相关性差，也不能关闭来源核验来提高返回率。

## 本次实际验证

```sh
.venv/bin/python -m pytest -q \
  tests/test_evidence_response.py::test_context_budget_counts_rendering_and_does_not_cut_rows \
  tests/test_evidence_response.py::test_empty_states_do_not_invent_answerability \
  tests/test_evidence_response.py::test_stored_source_audit_rejects_valid_but_changed_chunk \
  tests/test_reranking.py::test_disabled_and_equal_scores_keep_original_order \
  'tests/test_reranking.py::test_whole_failure_never_falls_back_or_leaks[raise]'
# 5 passed in 5.11s
```

另有上述临时Python标准输入探针，实际输出fixed_ranked_count=3、initial_selected=3、encoding_calls=[1,1]、budget1排除/174恢复、ranked_input_unchanged=true、new_encoding_calls=0。无真实服务请求，临时合成路径，不改现有索引。

L1：三阶段结果/预算省略/异常合同存在；L2：实质评分候选限制、截取/打包/来源校验执行；L3：测试及预算探针调用正式链路，不能当真实ANN/业务质量或生产可靠性证明。仅维护学习文档；源码/.env/运行配置/依赖不改，构建不适用，未跑全量。git diff --check和git diff --cached --check退出0。

## 学习证据与唯一下一步

6.3已讲解，用户理解待反馈，独立诊断/调试/实现未评估。讲解覆盖32/34节，余2节。唯一下一步：6.4追踪、延迟和用量的证据边界。
