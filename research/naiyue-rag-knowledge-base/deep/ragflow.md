# RAGFlow 静态深验：完整知识库产品路线

- 对象：https://github.com/infiniflow/ragflow
- 分支：`main`；commit：`1c970958db31d8a4872ee4d2595913897ae7676b`。
- 调研日期：2026-10-09；快照证据：[clone-snapshots.json](../raw/clone-snapshots.json)。
- 结论：`partial_borrow`，已读实际核心代码。适合借鉴知识库管理、摄取任务、检索与问答分开、可调召回/重排及 MCP 复用检索服务；本项目仍需自己定义 Markdown 原文定位、业务版本、需求/方案/历史用例的权威性规则和评测。
- 证据边界：README 自述、源码事实和设计判断在下文分别说明；未安装、未构建、未运行第三方程序或测试、未部署、未调用真实 Embedding/LLM/Reranker。因此 `deep_verified=true` 指静态源码深验，`live_verified=false`；无业务效果、延迟、费用结论。

## 对象当前形态与前置条件

README 以面向企业的 RAG 引擎、上下文层和 Agent 能力描述项目；这些宣传不能证明本项目业务有效。[README.md](../clones/ragflow/README.md)。

当前固定快照的重要变化：README 194–242 指向 `v1.0.0-rc1` 及以后使用 **Go 实现**；`go.mod:3` 为 Go 1.27。仓库仍有 Python `rag/` 与 SDK，不应沿旧教程假定 `api/apps` 是当前后端入口。`pyproject.toml:1-20` 中 Python 项目要求 `>=3.13,<3.14`，这也不同于 naiyue-rag 当前独立 Python 环境；本轮没有安装它。

README 157–161 给出的 Docker 推荐起点是 4 CPU、16 GB RAM、50 GB 磁盘，实际取决于索引引擎、解析、并发和本地模型。README 234 明确 Go 后端暂不支持 macOS，要求 Linux x86_64 主机。源码编译还涉及 CGO、Clang 20、LLD 20、CMake 4 等（242–262）。这是该快照使用文档的约束，未在本机验证。

`docker/docker-compose-base.yml:1-82,253-365,397-414` 定义 Elasticsearch/Infinity 等可选文档引擎、MySQL、MinIO、Kvrocks、NATS；并非所有可选服务都必须同时启用。README 234 明确 Go 默认部署用 Kvrocks 缓存/Checkpoint 与 NATS JetStream 队列。相较少量 Markdown 的独立 Python 库，整套产品有较大部署、资源和学习负担。

许可证为 Apache-2.0（`LICENSE:1-4`）；本轮只读参考，没有复制第三方业务代码。未来复用须保留许可和来源说明，并按实际修改重新验证。

## 一条真实 Markdown 摄取链

| 环节 | 读到的实际入口与行为 | 本地源码证据 |
|---|---|---|
| SDK 上传 | `Dataset.upload_documents` 把文件 multipart 提交到 `/datasets/{id}/documents`，上传与解析分开 | `sdk/python/ragflow_sdk/modules/dataset.py:54-70` |
| API 接线 | router 将该 POST 接到 `DocumentHandler.UploadDocuments`；`/datasets/{id}/chunks` 接 `ChunkHandler.Parse` | `internal/router/router.go:387-399` |
| 原文与目录 | `UploadLocalDocuments` 读取字节，保存到 storage，创建文档 SQL 记录与 File/file2document 关系；失败回滚 blob/记录；此时还不切分/Embedding | `internal/service/document/document_upload.go:24-113` |
| 摄取任务 | SDK `async_parse_documents` POST `/datasets/{id}/chunks → ChunkHandler.Parse → ChunkService.Parse → DocumentService.StartParseDocuments → IngestDocuments → IngestionTaskService.CreateForDocuments → createAndEnqueueWithKBCache`；任务入消息队列，返回 task_id | `sdk/python/ragflow_sdk/modules/dataset.py:136-146`；`internal/handler/chunk.go:180-212`；`internal/service/chunk/chunk.go:706-760`；`internal/service/document/document_parse.go:80-105`；`document_ingest.go:18-25`；`internal/service/ingestion_task_service.go:105-153,571-634` |
| 管道编排 | `PipelineExecutor` 装配 DSL、doc/tenant/KB、文档解析配置；`NewPipelineFromDSL → pipe.Run(ctx, inputs, parserConfig)` | `internal/ingestion/task/pipeline_executor.go:1080-1185`；`internal/ingestion/pipeline/pipeline.go:99-124` |
| 实际组件 | 通用模板连 `File → Parser → GeneralChunker → Extractor → Tokenizer`；md/markdown/mdx 均归 Markdown 解析；默认 512 token 切分，Tokenizer 同时 embedding/full_text；Extractor 默认关键词/问题数量为 0、摘要 false | `internal/ingestion/pipeline/template/ingestion_pipeline_general.json:16-36,72-87,141-215` |
| Markdown 解析 | `ParserComponent.Invoke` 读存储内容、决定文件类型；`dispatchParse → GetParser(FileTypeMarkdown) → NewMarkdownParser(GoMarkdown).ParseWithResult`；AST 变成有 text/type 的有序块 | `internal/ingestion/component/parser.go:442-528`；`parser_dispatch.go:78-107`；`internal/parser/parser/parser_type.go:31-52`；`markdown_parser.go:99-135,395-453` |
| 切分 | `chunkMarkdown` 先按分隔符拆文本块，再按 token 预算/overlap 合并，处理子片段；保留语义类型供标题检测 | `internal/ingestion/component/chunker/general.go:591-636` |
| Embedding | `Tokenizer.Invoke → embedChunks`；按 KB 解析模型，标题和正文分别 encode，按 batch 调用；缺模型、数量不匹配等返回明确错误 | `internal/ingestion/component/tokenizer.go:345-417,430-452,525-565` |
| 索引写入 | `processOutput → NormalizeChunks → ProcessChunksForPipeline → indexWriter.Write → engine.InsertChunks`；写入失败会尝试补偿 | `internal/ingestion/task/pipeline_executor.go:268-340,109-155`；`internal/ingestion/task/chunk_index_writer.go:71-123` |

