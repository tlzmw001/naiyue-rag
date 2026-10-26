# Spec0020：M3编码模块——参考调用链、公共合同与分片实施规范

日期：2026-10-12阶段设计；截至2026-10-14 Spec0021–0025输入、Provider/Dense、真Sparse、文档成对Batch与正式查询结果已离线接线，最新66新增/1167全量。真实服务/硬截止仍待。以下设计与调研时事实保留，当前实现以各切片Spec为准，不把openai未安装等历史环境当当前状态。

## 1. 来源与证据分级

参考仓库：https://github.com/Jerry-ai-dev/MODULAR-RAG-MCP-SERVER；本机路径/分支/commit为/Users/zmw/MODULAR-RAG-MCP-SERVER、main、f658c5a4011c8b826707a65a3b11ce9301b0626f。只读该固定源码快照，不声称核验了远端最新提交，没有运行setup、参考测试、完整服务或发布Skill。

重点核README、DEV_SPEC、pyproject.toml、core/settings.py/config/settings.yaml、ingestion/pipeline.py、ingestion/embedding三组件、libs/embedding四接口/工厂/三Provider，以及dense_retriever、query_processor、vector_upserter/BM25Indexer相关消费者。参考声明、实际源码、局部模拟探针和真实服务结果分别如下：

| 层次 | 核对结果 |
|---|---|
| 项目自述 | DEV_SPEC称双路编码可含BM25/SPLADE、并行及原子存储等设计能力；不直接作为运行事实 |
| 源码事实 | 当前SparseEncoder产出词频/文档长度；BatchProcessor按批串行Dense→Sparse；两类存储分步骤执行。没有在这条实际编码链发现SPLADE调用或双路原子事务 |
| 依赖事实 | pyproject核心依赖含jieba、LC splitter；openai>=1.0列于dev可选组，未锁参考SDK运行版本。Embedding用自有BaseEmbedding及原生SDK/httpx，没有使用LangChain Embeddings封装 |
| 本机局部探针 | 从固定源码AST提取原类，SDK/Dense/Sparse故障为模拟依赖，实际jieba对照在本项目ignored缓存内运行，socket禁止连接；见第11节 |
| 真实服务 | 本轮0请求。旧智谱Embedding/GLM探针属于历史证据，不迁移为新SDK/新输入文本/本地模型已经通过 |

