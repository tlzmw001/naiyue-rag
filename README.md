# naiyue-rag

以RAG为核心的独立知识库Agent工程与实践课程。将Markdown需求、方案和既有用例变成可定位、可评测的知识证据，在独立任务上下文中搜索、精读、解释和补查，支撑另一条线的主测试Agent完成用例设计、问题排查、知识问答和自动化用例理解。长期覆盖Modular参考主要模块，反馈思想参考Self-RAG；生产级是建设目标，不代表当前成熟度。

## 首次克隆与验证边界

本仓库同时保留正式RAG核心、早期实验代码、设计记录、合成材料与课程笔记。当前正式使用入口见[独立示例](examples/core-demo/README.md)，依赖版本见根目录`requirements-*.txt`及对应锁文件；模型、路径和凭证按示例在本机配置。现有本地模型依赖与wheel锁经过macOS arm64/Python 3.12验证，不代表其他平台已完成安装验收。

真实`.env`、虚拟环境、`data/`下的索引/模型/实验运行产物、第三方源码克隆及调研原始抓取文件不提交。空凭证模板为[.env.example](.env.example)。自己的研究报告、候选记录和来源元数据保留；报告中指向本机clone、raw抓取目录或历史运行产物的链接，不表示这些资产随仓库提供，公开来源URL与固定commit仍可用于追溯。

`pytest tests`包含早期A2/向量快照与LightRAG实验回归，其中部分依赖未提交的历史`data/experiments/`快照、分词缓存和独立`.venv-lightrag`。因此文档中的本机全量通过记录不能当作“新克隆直接全量通过”的承诺；本次首次提交不重构这些历史测试，也不通过skip隐藏缺失资产。正式核心的确定性测试可从以下入口开始（需已安装对应测试/运行依赖）：

```sh
.venv/bin/python -m pytest -q tests/test_retrieval_smoke.py \
  tests/test_evidence_response.py::test_pipeline_is_real_consumer_and_encodes_once \
  tests/test_evidence_response.py::test_whole_json_limit_is_not_context_limit
```

这些入口使用合成材料和模型/Chroma替身，不需要真实Key或已保存的业务索引；不能替代真实模型、资料质量或生产性能验收。实际模型摄取/检索和可选本地重排需按独立示例显式准备，不会由这些测试代为证明。

## 当前阶段与下一步

2026-10-16，阶段A的 **M1–M6独立RAG核心已完成当前本地工程验收**：Markdown摄取/结构准备、成对编码、版本与双索引管理、范围检索/可配置BM25统计/RRF、GLM与本地CrossEncoder重排、完整证据/引用/预算及独立CLI。当前全量 **2151 passed in404.22s**。这不是生产成熟度或真实知识库质量声明。

用户已确认按[阶段A/B/C](docs/project-plan.md)推进；**当前处于阶段B系统学习，六章机制讲解与调试路线已覆盖，6.5本人定位练习待完成，独立调试能力未评估**，不继续扩Agent/MCP。具体小节进度、六章地图与真实代码入口见[学习路线](docs/1.0/learning-roadmap.md)。本人独立调试/实现能力仍需课堂和练习验证。

两种后端已有实质实现与实际调用：此前真实embedding-3＋GLM-5.2合成闭环，本轮真实CPU/同池对照及CLI接线。模型准备与两类配置见[独立示例](examples/core-demo/README.md)；实现/验证见[Spec0041](docs/specs/0041-m6-reranking-contract-and-glm.md)、[0042](docs/specs/0042-m6-evidence-and-independent-entry.md)、[0043](docs/specs/0043-m6-local-cross-encoder.md)。同池小样本跨文档题Recall@5：关闭1/3、GLM3/3、本地2/3；标签由助手构造未用户审核，不当真实资料通过。本地只覆盖重排，Embedding完全离线部署尚未验证。详细当前状态见[交接](docs/handoff.md)。

## M5.4–M5.5：统一检索与同版本补读

`HybridSearch(manager, query_encoder, hybrid_settings).search(...)`从原始问题只编码一次，按配置并行/串行运行两个真实Retriever，再等权RRF；默认示例[20/20/10/k60](examples/hybrid.example.yaml)沿参考，BM25统计方式global/scope可配。结果保留两路排名/分数、融合排名、版本和安全总追踪。7种原生场景中并行/串行结果一致；任一路或融合失败整次报错，准备错误即使trace缺失也保持原阶段与用量，见[Spec0038](docs/specs/0038-m5-hybrid-search.md)。

`KnowledgeReader(storage_settings)`消费同一个PreparedQuery，提供read_chunk、read_lines、related_documents；不重选latest、不读原始Markdown或.env、不调用模型/两路SDK。完整用例和实际SourceSpan保持，行号基于保存原文，支持LF/CRLF/CR与空文档；已有引用/名称配对只显式列出，不自动扩大范围或改变召回排序。预算超限明确失败，见[Spec0039](docs/specs/0039-m5-knowledge-reading.md)。

HybridResult/RerankResult是内部结果，含查询编码；ResponseBuilder已组装带预算、完整正文和引用的最终JSON证据，独立使用见[完全合成示例与命令](examples/core-demo/README.md)。M5的本机工程验收不证明真实知识库质量或生产性能，最小追踪不伪造ANN内部比较次数。

```zsh
.venv/bin/python -m pytest -q tests --tb=short
# M5模块最终：2046 passed in 341.34s (0:05:41)
```

## M5.2–M5.3：正式向量与关键词召回

[Spec0036](docs/specs/0036-m5-dense-retrieval.md)的DenseRetriever消费PreparedQuery，使用固定版本的原生Chroma查询；文档范围在原生top_k前过滤，返回完整Chunk及distance/score。沿参考score=max(0,1-distance/2)，显式score_kind，分数不表示答案可信度。51新增检查及全量1934 passed in263.99s通过，包含原生距离0/1/2、范围前置和跨进程来源回取。

[Spec0037](docs/specs/0037-m5-sparse-retrieval.md)的SparseRetriever消费同一PreparedQuery，由[示例配置](examples/sparse-query.example.yaml)提供top_k和statistics_scope。用户已要求两种模式用于对照：`global`复用全库持久权重，`scope`从已存词项按有效文档范围在内存重算；均只在范围内选top_k，不重新分词或Embedding、不改写BM25索引。结果记录模式/score_kind，零命中与异常分离。实际YAML→两分支与原生跨进程、手算权重对照已通过，切片96 passed in42.57s（51新增、45 Dense回归）；最终全量记录见Spec。

调用方先持有实际DocumentManager和QueryEncoder，问题只准备一次，再分别检索：

```python
from naiyue_rag import QueryPipeline, DenseRetriever, SparseRetriever, load_sparse_query_settings

prepared = QueryPipeline(manager, query_encoder).prepare(query, scope_document_ids=document_ids)
dense = DenseRetriever(manager).retrieve(prepared, top_k=dense_top_k)
sparse = SparseRetriever(manager, load_sparse_query_settings(sparse_query_config_path)).retrieve(prepared)
```

这是库级调用形状，变量由调用方配置/装配；尚未提供完整Hybrid工具响应。测试使用合成材料、真实本机索引与SDK MockTransport，真实模型POST0；真实资料质量、scope额外计算成本和大库性能仍待实测。

## M5.1：查询准备（2026-10-15）

