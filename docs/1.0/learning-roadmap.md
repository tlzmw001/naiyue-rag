# 学习路线与代码阅读顺序

## 当前学习位置

### 阶段B章节地图（面向RAG初学者，共34节）

当前第6章第5节（2026-10-26）：完整查询走读与定位练习；已提供正常调用链、并行线程/变量断点及既有异常迁移练习。六章34节机制讲解与调试路线已覆盖，6.5本人练习待完成，独立能力未评估；阶段B不自动验收为完成。唯一下一步：用户提交一次实际调试观察或卡住位置。每节按“业务例子→概念与手算→实际数据流→关键代码→必要测试走读”组织；算法在对应章节展开，不要求先学完整数学或框架。小节数随实际难度调整，不承诺完成日期，两条学习线共享可用时间。

| 章 | 主题 | 小节数 | 当前代码阅读入口 | 学习状态 |
|---|---|---:|---|---|
| 1 | RAG整体认识与项目边界 | 4 | RetrievalPipeline.query→HybridSearch.search→CoreReranker.rerank→ResponseBuilder.build | 1.1–1.4已讲解；用户调试/独立能力未评估 |
| 2 | Markdown解析与分块 | 6 | MarkdownLoader→prepare_knowledge_base→DocumentChunker→ChunkRefiner | 2.1–2.6已讲解；本人理解/调试待反馈 |
| 3 | 文本表示、Embedding与成对编码 | 6 | input_preparer→DenseEncoder→SparseEncoder→BatchProcessor/QueryEncoder | 3.1–3.6已讲解；理解/本人调试待反馈 |
| 4 | 索引、存储与文档生命周期 | 5 | BundleStore→VectorUpserter/BM25Indexer→DocumentManager→IngestionPipeline | 4.1–4.5已讲解；理解/本人调试待反馈 |
| 5 | 检索算法、重排与证据组装 | 8 | QueryPipeline→DenseRetriever/SparseRetriever→RRFFusion→CoreReranker→ResponseBuilder/KnowledgeReader | 5.1–5.8已讲解；理解/本人调试待反馈 |
| 6 | 质量评估、故障定位与独立调试 | 5 | 现有确定性测试→实际数据与报告 | 6.1–6.4已讲解；6.5路线已提供，本人练习待完成 |

#### 各章小节

- 第1章：1.1 RAG解决什么、检索和推理的边界；1.2 建库与查询两条数据流；1.3 查询输入、证据输出与模块合同；1.4 正常、空结果与失败的完整链路。
- 第2章：2.1 Markdown如何变成结构化文档；2.2 标题、正文、表格与真实定位；2.3 固定长度、重叠与递归切分；2.4 结构规则与语义分块的区别；2.5 一行一用例、表头与上下文完整性；2.6 L0/L1/L2引用、名称配对与跨文档关系边界。
- 第3章：3.1 原文、检索文本与编码文本；3.2 Embedding和向量空间；3.3 分词、词频与稀疏表示；3.4 文档/查询编码与模型一致性；3.5 成对批处理、ID与hash配对；3.6 超限、整次失败与真实用量。
- 第4章：4.1 原文、资料包与索引的区别；4.2 Chroma向量存储和相似度索引；4.3 BM25索引的构建与重载；4.4 同版本激活与固定查询快照；4.5 重复摄取、更新、移除和历史保留。
- 第5章：5.1 查询处理、范围与top_k；5.2 余弦相似度、距离和向量召回；5.3 TF/DF/IDF、长度归一化与BM25；5.4 全库/范围统计及其排序影响；5.5 双路互补与RRF手算；5.6 重排原理：LLM与CrossEncoder；5.7 完整证据、预算和引用；5.8 跨文档补读与上层再次检索的边界。
- 第6章：6.1 检索质量、回答质量与工程质量；6.2 标注单位、Recall@k与固定样本对照；6.3 失败归因与单变量实验；6.4 追踪、延迟和用量的证据边界；6.5 从Debug Test走完整分支并独立定位一次问题。

第1章四节见[Lesson9](lessons/lesson-9.md)、[Lesson10](lessons/lesson-10.md)、[Lesson11](lessons/lesson-11.md)、[Lesson12](lessons/lesson-12.md)。

第2章六节见[Lesson13](lessons/lesson-13.md)、[Lesson14](lessons/lesson-14.md)、[Lesson15](lessons/lesson-15.md)、[Lesson16](lessons/lesson-16.md)、[Lesson17](lessons/lesson-17.md)、[Lesson18](lessons/lesson-18.md)。

第3章3.1见[Lesson19](lessons/lesson-19.md)，含四步文本表示与hash；3.2见[Lesson20](lessons/lesson-20.md)，含向量手算与Dense响应；3.3见[Lesson21](lessons/lesson-21.md)，含真实词项与TF；3.4见[Lesson22](lessons/lesson-22.md)，含三类身份与编码前后校验；3.5见[Lesson23](lessons/lesson-23.md)，含批次配对与完整交付；3.6见[Lesson24](lessons/lesson-24.md)，含限额/截止/用量与章节收束。

第4章4.1见[Lesson25](lessons/lesson-25.md)，含原文快照、资料包五文件与索引职责；4.2见[Lesson26](lessons/lesson-26.md)，含Chroma原生映射/持久化、HNSW与回读校验；4.3见[Lesson27](lessons/lesson-27.md)，含BM25倒排/矩阵/行映射及空态持久化；4.4见[Lesson28](lessons/lesson-28.md)，含三产物激活、revision与固定查询快照；4.5见[Lesson29](lessons/lesson-29.md)，含重复摄取、配置复用、合并更新、显式移除与历史保留。

