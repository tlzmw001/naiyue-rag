# Spec0037：M5.3 配置化全库/范围统计的关键词召回

日期：2026-10-15。状态：已实现/接线/本地验收。按持续推进授权及用户“双模式配置以便对照”要求实施。

## 1. 当前链与目标

QueryPipeline.prepare已经产生同版本、同tokenizer的问题词项；DenseRetriever已经消费PreparedQuery执行范围内原生Chroma召回。本片让相同PreparedQuery通过SparseRetriever查询正式BM25索引，明确支持global/scope两个统计口径，后续Hybrid融合仅用各路排名，不直接混合分数。

参考为main/f658c5a4011c8b826707a65a3b11ce9301b0626f（URL与本机路径见Spec0036），2026-10-15只读核对：SparseRetriever.retrieve→加载指定collection的BM25Indexer→query(关键词)使用已存IDF/avgdl→Chroma.get_by_ids回正文；旧A2 experiments/keyword_index.pool_data则先选范围再建立BM25S。正式M4保存BM25S0.3.13/lucene/float64的全库矩阵，默认可直接复用。用户选择两种均保留，不把它们说成分数/排序等价。

## 2. 配置与接口

- 新`core/sparse_query_settings.py::SparseQuerySettings(top_k, statistics_scope)`及`load_sparse_query_settings(path)`，复用严格YAML工具；字段必须完整且无额外字段，top_k严格正整数，statistics_scope闭集global/scope。新增`examples/sparse-query.example.yaml`（top_k:20、statistics_scope:global），不改真实.env或当前运行配置。
- 新`BM25Store.query(bundle_id, query_terms, *, document_ids, top_k, statistics_scope)`，storage/bm25_query.py承载只读查询；返回完整Chunk与正分score。Chroma与BM25各自消费同一原包/范围，不要求Sparse再经Chroma读文本，避免把向量存储当唯一正文源；上层已对同版本三件套核验。
- `query/sparse_retriever.py::SparseRetriever(document_manager, settings).retrieve(prepared)`，实际加载配置对象并传入存储query，不重新编码或选catalog；settings防御复制，每次验证配置有效、KB和完整active描述、范围投影一致。
- `core/sparse_results.py`提供严格SparseHit(rank,chunk,score)、SparseResult(prepared,top_k,statistics_scope,hits)及JSON往返。模式进入结果，score_kind分别为bm25s_lucene_global_v1/bm25s_lucene_scope_v1；不能把两种score当相同尺度或答案可信度。
- 扩展QueryJobError sparse阶段/query_sparse_failed，必要故障保留实际active/encoding_report；根/query导出实际入口。

## 3. 正常与失败数据流

1. 严格校验terms实际list/非空UTF8词项/不重复、top_k≤max_chunks、scope属于保存包且不重复；空query_terms合法，不能传入BM25S.get_scores([])。不二次分词、不另做长度/停用词政策，也不擅自lower改变已经编码的词项。
2. 复用BM25Store._prepare/_load_index完整核验已存索引，包括scope为空、OOV、空词项或空词表。范围不能为空态掩盖损坏。
3. global：直接已加载模型get_scores(query_terms)，统计N/DF/avgdl为保存完整知识库；先按document_ids选合规分数，再排序选top_k，不能先全库截断。
4. scope：从已存rows/records按source_document_id投影，保留范围内空词行；以同一k1/b/lucene/float64在内存建立BM25S并评分。无候选/无词表/空query_terms返回[]；不写磁盘、不改变active，不重解析/分词/Embedding。不能从global预计算分数简单筛选冒充scope重算。
5. 两种模型的原生输出必须形状等于参与统计的片段数、float64、有限非负；按分数>0筛选（零分不是证据），再score降序/ID升序，结果≤top_k。输出完整Chunk映射来源，零/未知词不代表问题无答案。
6. ready有片段但Sparse合法无命中仍返回空hits；不会隐式把编码或索引异常变成空结果。未激活无SDK，已有空态仍核验选定索引。错误无部分hits、正文或原始异常，BaseException传播。
7. 结果有界序列化；超过max_bundle_bytes报query_result_limit。日志固定模式/阶段/结果数，原PreparedQuery.trace/编码报告保留；统一混合检索trace后续接入。不编造scope重建耗时或账单，性能专门对照。

