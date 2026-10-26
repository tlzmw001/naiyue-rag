# HKUDS/LightRAG 静态深验

- 日期：2026-10-09（用户工作区日期）。
- URL：https://github.com/HKUDS/LightRAG
- 分支：main；commit：`453dce83d6d0354a06e46c8d4029a0895c4e054b`。
- 证据根：`research/naiyue-rag-knowledge-base/clones/lightrag/`；下面源码路径相对此根。
- 许可证 MIT，`LICENSE:1-21`、`pyproject.toml:12-20`。本轮没有复用业务源码。
- 仅静态深验；没有安装、跑测试、摄取或模型调用。`deep_verified=true` 不等于 runtime 通过；`live_verified=false`。

## 问题与交付形态

README:263-271 自述为把图与向量结合的轻量框架，并支持增量/选择性删除。这轮验证的是开源 Python 库和 REST 接线，不使用 README 的“高质量/快速”作为我们语料的效果结论。Python >=3.10，`pyproject.toml:23-54` 核心依赖含 aiohttp、nano-vectordb、networkx、numpy、pydantic、tiktoken 等；API optional 依赖还含模型 SDK、服务和解析组件。

## 摄取真实调用链

1. `lightrag/lightrag.py:2272-2377`：insert → ainsert。输入是字符串/字符串列表，可传 ids/file_paths。ainsert从配置解析固定token参数快照，再调用入队/处理。默认实现为固定token，SDK convenience入口不提供R/V/P/C选择参数。2026-10-09补充核验：ainsert注释宣称一律F，但pipeline.py:1004–1006未传process_options生成空选项，:5500–5545无选择器分支可以调用自定义chunking_func；此前“SDK一律固定F”的表述过强。通过入队/处理接口显式选择C可使用自定义回调，显式F/R/V/P则绕过它。仅静态追踪，未运行这些分支，见[摄取组件比较](../../../docs/research/markdown-component-experiment.md)。
2. `lightrag/pipeline.py:740-814,1053-1128,1248-1344`：验证输入、规范来源、计算 ID/content hash，写 full_docs 和 doc_status，再排入处理。给 ids 则使用 ids；已知来源默认以规范 basename hash 作为文档 ID，否则正文 hash。同来源或相同正文会记录重复；这不是“同名文件改正文自动覆盖”。
3. `pipeline.py:4991` 的 process_single_document 是实际文档处理函数，读取内容和持久化的 chunk_options，分派切分策略；`:5545-5693` 对输出校验、按 embedding token 限制硬切分并在有 blocks sidecar 时回填 provenance。
4. `lightrag/utils_pipeline.py:144-202` 的 build_chunks_dict_from_chunking_result 保留 chunk 字段，加入 full_doc_id/file_path/llm_cache_list；优先 doc_id 前缀的显式 chunk_id，否则 chunk_order_index，碰撞时再 hash。内部 `_source_span` 在写存储时去掉。
5. `pipeline.py:5693-5752` 同时写 doc_status PROCESSING、chunks_vdb 和 text_chunks，随后 _process_extract_entities。可用 process_options `!` 跳过 KG，保留向量片段（服务/低层 pipeline 路径）。
6. `lightrag/lightrag.py:3762-3779` 调用 `lightrag/operate.py:3942` 的 extract_entities；它从 `global_config['role_llm_funcs']['extract']` 取模型，并逐片段提取实体/关系。`:4094-4140` 用正文和可选 heading breadcrumb 组 prompt；来源 chunk_id/file_path 保留在结果。默认建图需要 LLM，不只是向量化。
7. `pipeline.py:5804-5836` 调 `operate.py:3514` 的 merge_nodes_and_edges；它组合抽取结果，借 keyed lock 处理实体/边，更新图、实体/关系向量及 full_entities/full_relations/entity_chunks/relation_chunks 追踪。`operate.py:2429,2782` 是实际 node/edge merge/upsert，下层会总结描述。
8. `pipeline.py:5839-5850` 先 `_insert_done()` 刷新派生存储再写 PROCESSED（后续行）。默认 NanoVectorDB 的 `kg/nano_vector_db_impl.py:455-510` upsert 先缓冲；`:531-704` flush 时批量 embedding，并写向量客户端，再由持久化 callback 保存。不能把所有 upsert 都描述为当场发 embedding 网络请求。

默认存储 `lightrag.py:696-705` 是 JsonKVStorage / NanoVectorDBStorage / NetworkXStorage。`:1804-1900` 根据名称创建类，以 workspace 和 namespace 分开实例，实际创建全文、片段、图和三路向量存储。

## 查询与纯证据出口

`lightrag.py:4876-5113` 有专门的 query_data/aquery_data：复制 QueryParam，设 only_need_context=true、stream=false，然后 local/global/hybrid/mix → kg_query，naive → naive_query。返回 `status/message/data/metadata`，其中 data 包括 entities/relationships/chunks/references，metadata 包含 keywords 与阶段计数。无结果有 failure_reason=no_results，而非法输入/未知 mode 可以 raise，消费者须分开处理。

`operate.py:4693-4806` 的 kg_query：高低层关键词 → _build_query_context → 纯上下文直接 return；常规查询则构造 prompt 并调用 QUERY 角色 LLM（`:4907`）。**query_data 跳过答案生成，不保证完全无 LLM**：`get_keywords_from_query:4975-5003` 没给 hl_keywords/ll_keywords 时调 `extract_keywords_only:5112-5180`，后者通过 KEYWORD 角色 LLM 提取词。如果显式提供非空关键词，可跳过该提取；naive 为片段向量检索。向量和可选 reranker 仍可能使用服务/算力。