第5章5.1见[Lesson30](lessons/lesson-30.md)，含查询预检、范围投影、前置过滤与分层top_k；5.2见[Lesson31](lessons/lesson-31.md)，含余弦/距离/score手算与Dense完整来源召回；5.3见[Lesson32](lessons/lesson-32.md)，含片段级TF/DF/IDF、长度修正、Lucene实际计分与Sparse链；5.4见[Lesson33](lessons/lesson-33.md)，含候选/统计母体区别、global/scope反转与配置接线；5.5见[Lesson34](lessons/lesson-34.md)，含等权RRF、候选来源合并、双路串并行与失败合同；5.6见[Lesson35](lessons/lesson-35.md)，含LLM/CrossEncoder、完整评分ID/预算/异常路径；5.7见[Lesson36](lessons/lesson-36.md)，含原文绑定、完整片段预算/局部引用与JSON上限。5.8见[Lesson37](lessons/lesson-37.md)，含read_chunk/read_lines/related_documents、同版补读与新增查询的区别及Agent职责。当前只登记讲解及助手验证，用户理解待反馈，本人调试/复写/独立实现未评估。第6章6.1见[Lesson38](lessons/lesson-38.md)，含三类质量、历史规则适用性、阶段证据覆盖与当前评测边界；6.2见[Lesson39](lessons/lesson-39.md)，含标注单位/Recall手算、空gold、标签定位与跨分块对照边界；6.3见[Lesson40](lessons/lesson-40.md)，含首次丢失边界、固定输入预算1→174对照及异常合同；6.4见[Lesson41](lessons/lesson-41.md)，含计时边界/并行重叠、调用与请求/用量独立性、未知费用及当前报告未自动落盘；6.5见[Lesson42](lessons/lesson-42.md)，含正常全链/工作线程断点、替身边界及本人定位练习；路线已提供，练习尚未执行。唯一下一步：本人提交调试观察或卡住位置。既有查询Debug Test路线见Lesson12，不以课堂笔记或测试通过替代本人掌握。

M6后续阅读入口：`reranking/core.py::CoreReranker.rerank`、`llm.py::LLMReranker.score`、`cross_encoder.py::CrossEncoderReranker.__init__/score`、`response/builder.py::ResponseBuilder.build`、`app.py::execute`。历史开发记录保留在下文；当前课堂位置以上述章节地图为准。


2026-10-16阶段A已完成当前本地工程边界，下一步为第1章系统学习。以下2026-10-15为历史开发位置：M5.2 Dense、M5.3两种BM25统计、M5.4 HybridSearch/RRFFusion及M5.5 KnowledgeReader已有实现/接线，M5模块全量2046 passed in341.34s；当前不是进入课堂。恢复系统学习时，查询章节顺序为QueryPipeline.prepare→DenseRetriever/SparseRetriever→HybridSearch._dense/_sparse/search→RRFFusion.fuse与core.hybrid_results.fused_hits→KnowledgeReader.read_chunk/read_lines/related_documents。事件barrier测试证明并行启动，原生两worker实测串行/并行结果一致；原文精读不启动模型/SDK或重选catalog。已说明职责和结果；本人源代码走读、复写/调试与追问无新增证据。M6的CoreReranker→LLMReranker→ResponseBuilder→RetrievalPipeline/CLI已有接线与真实合成GLM闭环，见Spec0041/0042；本地CrossEncoder已完成单环境兼容依赖及真实CPU/同池/CLI验证，阶段A本地全量2151通过，准备进入本章地图，见Spec0043。完整课堂继续暂挂，无本人掌握证据新增。

2026-10-15用户已确认[三阶段顺序](../project-plan.md)：阶段A先完成M1–M6独立RAG核心，阶段B按全链路/解析/编码/存储/检索重排/调试验证六章系统学习，阶段C扩展Agent/MCP/完整评测等。当前A进行中，完整课堂暂挂；必要机制说明与工程结果不替代本人掌握。M5[调用链对照](../research/m5-query-chain-2026-10-15.md)与[Spec0035](../specs/0035-m5-query-preparation.md)是查询章节起点；当前开发位置以上段及交接顶部为准。

M5.1阅读入口：`query/query_processor.py::QueryProcessor.process`→`query/pipeline.py::QueryPipeline.prepare`→`DocumentManager._document_bundle/_audit`→`QueryEncoder.encode`→`core/query_preparation.py::PreparedQuery`；错误路径在`QueryPipeline._fail`。新增103 passed in33.30s，其中5个原生跨进程场景消费准备结果回取完整片段。以后课堂可从`tests/test_query_preparation.py::test_ready_scope_projection_encoding_and_trace`、`test_actual_activation_during_encoding_does_not_change_selected_snapshot`及`tests/test_query_preparation_wiring.py::test_native_preparation_restart_and_pinned_chunk_consumer`进入。当前只说明职责、固定快照及错误报告机制，未做本人逐步调试、复写或追问；ready不代表已完成检索。

当前Spec0021–0027输入/成对编码/项目凭证及监督验收已接线；Spec0026新增55离线/1266全量通过，真实embedding-3两次HTTP200得到2文档+1查询的2048维向量/服务91tokens，仅属编码工程证据。用户继续开发，Lesson8完整课堂暂挂；监督/持久检查点的职责与结果已说明，尚未本人走读、独立调试或复写。代码入口validation/encoding_check.run_check→encoding_worker.run_job/ObservedDense→check_report.Ledger，对应test_actual_sdk_sparse_and_parent_reports与test_real_blocking_child_is_killed_reaped_and_keeps_dense_usage。M4.1资料包首片已实现/接线：91新增/1357全量通过，独立进程重载；M4.2实施及唯一开发下一步见下文。学习随用户安排恢复。

M4章节地图（计划，尚未完整课堂走读）：

