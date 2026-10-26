# Spec0011：沿Modular实现接入Chroma（本机切片已实现与验证）

日期：2026-10-10。用户已授权先做Chroma，并要求尽可能参考相同实现/参数、不同之处先讨论。基础解释后接受建议，随后明确“可以开始按你的建议做了”。Cloud已澄清为Claude，其生成接入与Embedding配置分开。**本Spec的独立Chroma适配及本机固定缓存对照已实施，实际证据见第9节；不代表所有应用入口已切换后端或完整产品通过**。与Spec0010同属已确认总体目标，不重新讨论是否做向量数据库/重排。

## 1. 来源与当前数据流

Modular main commit `f658c5a4011c8b826707a65a3b11ce9301b0626f`，本机只读目录`/Users/zmw/MODULAR-RAG-MCP-SERVER`工作区干净。追VectorUpserter.upsert→生成ID/records→ChromaStore.upsert→collection.upsert；ChromaStore初始化PersistentClient/Settings/get_or_create_collection，query显式query_embeddings/n_results/where/include并转相似分数。pyproject仅约束chromadb>=0.4.0，未锁定原运行版本。

本项目当前Spec0010 load_snapshot→核源/文件向量/授权范围→查询向量回调→精确Dense/BM25/RRF→完整预算证据。已有unit_id、源版本/位置、完整用例契约必须保持。新切片只加Chroma及旧向量/问题对照，不改Embedding/分词/派生文本/重排，不删除旧结果。

