# 指定参考：MODULAR-RAG-MCP-SERVER

静态源码深验，2026-10-09。main / f658c5a4011c8b826707a65a3b11ce9301b0626f。来源 https://github.com/jerry-ai-dev/MODULAR-RAG-MCP-SERVER 。没有运行测试或模型服务。

摄取：scripts/ingest.py 的 main/load_settings/discover_files 只发现 PDF，调用 IngestionPipeline.run。pipeline.py:132 起装配 loader、chunker、transform、EmbeddingFactory、VectorUpserter 和 BM25Indexer；197 起 SHA256 跳过→PDF解析→切分→增强→Dense/Sparse编码→438向量写入→448 BM25更新→523成功标记。两存储顺序写入，不是跨存储事务证明。DocumentChunker 在131处构造 Chunk，只传id/text/metadata，没有填类型预留的start/end_offset；来源引用和chunk序号不等于原文精确位置。

查询：scripts/query.py装配两路检索。HybridSearch.search预处理→召回→失败降级或抛错→RRF→后过滤→截取；create_hybrid_search读取rrf_k，配置已接线。MCP QueryKnowledgeHubTool.execute初始化collection，线程运行同步检索/重排后调用ResponseBuilder；_perform_search在350处把异常变成空列表，因而该入口可能混淆检索失败与无证据。

模型：EmbeddingFactory读取embedding配置供摄取和DenseRetriever使用；LLMFactory读取llm配置供ChunkRefiner、MetadataEnricher和LLMReranker.chat。ResponseBuilder.build:153仅格式化检索证据与引用，不生成问题答案。EvalRunner可注入answer_generator，但默认358起拼接片段；scripts/evaluate.py未传真实生成器。默认golden_set空相关ID不支持有效召回判断。

借鉴：核心和MCP适配分离，阶段trace、固定标签集、工厂实际接线检查。与本需求差别：默认PDF；没有在本链证明Markdown行号/稳定版本与测试文档角色；默认MCP引用缺少我们要求的完整证据契约；不采用其全量组件列表作为首期范围。

依赖Python>=3.10、PyYAML、LangChain splitter、Chroma、jieba、MarkItDown、MCP、Streamlit、Ragas。pyproject声明MIT，但固定树没有LICENSE/COPYING，未来代码复制须先确认授权。没有复制其代码或第三方Skill。

核心证据：clones/modular-rag/scripts/ingest.py；src/ingestion/pipeline.py；src/ingestion/chunking/document_chunker.py；src/core/query_engine/hybrid_search.py；src/mcp_server/tools/query_knowledge_hub.py；src/core/response/response_builder.py；src/observability/evaluation/eval_runner.py；pyproject.toml。之前完整追踪也保存在本仓库docs/research/modular-rag-mcp-server-2026-10-09.md。

## 根据用户Markdown结构补充的组件复用取舍

2026-10-09复核，仍限定上述固定commit。此为静态源码与设计分析，未运行第三方代码或业务实验。

- 项目自述：DEV_SPEC.md:243-245、514-524将切分描述为递归字符切分并强调结构/语义保留；README.md:359-363同时说明当前默认PDF Loader及其他格式扩展点。
- 源码事实：pipeline.py:145-152直接装配PdfLoader和DocumentChunker；pdf_loader.py:94-105检查PDF扩展名并调用MarkItDown.convert。我们的输入已是Markdown，不需要先沿用该PDF转换路径，但是否采用其他读取组件仍待选型。
- 源码事实：DocumentChunker.__init__调用SplitterFactory.create；splitter_factory.py:79-99读取settings.ingestion.splitter、查注册表并构造实现，内置注册入口:25-27注册recursive。document_chunker.py:116-138调用底层split_text，再为每条字符串生成ID、继承metadata、构造Chunk。这体现组件复用与项目自有适配组合，不证明所有算法自研。
- 源码事实：recursive_splitter.py:13导入langchain_text_splitters.RecursiveCharacterTextSplitter；:42-51的默认分隔符是段落换行、行换行、英文标点、空格和字符；:85-87读取chunk_size/chunk_overlap，:110-115以length_function=len、is_separator_regex=False实例化。切分单位在此按字符数衡量，不是Embedding相似度检测的语义切分。
- 源码边界：document_chunker.py:131-135未填原文offset；所读切分链没有将测试维度、表格行/列或跨用例前置引用识别成专用业务对象。不能从注释“保留结构”推断长用例永不被拆；长行可能进入更细分隔符是设计风险，未本机复现。
- 设计推断：可优先比较“复用现成读取/结构解析/通用切分组件，加项目特有的用例/元数据/定位规则”。需求章节与用例表格未必要采用同一种策略；成熟Markdown解析组件能否完整保留表格、源位置和内联元素需核验。自写业务规则不等于自行实现通用Markdown语法解析器或插件框架。此方向未获用户选择。

窄范围官方文档刷新：LangChain递归切分说明按分隔符和长度工作，中文可配置标点，https://docs.langchain.com/oss/python/integrations/splitters/recursive_text_splitter 。Markdown标题切分文档两次直接读取失败，未据失败页面推导能力；原响应保存于../raw/web/parsing-component-page-reads-2026-10-09.json。本轮没有增加候选深验名额、安装组件或启动实验。