`_build_query_context:6075-6197` 实际四阶段：_perform_kg_search → token truncation → merge chunks → build context/raw_data。预算不是只有 QueryParam 字段；truncate/merge 实际消费它们。上下文格式转换 `utils.py:7611-7731` 输出结构化证据。

| Mode | 源码机制 | 与微软 GraphRAG 区别 |
|---|---|---|
| local | 低层关键词向量找实体，再查图节点与相关边/片段 | 实体入口路线相似，不直接证明同算法 |
| global | 高层关键词向量找关系，再查关联实体/片段 | 不采用社区报告 MapReduce |
| hybrid | 两路实体/关系结果轮流合并、去重 | 不等于 BM25 + dense 两路召回 |
| mix | hybrid 图结果再加原始 query 的片段向量召回 | 图和片段向量结合 |
| naive | 仅片段向量结果 | 可作为图方法的基础对照 |
| bypass | 跳过检索，直接答案路径；query_data 返回空数组 | 无证据检索价值 |

证据：`operate.py:5280-5498` `_perform_kg_search` 的实际分支与 round-robin；`:6200-6260` 实体向量查图；`:6529` 关系入口；`lightrag.py:4963-4970` 文档注释与实现互相校核。需注意 local/global 与别的项目同名但语义不同。

## 模型配置、追踪和来源

`examples/lightrag_openai_demo.py:81-91` 给 LightRAG 注入 embedding_func 与 llm_model_func，调用 initialize_storages。`lightrag.py:933-1058,1761-1800` 可注入独立 embedding、LLM、reranker，包装并发/超时；`:1904-1909` 没有 llm_model_func 会报错。操作从 `_build_global_config` 的角色模型集合消费：extract、keyword、query，说明回调被实际调用。用户模型网关的兼容性、用量、费用未知。

status/track_id 对摄取可观察，query_data 有阶段计数、关键词，source_id 关联实体/边与片段。这些是静态接线，不是本机追踪输出。`operate.py:6075-6197` 的 metadata 不等于完整模型计费/trace。

来源定位需要特别校核：

- `utils_pipeline.py:248-262` 将 file_path 规范为 basename，不能自动保留我们想要的项目相对路径唯一性。
- chunk_schema.py:41-82 支持 heading 层级；token_size.py:43-110 可临时跟踪原文 span；pipeline 在 blocks sidecar 存在时回填 provenance。这些能力不能简化成“没有任何定位”。
- 但默认 RAW SDK 链没有保证 Markdown 标题/行区间被解析；`utils_pipeline.py:194` 删除临时 `_source_span`。
- `utils.py:7699-7712` 的最终 chunk 证据字段是 reference_id/content/file_path/chunk_id。内部 full_doc_id/heading/sidecar 与业务版本号、Markdown 行区间没有在此数据出口全部透传。我们需定义自己的证据契约并写序列化测试。

## 更新删除与维护代价

`pipeline.py:1248-1312` 已存在同 basename 被视为重复，即使给了新的正文/不同 ids。普通重复摄取不是就地版本更新。本轮未发现这一入口的原子“新版本替换旧版本”契约，不可声称按 file_path 自动 refresh。

`lightrag.py:6727-6770` 的 adelete_by_doc_id 定义完整文档删除结果与 pipeline 互斥；`:7140-7178` 调 `_purge_kg_contributions` 删除该文档贡献并修复仍有来源的图对象，然后才处理片段、缓存与文档状态。恢复锚点、剩余片段的抽取缓存、源贡献 tracking 都是图额外生命周期成本。没有运行并发/失败恢复测试，不声称删除具备跨存储原子事务。

README:450 明确切换 embedding 模型需重建向量，建议真实部署保留图/片段并用工具重建；这是文档说明，未运行工具。

在本轮 lightrag Python/docs Markdown 范围未发现内置 MCP server 接线。已验证的是 SDK 和 REST 查询结构；未来 MCP 可包装 query_data，但还需补知识库范围、文档版本、位置与独立错误码。

## 借鉴建议与验证边界

`partial_borrow / borrow_idea`：最值得借鉴的是 **query_data 与答案生成分离**、chunk→来源→图贡献追踪、四阶段查询与预算、naive 对照路径。整体接入仍需维护图抽取质量、多个存储及删除重建，且用户的首期中文需求/设计/旧用例没有测过。

相对普通 RAG 实际新增：片段 LLM 实体/关系抽取和描述总结；实体及关系向量索引；图和来源贡献记录；KG 查询默认关键词 LLM；删除时图重建。复杂度从源码可见，“Simple/Fast”是项目定位，当前不量化速度或成本收益。

后续最小实验（仅提议）：同一固定语料下比较 naive、mix，含同义表达、精确需求编号、跨文档关联问题；标注原文片段和关系真值，测 Recall@k/关联精度、切分定位、同名更新与删除、额外 LLM/embedding token 和延迟。query_data 不生成答案，但关键词提取费用要计入。

命令结果：`git sparse-checkout set lightrag docs examples tests` 退出码 0；rev-parse HEAD / branch 显示上述 commit 与 main。仅执行源码读取/搜索。已定位 `tests/api/routes/test_aquery_data_endpoint.py` 与 `tests/chunker/test_token_window_source_span.py`，未运行；不声称测试通过。`observed_pitfalls=[]`，本轮没有采集实际失败日志/Issue 记录；风险不升级为踩坑事实。构建/业务测试不适用；live 服务 false。