上述链不是只有接口声明。`cmd/ragflow_server.go:72` blank-import `ingestion/wire`；`wire.go:45-48` import 真实组件触发注册。`task/embedder.go:686-704` 的 `init()` 给 `DefaultEmbedderResolver` 注入真实实现，读取 KB 的 `EmbdID` 并调用 `ModelFactory.NewEmbeddingModel`；Tokenizer 用这个 resolver，缺接线会报错。模板配置又作为 parserConfig override 传进 `pipe.Run`。这些构成静态 L3 接线证据，尚无运行证据。

## 一条真实查询链

`RAGFlow.retrieve` 提交 question、dataset_ids、document_ids、similarity_threshold、vector_similarity_weight、top_k、rerank_id、metadata_condition 到 `/retrieval`（`sdk/python/ragflow_sdk/ragflow.py:193-250`）。router 331 接 `DatasetsHandler.SearchDatasets`，再调用 `DatasetService.SearchDatasets`。

`internal/service/dataset/search.go:24-146` 检查问题与 dataset_ids；逐知识库验证 `kbDAO.Accessible`；校验同次查询的知识库 Embedding 模型兼容性。232–251 将 metadata 条件转换为 doc_ids；273–313 根据 KB.EmbdID 与 rerank_id 构造真实模型，并调用 `nlp.RetrievalService.Retrieval`。

`internal/service/nlp/retrieval.go:94-227` 验证分页/候选数量；`Search` 749–808 构建词项表达式，有模型时 `GetVector` 把查询按 **Query=true** 编码并用 cosine 建向量匹配；无模型走关键词。默认混合路径使用词项、向量、fusion 表达式，非向量专用路径才加融合。Infinity 使用请求的 weighted_sum 权重，其他引擎的首次召回固定权重 `0.001,1`，调用者权重在后续重排作用（607–645）。因此不能把它概括成默认 RRF，也不能假定所有引擎的混合行为一致。

`scoreSearchResult` 453–570 有 rerank model 时调用 `RerankByModel`，否则走标准/带 KNN 的评分；排序和阈值筛选在 195–227。返回 chunk、文档、知识库、正文、positions、similarity/term_similarity/vector_similarity 等（280–355）。`dataset/search.go:323-348` 映射为 id/content/document_id/dataset_id 等并去掉原始向量；SDK 把它们构造成 Chunk 对象。

这里 SDK 的 `keyword=true` 意味着可启用 LLM 关键词抽取（`dataset/search.go:262-273`），不是启用关键词索引的开关。纯检索默认无须生成答案，但自动 metadata/cross_languages/keyword 等选项可以额外调用聊天模型，不能一概写为完全无 LLM 调用。

KG 边界：同一 `SearchDatasets` 路径 320–322 即使 `use_kg=true` 也显式 warning 并跳过；SDK 有参数不证明这个接口已接上 KG。另读到 chat 路径 `chat_pipeline.go:1011-1030` 确有可选 graph pipeline，这个差异只适用于上述两个入口，不能断言整个产品无 KG。

## 问答、大模型与 MCP 如何消费结果

