# Lesson 30：阶段B·5.1 查询处理、范围与top_k

日期：2026-10-23。第5章共8节，本节第1节。目标：理解原始问题怎样变成固定版本、明确范围且可供两路复用的PreparedQuery，以及各层top_k的数量含义。只学习现有实现，不修改查询清理、范围或算法策略。

## 本章地图

5.1查询处理/范围/top_k → 5.2余弦相似度/Dense → 5.3 TF/DF/IDF/BM25 → 5.4 global/scope统计 → 5.5 RRF → 5.6 LLM/CrossEncoder重排 → 5.7证据预算/引用 → 5.8跨文档补读/再次检索边界。检索打分算法分别在后续对应小节展开。

## 具体输入与输出

课堂示意：G2/revision2中D1=L1模块说明、D2=历史L2需求、D3=历史用例；它们分别含C11/C12、C21、C31等片段。D/C只是缩写，实际document_id为doc-加64位小写十六进制，chunk_id为unit-加64位小写十六进制。调用方应取得真实ID，不能把D1或文件路径直接当ID提交。

```python
prepared = query_pipeline.prepare(
    "关闭 cvr_ltv 开关后，历史分数行为是什么？",
    scope_document_ids=[d1, d2, d3],
    exclude_document_ids=[d3],
    expected_revision=2,
)
```

输出形状（非真实服务数据）：status=ready；active固定G2；document_ids=[D1,D2]（实际按ID排序）；chunk_ids=[C11,C12,C21]（实际按ID排序）；query_sha256为本次原始查询摘要；encoding含Dense向量与Sparse查询词项及用量报告；trace_report记录已执行阶段。

chunk_ids表示可以参与检索的全部片段，不是已经召回的结果。prepared没有candidates/results；ready只说明具备检索条件，不能证明能回答问题。

当前正式公开查询路径是字符串加关键字参数，不是旧实验core.types.QueryRequest。其主链：

```text
RetrievalPipeline.query(query, scope/exclude/revision)
  → HybridSearch.search
      → QueryPipeline.prepare
          → QueryProcessor.process：纯预检
          → DocumentManager._document_bundle：选一次活动快照
          → _scope：合法文档集合投影到片段集合
          → _identity：编码身份与三类产物审计
          → ready才QueryEncoder.encode
          → PreparedQuery
      → DenseRetriever / SparseRetriever：消费同一份准备结果
      → RRF
  → CoreReranker → ResponseBuilder
```

## QueryProcessor做什么

入口query/query_processor.py:34。核query为非空白且UTF-8有效的str；核scope/exclude列表格式、重复、数量和document_id语法；核expected_revision；纯计算地准备编码输入并检查输入/批次限额，包含query_prefix字节。

它不查存储、不请求模型、不进行LLM问题改写、不生成业务过滤条件。scope转换为tuple以隔离调用方后续修改，None与空tuple保持不同语义；QueryPipeline再核这些ID是否真实存在于所选快照。

当前query.strip()仅用于拒绝纯空白输入，没有把strip结果赋回query。首尾空白仍进入实际编码与hash；用户认可的去首尾空白优化已记录future-work，尚未实施。当前输入中的否定、数值、标识符与source:L2_A.md等语法都作为查询文本，不触发读取文件或自动缩小范围。

## 范围计算与分支

`QueryPipeline._scope`第85–92行：known来自所选Bundle全部Document；scope=None时采用known，显式scope时采用指定ID集合；再减exclude；最后按Chunk.source_ref投影片段。

普通写法可理解为：

```python
if scope is None:
    selected = known
else:
    selected = set(scope)
effective_documents = selected - set(exclude)
```

| 输入 | 含义与结果 |
|---|---|
| scope=None | 从当前KB全部已登记文档中选择 |
| scope=[] | 明确不选择文档，不当作全库 |
| scope=[D1,D2]、exclude=[D2] | 只选D1的片段 |
| scope=[D1]、exclude=[D3] | D3若属于当前KB则合法，结果仍D1；exclude无需属于scope |
| scope/exclude含格式不合法ID或重复 | request阶段拒绝，尚未读取catalog |
| ID格式合法但当前版本不存在 | resources阶段query_invalid_scope，尚未审计SDK/编码 |

显式exclude也必须属于known；不存在的ID不静默忽略。排序是按ID规范化，不是按相关性排序。这里不提供module_name/L0/L1/L2类型过滤、不自动扩展父文档或引用链；调用方选择实际ID，或用None全库检索。scope是检索约束，不是本项目新增的文档授权系统。

跨文档可能涉及其他L1/L2时，过早锁定当前需求一份文档会排除外部证据。top_k再大也无法恢复已排除的文档；引用关系补读和上层是否再次检索在5.8展开。