2026-10-15 [Spec0034：M4.7显式移除](../specs/0034-m4-document-removal.md)已实现/接线，切片160 passed in40.56s（78新增），全量1780 passed in201.57s。阅读入口IngestionPipeline.remove_document→_document_bundle/profiles_match/project_detail→_audit_base→_build_and_activate→_activate_existing→RemovalReceipt；与run变化分支共用构建链，失败不在外层重包覆盖阶段/用量/提交状态。确定性入口test_remove_one_document_preserves_sources_and_old_indexes、test_removed_source_is_added_by_next_explicit_ingestion、test_commit_uncertain_requires_catalog_readback；原生test_native_removal_preserves_old_version_and_existing_consumer[normal/zero/all-empty/mixed]。职责/结果已说明，完整课堂暂挂，本人独立调试/复写未评估。唯一开发下一步梳理M5查询链并写M5.1 Spec。

2026-10-15 [Spec0033：M4.6](../specs/0033-m4-ingestion-and-updates.md)已实现/接线/本地验收：新增86、全量1702 passed in 170.29s。阅读入口IngestionPipeline.run→plan_ingestion→复用分支/全库prepare→BatchProcessor→BundleStore/两路build→activate→IngestionReceipt；失败看IngestionJobError的当前报告、候选ID和激活状态。确定性入口test_first_ingestion_and_repeat_skip_encoding_and_builds、test_update_merges_history_and_replaces_current_l1、test_successful_encoding_is_retained_on_real_revision_race、test_commit_uncertain_is_not_claimed_as_rollback；原生入口test_public_pipeline_restart_reuse_and_existing_chunk_consumer[normal/zero/all-empty/mixed]。职责/结果已说明，完整课堂暂挂，本人代码走读/独立调试/复写未评估。唯一开发下一步M4.7显式移除Spec。

2026-10-15 [Spec0032：M4.5](../specs/0032-m4-document-management.md)已实现/接线/本地验收：新增84/全量1616 passed in 148.35s。阅读入口DocumentManager.list_documents/get_document_detail→_document_bundle→IndexCatalog.read/BundleStore.load→document_views.project_list/project_detail；核心是一次快照与跨调用revision门禁。对应test_activation_during_read_does_not_mix_versions[list/detail]、test_broken_index_does_not_hide_document_snapshot[chroma/bm25]、test_native_activation_metadata_read_and_id_consumer[normal/zero/all-empty/mixed]。已说明职责与验证，完整课堂暂挂，本人走读/独立调试或复写未评估。唯一开发下一步M4.6重复摄取与文档更新Spec。

2026-10-15 [Spec0031：M4.4](../specs/0031-m4-same-version-activation.md)已实现/接线/本地验收：89新增/1532最终全量通过。代码入口DocumentManager.activate/open_active→IndexCatalog.write/current/publish/read；IndexVersion/ActiveVersion为固定绑定。真实三产物跨进程与历史修订、busy/冲突、提交不确定/读IO有测试，入口test_activate_repeat_reopen_and_fixed_identity、test_actual_revision_preserves_historical_l2_and_old_snapshot、test_native_three_artifacts_activate_and_restart及test_process_lock_and_stale_revision_without_sleep。已说明职责和验证，完整课堂暂挂；本人复写/独立调试未评估。唯一开发下一步M4.5只读文档列表/详情Spec。

2026-10-15 [Spec0030：M4.3](../specs/0030-m4-bm25s-storage.md)已实施：54新增/1443最终全量通过；真实M3词项→BM25保存/另进程重开，空/正常分支有接线证据。入口BM25Store._prepare→bm25_backend.statistics，BM25Indexer.build→_load_index→load_native/audit_model；test_bm25_store的test_build_reload_repeat_and_identity、test_empty_rows_preserve_mapping，test_bm25_integrity的test_hand_scoring_matches_persisted_model和test_invalid_npy_rejected_before_native_allocation，test_bm25_native的test_formal_sdk_encoding_native_save_reload。已说明职责/分支，完整代码课堂暂挂；本人独立调试/复写未评估。开发下一步M4.4激活Spec；scope统计留到M5明确。

2026-10-15 [Spec0029的M4.2](../specs/0029-m4-chroma-index.md)已实现：32新增/1389全量通过，同进程共享.env、完整Chunk跨进程回读。源码入口storage/chroma_index.py的VectorUpserter.build→_check_rows及ChromaStore.audit/get_by_ids，SDK边界在chroma_backend.open_collection。确定性入口test_chroma_index.py::test_formal_roundtrip_repeat_and_isolation及test_write_failure_stops_batches_and_no_ready；原生接线test_chroma_native.py::test_real_formal_encoding_store_and_new_process。已说明职责/配置与失败边界，完整课堂继续暂挂，不登记本人独立掌握。当前开发下一步见上文M4.3段及handoff。

| 章 | 主题／预计小节 | 当前入口与学习证据 |
|---|---|---|
| 1 | 原文与派生产物绑定、资料包身份／2–3 | storage/artifact_bundle.py的prepare_index_bundle/IndexBundle.__post_init__；已说明职责，本人复写/调试未评估 |
| 2 | 文件写入、发布、重载和失败／3 | storage/bundle_store.py的save/load；test_actual_sdk_sparse_and_new_process_reload、test_short_write_cannot_publish_an_incomplete_bundle；工程已验，本人掌握未评估 |
| 3 | Chroma与BM25S同版本索引／按后续Spec | M4.2/M4.3持久化及M4.4共同激活/重开已接线验收；完整课堂暂挂 |
| 4 | 活动版本、更新/历史与文档管理／按后续Spec | Spec0031激活/固定版本重开已验；列表/详情/更新/移除仍分片，完整课堂暂挂 |

M3.1实际阅读入口：core/encoding_settings.py→encoding/input_preparer.py→encoding/validation.py，对应test_encoding_settings/test_encoding_inputs/test_encoding_validation；输入输出、分支、断点与变量产生时点见Spec0021验收段。已说明原文/检索文本/Embedding前缀分开、index恢复、未知usage保留；本人走读和调试尚无证据。

