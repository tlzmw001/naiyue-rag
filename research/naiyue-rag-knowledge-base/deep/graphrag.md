# microsoft/graphrag 静态深验

- 日期：2026-10-09（用户工作区日期）。
- URL：https://github.com/microsoft/graphrag
- 分支：main；commit：`5faaaf4f5685fa2056fa8c3bf9342cb089f2942f`。
- 本地证据根：`research/naiyue-rag-knowledge-base/clones/graphrag/`。下文路径相对此根。
- 许可证：MIT，`LICENSE:1-21`；复用须保留版权及许可证。本轮没有复制源码到产品。
- 当前源码要求 Python `>=3.11,<3.14`（`packages/graphrag/pyproject.toml:26`），与 `docs/get_started.md:7` 的旧 Python 3.10–3.12 说明不完全一致；环境选择以当前包元数据为准。本机项目 Python 3.12 可满足版本约束，但未安装依赖验证。
- `deep_verified=true` 仅表示已入选且阅读核心实现。没有安装依赖、跑测试、摄取、调用模型或服务；`live_verified=false`。

## 它解决什么问题

README 与 `docs/query/overview.md:1-35` 将其定位为用 AI 抽取的图及社区报告形成问答上下文。适合检查“整个语料的主要主题是什么”和实体关联问题的技术路线。它不是测试领域的需求/设计/用例本体。README:3-5 明确称研究项目并处于维护模式，README:36-40 表明示范性质和索引成本警告；这些是项目自述，不是本轮可靠性测试。

## 真实摄取调用链（标准模式）

1. `packages/graphrag/graphrag/api/index.py:29-94` 的 `build_index(config, ...)` 创建 pipeline，遍历 `run_pipeline` 输出并报告 workflow 错误。
2. `packages/graphrag/graphrag/index/workflows/factory.py:40-97` 从 `config.workflows` 或 method 的实际注册列表选 pipeline。standard 顺序是 load_input_documents → create_base_text_units → create_final_documents → extract_graph → finalize_graph → 可选 claims → create_communities → create_final_text_units → create_community_reports → generate_text_embeddings。
3. `index/workflows/load_input_documents.py:20-58` 通过 `create_input_reader(config.input, context.input_storage)` 读文档并写 documents。具体路径以下省略 `packages/graphrag/graphrag/` 前缀。
4. `packages/graphrag-input/graphrag_input/text.py:16-45` 的 TextFileReader 默认文件模式是 txt；显式 `config.input.file_pattern` 可读取 md 原文。它读全文，以正文 SHA512 作 ID，以 basename 作 title，记录创建日期，没有解析 Markdown 标题层级和原文行区间。`input_config.py:12-49` 是实际配置定义。不能把自定义文件模式理解成已具备 Markdown 结构解析。
5. `index/workflows/create_base_text_units.py:27-54` 根据 `config.chunking` 创建 tokenizer/chunker；`:99-111` 写 `id/document_id/text/n_tokens`，片段 ID 由正文 hash 得到。`chunk_document:127-160` 可把配置指定元数据加到正文，再调用 chunker；未写行号、标题路径、显式文档版本。
6. `index/workflows/extract_graph.py:32-91` 从配置解析抽取和总结模型，实际 `create_completion`，再把 `entity_types/max_gleanings` 等传给 `extract_graph`。`:97-154` 对 text_units 抽图、验证非空实体和关系、合并描述。不是仅声明抽象接口。
7. `index/operations/extract_graph/graph_extractor.py:85-122` 每个片段用 `completion_async` 抽实体/关系，可重复 gleaning 并发起继续提取/是否继续的 LLM 调用；`:124-179` 解析定界符结果并把 source_id 关联到片段。
8. `index/workflows/create_communities.py:25-51,55-96` 消费 config.cluster_graph，通过 `index/operations/cluster_graph.py:20-97` 的 hierarchical Leiden 生成社区层级。
9. `index/workflows/create_community_reports.py:41-90` 读取实体/关系/社区，用 `config.community_reports.completion_model_id` 创建 LLM，生成社区报告并写表。
10. `index/workflows/create_final_text_units.py:82-112` 将片段与 entity_ids/relationship_ids/covariate_ids 接线。`index/workflows/generate_text_embeddings.py:72-136` 消费 config.embed_text.embedding_model_id 和 names，读取对应表，创建/连接配置的 vector store，编码并存储选定字段。

产物是 documents、text_units、entities、relationships、communities、community_reports 等表和配置选择的向量索引。默认表/存储具体形式由配置选择，不能把 Parquet/LanceDB 固定为任何运行都必用。

Markdown 不需要强制改后缀或转 txt：TextFileReader 配置文件模式后可直接读取 md 字符串。另有 `packages/graphrag-input/graphrag_input/markitdown.py:19-49` 转换 reader，但直接 Markdown 文本路径不依赖它。两者都不自动产生我们要求的原始 md 行区间。

## 查询调用链与模式区别

**Local**：`api/query.py` 的 local_search/local_search_streaming 读取表对象并构建引擎；`query/factory.py:37-100` 将 local_search 的 completion/embedding model、top_k 和预算接到 `LocalSearch`、`LocalSearchMixedContext`。`query/structured_search/local_search/mixed_context.py:91-221` 先 map_query_to_entities，再收集实体/关系、社区报告与 text unit，按 text_unit_prop/community_prop 分配 token 预算。`query/context_builder/entity_extraction.py:42-96` 对查询编码，对实体描述向量召回，再映射回实体。这不是简单的片段向量搜索。