官方资料：[Collection配置](https://docs.trychroma.com/docs/collections/configure)、[Query/Get](https://docs.trychroma.com/docs/querying-collections/query-and-get)、[Embedding函数](https://docs.trychroma.com/docs/embeddings/embedding-functions)、[Python客户端](https://docs.trychroma.com/reference/python)。本地持久客户端先验证开发链，生产服务端/认证/并发/备份另阶段验收。

## 2. 版本与依赖方案（准备阶段记录，实际安装见第9节）

本机Darwin arm64/Python3.12.14；现有分发86项（含pip），chromadb/onnxruntime未安装。PyPI核验chromadb1.5.9支持Python>=3.9且有macOS arm64 abi3 wheel；下载后只静态读取5份源码并核SHA256，不运行第三方setup/模型/SDK。

用全部现有分发版本作为constraints，`pip install --dry-run --only-binary=:all:`解析成功：新增49包，旧版本变化0。计划包含ONNXRuntime等Chroma声明的依赖，但不使用其默认Embedding或下载模型。具体名称/版本/hash保存在Git忽略的data/research/chroma-design-20261010/planned-packages.json，解析与wheel/来源记录同目录。不是实际安装/导入/跨机器兼容结果。

建议在当前独立RAG .venv内按固定hash安装这些新增wheel，不升级既有包；新增requirements-chroma.txt/requirements-chroma.lock.txt记录新增依赖及原约束，不覆盖旧锁。实际安装前须确认此具体依赖方案；安装后核元数据旧版本保持、pip check和旧456测试。禁止sdist构建、第三方setup或静默换版本；解析成功不代替导入/原生持久存储测试。

## 3. 与参考保持一致的部分

| 项目 | 参考源码/配置 | 本片建议 |
|---|---|---|
| 部署接法 | PersistentClient(path=配置) | 保持本机PersistentClient，目录来自本项目配置/独立run，绝不写参考目录 |
| collection名称 | knowledge_hub，可配置 | 保持此默认名称语义，值经配置显式提供，各run路径隔离 |
| 距离空间 | hnsw:space=cosine | 保持cosine；优先使用该固定SDK兼容/推荐API表示并核实际configuration，不能只看metadata |
| 写入 | collection.upsert，显式ids/embeddings/metadatas/documents | 保持显式upsert；同ID重复写数量不增长，内容/来源校验 |
| 查询 | query_embeddings、n_results、where | 保持显式向量与候选上限；允许范围由应用层生成过滤条件 |
| include | metadatas/distances/documents | 保持三类载荷，缺字段明确错误，不补假距离 |
| 分数展示 | max(0,1-distance/2) | 保留reference_similarity展示，同时登记distance及cosine=1-distance；RRF桥接用正确标识的cosine，不能将0–1分数叫原始cosine |
| 遥测 | anonymized_telemetry=False | 保持关闭，并监控本片原生查询网络尝试，配置被接受不等于没有外发 |
| HNSW其他项 | 参考未显式设置 | 不擅自调参；记录1.5.9实际生效默认值，不声称等于未知原运行版 |
| 召回/RRF | 配置20/20/10、k60 | Dense20和k60一致；融合宽度用两组显式对照，见下表 |

配置写法可能随版本变化，但语义参数尽量相同。静态源码存在legacy hnsw metadata转换；实际创建与重载仍须验证cosine生效，不能以兼容函数存在当完整接线证明。

## 4. 必须讨论的适配建议

| 差异 | 参考方式 | 推荐适配及原因 |
|---|---|---|
| 固定版本 | chromadb>=0.4.0 | 固定1.5.9与完整hash，当前参考没有可还原的唯一版本 |
| 重置/删除能力 | Settings.allow_reset=True，Store含clear/delete | 本片allow_reset=False，不暴露reset/clear/delete；当前目标是写入/查询/重载对照，删除管理后续按已定权限规则建设 |
| 默认Embedding | 未传embedding_function，保留SDK默认 | 显式embedding_function=None，仍传我们已有向量，防止未来误调用query_texts而切换模型或下载权重 |
| SDK配置读取 | Settings默认env_file=.env，包导入构造全局Settings | 实验SDK在受控空工作目录的子进程加载、显式Settings(_env_file=None)并约束环境；产品加载规范后续定，不改/透读真实.env |
| 片段ID | source_path hash＋chunk_index＋text hash | 保存既有unit_id并保留来源/版本；否则已有原文/关系/评测映射断开，本片不迁移所有ID |
| 复杂元数据 | 列表逗号连接、其他对象str转换 | 索引过滤字段用scalar，原Evidence/位置/上下文保留无损JSON或canonical映射；模型返回仍为原完整证据，避免丢结构 |
| 范围与结果校验 | 简单where构造；结果字段缺失可默认空/距离0 | 实际授权∩请求−排除生成where，结果范围/ID/版本/正文/距离逐项核对；空是正常、后端/映射失败明确错误，沿已认可策略 |
| 融合宽度 | 参考默认fusion_top_k10；旧A2为20 | 首组只换Dense、保持20/20/20/8000作单变量；另组用参考20/20/10/k60。分开报告，旧结果不回写，不未经对照把两变量收益归因数据库 |

本片按参考方式写我们自己的适配，不复制整个参考类。根目录未找到独立许可证文本的既有观察保留，若后续直接复用代码再核授权与来源，不因“成熟项目”跳过本地验证。

### 4.1 Embedding可配置要求与本片边界（讨论补充）

用户明确要求模型由用户配置，原“Cloud”随后澄清为Claude。Anthropic当前[官方Embedding说明](https://platform.claude.com/docs/en/build-with-claude/embeddings)明确没有自有Embedding模型；Claude支持放在知识库Agent的推理/生成接入范围，Embedding单独选择OpenAI兼容接口或本地模型服务等已核验后端，不声明Claude原生Embedding支持。embedding-3/2048仅为当前实验配置，不是产品固定模型。“禁用Chroma默认Embedding”表示由应用显式选择适配器生成向量，不限制用户选择模型。

参考固定commit的EmbeddingFactory实际注册openai/azure/ollama；OpenAIEmbedding调用OpenAI客户端embeddings.create(input/model)，AzureEmbedding调用AzureOpenAI并使用deployment_name；OllamaEmbedding逐条调用/api/embeddings(prompt)。这些是源码事实，未运行参考服务。当前官方OpenAI接口为[Embeddings](https://developers.openai.com/api/reference/resources/embeddings/methods/create)，Ollama当前文档为[/api/embed](https://docs.ollama.com/api/embed)，input支持单条/数组、响应embeddings；未来本地适配需按目标版本核验，不直接照搬旧端点。

设计建议：按实际协议复用适配器，分别配置协议、模型/部署名、连接地址、凭证引用与模型相关参数；本地若提供OpenAI兼容Embedding接口可复用同协议适配，Ollama原生接口另适配。云厂商支持范围以真实Embedding接口核验为准，聊天兼容不证明Embedding可用。本轮只记录需求与建议，不登记适配器已实现/已接线。

每份索引绑定实际模型及版本/权重修订（可获得时）、向量维度与文档/查询编码策略；查询必须使用匹配的编码空间，相同维度不足以证明可比较。实际模型或关键编码策略变化时新建索引并重新向量化，保留旧索引供对照；换Key/等价地址不必自动认定模型变化，但必须核验兼容。当前identity仅有endpoint/model/dimensions/policy_id，完整多后端身份/迁移另Spec，不在本片悄悄更改公开契约。

本Chroma对照仍复用既有缓存向量，不加入新模型或新协议变量。基础解释后用户已接受此前建议，Claude含义已澄清；依本Spec推进现有Chroma切片，不重复请求同一适配批准。Embedding适配优先沿参考原生SDK/HTTP方式的建议与知识库Agent的LangChain底座分开，完整多后端接口仍在后续Spec设计/验证，不扩入本片。

## 5. 范围、数据流与契约草案

只用本机11历史Mock/52公共unit及A1真实缓存2048维向量、原四问题向量，模型请求0。单文档scope仍检查10单元。新的query向量API、知识库Agent循环、重排/网络服务、真实材料/CPU模型不在本片。

建议流程：核原源/向量/配置→新run与显式Chroma配置→受控SDK worker写入52→count/ID/向量/元数据/正文对齐→持久化退出→新进程只读打开同collection并核配置/身份→按真实允许范围query→映射canonical证据→原BM25/RRF/8000→检索后labels评价→保存结果/差异/终态。SDK内部持久化可有正常运行文件写入，所谓查询进程“只读”是禁止业务upsert/删除/补建，不冒充字节级只读文件系统。

ChromaStore职责为初始化/显式批次upsert/query/get_by_ids/count；不预填不需要的删除方法、其他厂商工厂或整个参考框架。查询输出保留id/距离/reference_similarity/metadata/text，不假装分数全是原始cosine。证据映射按ID查，不能假设SDK返回数组顺序等于请求IDs。

实验入口配置必须显式包含keyword_run作为原A2对照目录；旧A2构建配置中该值可能为None，不能直接原样当作新实验配置。入口验证必需路径并在启动worker前解析为绝对路径。新增测试准备函数补齐该目录属于测试输入修正，未修改验收断言、已有测试或共用helpers；旧原文、缓存与结果保持不变。

应用scope配置来自受信资源，用户不能直传任意where扩大范围。空允许集合直接返回空候选，非法范围/metadata/模型维度/identity失败阻断；collection缺失/错误空间/不完整snapshot不得自动创建或修复成成功。写入准备可create，重载查询只能get。

## 6. 影响文件（设计清单，均已实施）

- 包内新增`naiyue_rag/chroma_store.py`：实质SDK适配，单文件≤500。
- `experiments/chroma_probe.py`与`experiments/chroma_worker.py`：输入/worker监督/重载与完整A2对照，复用已有低层检索/评价；不改Spec0010公开签名或已验证字段语义。
- `tests/test_chroma_store.py`与`tests/test_chroma_probe.py`：模拟错误＋真实SDK持久重载/过滤/映射/对照，不改旧tests/helpers。
- 上述新增依赖记录与README/handoff/学习入口；实际job/config只在新data run显式提供，不改真实.env或全局运行配置。

本片约5新源码/测试＋2依赖文件，另文档同步；如果实现发现契约需改先更新Spec，不能顺手迁移整个已有实验目录。没有新外部服务。

## 7. TDD与验收

1. 写模块缺失红灯后最小实现；真实SDK接口/版本错误按单假设复现，连续三次失败停止。
2. 固定SDK/model/vector/corpus/参数身份，写52、重复upsert仍52，取回ID/metadata/正文/原生向量可核对；原生向量对float32转换值使用rtol=1e-6/atol=1e-8，原生cosine distance与1−精确cosine的绝对误差≤1e-6。ID/正文/metadata严格相等，不放宽为近似；ANN候选与精确排序差异记录，不要求字节相同。
3. 新进程get现有collection；cosine实际配置、默认Embedding禁用、reset拒绝、missing collection失败，出错不返回假空。
4. 两路实际scope一致，单文档只有指定材料，非法/排除scope与数据库错返回被阻断；用例正文/上下文/源位置/版本不变。
5. 与旧A2对比Dense top20交集/距离与排序差异，保持BM25精确一致，分别报告两组融合profile候选/必要返回与预算损失；不以小样本或测试通过证明ANN大库性能/业务质量。
6. 本机SDK真实运行、模拟HTTP/错误、真实旧向量和原材料各自标注；0模型调用，网络阻断失败诊断可见。52小样本不足以证明HNSW性能，实际底层路径未观测时未知。
7. 原456测试、compileall、pip check、文档/配置/依赖hash均通过；源码≤500，旧包版本/旧原文/向量/A2结果不改。应用构建不适用，不发布/部署/push。

## 8. 实施前准备证据（历史记录）

PyPI元数据、arm64 wheel的5份源码/hash、86原分发constraints和新增49项固定计划在data/research/chroma-design-20261010；dry-run退出0，计划旧版本变化0。未安装chromadb、执行SDK/模型或写真实Chroma数据库，未创建上述产品源码/新测试，不能说原生接线通过。

以上为实施前状态。当前实际实施、失败与验收见下节。

## 9. 实际实施与验收（2026-10-10）

已新增ChromaStore、chroma_worker/chroma_probe、两份测试和两份增量依赖记录，沿本项目已有supervise/worker_environment/offline_guard、源加载、BM25/RRF/证据/评测复用；没有复制参考类代码。37项新增测试通过，详细全量结果见handoff。

TDD与修复过程如实保留：首先2个收集错误为新模块不存在。Store最小实现31测试通过；首次原生子进程因旧相对路径读取缓存失败，源代码将路径解析为绝对路径；随后新增测试准备函数缺keyword_run导致None路径，补齐必需对照输入并在源入口显式校验，不修改验收断言或已有helpers。36测试/492全量通过后，发现reset检查可把任意IO失败当正常拒绝，追加回归红灯“DID NOT RAISE”，只改源代码接受AuthorizationError，其余reset_check_failed；37测试通过。裸pytest误收集research第三方测试产生96收集错误，后续严格使用既有pytest -q tests命令，不删或skip第三方/本项目测试来通过。

实际增量安装命令：

```sh
.venv/bin/python -m pip install --no-deps --require-hashes --only-binary=:all: --disable-pip-version-check --cache-dir data/research/chroma-design-20261010/pip-cache -r requirements-chroma.lock.txt
.venv/bin/python -m pytest -q tests/test_chroma_store.py tests/test_chroma_probe.py
.venv/bin/python -m experiments.chroma_probe --baseline-run data/experiments/a2-bm25-rrf/20261010T054002Z-99569e55 --output-root data/experiments/chroma-a2-reference --runtime-lock /Users/zmw/naiyue-rag/requirements-chroma.lock.txt --collection-name knowledge_hub --worker-timeout-seconds 60 --deadline-seconds 180
.venv/bin/python -m pytest -q tests
.venv/bin/python -m compileall -q naiyue_rag experiments tests
.venv/bin/python -m pip check
git diff --check
```

安装退出0：49新wheel，86原分发版本不变；SDK在worker核49版本及源码/原生库RECORD哈希。37 passed in1.64s；最终全量493 passed in49.25s，compileall退出0、pip check为No broken requirements found、git diff --check退出0；没有应用构建。正式最终run为data/experiments/chroma-a2-reference/20261010T172157Z-f331697b，CLI退出0、status=complete/model_calls=0/python_network_attempts=0。此前171734Z-acc12a17保留，不回写其结果。

L1：3实质源码/2测试/2依赖文件存在，源码单文件均≤500行。L2：SDK显式参数、source canonical JSON无损、完整批校验、授权scope前过滤、结果绑定与安全错误、固定float32/距离审计真实实现。L3：main→run→load_corpus/load_index→受控writer(Store.upsert/count)→进程退出→reloader(Store.get/audit/query)→原Sparse/fuse/pack→最后evaluate→终态/报告，实际CLI完整走通。查询进程拦截SDK create/upsert，调用数均0；没有切换retrieve_once既有文件后端。

52→重复52→另进程52；完整原文/上下文/版本/实际位置与ID校验精确通过。向量相对float32期望最大绝对误差1.4901161193847656e-8；四题distance最大误差6.91343928216348e-7≤原定1e-6，没有放宽容差。真实reset拒绝为AuthorizationError/401，缺collection为NotFoundError；identity不符明确拒绝，不当空结果。

实际配置公开字段为hnsw.space=cosine、ef_construction100、ef_search100、max_neighbors16、resize_factor1.2、sync_threshold1000、embedding_function=None；其他未暴露字段/查询实际底层路径未知，不能声称与未知参考版本默认完全相同。52单元不足以证明ANN大库性能。

| 任务 | 原A2 / Chroma A2必要覆盖 | Chroma参考fusion10覆盖 | Dense顺序/最终A2证据顺序 |
|---|---|---|---|
| Q01 | 3/8 / 3/8 | 2/8 | 一致/一致 |
| Q02 | 1/5 / 1/5 | 0/5 | 一致/一致 |
| Q03 | 2/2 / 2/2 | 2/2 | 一致/一致，指定文档10单元 |
| Q04 | N/A / N/A | N/A | 一致/一致，系统unknown |

Sparse与旧A2逐字段相同。Dense交集20/20/10/20，排序一致；reference profile改变融合宽度而非数据库，Q01/Q02降低不能归因为Chroma。Recall按相关公共单元计，必要覆盖按标注源范围完整覆盖计；标签仍assistant_constructed/not_reviewed，既有质量缺口未解决。

SDK遥测关闭且Python socket/DNS阻断0尝试；Rust原生网络未独立捕获，不能把Python计数当全进程网络证明。增量锁仅本机arm64/Python3.12已验证，真实大库/更新/并发/生产服务/新Embedding/Claude/Agent/MCP均未因此通过。120项旧源/测试/Mock/锁/基线hash保持；最终核验见handoff。构建不适用，compileall为语法检查。

**唯一下一步：逐行讲解ChromaStore.query的范围约束与原文绑定，用具体查询验证理解；教学未登记为独立掌握。**
