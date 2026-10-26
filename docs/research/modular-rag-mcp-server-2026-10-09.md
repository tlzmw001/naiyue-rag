# Modular RAG MCP Server 定向源码调研

## 2026-10-10补充：A2与参考的对齐边界

用户询问A2是否与参考一致。本机固定commit源码核对：双路非空时，参考HybridSearch调用RRFFusion.fuse，以等权1/(k+rank)累加，并按分数/片段ID稳定排序；配置rrf_k=60，与当前A2算法主干相同。参考也有加权方法，但该主路径未调用；只有一路非空时参考可直接返回该路原分数，当前A2仍作RRF。

实现与完整流程有差异：参考以Chroma检索向量、自有BM25Indexer（IDF=log((N-df+0.5)/(df+0.5))）；A2用冻结文件向量精确cosine、BM25S Lucene参数。参考配置dense/sparse/fusion为20/20/10且入口可覆盖最终top_k，A2当前20/20/20＋完整8000字符预算。参考有查询处理/元数据过滤/可选重排及格式化引用，A2尚无重排，增加Markdown完整用例/实际源位置与预算诊断。参考可单路错误降级，Spec0010入口目前失败显式抛出且不隐式降级。

因此A2是同一Dense＋BM25＋RRF路线的本业务基线，不是参考原代码/全流程/配置效果的复现。本轮只读对照，没有运行参考测试或同语料效果比较，不从差异判定哪一实现质量更高；完整模块目标继续按ADR0004建设。