`query/structured_search/local_search/search.py:56-140` 调用 context_builder.build_context 后构造 prompt 并生成答案，SearchResult 保留 context_records。公共 local_search 不是纯证据出口。可以借鉴/调用下层 context builder，得到上下文和结构化 records，但仍需包装我们自己的稳定证据字段与数据范围契约。

**Global**：`api/query.py:65-124` 的 global_search 收集 global_search_streaming 答案以及回调 context_data；`query/structured_search/global_search/search.py:142-209` 以社区报告批次生成多个 LLM map responses，合并/过滤后再 reduce 生成答案。不是“全库 BM25”，也不是 LightRAG 的关系向量模式。它增加多个查询时 LLM 调用。

**Basic/DRIFT**：`query/factory.py:183-278` 与 `docs/query/overview.md` 显示 Basic 是基础向量 RAG；DRIFT 将社区信息与迭代局部问题结合。当前证据未出现名为 mix 的 GraphRAG 模式，不能将 LightRAG mode 名套入。

## 模型与配置接线

`config/load_config.py:15-52` 调用 graphrag_common loader，实例化 GraphRagConfig。模型由各 workflow/query 的 model_id 从该配置选择。`packages/graphrag-llm/graphrag_llm/completion/completion_factory.py:55-159` 根据 type 注册 LiteLLM 或 mock，也允许注册自定义类型；把 model_provider/model、retry、rate_limit、cache、metrics 和 tokenizer 传到实例。`completion/lite_llm_completion.py:171-205` 调用实际异步模型函数。Embedding 有独立 factory，并由索引/Local 查询明确调用。使用模型服务需要兼容接口、独立 key 与模型配置，本轮没有验证用户网关是否支持。

`index/run/run_pipeline.py:117-158` 实际逐 workflow 执行、记录 profiler/callback，异常 logger.exception 后产出带 error 的 PipelineRunResult。存在追踪接线不代表我们测过失败恢复。具体 token/费用未知。

## 来源、更新与证据边界

- `packages/graphrag-input/graphrag_input/text_document.py:15-31` 保存 id/text/title/creation_date/raw_data；`data_model/text_unit.py:12-69` 保存 document_id 和图 ID、可扩展 attributes。图可追到 text unit 和文档，但所追默认 TextFileReader → text_units 写入链没有原始 Markdown 行号、章节和独立版本字段。
- `index/update/incremental_index.py:29-56` 的 get_delta_docs 按 **title** 的存在与否生成 new_inputs/deleted_inputs；不是正文 hash 差异。`index/workflows/load_update_documents.py:49-62` 只返回 new_inputs。`update_final_documents.py:19-37` 调用 concat_dataframes；`incremental_index.py:59-84` 合并旧/新增文档。按已追路径，同 title 正文改动不会被判新增，deleted_inputs 未被这条 workflow 消费。这是源码边界，不是本机复现出的 bug，也未声称所有自定义 reader 都一样。
- text reader 的 basename title 意味着不同目录同名文件须额外设计唯一来源。未验证自动覆盖/删除/版本回滚，不可当我们的更新方案直接采用。
- 社区报告及实体/关系描述是模型派生产物。要作为测试证据，应追原始需求段落，并区分显式业务关系与模型推断关系。图结构存在不证明“需求 A 被用例 B 完整覆盖”。
- 在本轮 packages Python 与 docs Markdown 范围搜索未发现直接 MCP server 实现；当前验证的是库与 CLI 查询入口。未来 MCP 需适配查询结果和错误。

## 对我们是否可借鉴

结论：`partial_borrow / borrow_idea`。借鉴文本与图来源关联、配置到模型的接线、上下文预算和 Local/Global 的问题分类；首期不推荐整体采用标准建图管道。理由是 Markdown 需求事实定位与版本更新是我们的关键要求，而标准图抽取、描述总结、社区报告及 MapReduce 带来额外模型调用、存储、提示词与质量评估工作。

实际新增成本来自已追调用链：片段抽取和 gleaning；跨片段描述总结；Leiden 运算；社区报告 LLM；多个向量字段；Global 多批 map + reduce。没有模型单价、token 与语料样本，不量化节省/费用/性能。文档宣称 Fast 更省且默认 NLP 偏英文（`docs/index/methods.md`），对我们的中文语料仍需单独验证。

更换 Embedding 的设计推断：库按字段建立独立向量索引，LanceDB 实现检查向量维数（`packages/graphrag-vectors/graphrag_vectors/lancedb.py:87-102`）。换 embedding 模型后要用新模型重编码相应数据并保证查询/索引使用同一向量空间；即使维数相同也不证明旧向量兼容。已读源码没有证明自动完成模型切换迁移，因此不能称只改配置就可继续查询；不必由此推断所有图/LLM 派生内容必须重做。

最小后续实验（仅提议）：在同一批批准的 Markdown 与固定问题上比较基础证据召回与局部图召回；另给跨文档汇总问题；标注原始片段 Recall@k、关系事实准确率及额外 token/延迟。先人工给出需求—方案—用例关联作为真值，防止评测只验证图的自洽。

## 验证与限制

本轮命令：`git sparse-checkout set packages docs tests` 退出码 0；`git rev-parse HEAD` 得到上述 commit；`git branch --show-current` 得到 main；阅读/search 用 cat/sed/rg/nl。未运行第三方代码。测试/构建结果：不适用，本轮静态调研不执行。`observed_pitfalls=[]`，没有实际失败记录；源码限制仅记录为风险/缺口。路线未被判死，维护模式也不等于技术路线不可行。