M3.2入口：[DenseEncoder.encode_batch](../../naiyue_rag/encoding/dense_encoder.py)→[OpenAICompatibleEmbedding.embed](../../naiyue_rag/encoding/openai_embedding.py)→[BoundedTransport/_BoundedBody](../../naiyue_rag/encoding/bounded_transport.py)→既有规范化。实际Debug Test节点、参数ID、故障抛出/捕获与WATCH在Spec0022第7节；先走test_actual_dense_path_preserves_source_and_reorders_indices[query]，再看超大错误正文[absent-500]。本人完整走读/复述尚未观察，不登记独立能力。

M3.3首片入口：[SparseEncoder.encode_batch/query_terms](../../naiyue_rag/encoding/sparse_encoder.py)→[SparseTokenizer.tokenize](../../naiyue_rag/encoding/sparse_tokenizer.py)→[SparseRecord](../../naiyue_rag/core/sparse_types.py)。Spec0023第8节列正常TF/空词项/cache读写失败和真实M2的测试节点、断点/栈帧/WATCH；从test_real_terms_tf_query_dedup_prefix_and_roundtrip走8词/7唯一词与查询去重，再看缓存禁止fallback。职责与数据结构已说明，本人走读/复写/追问未评估。

M3章节地图（计划，不登记已学完）：

| 章 | 主题／预计小节 | 当前真实参考入口 |
|---|---|---|
| 1 | 输入表示、来源和身份／2–3 | 已实现EncodingSettings、input_preparer、M2 ChunkRefiner；Spec0021测试 |
| 2 | Provider协议、向量和usage／3 | 已实现DenseEncoder/OpenAICompatibleEmbedding/BoundedTransport/normalize_embedding_response；Spec0022测试 |
| 3 | 中文词项、批次完整性／2–3 | 正式Sparse/BatchProcessor及成对结果/报告已接线；Spec0023/0024测试，参考作为对照 |
| 4 | 正式查询结果、真实服务证据／2–3 | QueryEncoder/QueryEncodingResult已离线接线；Spec0025/0026测试入口；验收worker已接线/真实2请求，小样本监督与生产任务边界分开 |

当前已说明职责、串行/部分失败与分词差异；参考局部模拟和既有127测试不替代M3本人走读或独立掌握。

关系学习入口：[prepare_knowledge_base](../../naiyue_rag/ingestion/knowledge_preparation.py)→[build_document_relations](../../naiyue_rag/ingestion/document_relations.py)，预计3–4小节：文档登记/版本、原生语法与实际位置、精确配对/冲突、批次异常与接线。对应[关系测试](../../tests/test_document_relations.py)与[批次接线测试](../../tests/test_knowledge_preparation_wiring.py)，精确参数ID/断点/变量产生时点/故障入口见Spec0019第10节。仅范围与机制已说明，未做本人源代码走读或调试；没有独立掌握证据。

规则准备学习入口：[prepare_document→ChunkRefiner.transform→MetadataEnricher.transform](../../naiyue_rag/ingestion/chunk_preparation.py)，预计2–3小节：原文/派生视图与指纹、事实元数据与冲突、异常传播与跨层测试。对应[规则测试](../../tests/test_chunk_preparation.py)、[接线测试](../../tests/test_preparation_wiring.py)，精确参数ID/断点/故障注入见Spec0018第7节。已说明范围与两份文本的机制，未观察本人调试或复写；不称为已掌握。

M2后续学习入口：[scan_document](../../naiyue_rag/ingestion/markdown_structure.py)→[DocumentChunker.split_document](../../naiyue_rag/ingestion/document_chunker.py)，对应[结构测试](../../tests/test_markdown_structure.py)/[Chunk测试](../../tests/test_document_chunker.py)/[配置加载跨层测试](../../tests/test_chunking_wiring.py)。学习状态仅已讨论结构与业务单元保护思想，未逐行走读或本人调试，不提前记独立能力。具体实验指标定义与脚本入口见Spec第7节。

M1学习入口：[MarkdownLoader.load_all/load](../../naiyue_rag/ingestion/markdown_loader.py)及[单文件测试](../../tests/test_markdown_loader.py)、[跨层加载测试](../../tests/test_markdown_loader_wiring.py)。预计3–4小节：原文字节与Document合同、ID/版本与重复来源、文件/目录异常及副作用、与M2交接。优先走test_update_retains_id_and_changes_version，再比较非法编码/批次失败；教学原文为合成/结构样本，未收取本人调试结果，不提前写完成笔记。

章节继续沿M0–M9主线，规模随职责调整，不承诺工期，测试Agent与RAG共享投入。以下早期路线及时间记录保留为历史，不作为当前下一步。

## 历史初始路线

初始记录：2026-10-10，组件与A1/A2/A3/B0/B1实验已运行；完整产品RAG核心/知识库Agent尚未实现。总体目标见[ADR0004](../decisions/0004-knowledge-agent-goal-and-boundaries.md)。