官方一手补充（2026-10-12读取）：[OpenAI Embeddings API](https://developers.openai.com/api/reference/resources/embeddings/methods/create)、[官方SDK重试/超时说明](https://github.com/openai/openai-python#retries)、[Ollama /api/embed](https://docs.ollama.com/api/embed)。SDK文档当前说明默认自动重试和较长timeout；参考未显式配置这些值，参考运行SDK版本未知，不推定其真实调用次数或截止。Ollama当前接口支持批input、默认截断，实施须明确truncate=false；参考使用/api/embeddings逐条prompt，不能把新文档接口说成参考已接线。

## 2. 参考真实调用链与参数接线

### 离线摄取

```text
IngestionPipeline.__init__
  Settings.embedding → EmbeddingFactory.create → OpenAI/Azure/OllamaEmbedding
  Settings.ingestion.batch_size → DenseEncoder及BatchProcessor
  SparseEncoder() → 默认分词参数

IngestionPipeline.run
  原文→Chunker→Refiner→MetadataEnricher→Caption
  → BatchProcessor.process(chunks)
      外层切batch
      → DenseEncoder.encode(batch)
          chunk.text→内层batch→embedding.embed(texts)
      → SparseEncoder.encode(batch)
          chunk.text→jieba.lcut→过滤/小写→Counter
  → dense_vectors、sparse_stats
  → VectorUpserter.upsert(chunks,dense_vectors)
  → 将sparse_stats.chunk_id按zip改成vector_ids
  → BM25Indexer.add_documents(sparse_stats)
  → 后续FileIntegrity成功登记
```

文件定位：pipeline.py:167–180/385/437–451；dense_encoder.py:66/121；batch_processor.py:112/157–173；sparse_encoder.py:72/134；openai_embedding.py:101/160；vector_upserter.py:101。

参考配置示例batch_size=100、provider=openai、model=text-embedding-ada-002、dimensions=1536；示例同时具有azure_endpoint，OpenAIEmbedding构造会按其兼容分支构造部署地址和api-key认证。provider标签本身不足以描述最终目标。以上为本机配置/源码事实；不复制URL/Key，也不把100或1536当本项目最优默认。

OpenAI/Azure调用原生SDKembeddings.create；OpenAI仅在模型名text-embedding-3前缀匹配时发送dimensions。当前智谱model=embedding-3不符合该前缀。SDK响应以data列表顺序取embedding，仅检查数量；本机SDK替身反序index的探针没有按index恢复顺序，也没有执行配置维度/有限性/范数/usage/model等本项目已有严格校验。Ollama则循环文本，各发一个/api/embeddings请求，base_url取显式构造参数或环境/默认，settings.embedding.base_url未在其构造中读取。

### 在线查询

```text
HybridSearch.search(query)
  → QueryProcessor.process→ProcessedQuery
  → DenseRetriever.retrieve(processed_query.query,...)
      → 同类Embedding Provider.embed([query])
      → vector_store.query(query_vector,...)
  → SparseRetriever使用QueryProcessor关键词
  → 融合/重排/证据（M5–M6职责）
```

DenseRetriever不调用摄取DenseEncoder/BatchProcessor，而是直接调用Provider；这说明文档/查询应共用模型适配和向量验证，但上层任务与批次流程分别负责。查询改写/提取业务过滤/MCP均不并入M3。

## 3. 当前本项目资产与缺口

| 当前资产 | 可复用的实质 | 不能直接迁移的约束 |
|---|---|---|
| Spec0016–0019/M1–M2 | Document/Chunk、真实SourceSpan、retrieval_view、关系、prepare_knowledge_base | 新72Chunk尚未向量化；派生文本必须校验，不直接相信metadata里任意text |
| experiments/embedding_probe.py | 向量按index恢复顺序；数量/维度/数值/非零范数；usage与安全错误 | 固定智谱协议/模型/限额，仍是实验，不让新核心反向导入 |
| experiments/vector_embedding.py | 文档/查询批次预检、请求记录、usage、worker总截止、不自动重试 | 固定model=embedding-3/dim2048/batch≤16及Mock路径/56输入/5请求等实验界限 |
| experiments/vector_index.py | input_sha绑定、模型身份、缓存校验；make_index_text=context正文+body | 原52单元/旧index-text策略与新72片段不同；不得把旧向量错配给新Chunk |
| experiments/keyword_index.py | A2中文搜索分词、ASCII标识符保留、HMM=False、词典/版本身份、BM25S | 与旧corpus/存储/缓存创建/范围耦合，M3只提升分词与逐项统计，评分/存储归M4–M5 |
| naiyue_rag/retrieval.py | query_sha、身份匹配与安全验证的工程经验 | 旧A2快照/回调仅作实验参考，正式M3/M5不为其新增兼容适配 |
| core/settings.py | 严格YAML、重复键/alias/merge拒绝、路径与错误规则 | snapshot路径和旧sparse/rrf参数是当前必填/固定，不能用虚假路径补出通用编码配置 |

当前环境：Python3.12.14、httpx0.28.1、jieba0.42.1、bm25s0.3.13；openai未安装。LC splitter1.1.3仅在M2使用，不据此要求编码也通过LangChain。旧真实缓存/测试/协议留作回归资产，不整体搬迁或重写。

## 4. 推荐模块边界与完整数据流

```text
documents + prepared chunks
  → prepare_document_encoding_inputs：源绑定/派生文本验证、选择layout、计算输入hash
  → BatchProcessor：整体预检/唯一分批负责人
      → DenseEncoder：完整一批→Provider.embed→向量/usage规范化
      → SparseEncoder：同批retrieval_text→词项/TF统计
      → 按item_id与输入hash核对，输出成对记录
  → 完整EncodingResult（M4消费者待建）

QueryRequest
  → prepare_query_encoding_input：保留问题原文/hash，应用显式Dense前缀
  → DenseEncoder单项 + SparseEncoder.query_terms
  → QueryEncodingResult（M5消费者待建）
```

DenseEncoder/SparseEncoder不写数据库；Provider只做协议/能力与单请求，不切分知识文档、不决定重检索；BatchProcessor只对编码任务负责，不启动Agent循环。BatchProcessor按批串行，首期不扩并发/异步/恢复队列。唯一分批层避免两套batch_size相互影响；DenseEncoder.encode_batch一次至多一个已计划请求。Query不绕过同一Provider和向量校验。

保留参考模块职责，但不建立无人消费的插件注册、空厂商类或默认模型。BaseEmbedding/工厂到具体Provider与Encoder同时接线时建立；首个工厂只有已实现后端，其他后端配置须明确unsupported_provider。

## 5. 独立正式编码配置（已确认）

用户选择：“独立入口，不必保留了，之前的都是实验，我们现在是做正式项目”。正式采用EncodingSettings及load_encoding_settings；复用严格YAML校验机制，不把load_settings/to_snapshot_config、旧快照格式或旧调用兼容作为产品设计约束。正式入口无需dataset/corpus_run/vector_run，不要求虚假路径，也不为实验建立额外兼容分支。既有可靠算法、来源合同和失败证据继续作为参考资产，正式实现按当前职责与消费者设计。

当前实际消费者核对：naiyue_rag.__init__仍导出旧Snapshot/Bootstrap/检索入口并间接加载experiments；DocumentChunker仍从整体Settings取得ingestion。这些属于待迁移的实验耦合，正式接线时按调用链处理，不能在新入口外再包一层旧快照来维持兼容。取消兼容要求不等于本轮删除整个experiments目录或旧结果；具体代码迁移/清理范围在对应切片列明。

推荐结构分三组，所有值由配置/明确参数提供；仅复用读取/校验机制，不读取其他仓库.env：

| 组 | 拟字段与用途 |
|---|---|
| embedding | provider、base_url、model、expected_dimensions、request_dimensions（null=不发送）、可用model_revision、显式响应model别名声明；endpoint与凭证分开 |
| representation | document_text_mode=raw/labeled_case；text_layout=view_only/contexts_then_view；document_prefix/query_prefix（可为空）；策略版本 |
| batching/runtime | batch_size、max_inputs、max_input_utf8_bytes、max_batch_input_utf8_bytes、max_requests、timeout_seconds、deadline_seconds、max_response_bytes；Sparse词典/策略/cache目录到对应片接线 |

字段正整数排除bool，float时限有限正值；请求维度与期望输出维度各自校验，绝不凭模型名前缀猜协议能力。URL拒绝含凭证或不明确目标；正式配置直接定义SDKbase_url和Provider协议路径，不另建旧endpoint格式转换层。参数100只是参考配置，不能覆盖实际Provider限制或当效果最优。未提供required组/字段明确失败，无隐式模型/维度回退。

凭证由本项目应用装配层按显式环境变量名取得或调用方注入；2026-10-14 Spec0027已支持命名变量未设置时读显式项目根.env，保持纯配置加载器不加载.env，Provider不隐式选择其他Key/目标。SDK构造时显式提供Key/base_url/timeout/max_retries=0；SDK环境读取、代理/重定向、响应读取边界需对选定版本核验，不由构造参数名字就宣称控制已生效。

模型数值空间身份包含协议/有效目标/model/revision（未知留空）/请求参数/期望维度及明确后处理；不含Key。representation身份与最终文本hash另存。batch大小、timeout、实际usage不是模型空间字段。不能仅凭维度相同复用缓存，已知模型revision更新需重建；未提供revision不伪造已知值。

## 6. 输入、输出及文本表示

拟公共合同：EncodingInput、ProviderBatchResult、EncodedRecord、EncodingResult、QueryEncodingResult；标准dataclass/显式校验，json往返、复制和安全repr沿M0，不加Pydantic依赖。字段在实际消费者切片创建，先不预建空类。

EncodingInput至少：item_id、kind(document/query)、来源文档ID/版本/SourceSpan（query为null）、retrieval_text及hash、embedding_text及hash、representation_identity。生成文档输入时重新核对Document→Chunk正文/contexts，并按M2 Refiner重推应有view，核对规则、input/text指纹及内容，拒绝伪造/混合模式/重复ID/跨库/缺来源。

retrieval_text按显式layout构造：view_only只取已验证view；contexts_then_view按已有contexts顺序拼接其原文，再拼接view，沿旧make_index_text职责。上下文进入检索文本是M3的显式派生布局，不改变M2 Chunk.text/SourceSpan或retrieval_view；不自动去重/扩写/摘要。

推荐第一对照起点：raw + contexts_then_view、Dense前缀为空，尽量沿A2已有表示；新几何/ID仍不同，不宣称与旧A2质量等价。之后保持其他变量不变，分别对照labeled_case或view_only，不同时改变两轴。

Dense输入=显式前缀+retrieval_text；Sparse仅消费retrieval_text，不把Embedding训练提示前缀加入BM25词项。查询保留QueryRequest.query及其原始query_sha，配置前缀后的embedding_text另hash；不自动strip/改写问题，QueryRequest已有边界保持。

ProviderBatchResult包含vectors、可核的返回model、usage或null、请求证据种类。向量按response.index恢复输入顺序；Ollama无index列表时按其协议顺序映射并核数量。拒绝重复/缺失/越界index、维度错误、bool/非数值/NaN/Inf及零范数。明确响应模型别名须配置；不静默接受换模型。得到的向量不额外单位化或补零。

EncodedRecord以item_id绑定两份数据：Dense(vector、embedding_text_sha、model_space_id)与Sparse(tokens、term_frequencies、doc_length、unique_terms、retrieval_text_sha、tokenizer_id)。M4不允许按zip盲目改ID；每行均核对原输入。Sparse是BM25所需词项统计，不标成神经稀疏模型结果，也不在M3计算范围相关IDF/最终排名。

EncodingResult只在全部成功时交付成对records、源批次/表示/模型/分词身份和安全report。空输入正常返回空结果、请求0；不能把失败结果伪装为空库。QueryEncodingResult交给正式M5查询链；不增加旧retrieve_once回调适配。query_sha、模型身份、来源种类与usage等有价值信息按新正式合同保留，不受旧响应字段集合约束。

## 7. 正常、失败与可观察性

先完成整批来源/表示/长度/身份校验，再发第一请求。按输入顺序、数量上限与总文本UTF8字节上限确定批次；单项超任一限制整次预检失败，不截断完整用例、不丢弃后编码。UTF8字节是本机资源界限，不冒称精确模型token上限；已知服务token界限在Provider核对，未知不能编造。

| 场景 | 结果与请求边界 |
|---|---|
| 正常多批 | 串行Dense→Sparse，逐批核数量/ID/hash，最后完整返回 |
| 非法来源/视图、重复ID、错误身份、缺Key、超限 | 调用前失败；预检0模型请求 |
| 超时/认证/429/5xx/重定向/坏JSON/错index/错model/错维度 | 固定EmbeddingError/EncodingError，整次失败；不换模型/不隐式重试/不降单路 |
| Sparse或词典/cache关键IO失败 | 明确错误；Dense已成功的用量仍记录，局部数据不交付完整结果 |
| 空输入/查询无Sparse词项 | 空文档任务正常；查询terms=[]允许，不能凭此判业务无答案 |
| 报告字段/写入 | 直接传report，安全白名单；不加ContextVar或通用事件系统。需要存储时另按M0已接受的显式观察策略接Collector |

report记录job_id、批范围/输入数量与hash、阶段/错误码、单调耗时、attempted/confirmed请求、已知usage与未知次数；未知token/成本不能写0。批usage不能按字符平均分配给Chunk后冒称真实逐项用量。已知费用只在用户提供价格和真实usage时估算，账单始终另核。

失败异常附安全report，保持原必要异常语义；不记录请求正文、词项清单、向量完整值、凭证、供应商异常正文/headers/URL。没有证据的HTTP终态、服务端token/cost保持未知。只隔离Exception，不吞BaseException。

timeout不等于任务硬截止。HTTP片在请求前检查剩余时限，SDK超时显式配置；真实验证沿现有worker监督设整体截止/请求数。不先引入并发取消框架。请求预算只覆盖一次编码任务，不冒称覆盖知识库Agent整个会话。

## 8. 参考差异、理由与状态

| 项目 | 参考实现 | 本项目方案与理由 |
|---|---|---|
| 组件职责 | Provider/Dense/Sparse/Batch/工厂 | 沿用，按实际后端逐个接线；首期单一分批负责人 |
| 文本 | 直接chunk.text（前面已修改） | 原始证据不动，显式验证view/layout；保持可比较与追溯 |
| 批失败 | 捕获继续，可能部分Dense/Sparse不齐 | 沿用户已确认整次报错，ID/hash成对检查，防止错配 |
| 分词 | jieba.lcut、min_term_length=2、小写 | 继续搜索分词及完整标识符适配；中文最小词长可配置、2为候选，数字/ASCII短词单独核规则。连续“开关”已识别整词，带空格“开 关”不同；具体对照与实现M3.3完成 |
| 维度/顺序 | 前缀决定dimensions；取data列表顺序；维度一致性为主 | 显式request_dimensions与expected_dimensions、按index恢复、有限/非零等已有严格校验 |
| SDK | 原生OpenAI/Azure，未显式retry/timeout、每次新client | 仍推荐原生SDK；固定版本/依赖后显式关闭重试，生命周期/超时/响应界限实测；不无故加LangChain封装 |
| 本地Ollama | /api/embeddings逐文本，环境/default地址 | 单独兼容片核当前/api/embed批量协议，truncate=false；URL/model全部配置，实际运行另验 |
| 追踪 | 参考部分记录原异常/词项 | 沿本项目安全白名单，真实usage与未知分开，不复制敏感日志 |
| 缓存/原子存储 | DEV_SPEC有更广设计叙述；实际多阶段IO | M3只产完整编码结果，M4负责同版本保存/激活及重启一致性，不提前承诺事务/差量复用 |

Claude是生成/推理模型方向，不创建不存在的Claude原生Embedding适配。OpenAI兼容协议可以服务不同云平台或本地服务，具体能力按端点核验，不能由可聊天推定可Embedding。

## 9. 分片顺序与影响范围

### M3.1：配置、输入表示与结果校验

按已确认独立入口新增core/encoding_settings.py及core/encoding_types.py、encoding/input_preparer.py及encoding/validation.py、对应测试。复用/提取严格YAML读取机制、向量/usage校验约束，但正式模块不反向导入实验、不给旧ProbeError或快照协议新增兼容导出。先核公共包导出和配置消费者，将正式加载路径与实验耦合分开；当前有实质实现的M0/M1/M2功能按正式职责复用，数据/异常合同变化列入切片并同步真实调用与测试。必要的测试入口迁移是调用方变化，不放宽业务断言或skip失败。

本片交付真实可调用的文档/查询输入准备与Provider响应规范化；受M2和后续Encoder实际消费。先红灯（入口不存在/非法输入预期行为）再最小实现，测试用模拟原始响应且明确simulated。不创建虚假可运行Provider、空Factory或宣称模型已接通。此片无新依赖/服务/数据库。若影响文件接近500行，按实际职责拆分，不向M0 types持续堆字段。

### M3.2：首个OpenAI兼容Provider与DenseEncoder

已按Spec0022完成SDK版本/机制核验及Provider、Dense/有界transport真实实现，60新增/957全量离线通过；只新增2包、135版本不变。首期只有一个实现后端，按用户确认的Spec0022不建无人消费的BaseEmbedding/注册表/create包装；第二后端/实际选择消费者需要时再接工厂。真SDK+模拟HTTP接线，不当服务验证或整任务硬截止。必要适配列于Spec0022，没有另造整套HTTP框架。

### M3.3：SparseEncoder与BatchProcessor完整闭环

首片Spec0023正式Sparse已完成：独立配置/词项/TF/JSON、可核cache与查询去重，12Mock真实jieba接线，47新增/1004全量。下一片单独制定BatchProcessor规范，接Dense/Sparse逐批成对结果和整任务报告；不把旧实验接口当兼容约束。模型/表示/源版本/词典/过滤身份分开，检索质量仍需后续单变量对照。

### M3.4：正式查询编码与真实服务验收

QueryEncodingResult按正式合同由M5消费，M3核文档与查询共用Provider/验证及表示身份，不绕到旧Snapshot/旧embed_query入口。新Chroma应用消费归M4/M5。随后以公开/合成输入确认凭证可用性、端点/model/请求数、截止与预算后实测文档/新查询。同一新M3输入重建独立向量，旧缓存只作对照资料；旧临时Key与旧“实验不考虑预算”不无限迁移到新任务。

Azure及Ollama独立Provider片归M3后续，保留实际接口/身份/失败验收；CPU模型部署/模型下载在真实需求与环境核对后做，不承诺目前远端能跑。每片源码≤500、复杂变更单独补充规范；不一次生成完整M3/M4目录。

## 10. 验收矩阵与回退边界

| 类别 | 必须验证 |
|---|---|
| 配置L3 | 独立临时YAML无需快照路径，实际到输入布局、维度请求、batch、timeout等消费者；正式入口不依赖实验模块，无真实.env改动 |
| 输入 | 12Mock及超长用例；原文/context/view/hash逐项核验；raw/labeled/layout独立；缺来源/篡改/混模式/重复ID/跨库/超限0调用；空输入 |
| Provider | index反序/重复/缺失/越界；数量、model别名、dimension请求/输出、NaN/Inf/bool/零范数、usage未知；显式Key/目标/no retry/close与有界响应 |
| 批次 | 数量/字节两界限、稳定顺序；第2批Dense或Sparse失败，不返回部分成功；安全report保留已知/未知用量；deadline边界确定性测试 |
| Sparse | 单字开关、cvr_ltv/TC-01、重复词、query去重；词典/版本/HMM策略身份；缓存关键IO失败明确；M4后在相同范围评分 |
| 接线 | M2→真实M3组件；Doc和Query共用Provider/校验；正式QueryEncodingResult合同；替身/真实服务分账；M4/M5未接时如实说明 |
| 回归/工程 | 正式功能与未迁移消费者回归、compileall、pip check、git diff --check、依赖/未触碰资产hash；实验接口不作新增兼容验收。测试迁移保留行为/异常断言，不能以skip掩盖问题；没有应用构建时标不适用 |
| 业务质量 | 编码接口通过不等于检索通过；M4–M5用固定题/候选/预算、人工或合成标签分开对照，成本/延迟无数据留未知 |

回退以正式切片的可恢复状态和后续M4同版本索引为边界，不设计回到旧实验API的兼容通道。用户已允许正式主线摆脱实验入口；实际API/文件迁移仍须列明消费者、影响和测试。原始材料及对照结果不混入正式活跃索引，发布/部署/push等另按规则执行。模型/策略/文本变更需要独立索引身份，不能无验证激活混合版本。

## 11. 本轮实际梳理验证

```sh
.venv/bin/python data/research/spec0020-evidence/reference_probe.py
# exit 0，socket禁止；参考BatchProcessor模拟Sparse第二批失败：Dense=3，Sparse=2，success=2，failed=1
# 参考OpenAIEmbedding+SDK替身：embedding-3未发送dimensions；反序data保持反序；client仅显式api_key/base_url
# 真实jieba对照：参考cvr/ltv/tc/01；A2开/关/cvr_ltv/tc-01
.venv/bin/python -m pytest -q tests/test_embedding_probe.py tests/test_vector_embedding.py tests/test_keyword_index.py tests/test_retrieval_once.py
# 127 passed in 10.79s
```

探针仅选择原生类的方法，未运行参考pipeline/setup；第一次抽取类的注解依赖顺序错误（SparseEncoder尚未定义）修正了探针加载顺序，参考源码不改。SDK/编码故障都是替身，模型请求0；词项差异只证明机制，不证明哪条检索更好。成功输出与源码hash保存reference-probe.json；未把带raw词项的研究输出当生产日志。

上述127项为既有实验/旧查询契约验证，非M3新TDD/验收。本轮未重跑841全量、未安装SDK/改产品代码；新增规范只做文档检查。Model/Provider实际服务结果待后续单独核验。

## 12. 学习位置与唯一下一步

M3课堂预计4章、约9–12小节：①输入表示与hash/身份，②Provider协议与向量/usage校验，③中文词项及批次完整性，④正式查询编码与真实服务证据。按实现后的真实分支/确定性测试学习，不一次学完所有后端。现阶段已说明参考链路和差异，源码走读/本人调试/独立实现未评估，不新建虚假完成课。

当前唯一下一步：制定BatchProcessor成对编码Spec。Spec0021/0022/0023分别完成输入、SDK/Dense和真实Sparse离线接线（最新1004全量）；检索质量、整任务硬截止及真实服务未验收，本阶段真实服务请求0。
