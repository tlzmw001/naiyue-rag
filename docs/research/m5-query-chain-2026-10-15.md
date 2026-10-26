# M5 查询链：参考源码与正式核心对照

日期：2026-10-15。性质：静态源码对照、现有组件测试及合成探针；不是M5产品实现或检索质量验收。阶段顺序以[项目计划](../project-plan.md)的A/B/C边界为准；首片提案见[Spec0035](../specs/0035-m5-query-preparation.md)。

## 1. 来源与证据边界

- 参考：[MODULAR-RAG-MCP-SERVER](https://github.com/Jerry-ai-dev/MODULAR-RAG-MCP-SERVER)，本机只读 `/Users/zmw/MODULAR-RAG-MCP-SERVER`。
- 分支 main，commit `f658c5a4011c8b826707a65a3b11ce9301b0626f`，工作区干净；未查询远端，不能称本轮GitHub最新版本。
- README/DEV_SPEC为项目自述；本轮沿当前源码核对实际调用。pyproject声明MIT、Python>=3.10，Chroma等依赖范围不代表其实际运行版本；未运行setup/Skill/参考测试/服务，不复制第三方代码。
- 19项参考文档/配置/源码/测试指纹存于 `data/research/spec0035-evidence/source-review.json`；不读取真实.env或复制凭证。

## 2. 一条真实装配与查询调用链

```text
ProtocolHandler注册 query_knowledge_hub
  → QueryKnowledgeHubTool.execute(query, top_k, collection)
    → _ensure_initialized(collection)
       EmbeddingFactory / VectorStoreFactory / BM25Indexer
       → DenseRetriever / SparseRetriever
       → QueryProcessor() / create_hybrid_search(settings,...)
    → _perform_search → HybridSearch.search
       → QueryProcessor.process
       → 合并query内filters与显式filters（显式值优先）
       → 两路并行
          DenseRetriever.retrieve(original_query,filters)
            → embedding_client.embed([query])
            → ChromaStore.query(where=filters)
          SparseRetriever.retrieve(keywords,collection)
            → BM25Indexer.load/query → chunk_ids
            → vector_store.get_by_ids → 拼回text/metadata
       → 双路成功时RRFFusion；一路异常可降级到另一路
       → 融合后的metadata过滤 → top_k
    → 可选CoreReranker.rerank
    → ResponseBuilder.build → citations + Markdown/MCPToolResponse
    → TraceCollector.collect → 返回
```

关键位置（均指上述commit）：

- [工具初始化](https://github.com/Jerry-ai-dev/MODULAR-RAG-MCP-SERVER/blob/f658c5a4011c8b826707a65a3b11ce9301b0626f/src/mcp_server/tools/query_knowledge_hub.py#L140)：函数说明提缓存，但实际每次初始化重建vector store/retrievers/query processor/hybrid；embedding/reranker在实例中复用。BM25路径由collection拼出，查询前重载，不是跨两路的固定版本快照。
- [HybridSearch.search](https://github.com/Jerry-ai-dev/MODULAR-RAG-MCP-SERVER/blob/f658c5a4011c8b826707a65a3b11ce9301b0626f/src/core/query_engine/hybrid_search.py#L203)：process→retrieval→fallback/fusion→post-filter。421行线程池max_workers=2，两future依次result(timeout=30)，不能仅凭这行宣称整次查询有30秒硬截止。
- DenseRetriever:143–177：直接对原始query做Embedding；ChromaStore:203查询原生cosine，返回分数用 `max(0,1-distance/2)`，不是我们旧A2的原始cosine刻度。
- SparseRetriever:141–182、222–240：load失败/异常可变为False后返回空；BM25按加载索引的统计量评分，先top_k再回取正文，接口只接collection，没有文档ID范围参数；某些结果转换错误会跳过条目。
- HybridSearch:534–581只从filters提取collection交给Sparse；其他metadata条件靠后置过滤，不能等同两路都在同一文档范围内召回。融合截断后再过滤可能减少最终候选；缺字段宽松处理也不适合作为严格范围保证。
- [RRFFusion.fuse](https://github.com/Jerry-ai-dev/MODULAR-RAG-MCP-SERVER/blob/f658c5a4011c8b826707a65a3b11ce9301b0626f/src/core/query_engine/fusion.py#L84)：1-based排名累加1/(k+rank)，同分按chunk_id；HybridSearch仅一路有非空结果时直接返回原分数，不重新计算RRF。

## 3. QueryProcessor与参数的实际接线

参考QueryProcessor:89–93默认min_keyword_length=1、max_keywords=20、enable_filter_parsing=True。process:117起：折叠空白→解析key:value→jieba.lcut→停用词/长度/去重/数量截断。仅过滤长度规则作用全部token，不能直接套到我们的0/1等参数值。

- 正文Dense实际使用ProcessedQuery.original_query，折叠空白/去过滤只影响关键词路径。
- FILTER_PATTERN匹配一般key:value，除collection/type/source/tag外也接受任意key，且从稀疏查询文本删去匹配。这可能将技术内容误作过滤条件，不能把它当作本项目已接受的查询语法。
- 工具装配显式QueryProcessor()；当前Settings.retrieval字段只有dense_top_k、sparse_top_k、fusion_top_k、rrf_k，没有接上述QueryProcessor可选参数。工厂函数有参数不等于当前YAML能够配置它。
- DEV_SPEC:311起自述同义词/别名扩展；核对当前QueryProcessor实际链未见这些扩展接线，不能作为已实现事实。
- 当前config/settings.yaml:60–64显式20/20/10/k60；create_hybrid_search:750起实际读取rrf_k，HybridSearch._extract_config读取三top_k，同时将并行/双路/后置过滤设为True。其他代码默认值不应冒充用户配置。

参数差异：本项目旧A2实验candidate_k≤20、rrf_k60、context≤8000（Spec0010历史约束），不能把参考fusion10自动当作业务最优。M5.1不引入召回数量参数；M5两路/融合切片再用可配置值和固定样本比较，保留A2对照。

## 4. 结果怎样被重排、响应、追踪和评测消费

- CoreReranker.rerank:235：关闭或少量候选短路；否则转换候选调用后端，返回结果及fallback信息；错误策略由配置决定。属于我们的M6，当前不借M5.1提前实现。
- ResponseBuilder.build:153：基于检索结果生成citations、Markdown和metadata，可组装图片块，返回MCPToolResponse；这条build链没有执行通用LLM问答生成。带引用检索结果不等于问题已经被生成模型回答。
- QueryKnowledgeHubTool.execute:255起创建TraceContext，HybridSearch记录query_processing/dense/sparse/fusion，reranker记录rerank；最终trace.metadata保存query片段、正文和来源，TraceCollector收集。本项目沿安全统计/标识追踪，不照搬原文或查询日志。
- 工具_perform_search:317/348捕获搜索异常并返回[]；execute还构建错误响应。因此必须区分“真的没候选”和“搜索失败被转空”，不能凭外层空响应推断底层成功。
- EvalRunner._evaluate_single:253、_retrieve:311直接调用同一HybridSearch，收集chunk IDs，按配置重排、可选生成，再交evaluator；它不要求MCP。其retrieve异常也会返回[]，评测解读须区分失败原因。本项目保留独立核心可评测设计，完整Runner/Provider留阶段C。
- 当前参考tests/integration/test_hybrid_search.py使用Fake/Mock检索器检查编排，test_query_processor.py检查分词/过滤；本轮仅阅读，不当参考真实模型/索引服务验证。

## 5. 我们的现有资产与M5分片建议

| 现有资产 | 当前事实 | 下一步消费 |
|---|---|---|
| QueryEncoder/QueryEncodingResult | 一个新问题得到向量、词项、双hash、三种身份和真实本次EncodingReport | M5.1按选定版本验证后调用；Dense/Sparse消费同一结果，避免再次编码 |
| DocumentManager/_document_bundle/_audit | 一次选active/包，按保存的两路参数审计；旧版本保留 | M5.1固定版本与范围；M5后续只读该bundle/index，不再选latest |
| ChromaStore | 正式保存、完整审计、按ID回读；尚无正式相似度query方法 | M5 Dense切片扩展原生查询，不能说已有新问题召回 |
| BM25Store | 正式保存、原生模型加载与逐词审计；尚无正式范围检索 | M5 Sparse切片明确统计语义后接查询 |
| 旧retrieval.py/a2_snapshot.py | 调用experiments且依赖旧快照/合同 | 对照、复用机制；正式路径不加旧包装，不未经核验删除消费者 |
| TraceContext | 安全固定字段，可记录请求/资源/编码阶段并终结 | M5.1复用，不改旧七阶段、不提前建追踪平台 |

建议顺序：M5.1查询准备（纯QueryProcessor+QueryPipeline编排）→Dense→Sparse→Hybrid/RRF→受控关系导航/补读，具体后续片Spec逐项确认。M5.1不返回检索命中。BM25范围内重算与全库统计后过滤的取舍在Sparse切片编码前单独说明，不能借范围ID已确定就声称评分语义已确定。

## 6. 本轮本机证据

- 基础回归：`.venv/bin/python -m pytest -q tests/test_query_encoding.py tests/test_query_encoding_wiring.py tests/test_index_versions.py tests/test_document_manager.py tests/test_document_manager_wiring.py --tb=short` → **155 passed in24.06s**。真SDK MockTransport/真Sparse及本机索引等证据以各测试范围为准，不是M5.1新功能通过。
- 合成探针：原始query（含source:字样）原样进入Dense，实际Sparse保留cvr_ltv/0/1/0.5/tc-01，Dense模拟调用1次；现有M2范围投影2文档/5片段；旧QueryRequest对[]范围报invalid_scope。首次探针对异常基类误写ValueError，核实后捕获实际RetrievalError；未改源码掩盖。
- 探针“不开启”的Sparse词项为“开启”：中文最短词长2可能丢单字否定。Dense仍保留完整原文；本轮不擅改已确认词项政策，需固定质量样本验证业务影响，不声称否定语义已解决。
- 来源/探针/测试日志及资产检查：`data/research/spec0035-evidence/`。真实模型0、真实.env读改0；未重跑1780全量，未实现M5或运行参考服务；课堂仍处阶段A必要说明，独立掌握无新增证据。