| 顺序 | 主题与将来阅读入口 | 要能解释的问题 | 课堂证据 |
|---|---|---|---|
| 1 | 系统边界、一个文档查询例子；本计划与首期 Spec | 摄取与查询的输入输出，证据与答案的区别 | 本人复述主流程 |
| 2 | Markdown 解析和可定位切分；首个源码入口与测试 | 原文行号、标题、片段 ID 从何而来，更新后怎样定位 | 逐行读核心函数、改一条切分测试 |
| 3 | 首条召回与结构化证据；查询入口与索引实现 | 候选如何产生与排序，范围/空结果/异常如何区分 | 手算小例子，追一条查询调用链 |
| 4 | 固定评测与最小追踪；标注与评测代码 | 片段级 Recall@k 的分子分母，失败归因和可重复性 | 自己标注与计算一题 |
| 5 | Embedding 与向量检索 | 文本如何成为向量，相似度、维度、模型与索引版本如何匹配 | 手算两维相似度，对照一条真实运行 |
| 6 | BM25、RRF、重排与预算 | 各阶段改变了什么，何时收益或退化 | 手算词项与 RRF，固定集单变量对照 |
| 7 | PDF/网页与生命周期 | 页码/URL 定位、重复摄取、更新/删除和多存储一致性 | 样本断言与故障注入 |
| 8 | 可选问答与对外适配 | 引用存在和主张支持为何不同，Agent 如何消费证据 | 引用校验与无答案问题复盘 |
| 9 | 知识库Agent独立上下文与四场景 | 主任务与知识目标、输入输出、探索历史与交接结果怎样分开 | 对照一次直接检索与委托，复述职责 |
| 10 | Self-RAG启发的反馈与停止 | 材料相关为何不等于主张支持，具体缺口如何决定下一动作 | 审核支持/不支持样例，调试补查与预算终态 |
| 11 | 生产验证与管理模块 | 更新/恢复/范围/追踪怎样接线，Dashboard与MCP怎样消费同一核心 | 故障注入、真实客户端及阶段验收 |

参考完整模块地图见[目标架构](../research/target-architecture-and-module-map.md)。原Self-RAG训练/特殊token解码与本项目思想适配区别见[定向调研](../research/self-rag-2026-10-10.md)。本轮只确认准备学习与建设，没有新课堂、用户复述/独立复写或面试掌握证据。

阅读真实代码时，先看调用方和实际输入输出，再看被调用函数、状态、副作用和失败路径；复杂语法代入具体值展开。每课在 `lessons/` 记录读到的函数与行、疑问、待复习点和用户练习结果。功能“已实现/已接线/已验证”与学习“已讲解/引导后理解/独立实现/可应对追问”分开登记。用户说“懂了”只记录自述理解。

第一小课只建立主流程和边界；源码逐行教学从第一个已确认切片及其测试开始。

## 当前真实代码入口

