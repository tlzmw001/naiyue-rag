# Lesson 42：阶段B·6.5 完整查询走读与定位练习

> 2026-10-26。目标：从既有确定性测试进入正式RAG查询链，查看每层真实输入/返回，再用另一条已有错误测试验证定位能力。本节已提供路线与练习，用户尚未实际调试，不登记独立定位成功，不自动进入阶段C。

## 一次完整查询要拿到什么

正常入口：tests/test_evidence_response.py::test_pipeline_is_real_consumer_and_encodes_once，无参数ID。正式调用测试91行：pipeline.query(QUERY,expected_revision=1)。

```python
QUERY = '  开关 关 开关 TC-01 cvr_ltv 0.5  '
```

scope/exclude默认None，使用当前共享知识库范围；expected_revision=1是活动修订检查。当前不去首尾空白，优化已在future-work，不能在WATCH手改query再当当前行为。

返回result为最终JSON字典，含status、answerability、active、context_text、evidence、omitted、observations，不含内部向量。课堂目标是追踪同一请求的文档范围/查询表示/候选/重排/证据，不把这些合成查询解释成业务相关性验收。

```text
测试91行 → RetrievalPipeline.query
  → HybridSearch.search
      → QueryPipeline.prepare
          → 选择活动包/文档范围、审计身份与索引
          → QueryEncoder.encode → Dense/Sparse → 配对 → PreparedQuery
      → 两个工作线程：DenseRetriever / SparseRetriever
      → 汇合检查 → RRFFusion → HybridResult
  → CoreReranker.rerank → RerankResult
  → ResponseBuilder.build
      → KnowledgeReader._bundle核保存来源
      → 整条证据/引用/预算 → 最终dict
  → 返回测试92行断言
```

## 开始前：两个会影响走读的细节

1. 测试89行的build(job)已经搜索并重排一次，用来装配Builder；紧接着清空Dense/Sparse calls。随后创建新Backend，91行才是本次正式完整链。不要把89行准备过程算成91行重复编码。
2. tests/test_hybrid_search.py:18设置parallel_retrieval=True，两路实际线程池执行。F11主线程的submit/Future.result不会依次进入两个Retriever；保留当前配置，使用工作线程函数断点，再看主线程汇合，不为课堂改代码/YAML/IDE设置。

先只在query/retrieval_pipeline.py:7设置入口断点，从Test Explorer点Debug Test。F5越过夹具和89行准备；停在query后，再添加本节其他断点，防止在先前装配过程反复停下。没有现成Debug Test入口时先反馈测试发现情况，不自动安装插件、修改解释器或IDE配置。

F10执行当前行，F11进入当前调用，Shift+F11从当前函数返回调用方，F5继续至下个断点。第三方SDK/线程池/已学存储内部可用边界断点跳过。变量只在赋值执行后产生；在调用前看不到返回对象是正常情况。

## 正常路线：七个观察站

| 观察站/断点 | 选择的栈帧 | 少量观察与产生时机 |
|---|---|---|
| retrieval_pipeline.py:7 | query | query、expected_revision；hybrid还未产生 |
| query/pipeline.py:128及140 | prepare | 128行前active.revision、len(docs)/len(chunks)；140行执行后result.status/active |
| encoding/query_encoder.py:50/63/68 | encode | Dense返回后dense.vectors[0][:3]；Sparse返回后row在配对65行产生，68行后result.query_terms/result.dimensions |
| query/hybrid_search.py:77/78 | search主线程 | 77行执行后dense.hits/sparse.hits；78行执行后hits融合结果 |
| retrieval_pipeline.py:9 | query | search已返回，hybrid及其三组候选可用 |
| retrieval_pipeline.py:10 | query | rerank已返回，ranked.hits可用，与hybrid.hits比较 |
| response/builder.py:79、测试92行 | build / 测试 | 79行output完整构造，返回后测试帧result可用 |

QueryEncoder第68行之后对象名result与外层prepare/result、测试result不同；看哪个值由当前栈帧决定。防御复制会创建新对象，跨层用ID/版本/字段核对，不要求Python对象is相同。

### 1. 查询表示

先F11进入search，再到prepare的128行进入编码；可在Dense/Sparse入口F11看替身，或者Shift+F11回encode。这里Dense返回固定[1.,2.,3.]，Sparse返回合成tokens；不是远程模型或真实jieba当前分词结果。

在encode配对完成后查看：item.retrieval_text、vector[:3]、terms[:5]；result构造后可看result.dense_vector[:3]、result.query_terms[:5]。同一PreparedQuery提供两路输入，不为每路重新Embedding。

### 2. 并行两路

工作线程断点：query/dense_retriever.py:38（已取bundle/版本，准备查库）、query/sparse_retriever.py:39（已核固定包与索引，准备查询BM25）。选Call Stack中命中线程的retrieve帧，看prepared.active.revision、top_k（Dense）或cfg.top_k（Sparse，赋值后）和prepared.document_ids。

两线程命中顺序不保证；继续F5让其完成，不在主线程等待Future时反复F11进入线程库。汇合后回HybridSearch主线程77行执行赋值，再观察：