调研日期：2026-10-09。上游 URL：[GitHub 仓库](https://github.com/Jerry-ai-dev/MODULAR-RAG-MCP-SERVER)。只读浅克隆到本机独立 `/tmp/naiyue-rag-reference-main`，分支 `main`，commit [`f658c5a4011c8b826707a65a3b11ce9301b0626f`](https://github.com/Jerry-ai-dev/MODULAR-RAG-MCP-SERVER/tree/f658c5a4011c8b826707a65a3b11ce9301b0626f)（提交日期 2026-03-06 +0800）。以下均针对该快照，不概括其他分支或后续版本。未安装依赖、运行测试、调用模型或启动 MCP；所有结论仅是 README/DEV_SPEC 阅读与静态源码追踪。

用户要求后，于2026-10-09另外从上述GitHub URL浅克隆到长期阅读目录 `/Users/zmw/MODULAR-RAG-MCP-SERVER`。本机核对：main、同一完整commit、Git工作区干净；README、DEV_SPEC、pyproject及检索/切分入口与调研快照内容一致。后续优先从该目录只读追踪源码；原调研副本保留。未执行第三方setup、Skill、安装或服务。这次克隆及文件一致性核验不代表项目功能测试通过。

## 项目自述与依赖

- [README](https://github.com/Jerry-ai-dev/MODULAR-RAG-MCP-SERVER/blob/f658c5a4011c8b826707a65a3b11ce9301b0626f/README.md) 宣称模块化摄取、Dense+BM25+RRF+重排、MCP、Dashboard、Ragas 和追踪。[DEV_SPEC](https://github.com/Jerry-ai-dev/MODULAR-RAG-MCP-SERVER/blob/f658c5a4011c8b826707a65a3b11ce9301b0626f/DEV_SPEC.md) 描述其目标、接口与阶段设计；这些宣称不自动等于实际质量或完整性。
- [`pyproject.toml`](https://github.com/Jerry-ai-dev/MODULAR-RAG-MCP-SERVER/blob/f658c5a4011c8b826707a65a3b11ce9301b0626f/pyproject.toml) 要求 Python >=3.10，依赖 PyYAML、LangChain text splitters、ChromaDB、MCP、jieba、MarkItDown[pdf]、Streamlit、Ragas、datasets。其元数据声明 MIT；该快照未发现单独 `LICENSE`/`COPYING` 文件。此轮没有复制第三方代码，未来复用须再核对许可证文件与适用范围。

## 摄取真实调用链（源码事实）

[`scripts/ingest.py`](https://github.com/Jerry-ai-dev/MODULAR-RAG-MCP-SERVER/blob/f658c5a4011c8b826707a65a3b11ce9301b0626f/scripts/ingest.py) 的 `main` 加载配置，`discover_files` 默认只接收 `.pdf`，构造 `IngestionPipeline` 并逐文件调用 `run`。[`pipeline.py`](https://github.com/Jerry-ai-dev/MODULAR-RAG-MCP-SERVER/blob/f658c5a4011c8b826707a65a3b11ce9301b0626f/src/ingestion/pipeline.py) 构造时实际接入 `PdfLoader`、`DocumentChunker`、三个 transform、`EmbeddingFactory`/DenseEncoder、SparseEncoder、VectorUpserter、BM25Indexer 和 ImageStorage。

`run` 的顺序是 SHA256 完整性检查 → [`PdfLoader.load`](https://github.com/Jerry-ai-dev/MODULAR-RAG-MCP-SERVER/blob/f658c5a4011c8b826707a65a3b11ce9301b0626f/src/libs/loader/pdf_loader.py) 用 MarkItDown 取正文并可提图 → [`DocumentChunker.split_document`](https://github.com/Jerry-ai-dev/MODULAR-RAG-MCP-SERVER/blob/f658c5a4011c8b826707a65a3b11ce9301b0626f/src/ingestion/chunking/document_chunker.py) 经 SplitterFactory 切文本并加 `chunk_index`/`source_ref` → refine/enrich/caption → BatchProcessor 产生 dense 向量与 sparse 统计 → [`VectorUpserter.upsert`](https://github.com/Jerry-ai-dev/MODULAR-RAG-MCP-SERVER/blob/f658c5a4011c8b826707a65a3b11ce9301b0626f/src/ingestion/storage/vector_upserter.py) 写向量库 → 将返回的向量 ID 写回 sparse 统计并更新 BM25 → 注册图片 → 标记摄取成功。若中途失败，Pipeline 记录错误并返回失败；向量库与 BM25 是顺序写，不能从这条链证明跨存储原子更新或自动回滚。

[`Chunk`](https://github.com/Jerry-ai-dev/MODULAR-RAG-MCP-SERVER/blob/f658c5a4011c8b826707a65a3b11ce9301b0626f/src/core/types.py) 类型预留 `start_offset/end_offset`，但当前 `DocumentChunker` 构造 Chunk 时没有填它们，仅保留片段序号及来源引用。因此不能把“类型有位置字段”当作已证明精确原文定位。PDF loader 的元数据也未在上述路径中证明正文片段与 PDF 页码逐片映射。

## 查询、证据与消费（源码事实）

[`scripts/query.py`](https://github.com/Jerry-ai-dev/MODULAR-RAG-MCP-SERVER/blob/f658c5a4011c8b826707a65a3b11ce9301b0626f/scripts/query.py) 装配 VectorStore/Embedding/DenseRetriever、BM25Indexer/SparseRetriever、QueryProcessor、HybridSearch 和可选 reranker。[`HybridSearch.search`](https://github.com/Jerry-ai-dev/MODULAR-RAG-MCP-SERVER/blob/f658c5a4011c8b826707a65a3b11ce9301b0626f/src/core/query_engine/hybrid_search.py) 预处理查询、合并 filters、并行或顺序跑两路召回；两路都失败时抛错，单路失败则降级；两路结果由 `RRFFusion` 融合，再做 metadata 后过滤和 top-k。`create_hybrid_search` 读取配置的 `retrieval.rrf_k`；这是真实接线，不只是配置字段。CLI 再按设置选择重排，并打印结果。

[`query_knowledge_hub`](https://github.com/Jerry-ai-dev/MODULAR-RAG-MCP-SERVER/blob/f658c5a4011c8b826707a65a3b11ce9301b0626f/src/mcp_server/tools/query_knowledge_hub.py) 从 MCP 入参得到 query/top_k/collection，初始化相应 collection 的检索器，在 `asyncio.to_thread` 中运行同步检索与重排，再调用 [`ResponseBuilder`](https://github.com/Jerry-ai-dev/MODULAR-RAG-MCP-SERVER/blob/f658c5a4011c8b826707a65a3b11ce9301b0626f/src/core/response/response_builder.py) 和 CitationGenerator 组装 Markdown、引用 JSON 与可选图像。ProtocolHandler 注册工具，MCP server 用 stdio 启动。这证明了源码有调用路径，未证明与真实 MCP 客户端互通。`_perform_search` 捕获检索异常后返回 `[]`；调用者会按空结果构造响应，失败与“确实无相关证据”在该路径可能混淆，这是我们契约要避免的设计风险。

## 配置、追踪与评测（源码事实及边界）

- [`settings.py`](https://github.com/Jerry-ai-dev/MODULAR-RAG-MCP-SERVER/blob/f658c5a4011c8b826707a65a3b11ce9301b0626f/src/core/settings.py) 解析配置；SplitterFactory 读取 `ingestion.splitter`，EmbeddingFactory、VectorStoreFactory 和 RerankerFactory 分别在上述装配路径调用。配置字段存在和被读取要逐个核对。例：`observability.trace_enabled/trace_file` 被解析，但 [`TraceCollector`](https://github.com/Jerry-ai-dev/MODULAR-RAG-MCP-SERVER/blob/f658c5a4011c8b826707a65a3b11ce9301b0626f/src/core/trace/trace_collector.py) 默认写固定 `logs/traces.jsonl`，上述入口直接构造 `TraceCollector()`；仅从这条路径不能证明这两个设置控制写入。Dashboard 的 TraceService 默认读同一固定文件。
- Pipeline 与 HybridSearch 向 TraceContext 写阶段数据；CLI/MCP 将其交给 TraceCollector。若写盘失败，Collector 记异常日志，不抛给调用者。Trace 中可包含完整正文、查询和片段；对真实敏感材料不宜照搬其默认载荷。
- [`scripts/evaluate.py`](https://github.com/Jerry-ai-dev/MODULAR-RAG-MCP-SERVER/blob/f658c5a4011c8b826707a65a3b11ce9301b0626f/scripts/evaluate.py) 构建同一 HybridSearch 并交给 [`EvalRunner`](https://github.com/Jerry-ai-dev/MODULAR-RAG-MCP-SERVER/blob/f658c5a4011c8b826707a65a3b11ce9301b0626f/src/observability/evaluation/eval_runner.py)。EvalRunner 读 golden set，逐题检索、可选重排、生成答案或以片段拼接作占位，再计算指标。当前脚本没有将 reranker 传入 EvalRunner；`_retrieve` 不使用传入的 collection 参数，并在检索异常时返回空列表。评测异常还会变成空指标。故评测报告需核对是否真的运行了预期路径。
- 默认 [`golden_test_set.json`](https://github.com/Jerry-ai-dev/MODULAR-RAG-MCP-SERVER/blob/f658c5a4011c8b826707a65a3b11ce9301b0626f/tests/fixtures/golden_test_set.json) 中 `expected_chunk_ids` 均为空；CustomEvaluator 的 hit_rate/MRR 对无标签题给 0，不能据此判断检索业务质量。`expected_sources` 虽有字段，EvalRunner 这条评测链仅把 `expected_chunk_ids` 传作 ground truth。

## 大模型接入位置（针对知识库需求补充的源码事实）

参考项目把 **Embedding** 与 **聊天 LLM** 分为两套抽象和配置。[`EmbeddingFactory`](https://github.com/Jerry-ai-dev/MODULAR-RAG-MCP-SERVER/blob/f658c5a4011c8b826707a65a3b11ce9301b0626f/src/libs/embedding/embedding_factory.py) 读取 `settings.embedding.provider`，在摄取的 DenseEncoder 和查询的 DenseRetriever 中使用同类 Embedding 客户端；例如 [`OpenAIEmbedding.embed`](https://github.com/Jerry-ai-dev/MODULAR-RAG-MCP-SERVER/blob/f658c5a4011c8b826707a65a3b11ce9301b0626f/src/libs/embedding/openai_embedding.py) 调用 embeddings API。向量化用于检索，本身不生成答案。

[`LLMFactory`](https://github.com/Jerry-ai-dev/MODULAR-RAG-MCP-SERVER/blob/f658c5a4011c8b826707a65a3b11ce9301b0626f/src/libs/llm/llm_factory.py) 读取 `settings.llm.provider`，返回 `BaseLLM.chat` 实现；例如 [`OpenAILLM`](https://github.com/Jerry-ai-dev/MODULAR-RAG-MCP-SERVER/blob/f658c5a4011c8b826707a65a3b11ce9301b0626f/src/libs/llm/openai_llm.py) 把消息 POST 到 chat completions 端点。实际消费者包括摄取阶段的 [`ChunkRefiner`](https://github.com/Jerry-ai-dev/MODULAR-RAG-MCP-SERVER/blob/f658c5a4011c8b826707a65a3b11ce9301b0626f/src/ingestion/transform/chunk_refiner.py) 与 MetadataEnricher，以及可选的 [`LLMReranker`](https://github.com/Jerry-ai-dev/MODULAR-RAG-MCP-SERVER/blob/f658c5a4011c8b826707a65a3b11ce9301b0626f/src/libs/reranker/llm_reranker.py)。这分别是片段改写/元数据增强和候选重排，不能等同于“基于证据生成问题答案”。

当前 `scripts/query.py` 和 MCP `query_knowledge_hub` 走检索、可选重排、`ResponseBuilder` 格式化引用的链路；`ResponseBuilder.build` 本身没有调用 LLM。EvalRunner 可注入 `answer_generator`，但默认回退是拼接前几个片段的正文，`scripts/evaluate.py` 没有注入真实回答生成器。因此该快照有 LLM 供应商适配和若干调用点，**不能据此说独立问答链路已接线或其回答质量已验证**。本轮未发真实模型请求。

## 可借鉴与不照搬的推断

可借鉴入口与核心分离、统一证据类型、双链路阶段追踪、固定评测集及显式工厂接线的检查方法。对于我们的首期，直接堆全套工厂、MCP、Dashboard、Ragas、图像处理会增加调试面；更适合先做一个可定位片段和单路召回的最小闭环。这个建议是基于本项目教学与验收目标的**设计推断**，不是参考项目源码的性能结论。没有本机运行、真实服务或质量对照数据，不能声称其实现有效或无效。