- `ModelFactory.NewChatModel/NewEmbeddingModel/NewRerankModel` 各自解析类型、模型与 API 配置后创建实例（`internal/service/model_factory.go:80-128`）；配置解析产生 model driver 与 APIConfig 的 BaseURL 等（957–968）。它们是独立类型的接入，现有 Agent 的聊天网关能用不代表 Embedding/Rerank 能用。
- `Session.ask` 对 chat session 走 `_ask_chat`，与 `RAGFlow.retrieve` 两个接口分开（`sdk/python/ragflow_sdk/modules/session.py:39-113`）。`chat_pipeline.go` 标准路径在 912–947 用 Retrieval 获取证据；1042 起准备知识块；1125–1178 给模型组装 system/citation/messages 并适配 token budget；1240 起 buildChatDriver、生成与 decorateAnswer；`decorateAnswer` 3056 起形成引用返回。引文提示与引用格式本身没有证明主张得到证据支持。
- MCP 是已有检索服务的适配层：`internal/handler/mcp_server.go:43-59` 注入 `mcpRetrieval`，后者 107 调 `ds.SearchDatasets`；204–253 给 chunk 附 dataset_name、document_name、document_metadata，返回 chunks、pagination 和 query_info。适合借鉴“同一检索核心供 SDK/HTTP/MCP 消费”。
- MCP 的 dataset_ids 缺省会枚举用户全部可访问知识库（`mcp_retrieval.go:42-67`）。本项目要求查询范围在检索前明确，不能未经决定复用这个默认值。
- Python SDK `Chunk.__init__` 只保留预声明字段，额外字段会被丢弃（`sdk/python/ragflow_sdk/modules/chunk.py:29-52`）；MCP 结果能带 document_metadata，不代表同一 metadata 会从 `retrieve()` 的 Chunk 对象保留下来。

## 更新、版本与本项目业务缺口

文档实体有 `ContentHash`、来源类型、名称、时间和处理状态（`internal/entity/document.go:22-45`），但 hash 不是业务版本号。上传路径同名时调用 `UniqueFileName` 另名并新建记录（`document_upload.go:65-93`）；不能把重复上传视作自动覆盖当前版本或稳定 document_id 的幂等更新。

已读重跑路径会跳过活动任务或已完成且 delete=false 的任务；delete=true 可清理 prior parse results 后重做（`document_ingest.go:86-125,172-177`）。完整删除会清理任务、引擎数据、SQL计数、文件关系（`document_crud.go:272-307,410-448`）；引擎删除与 SQL/对象存储是多个动作，并非单个跨存储原子事务。本轮未注入失败验证一致性。

官方 metadata 文档允许手工字段与过滤（`docs/guides/dataset/metadata_management.md:20-42`），可用来表达 `doc_kind=requirement/design/testcase`、version、有效状态；**这是本项目可以设计的用法**，不代表产品自动识别这些字段。其自动 metadata 配置变更只作用于新解析文档，旧文档需重解析（30）。查询链已接上 metadata 条件，但本轮读到的通用检索排序与 chat 组装没有“当前需求优先于过期方案或旧用例”的专用业务裁决；本项目需明确标注规则、冲突输出和测试，不能把相关性分数当正确性依据。

Markdown parser 的输出为 text/type/ck_type 等 AST 块，读到的 parser→chunker 链没有输出原始 `line_start/line_end` 和稳定 source-version 契约。查询 `positions` 来自索引位置字段，`indexdoc/position.go:37-76` 是 PDF框/电子表格范围，而 Markdown AST 输出没有相同位置。结论限定为本轮链路：尚未证明它满足我们所需 Markdown 原文行号与版本证据，不能把 chunk_id+文件名当完整可追溯定位。

## 已发生问题、风险和适用判断

**有发生记录的解析问题**：`markdown_parser.go:149-172` 与 `markdown_parser_test.go:282-308` 记录过美元货币符号被当 MathJax 后丢掉中间文本，13.8k 字符报告变成约1.4k。当前代码关闭 MathJax，回归测试要求各句保留。这是仓库源代码/回归注释提供的历史故障证据，本轮没有重现或运行测试。对我们提示：解析评测先检查内容守恒，需求表格、编号、金额、代码块均需专门样本。

**风险/待验证，未声称实际发生**：部署系统复杂；模型调用的费用和数据范围未知；SearchDatasets 与 Retrieval 源码直接把 question 写到 info 日志（`dataset/search.go:31,352`；`nlp/retrieval.go:95`），将来用于敏感需求必须审阅日志策略；多个存储的失败收敛需运行实验；默认全库 MCP 范围和SDK字段丢弃会影响自有证据契约。

推荐只借鉴上述机制；如果后续目标变为尽快获得可管理的企业知识库产品，可以另以 Linux 小型部署评估为对照。但当前独立 Python 工程/逐片段学习、少量 Markdown、Agent 用证据工具的目标，尚无证据支持直接采用整套 RAGFlow。

## 本轮检查与限制

- `git sparse-checkout set rag sdk internal cmd conf docker docs test`：exit 0；只扩展参考源码可读范围，未执行其中的配置或程序。
- 多次 `rg --files` / `rg -n` / `sed` / `cat`：完成上述调用链静态阅读；过程中旧目录猜测如 `internal/ingestor` 不存在，随后从 tree 定位为 `internal/ingestion`，未据猜测作能力结论。
- `python3` 加 `jsonschema.validate(card, scheme-card-schema)` → `scheme_card_jsonschema=PASS candidate=github-0986`；20 条 evidence_refs 路径检查全部存在；本文 2 条 Markdown 本地链接 → PASS；`git diff --check` → exit 0、无输出。这些为调研产物检查，不冒充参考项目功能测试。
- 构建/测试/真实服务：本轮均未执行；本机和业务正确性均未验证。
- 唯一下一步：与其余已选路线比较后由用户裁决首期知识库切片，独立定义原文/版本/范围证据和固定问题集，再决定检索实现。