## 为什么过滤必须进入检索

排序示意：全库最靠前是范围外X1、X2，其后才是范围内A1、B1，top_k=2。

- 全库先取前2再过滤：取到X1/X2，过滤后空，范围内证据没有机会进入。
- 先限定A/B范围再排序：候选池为A1/B1，取前2可以返回两者。

真实接线在storage/chroma_query.py:28–36：根据允许文档计算eligible，limit=min(top_k,len(eligible))；collection.query同时传query_embeddings、n_results和where.document_id.$in。Sparse同样消费prepared.document_ids；其统计范围global/scope与结果文档范围是不同概念，在5.4展开。本节核源码接口，不声称测出ANN内部搜索过程或真实业务召回率。

## top_k控制哪一层

top_k是按相关性排序后最多保留的候选片段数；不是文档数、token数、字符数或可信度阈值。多个片段可来自同一文档，不能保证跨文档覆盖。

| 配置 | 实际消费者 | 数量含义 |
|---|---|---|
| HybridSettings.dense_top_k | HybridSearch._dense → DenseRetriever.retrieve → ChromaStore.query | 向量路最多返回多少片段 |
| HybridSettings.sparse_top_k | HybridSearch._sparse → SparseQuerySettings → SparseRetriever | BM25路最多返回多少片段 |
| HybridSettings.fusion_top_k | RRFFusion.fuse | 两路合并去重排序后最多保留多少 |
| RerankSettings.top_k | CoreReranker → ranked_hits | 重排结果最多保留多少 |
| EvidenceSettings.max_context_characters | ResponseBuilder.build | 完整证据打包的字符预算，可能进一步减少条数 |

示意参数dense=20、sparse=20、fusion=10、rerank=5：两路有重叠时合并少于40份；融合最多10份；重排最多5份；预算可能只装下3份。数字用于解释，不是本轮推荐值或最佳实验结论。rrf_k虽也带k，是RRF公式平滑参数，不是保留数量。

当前top_k来自已装配配置对象，不是QueryPipeline.prepare或RetrievalPipeline.query的单次请求参数。HybridSettings严格正整数，bool/0/小数拒绝；HybridSearch还核三路top_k不超过当前max_chunks，先于准备/编码；合格候选不足k时返回较少，不补假结果。PreparedQuery本身不带top_k，数量合同在真实消费者层执行。

增加k主要改变后续候选/返回/重排工作量，不会让同一次查询按k重复做Embedding。k较大不保证质量更高；k太小可能让关键片段在重排前已经退出。具体值应固定数据对照，而不是在课堂示意中直接宣布最优。

## 正常、空态与错误

| 条件 | prepare状态/动作 |
|---|---|
| 没有活动版本，显式范围合法 | unactivated，不编码、不初始化索引目录 |
| 活动版本文档数0，或所选文档有记录但没有片段 | empty_index，不编码 |
| 活动版本有文档，但选完/排除后文档集合空 | empty_scope，不编码 |
| 有合法文档和片段，身份与审计通过 | ready，QueryEncoder成对编码一次 |
| 坏包、坏索引、编码身份不匹配 | 明确resources错误，不伪装空结果 |
| 编码失败 | embedding错误，携带已知用量，不隐式只走另一路 |

有active时，即使scope=[]也执行_identity/健康审计；空范围省掉查询编码，不意味着整个查询零IO。HybridSearch收到合法空准备结果后仍经过两路空分支和空融合，无模型编码/向量相似度查询；相应存储核验仍可能执行。若Sparse词项为空但Dense向量有效，准备状态仍可ready，空词项不等于空索引。

expected_revision与固定快照机制沿Lesson28：None选择一次当前active；显式revision要求选择时匹配，冲突在编码前失败；编码期间另一次激活不让本次重选latest。本节没有自动重试/Agent循环。查询不写入新Bundle或切换活动指针，但SDK审计可能有内部维护，不额外承诺磁盘字节绝对不变。

## Debug Test：先走正常准备，再看空分支

### 正常路径

入口：`tests/test_query_preparation.py::test_ready_scope_projection_encoding_and_trace`，无参数ID。VS Code Test Explorer点击Debug Test；先在测试第48行停住，夹具已准备/激活合成G1，再F11进入prepare。未学启动细节可F5到query/pipeline.py:110。