## 4. 影响范围与验收

新增配置/存储查询/结果/检索器、空值示例配置及专用测试；仅扩展BM25Store方法、错误阶段/导出，不改持久索引格式、旧接口/测试、依赖或真实环境配置。旧实验仍有消费者，不删除。

TDD：先新接口缺失红灯，再最小实现；覆盖真实YAML→配置→SparseRetriever→BM25Store→选定分支的接线，禁止只有声明而未消费。

- 以保存词项和小型手算例对照global/scope实际分数/排名；Spec0036内存反例扩展为正式调用合同，使用合成tokens，不伪称用户真实材料标注。
- 空query/词表/OOV/空行/空scope及非法类型、未知ID、配置变化/损坏、模型响应坏形状/NaN/负值、IO失败和结果超限。
- 固定PreparedQuery，禁catalog/编码/分词，查询期间新active不混入；实际编码报告保留，严格DTO往返/深复制与来源、模式、排序/唯一性校验。
- 原生跨进程正常/空范围/零/全空/混合，两个配置均调用真BM25S；scope内存构建不得写已有索引，文件字节/mtime保持，来源正文与完整用例回取一致。Embedding仅MockTransport，真实模型请求0。
- 全量回归、compileall/pip check/资产/依赖/格式与链接检查；实际结果追加到本Spec，不把绿灯当真实检索质量。

## 5. 风险、回退、下一步

scope首版每次内存建模有额外CPU/内存开销，暂不缓存；用于明确对照，质量/成本需要固定样本测量。global排名会受范围外语料影响，报告实际模式让差异可解释。两者都仅返回范围内候选。

本片只增加只读入口，旧包/索引/active保持，无自动回滚、删除或恢复。实现发现合同需变更先更新Spec。

下一片M5.4按参考HybridSearch/RRFFusion梳理一次编码→两路→同范围RRF及统一查询追踪，不隐式降级；参考20/20/10/k60配置到真实消费者时接线。

## 6. 实施与验证

配置→SparseRetriever→BM25Store.query→global加载模型/scope内存模型两分支已实际接线；结果模式与score_kind明确。scope仅消费已存词项，不写已有索引，也不重新Embedding/分词/解析。Sparse合法零命中与异常保持分离，模型/来源/版本沿同一PreparedQuery。

先运行专用测试得到**43 failed in5.34s**（缺少新接口/导出，见red-tests.txt）；最小实现后**43 passed in12.96s**，见unit-tests.txt。实现后补3项错误合同和5个原生跨进程检查，并与45项Dense回归一起执行：

```zsh
.venv/bin/python -m pytest -q tests/test_sparse_retrieval.py tests/test_sparse_retrieval_wiring.py tests/test_dense_retrieval.py --tb=short
# 96 passed in 42.57s（51新增、45已有）
```

手算N/DF/avgdl及Lucene权重与原生分数相符，范围过滤后top_k正确；正常/空scope/零/全空词/混合在每个场景均通过实际YAML加载运行global与scope，并与同版本保存词项手算排名/完整Chunk对照。查询前后BM25全部文件内容与mtime不变，编码/目录重选/外部socket禁止。Shape/NaN/负值/SDK异常不会变成空结果；用量及已选版本保留。

200旧资产仅4源码追加接口/导出/错误阶段，新增4源码、1示例配置、2测试；旧测试/配置/锁文件保持，137安装版本不变，源码最大266行。全量`.venv/bin/python -m pytest -q tests --tb=short`→**1985 passed in285.05s（0:04:45）**，exit0；compileall、pip check和git diff --check均exit0（No broken requirements found）。完整证据data/research/spec0037-evidence/verification.json及原始日志，独立打包构建不适用。真实模型POST0，真实.env读改0，无参考执行、删除、提交或push。完整课堂暂挂，无本人独立实现或调试的新证据。