`QueryPipeline(document_manager, query_encoder).prepare(query, scope_document_ids=..., exclude_document_ids=..., expected_revision=...)`实际串接纯请求预检、一次活动版本选择、文档范围投影、已存两路索引审计与M3问题编码。`scope=None`为全库、`[]`为空范围；未知ID明确失败。问题原文不改写，模型/表示/tokenizer/维度必须匹配所选索引，编码中激活新版本也不改变本次绑定。

返回严格`PreparedQuery`，状态为ready/unactivated/empty_scope/empty_index，包含所选版本、范围内文档与片段ID、成对编码及最小安全追踪。ready表示准备成功；该结果本身不含召回命中，上述正式Retriever/Hybrid是其消费者，最终证据在M6组装。失败返回安全`QueryJobError`，保留已选版本和本次已知编码用量。

```zsh
.venv/bin/python -m pytest -q tests/test_query_processor.py tests/test_query_preparation.py tests/test_query_preparation_wiring.py --tb=short
# 103 passed in 33.30s
.venv/bin/python -m pytest -q tests --tb=short
# 1883 passed in 229.56s (0:03:49)
```

5个原生跨进程场景覆盖正常、空范围、零片段、全空词项和混合词项；第三进程消费准备结果回读同版本完整片段/用例。使用真实本机Chroma/BM25/分词器与Embedding SDK MockTransport，外部网络阻断，真实模型POST0。固定样本检索质量、真实资料和大库性能尚未验证；当前每次准备仍完整加载资料包并审计两路索引。完整命令、全量结果与TDD修正见[Spec0035实施记录](docs/specs/0035-m5-query-preparation.md#12-实施与验收2026-10-15)。

## 配置 Key 和 Embedding 模型

[Spec0027](docs/specs/0027-project-dotenv-credentials.md)已实现项目凭证装配。先在项目目录复制空模板（不覆盖已有文件），再用编辑器填写标准API Key：

```zsh
cp -n .env.example .env
chmod 600 .env
```

根`.env`中填写`NAIYUE_RAG_ZHIPU_API_KEY=你的标准APIKey`，不提交该文件。只有空的[.env.example](.env.example)被Git放行。命名进程环境变量优先；不存在时只读显式项目根的.env，不向上查找、不插值或修改全局环境，空/非法值报固定错误。若当前终端曾export同名变量，它会覆盖文件值。

模型、协议、base_url和维度仍在[config/encoding.example.yaml](config/encoding.example.yaml)。`openai_compatible`表示接口协议，可用于兼容的云或自部署Embedding服务；更换模型同步设置维度/响应别名，已有向量需按新身份重建。当前Provider要求非空Key；无鉴权服务、原生Ollama及其他协议继续单独适配，未声称真实部署通过。

```python
from pathlib import Path
from naiyue_rag import load_embedding_provider

root = Path.cwd()  # 在项目根目录运行；应用也可以显式传入项目根
with load_embedding_provider(
    root / "config/encoding.example.yaml",
    project_root=root,
    key_env="NAIYUE_RAG_ZHIPU_API_KEY",
) as provider:
    print(provider.settings.embedding.model)  # 仅构造/关闭客户端，不发模型请求
    # 在实际调用处，用provider装配DenseEncoder、BatchProcessor或QueryEncoder。
```

该入口实际执行YAML→项目凭证→显式Provider；纯`load_encoding_settings`和旧实验命令不自动读.env。Key不会进入YAML/模型空间身份/结果报告。无模型请求的本地加载检查：

```zsh
.venv/bin/python -c 'from naiyue_rag.core.credentials import resolve_api_key; resolve_api_key(".", "NAIYUE_RAG_ZHIPU_API_KEY"); print("Key已解析，未发起模型请求")'
```

验证入口：`.venv/bin/python -m pytest -q tests/test_credentials.py tests/test_embedding_bootstrap.py --tb=short`，44 passed in1.26s；Spec0027当轮全量1211 passed in82.63s。测试使用合成Key与MockTransport，不证明真实Key权限/余额或本地服务效果。

## M4.7：显式文档移除与历史版本保留（2026-10-15）

[Spec0034](docs/specs/0034-m4-document-removal.md)已实现/接线并完成本地验收；全量1780 passed in201.57s。新增`IngestionPipeline.remove_document(document_id, expected_revision=...)`，从已保存的选定快照排除一份文档，与run共用完整M2/M3→资料包→Chroma/BM25→revision激活链。原Markdown及旧版本保留，不级联用例；保留引用产生明确诊断。原文件仍在目录时，后续主动run按新增重新纳入，符合用户已确认语义。

结果为严格`RemovalReceipt`：removed/not_found、请求ID、前后活动版本、旧文档摘要及本次编码报告。未命中不编码/新建版本，但已有版本仍审计并检查revision；最后一文档移除成为合法活动空库。处理身份不匹配明确报ingestion_profile_mismatch；构建失败、并发冲突和提交unknown沿原整次错误合同保留实际用量/状态。

```zsh
.venv/bin/python -m pytest -q tests/test_document_removal.py tests/test_ingestion_types.py tests/test_file_integrity.py tests/test_ingestion_pipeline.py tests/test_document_removal_wiring.py --tb=short
# 160 passed in 40.56s（含78新增）
.venv/bin/python -m pytest -q tests --tb=short
# 1780 passed in 201.57s (0:03:21)
```

四种原生跨进程场景完成新版本回取、完整旧版本审计/回读与既有消费者接线；Embedding用SDK MockTransport，真实模型POST0。首版全量重编码保留集，原始目录仍须满足构造校验；不提供物理擦除、GC或恢复API，M5查询/真实资料质量/大库性能另验。完整课堂暂挂，当前下一步见[交接](docs/handoff.md)。

## M4.6：正式摄取、重复判断与文档更新（2026-10-15）

[Spec0033](docs/specs/0033-m4-ingestion-and-updates.md)已实现/接线并完成本地验收。正式`IngestionPipeline`串接M1加载、源版本/策略判断、M2、M3编码、资料包/两路构建与原有activate。输入目录作为新增/替换集合，未提供的历史文档保留；完全未变时不执行编码/save/build，但仍执行两路完整审计与revision门禁。有变化或force时，首版对合并后的完整知识库重编码并构建新版本。

调用形状如下；调用方先用已有配置/Provider入口装配实际BatchProcessor，并持有Provider生命周期，本段未对真实目录或模型执行：

```python
from naiyue_rag import IngestionPipeline

pipeline = IngestionPipeline(
    storage_settings, ingestion_settings, batch_processor, chroma_settings, bm25_settings,
    knowledge_base_root=source_root, project_root=project_root,
)
receipt = pipeline.run(expected_revision=0)  # 初次；后续使用已读活动revision
# receipt.status / receipt.active / 四类文档计数 / receipt.encoding_report
```

回执中的编码报告只属于本次作业，复用时为None。失败抛IngestionJobError，保留实际编码观察、已知候选bundle_id和激活状态；冲突不覆盖其他写者，提交不确定标unknown，不自动重试/回滚/清理。force不绕过坏基线、索引健康、限额或来源检查。

```zsh
.venv/bin/python -m pytest -q tests/test_ingestion_types.py tests/test_file_integrity.py tests/test_ingestion_pipeline.py tests/test_ingestion_pipeline_wiring.py --tb=short
# 86 passed in 27.13s
.venv/bin/python -m pytest -q tests --tb=short
# 1702 passed in 170.29s
```

真实Sparse/Chroma/BM25+Embedding SDK MockTransport完成跨进程首次/重复、正常场景更新与历史保留，既有管理消费者回取完整用例；外部真实模型请求0。当前是库级入口，真实资料质量/大库/编码复用/移除与M5另验；Pipeline审计可能发生SDK内部维护写，不承诺M4.5管理读取的字节/mtime不变。完整课堂暂挂，下一步见[交接](docs/handoff.md)。

## M4.5：只读文档列表与详情（2026-10-15）

[Spec0032](docs/specs/0032-m4-document-management.md)已实现/接线并完成本地验收。`DocumentManager.list_documents()`返回当前活动版本的文档摘要；`get_document_detail(document_id, expected_revision=...)`返回该文档摘要与按原文位置排序的片段ID。公开结果为DocumentInfo、DocumentList、DocumentDetail；摘要保留逻辑ID、规范相对路径、原文hash、字节数与片段数。

一次读取固定一个已提交版本。列表的revision可约束后续详情；期间新版本激活会明确报catalog_revision_conflict。未激活、活动空库、文档未找到、空白文档有明确空态；损坏/超限报安全错误，整次失败。管理读取只核验元目录和规范资料包，不初始化两路SDK；索引健康继续由open_active核验。

```zsh
.venv/bin/python -m pytest -q tests/test_document_views.py tests/test_document_management.py tests/test_document_management_wiring.py --tb=short
# 84 passed in 14.86s
.venv/bin/python -m pytest -q tests --tb=short
# 1616 passed in 148.35s
```

真实M1/M2/M3+Embedding SDK MockTransport/真Sparse/Chroma/BM25先激活；新进程仅管理读取，再由另一进程消费详情ID回取完整用例。管理读取阻断网络、编码、源目录和.env读取，存储文件字节/mtime不变。这里只验证合成材料的工程接线；未测真实知识库质量/容量，也不承诺管理读取轻量：BundleStore仍加载完整编码并重核M2。完整课堂暂挂，下一步见[交接](docs/handoff.md)。

## M4.4：三类产物同版本激活（2026-10-15）

[Spec0031](docs/specs/0031-m4-same-version-activation.md)已实施并完成本地验收。`DocumentManager.activate(bundle_id, expected_revision=...)`实际串接BundleStore.load、ChromaStore.audit、BM25Store.audit；三类产物全部核验后，SQLite同一事务登记完整版本并切换唯一active。`open_active()`读取一次绑定、关闭目录连接后重新核验并返回固定ActiveVersion，后续配置改变不会替换它的集合名/k1/b。

- 相同完整版本返回unchanged且revision不增长；BEGIN IMMEDIATE序列化激活，陈旧revision明确冲突。候选失败保留旧活动版本；提交后无法确认则catalog_commit_uncertain，需重读确认。
- 初次未激活返回None，损坏/读取失败不当空库、不自动修复或退回旧版。正常/零片段/全空词表/混合词项、必要IO和双进程争用均有覆盖。
- 真实组件测试完成M1/M2/M3+Embedding SDK MockTransport/真Sparse→资料包/Chroma/BM25→激活→另进程重开与完整用例回取。L1修订、新增L2且保留历史L2、旧快照继续可读有合成验证。

```zsh
.venv/bin/python -m pytest -q tests/test_index_versions.py tests/test_document_manager.py tests/test_document_manager_wiring.py --tb=short
# 89 passed in 19.22s
.venv/bin/python -m pytest -q tests --tb=short
# 1532 passed in 127.11s
```

真实模型请求0，测试仅用隔离合成.env，真实项目.env未读改、无依赖升级或旧索引修改。这里是库级激活/重开；文档更新/移除、M5查询、真实资料质量与生产容量仍待分片验收。完整课堂继续暂挂，当前唯一下一步见[交接](docs/handoff.md)。

## M4.3：正式BM25S索引（2026-10-15）

[Spec0030](docs/specs/0030-m4-bm25s-storage.md)已实现：`BundleStore.load`→直接消费M3保存的`SparseRecord.tokens`→`BM25Indexer.build`→原生索引保存→`BM25Store.audit`重开与来源/数值审计。公开入口从`naiyue_rag.storage`导出；参数见[examples/bm25.example.yaml](examples/bm25.example.yaml)，`k1/b`可调。构建不需要模型Key或Chroma执行，不重新分词。

- 保留全部正式片段ID和行映射；部分空词片段保留零分行，零片段/全空词表保存明确empty状态，不向原生库发送空词表构建。
- Lucene/NumPy/float64、禁pickle；原生参数/NPY header、dtype/shape、文件哈希、词表和逐词项权重都核验。重算文件hash也不能让错行/错权重通过；NPY对象数组或夸张shape在原生数组加载前拒绝。
- 新候选目录审计成功后发布；重复构建返回unchanged、不改文件。坏库不补写，关键IO失败返回安全码，发布后fsync失败明确为不确定。
- 资料包、Chroma、BM25现可各自保存重开，跨库同版本激活属于M4.4。M5范围统计/召回/融合仍待；旧A2的scope内重算不等价于全库算分后过滤。

本轮新增54项通过；项目全量：

```zsh
.venv/bin/python -m pytest -q tests --tb=short
# 1443 passed in 111.38s
```

测试入口：[存储合同](tests/test_bm25_store.py)、[格式与数值故障](tests/test_bm25_integrity.py)、[真实组件跨进程接线](tests/test_bm25_native.py)。后者使用真实M1/M2/M3组件、Embedding SDK MockTransport、真Sparse/BM25S；正常/无片段/全空/混合词项均完成保存和另进程映射/分数对照，阻断重分词、Dense与网络调用。真实模型请求0、真实.env读改0、无依赖升级；这些是本地工程证据，真实资料/检索质量/生产容量另验。

## M4.2：正式Chroma索引（2026-10-15）

[Spec0029](docs/specs/0029-m4-chroma-index.md)已实现：已保存资料包→`VectorUpserter.build(bundle_id)`→原生Chroma→`ChromaStore.audit/get_by_ids`重开与来源回读。入口从`naiyue_rag.storage`导出；新适配消费正式M2/M3片段ID，不依赖实验unit。旧root同名类仍为实验入口。

- 配置：[examples/chroma.example.yaml](examples/chroma.example.yaml)只有集合名和批大小；存储根/知识库沿StorageSettings，模型/维度沿资料包。构造须显式`project_root`。正式代码同进程调用SDK，没有存储worker。
- 允许模型Key与原生Chroma字段共享项目`.env`；SDK实例显式读取`project_root/.env`。合法值按显式参数>环境变量>文件>SDK默认；重置关闭、遥测关闭和本地Rust后端由代码明确提供。SDK首次导入仍可能解析cwd/.env，非法已知字段会报`chroma_environment_invalid`，不会输出原始异常或值。
- 新索引独立目录构建、全量逻辑审计并关闭后发布；完整同版本返回unchanged，不再upsert。缺失/损坏不补写，失败不返回部分成功。来源/用例结构从核验后的资料包返回；索引回读不被资料包回填掩盖。
- “只读”约束业务记录；Chroma仍可能改内部文件。当前没有active指针、相似度查询/BM25S、更新删除、生产并发/性能验收。空库保留期望维度，不宣称SDK已绑定实际维度。

实际验证：

```zsh
.venv/bin/python -m pytest -q tests/test_chroma_index.py tests/test_chroma_native.py --tb=short
# 32 passed in 6.33s
.venv/bin/python -m pytest -q tests --tb=short
# 1389 passed in 99.55s
```

原生接线使用测试隔离进程内的合成.env、真实M1/M2/M3组件、Embedding SDK MockTransport、真Sparse与本地Chroma；写入后另一进程回读完整Chunk/用例、空库及异常启动通过。正式存储代码自身同进程执行。真实模型请求0、真实.env未读取/修改、无依赖升级；不能当真实资料或检索质量验收。下一步见[交接](docs/handoff.md)。

## M4.1：完整资料包存储（2026-10-14）

[Spec0028](docs/specs/0028-m4-artifact-storage-and-lifecycle.md)首片已实现：M1/M2原文、完整用例与来源关系，以及M3成对编码结果，经`prepare_index_bundle`严格绑定后，由`BundleStore.save/load`保存并重载。文件hash之外还会重核原文/位置/派生视图/输入hash/模型与分词身份。同一个完整包再次保存返回`unchanged`；关键IO失败显式报错，发布不确定单独标记。

入口：[storage包](naiyue_rag/storage/__init__.py)、[配置模板](examples/storage.example.yaml)。模板只含资源参数，相对目录`./data/indexes`解析为`examples/data/indexes`，由现有Git忽略规则覆盖；本轮未创建这个默认目录。初始化/配置加载无目录创建或模型调用。资料包是私有数据资产，包含必要原文和向量，日志与保存回执仅输出安全字段。

```zsh
.venv/bin/python -m pytest -q tests/test_storage_bundle.py tests/test_storage_bundle_wiring.py --tb=short
# 91 passed in 4.76s
.venv/bin/python -m pytest -q tests --tb=short
# 1357 passed in 98.29s
```

上述离线接线含真实M1/M2/M3组件、SDK MockTransport/真Sparse和独立进程重载，真实服务调用0。当前仅完成资料包，正式Chroma/BM25/活动索引与文档管理随后分片接入。支持本机串行保存，加载重做来源校验；大库、断电和多写者尚未验收。代码清理按已获授权在真实消费者完成替换后执行，当前四个相关旧模块仍有消费者，未删除。当前下一步以[交接](docs/handoff.md)顶部为准。

## M3服务验收记录（2026-10-14）

[Spec0026](docs/specs/0026-m3-supervised-service-check.md#9-实施与验收记录2026-10-14)已完成受监督小样本验收：项目.env/显式模型配置→M1/M2→成对文档和问题编码→安全检查点/关闭→父报告。embedding-3真实2次HTTP200，2文档向量+1问题向量均2048维，服务usage共91tokens；账单未知。新工具只发送固定两份合成Markdown和固定问题，不作为通用上传或生产任务入口。

```zsh
.venv/bin/python -m pytest -q tests/test_encoding_check.py tests/test_encoding_check_wiring.py --tb=short
# 55 passed in 6.31s（离线，含真实子进程终止回收）
.venv/bin/python -m pytest -q tests --tb=short
# 1266 passed in 89.33s
```

本次真实命令、两次请求分账和边界见Spec第9节；安全报告在`data/validation/20261014-spec0026-01/report.json`，不含Key/原文/向量。编译/依赖检查通过。全量首次因空.env.example缺失失败，补回后通过；真实.env未修改。无索引/召回/问答结果，不能把此次编码成功当业务质量通过。当前唯一下一步见[交接](docs/handoff.md)顶部。

## 已确认目标与建设入口

**2026-10-11推进方式更新：**按[模块主线M0–M9](docs/project-plan.md)从公共契约/配置、Markdown摄取、切分/元数据、编码、索引/管理、查询、重排/证据逐步建设，再接知识库Agent/MCP/管理与格式扩展。现有实验和Chroma是复用资产；[Spec0012](docs/specs/0012-live-query-embedding-preparation.md)暂停，先整理M0规范，本文不宣称完整产品模块已成熟。

主线已获认可；参考为默认骨架，重点适配Markdown、Agent策略和业务规则。[Spec0013：公共数据契约](docs/specs/0013-m0-core-contracts.md)及以下配置/查询追踪三片，已对当前A2消费者完成离线验收。M1–M5随后继续接这些基础能力；不代表通用摄取、完整产品或生产验收。

[Spec0014：YAML配置加载与资源装配](docs/specs/0014-m0-settings-loading.md)已实现/接线并离线验收：当时56新增/597总测试。入口`load_snapshot_from_settings(settings_path)`读取YAML、校验分组配置并装配既有A2资源；默认库内全部可检索，无文档授权清单，scope/exclude用于检索筛选。未改真实.env/YAML或依赖；仍是冻结合成资源兼容入口。

[Spec0015：统一最小查询追踪](docs/specs/0015-m0-minimal-tracing.md)已实现/接线：63新增/660总测试。沿参考请求上下文/收集器，成功与失败均交付安全trace_report，显式JSONL写入由`retrieve_with_trace`完成；写失败保留检索结果并标trace_persistence失败，双失败保留原检索错误。配置路径课已记Lesson7，新追踪代码尚未课堂/独立复写。

[Spec0016：M1通用Markdown原文加载](docs/specs/0016-m1-markdown-loading.md)已实现/接线：当时48新增/708总测试。普通目录无需manifest/Mock标记即可加载为Document，保留原文、字节版本及实际行起点；同库/路径更新保持ID。M2分块接线状态见下，新文档尚未编码/索引/查询。Loader与追踪课堂按用户要求暂挂。

[Spec0017：M2结构与可定位Chunk](docs/specs/0017-m2-source-bound-chunking.md)已实现/接线：当时39新增/747全量。M1 Document经结构扫描、可配置递归正文、完整业务块保护产出Chunk/SourceSpan；六组参数对照均保留合成完整用例，未选最佳检索值。

[Spec0018：M2规则文本准备与元数据](docs/specs/0018-m2-rule-preparation.md)已实现/接线：当时40新增/787全量。`prepare_document(document, chunker, text_mode=...)`实际串接切分、规则Refiner及Enricher，显式选择raw或labeled_case，保留原始Chunk及来源，派生检索文本有规则/内容指纹，标题和层级声明有依据。12份Mock两模式各12完整用例/248处原文回读通过，未验证哪种表示检索更好。

[Spec0019：M2显式文档关系](docs/specs/0019-m2-explicit-document-relations.md)已实现/接线：当时54新增/841全量。`prepare_knowledge_base(documents, chunker, text_mode=...)`实际返回片段、版本绑定的原文链接/精确名称配对及切分诊断，任一必要阶段失败整次报错；跨行代码/图片受到保护。12Mock→24链接/3配对/12完整用例/286处原文回读，共同11文档与旧A3的23边来源签名一致。尚未持久化、新编码/索引/查询。

[Spec0020：M3编码模块](docs/specs/0020-m3-encoding.md)按[ADR0005](docs/decisions/0005-formal-encoding-entry.md)建设正式独立入口。Spec0021输入、0022 SDK/Dense、0023真实Sparse及[0024成对BatchProcessor](docs/specs/0024-m3-paired-batch-encoding.md)已接线；本片97新增/最新1101全量。独立YAML→M1/M2→72输入→36批SDK模拟HTTP/真jieba→72成对记录与JSON报告；整次失败停止后批，保留已知请求/usage、未知不补0。没有真实模型/新索引；依赖版本保持，正式导入不加载实验。查询成对结果在下方Spec0025接线，硬截止和真实服务仍待，学习入口见[Lesson8](docs/1.0/lessons/lesson-8.md)。


[Spec0025：M3.4正式查询首片](docs/specs/0025-m3-query-encoding.md)已离线接线：`QueryEncoder(settings, dense_encoder, sparse_encoder).encode(query)`保留原问题，返回单向量、Sparse词频、稳定去重词项及报告；与文档使用同一配置身份，失败无部分结果。66新增/最新1167全量；真实SDK仅模拟HTTP、真jieba，真实模型0。完整检索/M5、硬截止和真实服务待验。

```sh
.venv/bin/python -m pytest -q tests/test_query_encoding.py tests/test_query_encoding_wiring.py --tb=short
# 66 passed in 5.61s
.venv/bin/python -m pytest -q tests --tb=short
# 1167 passed in 80.88s
```

2026-10-10总体方向已确认，见[ADR0004](docs/decisions/0004-knowledge-agent-goal-and-boundaries.md)。职责为主Agent完成用户任务→知识库Agent独立查证→RAG核心摄取/索引/检索/证据；A2作首个检索基线，Self-RAG思想用于需要证据、相关性、主张支持及任务效用检查，不声明复现特殊token训练/解码。

- [完整模块与分层](docs/research/target-architecture-and-module-map.md)：配置、摄取、编码、存储、查询、融合、重排、证据、MCP、追踪、评测、Dashboard、分层测试及后续PDF/图片扩展。
- [首切片Spec0010](docs/specs/0010-callable-a2-query-preparation.md)：一次新查询的A2调用/范围/预算/证据契约已完成离线接线，46新增/456总测试通过；真实新问题向量适配与完整知识库Agent尚未实施。
- [Spec0011：Chroma接入与参考参数对照](docs/specs/0011-chroma-reference-alignment.md)已完成：显式向量、cosine、持久重载、范围过滤与来源绑定，37新增/493总测试通过；A2配置证据顺序保持，参考fusion10在本组合成题减少必要覆盖。
- [当前交接](docs/handoff.md)与[学习入口](docs/1.0/README.md)：实际进度、验证、学习证据和唯一下一步。

总体目标不重复选；具体数据库、Agent框架、远端模型和各阶段接口在对应Spec确定，按一个小切片连续推进。测试Agent项目独立，本会话默认只修改本项目。

主要使用场景：模型已拿到新需求文档/L2、新服务的L1，或只有任务描述，调用知识库查找相关历史需求和历史用例，获得带来源与定位的片段后推理并编写新用例。历史用例可通过名称与L2或L1文档对应，具体命名一致性待样本核验。长期目标是纳入整个知识库；首个实验先用小型关联样本比较检索方法。

### M3成对编码验证入口

```sh
.venv/bin/python -m pytest -q tests/test_batch_processor.py tests/test_encoded_types.py tests/test_encoding_report.py tests/test_batch_wiring.py --tb=short
# 97 passed in 4.26s
.venv/bin/python -m pytest -q tests --tb=short
# 1101 passed in 74.91s
```

当前是离线库接口，编码器由调用方配置/初始化/关闭。`BatchProcessor(settings, dense_encoder, sparse_encoder).process(document_inputs)`只处理文档，成功返回成对`EncodingResult`，失败抛`EncodingJobError(code, report)`且无部分结果。正常/失败报告不包含正文/词项/凭证；请求次数和用量保留已知小计与未知状态。查询成对结果见Spec0025；真实模型、索引、业务质量另验，构建不适用。

## 当前状态（2026-10-11）

- 已初始化本地Git和独立Python 3.12.14 `.venv/`；固定LC splitter1.1.3、LlamaIndex core0.14.25、pytest9.1.1，新增jieba0.42.1/BM25S0.3.13，原83包版本不变，完整85包见`requirements-experiment.lock.txt`。
- 已建立项目规则、规划、交接、学习路线和参考项目的静态源码调研。
- 已有Markdown组件、模型接口、公共证据、A1/A2/A3/B0/B1实验与重放；Spec0010/0011/0013–0019已实现当前查询/存储资产/M0基础/M1加载/M2切分、规则准备与显式关系，Spec0021–0025接通正式输入/文档两路批处理与查询编码，最新全量1211 passed in82.63s。A3/B1当前配置无质量提升；尚无完整产品知识库Agent、MCP产品服务或真实大库验证，没有应用构建。
- 已明确目标材料是用户提供的 Markdown 需求、方案和既有用例；当前已用合成Mock建立A1固定基线，真实资料授权与验收仍待后续确认；见 [项目计划](docs/project-plan.md)。
- 已按用户确认的 `rndflow only research` 范围执行知识库/RAG/知识图谱关键词搜索；[方案调研报告](research/naiyue-rag-knowledge-base/report.md)保留当轮来源/候选，最新方向以ADR0004为准。A2初始基线已确定，最终后端/框架/部署模型按阶段验证。
- 已按照片中的通用结构建立[Mock样本v1](examples/mock-v1/README.md)：12份完全合成Markdown、4个讨论任务及来源位置清单。离线组件、A1/A2/A3已运行；远端真实资料未验证。
- 已确认并完成[第一轮检索对照范围](docs/decisions/0001-retrieval-experiment-scope.md)：A片段检索＋已有关系、B LightRAG图＋片段。公共片段、模型与8000预算固定，五组均运行，负向配置保留；结果不证明真实知识库质量或产品接线。
- 已按用户“执行”完成[Spec 0001](docs/specs/0001-offline-markdown-probe.md)：60条文档配置结果、195个真实组件片段，404项探针pass/76项fail。fail保留为结构缺口或源警告，不以测试通过宣布业务质量通过。
- 已按用户“继续”完成[Spec 0002](docs/specs/0002-embedding-api-probe.md)：智谱标准API的2次真实请求成功，3条合成文本各2048维，接口usage合计59输入tokens。按标价估算0.0000295元，真实账单未知；不作为检索质量或最终选型通过。
- 已完成[Spec 0003](docs/specs/0003-glm-generation-probe.md)：GLM-5.2共3次独立请求，前两次抽取校验失败；补诊断并澄清提示词后第三次通过结构、原文引用及4条合成事实检查。合计921输入/1156输出tokens，估算0.039736元，真实账单未知；不是LightRAG接线或跨文档质量验证。
- 五组A1/A2/A3/B0/B1范围及分阶段运行已确认；已完成前置[Spec0004公共证据单元](docs/specs/0004-common-evidence-corpus.md)：11份历史Mock→52单元（40正文/12完整用例），186处正文/上下文位置核对通过，最大单条渲染1104字符，1条失准手写行号警告。单文档范围也已核验，公共单元阶段模型调用0；五组中当前跑完A1/A2/A3/B0/B1。
- 用户允许扩大查询返回上限，首轮五组共同上限现设8000字符，见[当前预算决定](docs/decisions/0001-retrieval-experiment-scope.md)。Spec0004旧4000单条检查与产物保留；[A1 Spec0005](docs/specs/0005-a1-vector-baseline.md)已实施并真实验证。
- A1真实5请求HTTP200，56向量各2048维（52文档/4查询），7472输入tokens、估算0.003736元，实际账单未知。Q01前20召回4/8、最终覆盖2/8；Q02为1/5→0/5；Q03为2/2→2/2但排序仍有缺口；Q04无答案判断unknown。接口/工程接线成功不等于业务质量通过。
- [A2 Spec0006](docs/specs/0006-a2-bm25-rrf.md)已按“可以”实施并实跑；同语料/查询/向量缓存/预算，模型请求及网络尝试0。Q01必要返回2/8→3/8、Q02 0/5→1/5、Q03保持2/2，仍有召回/融合/预算遗漏；保留作当前比较基线。
- [A3 Spec0007](docs/specs/0007-a3-explicit-relations.md)已按“是的”实施：23条原文/名称关系、范围内两跳/分文档配额/再RRF/8000证据链已验证，0模型/网络。Q01必要返回3/8→2/8、Q02 1/5→0/5、Q03保持2/2；保留负向配置，不作为A2替代；B0接线已随后完成。
- [Spec0008：LightRAG接线/B0](docs/specs/0008-lightrag-b0-cache-wiring.md)已按“继续”实施：独立LightRAG1.5.7/62固定依赖、C!原11源→52完整单元、单文档独立10单元、缓存Embedding/禁止LLM、真实native存储/新进程重载/naive出口/8000证据已验证。31新增/368总测试通过；build/replay均0模型/0网络，结果与评测字节一致。候选/返回单元及指标与A1相同，分数最大差3.8331e-8；随后B1已完成，见下条，不能由B0工程通过宣称图有效。

- [Spec0009：B1模型图与mix](docs/specs/0009-lightrag-b1-model-graph.md)已完成真实接线、工程复核与无Key标准重放：原live审计bug失败保留，修复后复核既有52/10索引并补Q03，累计112真实HTTP/用量已记录，结果与评价重放字节一致；410测试通过。B1 Q01必要返回2/8与B0相同，Q02候选1/5→0/5，Q03保持2/2，当前图配置无质量提升；不是生产/真实材料/生成用例或MCP通过。

## 实验与验证入口

### M0公共数据契约（第一切片）

[core/types.py](naiyue_rag/core/types.py)含SourceSpan/Document/Chunk/QueryRequest/RetrievalResult，沿参考dataclass、保留源版本/位置/完整用例和检索字段；[core/errors.py](naiyue_rag/core/errors.py)统一错误身份，旧包/模块导出兼容。A2Snapshot实际构建源/片段类型，retrieve_once实际调用请求与候选映射，旧四题结果逐字段相同。

```sh
.venv/bin/python -m pytest -q tests/test_core_types.py tests/test_core_contract_wiring.py
.venv/bin/python -m pytest -q tests
```

本段为Spec0013当时结果：48 passed in1.35s；全量541 passed in51.83s。负cosine保留，非法/越权请求仍先于Embedding；类型往返/复制及安全错误有回归。139保护文件hash与135分发版本不变，无新模型或依赖。随后Spec0014补齐当前资源的YAML配置入口，状态见下；旧资源/算法迁移、通用Markdown摄取及统一追踪仍待，M0整体未验收。

## M0配置加载与资源装配（Spec0014）

本机离线库入口为`load_snapshot_from_settings(settings_path)`；显式传入本地YAML文件路径，返回供`retrieve_once`使用的A2Snapshot。配置文件结构见[Spec0014字段表](docs/specs/0014-m0-settings-loading.md)，暂未创建真实运行配置文件或自动加载.env。

配置分snapshot/embedding/retrieval/sparse/runtime，所有字段必填；资源及分词缓存的相对路径以配置文件目录为基准。默认加载库内全部可检索文档，无人员/文档授权清单；任务scope/exclude仍可筛选。配置中的模型/维度必须与当前缓存索引身份匹配，缓存目录必须不存在，不自动覆盖或重用。

验证入口：

```sh
.venv/bin/python -m pytest -q tests/test_settings.py tests/test_settings_wiring.py
.venv/bin/python -m pytest -q tests
```

实际56 passed in1.61s、597 passed in52.89s。新入口真实装配11源/52片段，配置路径实际产生分词缓存；原四题各路/预算/证据与A2精确相同。无新服务调用、依赖或真实配置修改；仍仅合成冻结资源，不是真实材料/动态模型/生产通过。

## M0最小查询追踪（Spec0015）

`retrieve_once`保留旧七阶段trace列表，并新增trace_report；原RetrievalError失败时附同名安全报告。报告含trace_id、UTC开始/结束、单调耗时、阶段数量及固定错误码，不记录用户问题或证据正文；未知usage为null，额外usage字段仅保留在旧结果，不写报告。

需要存储时显式使用`retrieve_with_trace(request, resources, embed_query, collector)`，collector由`TraceCollector(traces_path)`构造，路径由调用方提供；原入口不创建日志文件。成功写入追加一行JSONL，trace_persistence为written；写入失败为failed/trace_write_failed且检索结果保留。双失败保留原检索错误并附持久化状态，不重试/自动修文件。Collector初始化失败在查询前明确报错。

```sh
.venv/bin/python -m pytest -q tests/test_tracing.py tests/test_tracing_wiring.py
.venv/bin/python -m pytest -q tests
```

实际63 passed in5.26s、660 passed in57.99s，报告与实际JSONL重读相同，原四题候选/证据/预算保持。写成功仅表示write/close成功，不承诺fsync/多进程原子性；IO失败可能已有字节落盘。摄取追踪消费者、Dashboard、日志轮换和生产验证仍待。

### Chroma持久存储与A2对照

[ChromaStore](naiyue_rag/chroma_store.py)提供显式向量upsert/query/get/count；[实验入口](experiments/chroma_probe.py)从已验证源/向量缓存启动两个受控子进程，写入后退出，再重载审计和查询；随后复用BM25/RRF/完整证据/固定评测。现有retrieve_once仍使用Spec0010文件快照，此切片没有将所有调用入口自动切换到Chroma。

新增49个固定wheel、原86分发版本不变，依赖检查通过。以下增量锁适用于本次macOS arm64/Python3.12环境；其他机器尚未验证。先建立原实验环境，再安装：

```sh
.venv/bin/python -m pip install --no-deps --require-hashes --only-binary=:all: -r requirements-chroma.lock.txt
.venv/bin/python -m pytest -q tests/test_chroma_store.py tests/test_chroma_probe.py
.venv/bin/python -m experiments.chroma_probe --baseline-run data/experiments/a2-bm25-rrf/20261010T054002Z-99569e55 --output-root data/experiments/chroma-a2-reference --runtime-lock /Users/zmw/naiyue-rag/requirements-chroma.lock.txt --collection-name knowledge_hub --worker-timeout-seconds 60 --deadline-seconds 180
```

实际37 passed in1.64s；正式命令status=complete/model_calls=0/python_network_attempts=0。结果见[报告](data/experiments/chroma-a2-reference/20261010T172157Z-f331697b/report.md)与[完整终态](data/experiments/chroma-a2-reference/20261010T172157Z-f331697b/summary.json)。52条重复写仍52；另进程重载，正文/上下文/位置/版本精确校验，向量按已定float32容差审计。四题Dense顺序及A2最终证据顺序一致；Q01必要覆盖3/8、Q02 1/5、Q03 2/2、Q04N/A/unknown。另组参考20/20/10参数为2/8、0/5、2/2，不能归因为数据库优劣。

资料及缓存仍为Git忽略的合成实验资产，克隆后不自动拥有这些产物。SDK遥测关闭、Python socket/DNS阻断；Rust网络未独立观测。52单元与含启动/审计的耗时不证明大库ANN性能、业务质量、更新能力或生产部署。Embedding/Claude配置仍为后续接入范围，没有新增模型服务调用或修改真实.env。

### 可调用的一次A2查询

包入口：[load_snapshot](naiyue_rag/a2_snapshot.py)、[retrieve_once](naiyue_rag/retrieval.py)。资源配置/授权文档/新分词缓存目录由调用方显式提供；query/scope/exclude/候选数/字符预算在Embedding回调前校验，回调输出绑定查询hash和模型身份。旧冻结语料/索引仍是Git忽略的实验资产，克隆后不自动具备这些缓存。

```sh
.venv/bin/python -m pytest -q tests/test_retrieval_once.py tests/test_a2_snapshot.py
```

实际46 passed in8.25s；原四题用真实缓存向量与旧A2逐字段相同。新问题模拟回调只验证接口接线，不是真实Embedding质量；不自动读.env/调用模型。当前串行兼容层仍复用experiments的低层实现，每次核源快照，尚非独立发布/全库/高并发产品。完整契约、异常和TDD见Spec0010。知识库Agent底座首选建议为create_agent＋专用middleware，详见[底座取舍](docs/research/knowledge-agent-runtime-options.md)，本环境尚未安装Agent runtime。

在本目录执行：

```sh
.venv/bin/python --version
.venv/bin/python -m pip check
.venv/bin/python -m pytest -q tests
.venv/bin/python -m experiments.markdown_probe --dataset examples/mock-v1 --sizes 512 1024 --overlap 0 --output-root data/experiments/markdown-probe
.venv/bin/python -m compileall -q experiments tests
git diff --check
```

实验每次创建独立结果目录，输出`chunks.jsonl`、`summary.json`、`report.md`；退出0表示工具正常执行，不表示结构探针全部pass。当前报告见[实际结果](data/experiments/markdown-probe/20261009T145752Z-1c71c3e4/report.md)。data产物被Git忽略，克隆后需重新运行生成；代码及固定依赖可用于复跑，远端兼容性尚未验证。

独立环境复现：使用Python3.12建立`.venv`后，在该环境以`pip install --only-binary=:all: -r requirements-experiment.lock.txt`安装记录版本。没有应用构建，compileall仅为语法检查。测试和结构探针都不能验证RAG检索质量。

## Embedding接入核验

实现使用标准库HTTP，无新增依赖；读取本项目专用环境变量`NAIYUE_RAG_ZHIPU_API_KEY`，不自动加载`.env`。当前只是固定三条合成短文本的接口工具，不接受知识库文件；正式入口现已通过Spec0027支持项目`.env`；本节旧探针仍只读取命名环境变量。

以下命令会产生真实API请求，需有执行授权、专用凭证和预算；每次最多两次请求、不重试，整体120秒截止：

```sh
.venv/bin/python -m experiments.embedding_probe --endpoint https://open.bigmodel.cn/api/paas/v4/embeddings --model embedding-3 --dimensions 2048 --timeout-seconds 30 --deadline-seconds 120 --max-requests 2 --budget-cny 1 --unit-price-cny-per-million 0.5 --output-root data/experiments/embedding-api-probe
```

当前[实际报告](data/experiments/embedding-api-probe/20261009T155624Z-a4387149/report.md)只保存配置、输入hash、向量维度/范数、usage、余弦和安全错误信息，不保存Key、完整向量或原始响应。临时Key只在核验进程内传入；本轮没有写真实`.env`。data目录被Git忽略，克隆后没有本次结果；重跑会产生新的调用和费用。

## GLM生成接入核验

固定三行合成文本，用glm-5.2抽取实体、关系、关键词；结构与原文引用校验和合成事实检查分开。仍使用专用进程环境变量，不自动加载.env、不接受任意知识库输入。用户本轮取消生成核验费用门槛，每次最多1请求、不自动重试、30秒网络等待/120秒总截止。

以下命令会发起真实调用；需先在进程环境提供专用凭证：

```sh
.venv/bin/python -m experiments.generation_probe --endpoint https://open.bigmodel.cn/api/paas/v4/chat/completions --model glm-5.2 --max-tokens 1024 --timeout-seconds 30 --deadline-seconds 120 --max-requests 1 --input-price-cny-per-million 8 --output-price-cny-per-million 28 --output-root data/experiments/glm-generation-probe
```

[第三次实际报告](data/experiments/glm-generation-probe/20261009T174048Z-fca28a76/report.md)包含模型正文、校验后抽取、事实诊断及usage；首两次失败也保留，过程见Spec。data被Git忽略，克隆不会带上本机结果。status=complete表示接口与结构流程完成，quality_checks.passed单独标识合成事实检查；二者都不能代表真实知识库质量。无重试、最终问答、建图或MCP实现。

## 公共证据单元离线实验

复用固定LlamaIndex标题节点，增加完整用例行/来源适配；正文、维度、列名和来源说明各自保留实际原文位置。本入口输出共同实验语料，不建索引、不读取任务评分标签，不需要凭证或网络。

```sh
.venv/bin/python -m experiments.corpus_probe --dataset examples/mock-v1 --exclude-document-id MOCK-TASK-004 --max-evidence-chars 4000 --output-root data/experiments/common-evidence-corpus
.venv/bin/python -m experiments.corpus_probe --dataset examples/mock-v1 --include-document-id MOCK-CASE-001 --exclude-document-id MOCK-TASK-004 --max-evidence-chars 4000 --output-root data/experiments/common-evidence-scoped
```

每次独立输出sources.jsonl、units.jsonl、summary.json、report.md；超限/不支持/无法定位明确blocked、退出2，完整正文保留而非截断。当前[历史范围报告](data/experiments/common-evidence-corpus/20261010T021859Z-647de42b/report.md)和[单文档报告](data/experiments/common-evidence-scoped/20261010T021859Z-4821b020/report.md)在被Git忽略的data目录，克隆后需复跑。单条≤4000只证明它可单独返回，多条查询的总预算组装将在检索阶段实现。实际范围/位置检查不能替代召回质量或远端真实材料验证。

## A1向量检索与重放

使用52个公共单元，向量输入为语义上下文＋正文，原始cosine/范围先过滤/top20，完整证据按排名装入8000字符。实际查询从落盘索引重新加载；不调用GLM。实时模式需要此前专用进程环境变量，仍不自动读取.env。

完整live参数与命令见[Spec0005](docs/specs/0005-a1-vector-baseline.md#8-tdd影响文件与验证)。重放使用同一CLI参数，改为`--mode replay`并添加`--replay-run data/experiments/a1-vector-baseline/20261010T031953Z-52cfda4e`，输出新目录；仅接受有完整向量/索引/成功summary的原live目录，不默认补网络或支持重放结果目录再作为向量缓存。源码可用`.venv/bin/python -m experiments.vector_probe --help`查看参数。

[实际报告](data/experiments/a1-vector-baseline/20261010T031953Z-52cfda4e/report.md)、[简短失败分析](data/experiments/a1-vector-baseline/20261010T031953Z-52cfda4e/failure-analysis.md)及[零网络重放报告](data/experiments/a1-vector-replay/20261010T032159Z-45d42d2f/report.md)位于Git忽略的data。原始向量及索引不会随克隆提供；重放必须有原完整缓存。固定4题及标签为助手合成，非全部人工审阅；Q04有候选但系统unknown，不声称无答案识别通过。A1作为原失败基线保留，A2对照见下节。

### A2：BM25＋RRF离线对照（已运行）

jieba保留中文搜索词项/ASCII完整标识，BM25S在查询范围内建统计并保存/重载；原向量前20＋关键词前20→等权RRF(k60)→融合前20→完整8000字符证据。模型请求0；CLI阻断并计数连接/DNS，未观测的库调用网络标null。整体294测试通过，原A1结果/评测校验一致。

| 任务 | A1前20召回/必要返回 | BM25诊断前20召回/必要返回 | A2前20召回/必要返回 |
|---|---|---|---|
| Q01 | 4/8，2/8 | 6/8，2/8 | 5/8，3/8 |
| Q02 | 1/5，0/5 | 2/5，1/5 | 1/5，1/5 |
| Q03 | 2/2，2/2 | 2/2，2/2 | 2/2，2/2 |
| Q04 | N/A，N/A | N/A，N/A | N/A，N/A |

收益有限：Q01公式新返回，Q02旧用例新返回；仍有未召回/融合截断/预算排除，Q04系统unknown。仅合成固定集，不作为真实知识库或最终选型通过。详见[主报告](data/experiments/a2-bm25-rrf/20261010T054002Z-99569e55/report.md)、[逐条失败分析](data/experiments/a2-bm25-rrf/20261010T054002Z-99569e55/failure-analysis.md)及[Spec0006实际证据](docs/specs/0006-a2-bm25-rrf.md#9-2026-10-10实际实施与结果)。

本机已有完整缓存时可复现零网络重放（输出新目录，不需要Key）：

```sh
.venv/bin/python -m experiments.hybrid_probe \
  --mode replay --keyword-run data/experiments/a2-bm25-rrf/20261010T054002Z-99569e55 \
  --dataset examples/mock-v1 --tasks examples/mock-v1/tasks.json \
  --corpus-run data/experiments/common-evidence-corpus/20261010T021859Z-647de42b \
  --vector-run data/experiments/a1-vector-baseline/20261010T031953Z-52cfda4e \
  --endpoint https://open.bigmodel.cn/api/paas/v4/embeddings --model embedding-3 --dimensions 2048 \
  --output-root data/experiments/a2-bm25-replay --candidate-k 20 --rrf-k 60 \
  --bm25-k1 1.5 --bm25-b 0.75 --bm25-method lucene \
  --tokenizer-policy zh-search-ascii-ident-v1 --backend numpy \
  --max-context-chars 8000 --deadline-seconds 180
```

实际结果：status=complete attempts=0 network_attempts=0，exit0；评测文件与build字节相等，排名/返回除计时外相等。[完整实际argv/断言](data/experiments/a2-probe-evidence/live-replay-checks.json)在data；它与原生关键词索引均受Git忽略，克隆后不具备缓存，不自动补网络。

### A3：已有关系与分文档检索（已运行，当前配置退化）

11源构造20条原文引用/3条名称配对；2个未索引目标与1条失准旧行号保持诊断。查询范围内种子/两跳/L0终点、每文档4片段/局部RRF/关系路由20，再与A2等权RRF。新增43测试、总337通过；原85包环境及87份非切片资产hash不变，原A2结果/评价精确一致。已移除Key的新进程与重放模型/网络均0。

| 任务 | A2前20召回/必要返回 | 关系路由前20召回/必要返回 | A3前20召回/必要返回 |
|---|---|---|---|
| Q01 | 5/8，3/8 | 3/8，3/8 | 5/8，2/8 |
| Q02 | 1/5，1/5 | 1/5，1/5 | 0/5，0/5 |
| Q03 | 2/2，2/2 | 0/2，0/2（空） | 2/2，2/2 |
| Q04 | N/A，N/A | N/A，N/A | N/A，N/A |

关系找到了拆分/用例/命名文档，但局部配额、路由截断、再融合和预算损失关键证据。Q01新增返回E06/E07，却失去原E01/E02/E04；Q02原E03被推到最终rank23。Q03范围内无关联目标，候选/返回与A2精确相等；Q04unknown。工程通过不等于质量通过，当前A3不能替换A2，也不能据此排除所有关系方案。

[实际报告](data/experiments/a3-explicit-relations/20261010T071448Z-f02434ac/report.md)、[逐条失败](data/experiments/a3-explicit-relations/20261010T071448Z-f02434ac/failure-analysis.md)、[重放](data/experiments/a3-relations-replay/20261010T071448Z-eeebb96b/report.md)。无真实材料、生成答案或生产规模证据；现有合成标签仍not_reviewed，三组名称配对本来有显式引用，不单独归因其效果。

复现完整build命令见[Spec0007第8节](docs/specs/0007-a3-explicit-relations.md#8-验收与执行命令设计尚未运行)（现已执行，实际结果见第10节）；零网络replay用同参数，改mode=replay，增加`--relation-run data/experiments/a3-explicit-relations/20261010T071448Z-f02434ac`，output-root改为data/experiments/a3-relations-replay。原向量/A2关键词/关系索引必须完整存在；data被Git忽略，克隆没有缓存，不自动补网络。实际argv和相等断言见[final-live-replay-checks](data/experiments/a3-probe-evidence/final-live-replay-checks.json)。

**唯一下一步：汇总A1/A2/A3/B0/B1五组对照，讨论首期技术路线与真实材料验证要求。** 本次B1配置和负向结果保留，不通过调参数改标签提高分数。

## 阅读入口

1. [协作规则](AGENTS.md)
2. [交接记录](docs/handoff.md)
3. [项目计划](docs/project-plan.md)
4. [学习路线](docs/1.0/learning-roadmap.md)
5. [参考项目调研](docs/research/modular-rag-mcp-server-2026-10-09.md)
6. [Markdown 测试知识库方案对照](research/naiyue-rag-knowledge-base/report.md)

## B0实际验证入口

B0是缓存驱动的真实SDK实验，不是生产服务。运行依赖独立`.venv-lightrag`、固定词表和Git忽略的原公共语料/A1缓存；克隆仓库不会携带这些本机产物。安装范围及完整实际命令见[Spec0008](docs/specs/0008-lightrag-b0-cache-wiring.md)。

```sh
.venv/bin/python -m pytest -q tests
.venv/bin/python -m compileall -q experiments tests
.venv/bin/python -m pip check
.venv-lightrag/bin/python -m pip check
```

B0收尾结果：`368 passed in 31.23s`（历史记录；最新B1收尾为410项通过）；compileall退出0/无输出，仅语法检查；两环境pip check均`No broken requirements found.`，应用构建不适用。[B0报告](data/experiments/b0-lightrag-naive/20261010T082212Z-fae04e9e/report.md)、[逐条失败](data/experiments/b0-lightrag-naive/20261010T082212Z-fae04e9e/failure-analysis.md)、[重放](data/experiments/b0-lightrag-replay/20261010T082228Z-90499945/report.md)仅对本机可用；软件/词表准备使用网络，摄取/查询/重放阻断网络。

## B1实际产物

[Spec0009第11节](docs/specs/0009-lightrag-b1-model-graph.md)包含原live失败、工程复核和标准replay的真实命令/结果及调用记账。当前完整产物明确标engineering_revalidation，原失败run保留；[报告](data/experiments/b1-lightrag-mix/20261010T093445Z-04ab215d/report.md)、[失败分析](data/experiments/b1-lightrag-mix/20261010T093445Z-04ab215d/failure-analysis.md)、[无Key重放](data/experiments/b1-lightrag-mix/20261010T093652Z-8142cfdd/report.md)只在本机Git忽略的data。

```sh
.venv/bin/python -m pytest -q tests
env -u NAIYUE_RAG_ZHIPU_API_KEY .venv/bin/python -m experiments.graph_probe --config data/experiments/b1-probe-evidence/live-config.json --mode replay --graph-run data/experiments/b1-lightrag-mix/20261010T093445Z-04ab215d
```

实际410 passed in39.95s，重放status=complete attempts=0；配置/语料/索引/cache不随Git克隆，缺失必须失败。真实材料与生产能力仍待验证，代码课堂暂停。