Spec0001已经执行，34项测试通过。读取顺序：[load_sources](../../experiments/markdown_probe.py#L20) → [split_candidate](../../experiments/markdown_probe.py#L83) → [map_exact_source](../../experiments/markdown_probe.py#L67) → [inspect_document](../../experiments/markdown_checks.py#L34) → [run](../../experiments/markdown_probe.py#L183)。这些是实验工具，不是RAG产品调用链。

此前准备map_exact_source一个函数的讲解：TC-02源行194字符，实际映射字符[1036,1230)、第20行；空、无法匹配及重复文本路径分别返回unmapped/ambiguous。用户已明确当前先选型、不读代码，复述检查暂停。尚无用户复述、改动、复写或独立实现证据；不能将实验完成记为课堂掌握。

Spec0002已有Embedding接入工具及真实2请求，合计82项离线测试通过。未来阅读入口为[run](../../experiments/embedding_probe.py#L280) → [supervise](../../experiments/embedding_probe.py#L211) → [run_worker](../../experiments/embedding_probe.py#L151) → [send_embedding](../../experiments/embedding_probe.py#L105) → [validate_vectors](../../experiments/embedding_probe.py#L60)/[validate_usage](../../experiments/embedding_probe.py#L84) → [cosine](../../experiments/embedding_probe.py#L129)。本轮仅报告三条合成文本的维度、usage及余弦算例；未逐行讲解，不登记引导后理解、独立实现或面试掌握。

[本轮方案调研](../../research/naiyue-rag-knowledge-base/report.md)可用于区分知识库、RAG、图谱、模型和MCP职责。该资料已整理不代表用户已掌握；课程先从一份Markdown如何形成可定位证据开始，图谱留到有关系问题与对照实验时。

Spec0003已有独立生成探针；66项新增测试、合计148项通过，3次真实请求的失败/修正/通过均有记录。未来阅读顺序：generation_probe的run → supervise → run_worker → build_request/send_generation → validate_response/validate_extraction → assess_extraction → build_report。具体函数见源码；这是合成接口实验，尚非LightRAG调用链。本轮没有代码课堂、用户练习或独立实现证据，维持“先选型、不读代码”。

Spec0004公共证据实验已实现/接线/离线验证，43项新增测试、总计191项通过。未来阅读顺序：[corpus_probe.run](../../experiments/corpus_probe.py#L39) → [build_units](../../experiments/evidence_units.py#L180) → [scan_source](../../experiments/evidence_units.py#L31) → 旧split_candidate C2/map_exact_source → [adapt_cases](../../experiments/evidence_units.py#L116) → make_unit/[render_unit](../../experiments/evidence_units.py#L11) → [build_report](../../experiments/corpus_probe.py#L15)。实际TC-02正文仍在第20行/[1036,1230)，上下文分别为标题第1行、维度第11行、表头第17行、说明第13–15行，渲染727字符。仅作为可读结果例子，没有代码课堂、用户复述/复写/练习或独立实现证据；保持选型阶段暂停逐行教学。

Spec0005 A1已实现/接线/真实模型及重放验证；60项新增测试、总251项通过。未来阅读顺序：[vector_probe.run](../../experiments/vector_probe.py#L49) → [load_corpus](../../experiments/vector_index.py#L48)/load_queries白名单 → [supervise](../../experiments/vector_embedding.py#L141)/[run_worker](../../experiments/vector_embedding.py#L98) → write_index/[load_index](../../experiments/vector_index.py#L150) → [search](../../experiments/vector_index.py#L197) → [pack_evidence](../../experiments/vector_index.py#L211) → [evaluate](../../experiments/vector_eval.py#L81)。真实Q01 E01排19/E03排14，均进入候选但未返回；E05–E08在前20外。用于区分召回与预算失败，未给用户逐行课堂/复述或独立实现登记；继续暂停代码教学。

[Spec0006 A2](../specs/0006-a2-bm25-rrf.md)已实现/接线/离线对照与重放验证，43项新增/294总测试通过。未来阅读顺序：[hybrid_probe.main](../../experiments/hybrid_probe.py#L257)/[run](../../experiments/hybrid_probe.py#L167) → 原A1重算/校验 → [Tokenizer.tokenize](../../experiments/keyword_index.py#L43)/[pool_data](../../experiments/keyword_index.py#L72) → [build_index](../../experiments/keyword_index.py#L91)/write_index/load_index → [keyword search](../../experiments/keyword_index.py#L180) → [fuse](../../experiments/rank_fusion.py#L7) → 原pack_evidence/evaluate。Q01 E01 dense19/BM254→RRF9新返回；E08虽BM2520但RRF24排出融合前20。可用于解释召回与融合的取舍，尚未逐行教学/复述/手算或独立实现考核。代码课堂仍暂停，不创建完成笔记或登记本人掌握。

[Spec0007 A3](../specs/0007-a3-explicit-relations.md)已实现/接线/离线对照和重放；43新增/337总测试通过，当前质量退化。未来阅读顺序：[relation_probe.run](../../experiments/relation_probe.py#L139) → [baseline_recompute](../../experiments/relation_probe.py#L37) → [build_index](../../experiments/relation_index.py#L58)/write_index/load_index → [expand](../../experiments/relation_index.py#L189) → [build_route](../../experiments/relation_retrieval.py#L12)/[score_all](../../experiments/keyword_index.py#L187) → [combine_routes](../../experiments/relation_retrieval.py#L47)/pack → [check_evaluation](../../experiments/relation_probe.py#L68)。Q01关系找到了拆分/命名文档，最终仅返回E06/E07并失去原E01/E02/E04；可说明可达性/召回/排序/预算是不同机制，不由“加关系”推断收益。三跳不当两跳、反向原出处及bool不能冒充原行号等有工程回归，尚未代码课堂/本人复述、手算、调试或独立实现考核；继续暂停教学记录。

[Spec0008 B0](../specs/0008-lightrag-b0-cache-wiring.md)已实现/接线/真实SDK离线对照及重放，31新增/368总测试通过。未来阅读顺序：[lightrag_probe.main/run](../../experiments/lightrag_probe.py) → [make_payload](../../experiments/lightrag_mapping.py)（原源/52单元/范围）→ [run_scope/supervise](../../experiments/lightrag_runtime.py)（venv入口/子进程截止）→ [worker.execute/Callbacks.chunk/embedding](../../experiments/lightrag_worker.py)（普通闭包避免SDK deepcopy owner、C!、缓存）→ audit/flush/finalize → 新进程audit与aquery_data/原生raw → map_results/pack → 所有检索后evaluate。SDK172源码RECORD/实际正文与float32向量核验，四题候选/返回及指标与A1相同；能用于解释框架接线与质量收益的区别。代码课堂仍暂停，尚未逐行讲解/本人复述/手算/独立实现/追问考核；不创建完成笔记。下次选型先制定B1模型抽图和关键词调用Spec。

[Spec0009](../specs/0009-lightrag-b1-model-graph.md)是B1设计审阅。助手本轮沿1.5.7源码读到extract_entities→use_llm_func_with_cache→EXTRACT JSON/parser/merge-summary、aquery_data mix→KEYWORD→原查询/高低关键词Embedding→实体关系原文→round-robin。后续核心课题先区别“来源FK存在”与“关系被原文支持”，再读新回调值怎样往返；设计时尚无B1函数，部分实施现状见下记录；尚无真实原生抽图或课堂进度，未登记本人理解/独立实现。

B1部分代码已出现：[graph_transport](../../experiments/graph_transport.py)→[Journal/GraphCallbacks](../../experiments/graph_callbacks.py)→[execute/audit](../../experiments/graph_worker.py)。助手测试推进到真实SDK＋模拟provider的build/query，replay配置边界仍红，完整入口尚无；不是已讲解或本人已掌握。当前停止源码调试，待修原失败集成测试后继续选型实验，仍不登记课堂/独立实现结果。

B1当前实现/接线/工程复核/重放完成（410 tests），质量无收益且Q02退化。未来阅读顺序：[graph_probe.prepare/run/assess](../../experiments/graph_probe.py) → [共享/父/worker配置校验](../../experiments/graph_transport.py) → [Journal.request/_request/终态提交](../../experiments/graph_callbacks.py) → [execute/角色闭包/原生parser](../../experiments/graph_worker.py) → vector_pool/audit（同文本多实际响应及request绑定，不放宽容差）→ map_native/pack/evaluate。可用真实问题讲解“语义hash与物理响应身份”“图来源与最终证据的区别”：Q01 E06/E08图source登记但没进mix前20；Q02部分必要source登记但未返回。当前没有逐行课堂、复述、独立复写/调试或追问考核；继续暂停本人掌握记录。

## Spec0010：第一次可调用查询（已实现，逐行课待开展）

实际46新增/456总测试通过；阅读顺序：[包导出](../../naiyue_rag/__init__.py)→[load_snapshot/A2Snapshot](../../naiyue_rag/a2_snapshot.py)→[retrieve_once](../../naiyue_rag/retrieval.py)→_validate_request/resolve_scope/verify_current→_embedding→旧Dense/BM25→fuse→pack_evidence→返回证据与trace。原四题使用真实旧向量精确一致，新问题是假回调工程验证，不记为真实语义效果。

本轮简述了“先校范围再适配向量→两路排序→融合→预算证据”的输入输出，尚未逐行讲新函数或收取本人复述/复写。下一小课只追一条query，并对比越界scope在回调前拒绝；课堂/练习证据随后真实记录。Agent底座建议见[取舍](../research/knowledge-agent-runtime-options.md)，尚未安装/实测知识库Agent框架。

## Spec0011：向量数据库实际接线（已实现，小课待开展）

阅读顺序：[chroma_probe.main/run](../../experiments/chroma_probe.py)→既有源/向量加载→[launch_worker](../../experiments/chroma_probe.py)与既有supervise/受控环境→[worker.execute](../../experiments/chroma_worker.py)→[ChromaStore初始化/upsert](../../naiyue_rag/chroma_store.py)→进程重启后的get/audit→query→原BM25/fuse/pack→最后标签评价。重点读源码函数，不把数据库原生结果或引用存在当业务正确。

唯一下一小课只读ChromaStore.query：输入向量/scope/exclude/k→授权与请求交集减排除→where检索→按ID/正文/版本/完整元数据绑定→距离与cosine→返回候选。具体练习考虑“允许A、B文档，仅问A，如何限制召回”；尚未逐行讲解、复述、独立复写或追问验证。此前用户回答历史用例适用性应由Agent判断，只记引导后回答，不记独立实现。reset异常回归可用于后续区分预期拒绝与IO失败。

### 小课进度：检索前确定范围（2026-10-10）

本轮讲解到ChromaStore.query第186–202行：worker提供缓存向量及任务范围→检查scope存在/合法/未越界→None取允许清单、显式scope取请求清单→减exclude→空池返回或向SDK传where。展开集合子集与条件表达式；用A/B/C教学例子解释检索前过滤和全库top-k后过滤的差别。对照当前SDK的Collection.query→客户端_query→Rust bindings.query确认where实际下传，未讲ANN内部过滤算法。

本轮仅范围契约命令实际7 passed/24 deselected（SDK测试替身），不代替原生检索质量验证；业务代码未改。理解检查待用户回答，暂不写已确认理解或独立实现；本课正文笔记在确认后写入docs/1.0/lessons/。下一步先核对范围计算复述，再读结果原文绑定，不同时扩展新功能。

随后用户回答“B”，与None采用A/B、排除A后allowed={B}一致。已写[Lesson 1](lessons/lesson-1.md)，只登记本题引导后回答正确，其他边界复述/独立复写未验证。下一小课沿query第212–213行→_bound_unit第156–160行→初始化_records第75–79行，关注原文/元数据绑定；距离转换与排序留到后续。原文绑定理解检查待答。

用户对正文不一致回答“丢弃”，可确认其认为异常证据不应使用，尚不能确认理解是单条跳过还是整次失败。补充追到fail→RetrievalError→query原样raise→worker status=error/退出2；当前实现整次失败且不返回部分候选。下一检查只确认这一异常路径，暂不进入距离/排序，不登记独立实现或完整理解通过。

随后用户明确回答“整次报错”，与当前异常路径一致；已写[Lesson 2](lessons/lesson-2.md)，只记该引导题正确，其他条件/独立复写未验证。下节读query第214–219行：距离检查→score=1-distance→reference_similarity=max(0,1-distance/2)→分数降序/ID打破并列→rank；区别分数尺度与相关概率。已只读既有正式run的cosine配置和首条记录，非新原生请求；分数计算理解检查待答。

2026-10-11用户回答“0，0.5”正确，已写[Lesson 3](lessons/lesson-3.md)，仅记引导后计算。下一小课从chroma_probe.compare中的两路候选→rank_fusion.fuse，讲1/(60+rank)、按unit_id累加、缺路贡献0及融合排序。使用既有test_rank_fusion的a/b/c合成测试输入，实际fuse输出a=.03252247/b=.01639344/c=.01612903，非真实文档质量结果；本轮对应已有测试1 passed，原实现未改。RRF是否使用原始分数的理解检查待答，未登记独立实现。

用户回答“不会”正确，已写[Lesson 4](lessons/lesson-4.md)，只登记排名不变时RRF分数不变的引导理解；retrieval_info原分数仍改变。下一小课读vector_index.pack_evidence第211–244行→render_unit：完整块包括检索前缀/来源/上下文/正文，按候选顺序贪心装入字符预算，放不下记录budget_excluded并继续。实际长度演示A120/B100/C60、预算200输出A/C/182字符，教学构造文本不是真实原文；已有完整用例预算测试本轮1 passed。预算分支理解待答，尚未独立实现。

用户回答“尝试C”正确，已写[Lesson 5](lessons/lesson-5.md)，仅登记该引导分支判断。五次小题已分别作答，不等于整体独立实现。接下来串联chroma_probe.run→worker.query→compare中的BM25/fuse/pack，按召回/融合截取/预算三个阶段解释证据缺失；当前问题向量仍取缓存，retrieve_once仍为文件快照，不能把图示说成知识库Agent已接Chroma。综合复述待答，后续动态查询接入先Spec再实现。

用户随后表示“这里我已经理解了”，不再追问E题；记录为整体自述理解，综合复述未收取，不升级为独立实现/面试能力。当前五节课收尾，下一片见[Spec0012准备稿](../specs/0012-live-query-embedding-preparation.md)，先核真实新查询适配、SDK依赖与接口，不立即加Agent循环/重排。后续讲解从现有embed_query回调值往返开始。

2026-10-11用户要求先梳理参考模块、按模块持续开发，学习和实现顺序改随project-plan的M0–M9主线。Spec0012暂停，暂不继续模型SDK接入；前五节局部理解记录保留。下一课在M0模块Spec中明确数据契约/配置的真实消费者，再接Loader和Chunker；模块代码尚未生成，不预填本人掌握。

主线随后获认可，参考优先骨架与Markdown/Agent/业务差异明确。下一课随Spec0013读输入源/片段字典如何映射Document/Chunk/SourceSpan，QueryRequest与RetrievalResult如何保持公开兼容；该代码尚未创建，先看设计位置，不提前写成已讲解/独立实现。YAML配置与追踪为M0后续片，不跳模型接入。

Spec0013现已授权实现：48新增/541总测试，core/types.py5类真实用于A2Snapshot/retrieve_once。代码阅读顺序：retrieval._validate_request→QueryRequest.from_dict→dataclass构造/__post_init__→to_dict；随后A2Snapshot中的Document/Chunk/SourceSpan→canonical_units，再读_contract_rows中的RetrievalResult。内部键序标记compare=False保持值相等；可用实际红灯说明业务值与序列化桥接的区别。下一小课只走一条请求，不同时讲全部类型；本轮尚未逐行课堂/本人复写或独立实现，不提前创建lesson-6完成记录。

### M0小课：QueryRequest入口契约（2026-10-11）

沿retrieve_once第63行→_validate_request第16行→QueryRequest.from_dict第206行→dataclass生成初始化/__post_init__第186行→to_dict第211行展开一条合成请求。说明cls(**data)的参数展开、类型注解与显式运行时检查的区别、两处列表防御复制，以及对象可变时to_dict再次校验。转回字典用于兼容现有算法消费者，不改变公开接口；授权范围仍由resolve_scope处理。非法candidate_k在Embedding前抛request/invalid_candidate_k，无自动重试。

本机合成演示：输入scope追加MOCK-CASE-002后对象仍仅MOCK-CASE-001；输出exclude追加MOCK-CASE-003后对象仍为空；candidate_k字符串"20"被显式检查拒绝。实际命令`.venv/bin/python -m pytest -q tests/test_core_types.py::test_request_copy_and_roundtrip`输出1 passed in 0.04s。未改业务代码或调用模型，单条契约测试不代替全量回归/业务质量验证。理解检查尚未作答，暂不建lesson-6完成笔记，不登记独立实现或面试能力。下一步只确认类型注解与__post_init__的职责，再衔接M0配置Spec。

随后用户回答“是post_init里的显式检查，继续吧”，正确，已写[Lesson6](lessons/lesson-6.md)。只登记本题引导后理解，其他边界复述/独立实现未验证。现准备[Spec0014](../specs/0014-m0-settings-loading.md)：YAML→分组Settings/from_dict/validate→12字段兼容桥→原load_snapshot→现有查询，授权参数独立传入。参考按固定commit核实，路径/严格解析/安全错误和仅已用字段的差异待确认；未创建配置源码/测试或改真实运行配置，下一课堂在实现验证后讲配置值怎样到达真实消费者。

用户随后调整首期权限范围：内部共享知识库，全库默认可检索，新配置入口不要求授权清单；scope/exclude仅筛选任务内容。Spec0014已修订为load_snapshot_from_settings(settings_path)，内部从已校验源取得全部ID兼容旧load_snapshot。上述“授权参数独立传入”是此前提案，已被新决定替代；教学旧接口事实/旧测试保持，不把检索过滤讲成已实现的用户权限系统。本轮只修设计，未实施或新验证配置功能。

Spec0014随后获“继续”授权并完成：56新增/597全量，core/settings.py加载/冻结分组/严格校验/路径解析，bootstrap新入口真实装配全库11源/52单元并调用原检索。阅读顺序：[bootstrap.load_snapshot_from_settings](../../naiyue_rag/bootstrap.py)→[settings.load_settings](../../naiyue_rag/core/settings.py)第154行→Settings.from_dict/validate_settings→配置文件目录作为资源路径基准→to_snapshot_config→原load_snapshot。已有字典公开接口保持；仅离线旧缓存，无新模型/真实私有材料。下一小课只解释配置值如何到达消费者，暂不创建Lesson7或登记理解/独立实现；随后补M0最小追踪。

### M0配置小课进度（2026-10-11）

本轮只走bootstrap第15–16/26行→load_settings第158/169–177行→_resolve第149–151行→to_snapshot_config第90–96行。用已有测试的config/local.yaml、dataset=../materials、vector_run=vectors、cache=cache说明两层基准：相对配置文件参数先按cwd定位；文件内部资源相对source.parent定位。换cwd仍访问同一配置时资源含义不变，换cwd后随意使用同一相对配置参数则不保证同一文件。展开条件表达式/Path拼接及冻结对象replace：创建新分组和Settings，不直接改原对象。解析路径不创建目录或证明资源存在，资源加载负责核对。

实际已有路径测试本轮1 passed in0.16s，命令`.venv/bin/python -m pytest -q tests/test_settings.py::test_relative_resource_paths_follow_config_directory_not_cwd`。未改业务代码或运行模型，测试仅临时合成配置；不当新端到端/质量/全量回归。理解题待答，正式Lesson7待确认后写，不登记独立实现。唯一下一步先确认配置内部路径的基准，再准备M0最小追踪Spec。

用户随后回答“/tmp/rag-demo/config/vectors，继续吧”正确，已写[Lesson7](lessons/lesson-7.md)，仅该题引导后路径判断。当前准备[Spec0015](../specs/0015-m0-minimal-tracing.md)，助手只读参考TraceContext/TraceCollector→MCP成功/异常收集→Dashboard TraceService读取；当前原查询仅七阶段列表，失败缺完整报告/关联ID。新追踪/收集模块尚未创建，不预填学习或功能通过；先讨论安全报告与观测写失败行为。

Spec0015用户明确接受策略并授权实现，现63新增/660全量通过。实际阅读顺序：[tracing.retrieve_with_trace/_persist](../../naiyue_rag/tracing.py)→原[retrieve_once.record/failed](../../naiyue_rag/retrieval.py)→[TraceContext.record_stage/finish/to_dict](../../naiyue_rag/core/trace_context.py)→[TraceCollector.collect](../../naiyue_rag/core/trace_collector.py)→JSONL重读；只先讲结果与追踪存储两个终态的控制流，之后再讲计时和安全字段。旧七阶段/usage扩展兼容，报告仅token白名单；两个实际回归红灯可用于后续说明值相等与类型合法的区别、源码错误码与观测目录的对应。当前未逐行课堂/本人复写或追问，不创建Lesson8完成笔记；下一课后准备M1 Markdown加载Spec。