1. process执行后停在第112行，选prepare栈帧，看processed.scope_document_ids、processed.expected_revision。scope从调用的list复制为tuple，查询仍为原文。
2. 第118行执行前，base/active已产生；F11进入_scope，第90–92行看len(known)、len(docs)、len(chunks)。docs/chunks分别在第90/91行执行后产生；这里只投影有限ID，不展开完整Bundle。
3. 返回prepare第119行，观察docs/chunks；执行到第127行观察status=ready、active.revision=1。_identity内部沿第4章结论，先看输入/返回即可。
4. 第128行编码；第132行前encoding/report已产生，可看len(encoding.dense_vector)、encoding.query_terms[:8]、report.requests['dense_calls_started']。断点刚停在128行时value还不存在，不提前观察。
5. 返回测试第49行，result已赋值，观察result.status、len(result.document_ids)、len(result.chunk_ids)、reads。预期reads=[1]，Dense/Sparse各调用1次，PreparedQuery仍无候选结果。

测试Dense/Sparse为替身，Chroma为FakeClient；Bundle/BM25/SQLite走临时实际存储。catalog.read只是计数包装，内部仍调用原read；7 tokens是替身报告，不是真实服务用量。

### 空范围与非法范围

`tests/test_query_preparation.py::test_none_scope_exclusions_and_explicit_empty`，无参数ID：第68–70行循环三种空范围。停在prepare第127行看status=empty_scope，F10跳过encode；回测试第71–72行看empty.encoding=None、Dense调用次数未增加。测试最初第65行先做一次正常查询，所以不能把整个测试的累计Dense次数误认成0。

`tests/test_query_preparation.py::test_unknown_ids_reject_before_audit_or_encoding[args0]`，精确ID=args0：格式合法的未知scope在_scope第89行抛QueryJobError；prepare第146行_fail归一，pytest.raises捕获。测试把_audit换成pytest.fail，证明未知ID在SDK审计前拒绝；不是正常路径用占位成功跳过审计。args1是未知exclude分支。

### 配置是否真正到达查询

`tests/test_hybrid_search.py::test_config_yaml_is_consumed_by_actual_branches`，无参数ID。测试第35行写临时YAML：dense=2/sparse=1/fusion=2，第36行实际load_hybrid_settings→HybridSearch.search；HybridSearch._dense传2，_sparse传1，fuse传2。回第37–39行核结果上限及模拟collection.query的n_results=2。

这里native_query只是fixture名字，实际上替换FakeClient.query、按范围计算确定性余弦；不能称为真实原生Chroma查询。下列wiring测试用真实Chroma/BM25，但只验证准备结果及按ID回读；真实相似度/业务质量留到后续，不混淆两种证据。

## 本次实际验证

```sh
.venv/bin/python -m pytest -q \
  tests/test_query_processor.py::test_preflight_preserves_text_and_copies_scope \
  tests/test_query_processor.py::test_model_input_limits_include_query_prefix \
  tests/test_query_preparation.py::test_ready_scope_projection_encoding_and_trace \
  tests/test_query_preparation.py::test_none_scope_exclusions_and_explicit_empty \
  tests/test_query_preparation.py::test_unknown_ids_reject_before_audit_or_encoding \
  tests/test_query_preparation.py::test_unactivated_does_not_create_storage \
  tests/test_query_preparation.py::test_active_empty_library_or_blank_document_is_not_unactivated \
  'tests/test_query_preparation.py::test_broken_snapshot_is_not_empty_result[None-bm25]' \
  tests/test_hybrid_search.py::test_config_yaml_is_consumed_by_actual_branches \
  tests/test_hybrid_search.py::test_hybrid_limits_reject_before_encoding \
  tests/test_hybrid_search.py::test_explicit_empty_scope_still_runs_both_empty_branches \
  'tests/test_query_preparation_wiring.py::test_native_preparation_restart_and_pinned_chunk_consumer[normal-False]' \
  'tests/test_query_preparation_wiring.py::test_native_preparation_restart_and_pinned_chunk_consumer[normal-True]'
# 17 passed in 12.40s
```

两个原生normal场景分别非空范围/显式空范围：临时合成库构建→源目录移开→新进程准备→另进程按保存ID回读；真实Chroma/BM25/SQLite，Embedding通过SDK MockTransport且禁止外部网络，model_requests=0。非空场景实际查询编码模拟请求1、空场景0。临时.env/配置在tmp_path，不读改本项目真实.env、原索引或真实材料。

L1：QueryProcessor/QueryPipeline/PreparedQuery/HybridSettings已存在；L2：范围验证、集合投影、空态/编码分支及数量配置为真实实现；L3：17项覆盖配置到实际调用参数与跨进程消费者。本轮只维护学习记录，构建不适用；未跑全量或真实模型，不把测试通过当业务检索质量通过。git diff --check退出0。

## 学习证据与唯一下一步

5.1已讲解，助手核源码并定向验证；用户理解待反馈，本人独立调试/实现未评估。当前讲解覆盖22/34节，余12节（第5章7节、第6章5节）。唯一下一步：5.2余弦相似度、距离和向量召回，从两个小向量手算相似度，再追DenseRetriever到Chroma返回的距离/排序。