```python
[(h.chunk.id[-8:], h.rank) for h in dense.hits[:3]]
[(h.chunk.id[-8:], h.rank) for h in sparse.hits[:3]]
```

这是界面简短投影，正式核对用完整ID，后8位不保证全库唯一。78行融合后看[(h.chunk.id[-8:],h.rank) for h in hits[:3]]。不要把eligible_count当ANN内部比较次数，沿Lesson41。

### 3. 重排

回到RetrievalPipeline9行，hybrid已产生。F11进CoreReranker；31行进入测试Backend.score（test_reranking.py:21–25），它按枚举序号给分，不理解业务相关性。

Core35行返回后，外层query10行ranked已产生。比较hybrid.hits的ID顺序与[(h['chunk_id'][-8:],h['rank']) for h in ranked.hits]；默认测试重排top_k=2，Hybrid候选top_k=3，不能把截取后数量减少直接判为bug。

### 4. 最终证据

query10行F11进build。47行加载固定包并核身份/范围，50行核保存Chunk与候选实质一致；不查latest或调用生成模型。若此处深层不熟，可F5到55行逐条打包。

67行之后rendered/needed才产生，68行检查预算，70行保存完整证据。79行停下看：

```python
output['status']
[(e['citation_id'], e['source_path'], e['body'][:50]) for e in output['evidence']]
output['active']['revision']
```

Shift+F11回外层，F10/Shift+F11回测试92行，观察result['answerability']及len(job[3].calls)、len(job[4].calls)、len(backend.calls)。这三个计数只针对91行实际调用，预期各1；answerability仍unknown。来源/结构有效不证明合成评分的业务正确性。

## 替身、真实操作与副作用

- QueryEncoder本身、准备/检索编排、RRF、CoreReranker、Reader、Builder为生产实现。
- Dense/Sparse查询编码为test_query_encoding.setup替身；评分Backend为test_reranking.Backend。
- test_document_manager.prepared把Chroma client替为FakeClient；native_query夹具再替换FakeClient.query，在内存数据做余弦并构造返回。名字native_query不代表本次原生Chroma ANN。
- 资料包读写、BM25与SQLite临时版本管理实际执行；夹具在pytest临时目录建立合成产物，不改用户原索引或真实.env。此主线不是原始Markdown解析/建库的独立逐行练习，摄取路线见第2–4章。
- 主链读取固定数据并更新本次内存观察/替身调用记录；不在WATCH重新执行query/build/激活等有副作用或IO的函数。不装调试依赖，不改真实配置。

## 迁移练习：已有结果为何没成功返回

入口：tests/test_evidence_response.py::test_whole_json_limit_is_not_context_limit，无参数ID。这个机制已学过，这次目标是自己沿执行证据复述定位，不考记忆错误名。

现象：已经获得合法重排候选，却没有返回成功证据响应，测试最终仍通过。只用此已有测试，不修改代码/断言/配置，不关闭来源校验。

从测试61行实际build调用进入；先确认哪些数据已产生，再定位阻止成功返回的条件和负责层。课堂记录暂不替用户填原因、实际观察或结论；源码/test预期可以阅读，不伪装成盲测或已完成独立诊断。

建议用户反馈三项，允许有限字段或截图：

```text
1. 最后一个已完成的阶段，以及支持它的一个变量值：
2. 阻止返回的条件/配置/比较单位与实际观察值：
3. 异常在哪里产生、最终由谁捕获；为什么测试还能通过：
```

如果卡住，只反馈文件/行号、当前Call Stack帧和一个疑问，继续缩小讲解。是否独立完成、使用了什么提示，按真实操作记录；跳过练习可按用户新指令继续，保持该能力未评估。当前没有新增源代码bug，不为使错误测试“不抛异常”修改实现。

## 助手侧本次验证

```sh
.venv/bin/python -m pytest -q \
  tests/test_evidence_response.py::test_pipeline_is_real_consumer_and_encodes_once \
  tests/test_evidence_response.py::test_whole_json_limit_is_not_context_limit
# 2 passed in 2.86s
```

正常主链实际消费与预期异常测试均通过。助手已核代码/运行测试，没有操作用户的VS Code或收到用户调试输出；无真实模型请求。L1入口存在；L2生产链与预算错误真实执行；L3测试91行实际调用RetrievalPipeline→三层消费者，错误由现有pytest.raises验证。不能代替用户掌握、真实业务质量或生产验收。

仅学习文档修改，无源码/.env/运行配置/依赖/原索引修改；构建不适用，未跑全量。git diff --check与git diff --cached --check退出0。

## 阶段收束与唯一下一步

六章34节的机制讲解与本节调试路线已覆盖；6.5本人练习待执行，其他本人理解/独立能力仍以已有证据为准。不能记“已独立定位问题”或自动将阶段B验收完成，也不自动开始Agent/MCP开发。

唯一下一步：用户从现有练习入口提交上述三项调试观察，或给出卡住的具体位置，再接续辅导。
