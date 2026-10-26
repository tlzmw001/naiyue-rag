# Spec0033：M4.6 重复摄取、文档更新与正式 Pipeline

日期：2026-10-15。状态：**用户已接受，M4.6已实现并完成本地验收**。沿已认可的[完整版本重建路线](0028-m4-artifact-storage-and-lifecycle.md)及[活动版本](0031-m4-same-version-activation.md)，将 M1–M4 接成统一的库级摄取入口。本片没有服务、CLI、权限、删除或增量编码合并。

## 1. 具体场景与本次价值

G1 已保存 `L1_Module(v1)、L2_A、L2_A_测试用例`。本次源目录提供 `L1_Module(v2)、L2_B、L2_B_测试用例`：应在新的 G2 中替换同路径 L1，加入 B，并保留旧 A 和旧用例。原始目录没有提供 A，不代表删除授权。再次提交同样内容与处理策略，应在编码前发现没有变化，复用已激活版本。

用户早前已接受完整版本构建后激活的 M4 路线。本 Spec 细化执行合同：**未变化时不编码；有变化时先对合并后的完整知识库重新编码、构建完整三件套，再激活**。首片不混合旧 EncodedRecord 和新报告，不将“更新一个文件”称作“只计算一个文件”。代价与后续优化见第 8 节。

当前缺口是应用编排和源版本判定，不是缺少 SHA256 或另一套数据库。完整课堂继续暂挂；本轮机制说明不登记本人独立实现或调试能力。

## 2. 参考项目：自述、当前源码与适配差异

来源：[MODULAR-RAG-MCP-SERVER](https://github.com/Jerry-ai-dev/MODULAR-RAG-MCP-SERVER)，只读目录 `/Users/zmw/MODULAR-RAG-MCP-SERVER`，本轮核对分支 main、commit `f658c5a4011c8b826707a65a3b11ce9301b0626f`，工作区干净，调研日期 2026-10-15。核对 README、DEV_SPEC、pyproject 及 10 个相关源码/测试文件的指纹与入口，保存于 `data/research/spec0033-evidence/source-review.json`。本轮没有查询远端、执行参考 Pipeline/测试/setup/Skill，不能声称验证其真实服务效果。pyproject 声明 MIT、Python>=3.10，依赖给出范围而未证明其实际安装版本；本片独立实现，不复制第三方代码。

### 2.1 真实调用链

```text
scripts/ingest.py:241–263
  → IngestionPipeline(settings, collection, force)
  → run(file_path)
      compute_sha256(file_path)
      → should_skip(file_hash)；force=False 且 success 时直接返回
      → PdfLoader.load（再次打开原文件）
      → DocumentChunker → Refiner/Enricher/Captioner
      → BatchProcessor → dense_vectors/sparse_stats
      → VectorUpserter.upsert → Chroma
      → 把返回的 vector_ids 写入 sparse_stats.chunk_id
      → BM25Indexer.add_documents(..., doc_id=document.id)
      → 注册图片 → FileIntegrity.mark_success
      异常 → mark_failed → PipelineResult(success=False)
```

定位：[Pipeline](https://github.com/Jerry-ai-dev/MODULAR-RAG-MCP-SERVER/blob/f658c5a4011c8b826707a65a3b11ce9301b0626f/src/ingestion/pipeline.py#L234) 的检查在 234–248，编码在 375–386，存储在 438–453，成功/失败登记在 523–550；构造 141–190 已初始化各组件，跳过不等于没有启动成本。

[FileIntegrity](https://github.com/Jerry-ai-dev/MODULAR-RAG-MCP-SERVER/blob/f658c5a4011c8b826707a65a3b11ce9301b0626f/src/libs/loader/file_integrity.py#L243) 的 SQLite `ingestion_history` 以 file_hash 为唯一主键（185–194），should_skip 只查 hash/status（243–268），路径和 collection 是成功记录字段。它没有把路径、collection、Embedding/表示/分词/切分策略纳入该跳过条件。失败状态允许后续重新处理；mark_success 更新成功记录，但不是与两个索引共同提交。

### 2.2 不能直接照搬的更新保证

- DEV_SPEC:198 自述基于成功 hash 的零成本增量；本片只借鉴“昂贵步骤前判断”，不把 hash 扫描、旧包核验、SDK审计/初始化说成零成本。
- VectorUpserter:143–166 的存储 ID 使用路径 hash 前8位、chunk_index 和正文 hash 前8位。正文变了，ID 会变；Pipeline 的这条写入链未先删除旧 ID 差集，不能仅凭 upsert 证明旧修订全部退出检索。
- PdfLoader:99–100 的 document.id 是 `doc_`+内容 hash 前16位；Pipeline:450 将它交给 BM25.add_documents。BM25:342–343/394 的移除按存储 ID 的 `startswith(doc_id)` 匹配，前者与实际存储 ID 格式不同。这是本轮复核到的参数/源码事实；[既有调研第4节](../research/m4-storage-and-lifecycle-2026-10-14.md)记录了历史局部探针，本轮没有重跑该参考探针或整个 Pipeline，不报告参考 Chroma 中实际遗留条数。
- DEV_SPEC:272–282 自述存储原子性；该 run 实际顺序写 Chroma、BM25、图片和历史表，没有共同事务/旧数据补偿。失败时历史失败记录不等于已经撤回前面的写入。
- 参考 integration/test_ingestion_pipeline.py:167–217 有重复/force 的集成测试定义；本轮只读，不能把测试存在当作已经运行通过或覆盖上述身份差异。

| 职责 | 参考实现 | 本片方案与理由 |
|---|---|---|
| 流程编排 | Pipeline 串行安排加载到存储 | 沿用 IngestionPipeline 名称与串行主链，复用现有正式组件 |
| FileIntegrity | SHA256+独立 SQLite 成功历史 | SHA 已由 MarkdownLoader 同一次内容读取产生；以活动目录+规范资料包为成功事实，纯比较模块不再维护一份成功表 |
| 跳过身份 | file_hash/status | 稳定文档ID+源版本+切分/模型/表示/分词及索引策略；只与当前 active 比较 |
| 更新 | 逐文件写现有集合 | 合并旧快照和新源，整包/两路构建新版本后原子切换 active，避免混合修订 |
| 未提供文件 | 逐文件入口不隐含删除 | 目录为新增/替换输入集，不是删除清单，未提供的旧文档保留 |
| 成功时点 | 两路/图片完成后 mark_success | 仅 DocumentManager.activate 成功返回后，才能报告当前版本摄取成功 |
| force | 绕过成功 hash 判断 | 只绕过未变化分支，不绕过路径/来源/限额/revision/完整性检查 |
| 失败 | 返回 success=False，保存异常文本 | 抛安全 IngestionJobError，保留本次编码报告/候选ID和激活状态，不记录原始异常/原文 |

不新增 FileIntegrityChecker 抽象基类、可插拔历史库、通用注册器或多种 Pipeline 框架。本片只使用一个确定的纯比较实现。

## 3. 当前正式链与已有幂等的实际位置

```text
MarkdownLoader.load_all → Document(id=hash([KB,相对路径]), source_sha256=本次原字节hash)
  → prepare_knowledge_base：全批次切分/规则准备/显式关系
  → prepare_document_encoding_inputs → BatchProcessor.process
  → prepare_index_bundle → BundleStore.save
  → VectorUpserter.build + BM25Indexer.build
  → DocumentManager.activate(bundle_id, expected_revision)
  → list_documents/get_document_detail/open_active
```

现在这些操作由测试或监督工具分别装配；搜索正式包没有通用 IngestionPipeline，也没有摄取前的源版本 gate。validation.encoding_worker 是编码验收作业，不负责正式知识库更新；旧 a2_snapshot/实验消费者也不是本片入口。

| 已有入口 | 现在保证什么 | 没有保证什么 |
|---|---|---|
| MarkdownLoader.load | 同一次读取产出内容/hash，稳定逻辑ID，实际位置 | 不判定是否已摄取、不调用模型或存储 |
| BundleStore.save | 同一个完整资料包再次保存为 unchanged | 在它之前已经发生编码；bundle_id 含作业报告，不是源版本去重键 |
| 两路 build | 相同 bundle+对应索引策略可复用已核产物 | 不提供源文件更新编排或编码缓存 |
| activate | 同一完整版本 unchanged/revision不增；最终 revision 门禁 | 不决定哪些源文件应替换/保留，不自动编码或构建 |
| M4.5 list/detail | 一次固定源快照，版本/数量/来源核验 | 管理可读不证明两路健康，不是摄取成功的快速替代判据 |

本轮本机合成探针：两次独立编码的文档ID、源版本、source_fingerprint相同，EncodingReport.job_id及 bundle_id不同，两次 save 均 ready；重复保存原同一对象才 unchanged。使用测试 Fake Dense/Sparse、模型请求0，记录 current-dedup-probe.json。首次临时目录参数因 macOS `/var` 符号链接被严格路径检查拒绝，改用该临时根的 resolve 后通过；未修改生产路径检查。

## 4. 新入口、内部职责与数据流

新增库级接口，既有公开签名、构造和存储格式保持：

- `IngestionPipeline(storage_settings, ingestion_settings, batch_processor, chroma_settings, bm25_settings, *, knowledge_base_root, project_root)`。
- `run(*, expected_revision, force=False) -> IngestionReceipt`。
- 从顶层 naiyue_rag 公开导出 IngestionPipeline、IngestionReceipt；IngestionJobError 位于既有 core.errors。

使用实际 BatchProcessor；其 Dense/Sparse/Provider 生命周期仍由调用方持有。调用方可沿已有 load_embedding_provider 装配云端或兼容的自部署服务。本片不新建厂商协议、客户端工厂、懒加载回调、Key 参数或自动关闭调用方资源；不修改真实.env。构造不发模型请求，但调用方装配模型/Sparse以及后续 Chroma SDK 可能读取凭证、初始化资源，不能承诺无Key启动或完全无副作用。

run 扫描显式 knowledge_base_root 中全部普通 Markdown，**永远解释为新增/替换集合**。读取失败整次失败；没有枚举到的旧源保留，文件在扫描与加载间消失则沿 Loader 明确报错，不伪装成“未提供”。不加入单文件/任意 Document 输入第二入口或同步删除模式。

```text
validate：校验请求、配置与注入组件的一致性
  → select：一次选定 active+规范资料包，核验 expected_revision
  → load：MarkdownLoader.load_all 取得本次输入
  → plan：按稳定 Document.id 合并旧/新，得到源变化分类与 reuse_active
      ├─ 可复用且 force=False
      │    → manager.activate(旧bundle, expected_revision)
      │      完整两路审计+事务内revision再核对 → unchanged回执，无本次编码报告
      └─ 初次 / 有变化 / force=True
           → 全部合并文档重做M2及输入预检
           → 一次 BatchProcessor.process（全候选片段）
           → prepare_index_bundle → BundleStore.save
           → VectorUpserter.build → BM25Indexer.build
           → manager.activate(候选bundle, expected_revision)
             核验三件套并切换active → 当前回执+本次真实EncodingReport
```

选定基线复用 DocumentManager._document_bundle 的事实读取合同：一次选定元目录、revision门禁、同包身份核验；该方法不替新 Pipeline 决定跳过或成功。先前管理方法无改动。不调用 list/detail 迭代拼装正文，也不调用会重新选 latest 的 open_active 作为旧快照。

复用分支直接调用原 activate，原因是最终返回前仍需验证两路完整性和事务内 revision。它会获取原有短事务并执行审计；不是 M4.5 的纯管理只读路径，不能承诺 Chroma 原生内部文件字节/mtime不变。未变化只承诺**不执行 BatchProcessor/Dense/Sparse编码、不新建资料包或索引版本、不增加活动revision**；不新增失败降级或后台修复。

实现细化：对于需要构建且已有active的分支，在编码前使用原DocumentManager._audit和已选版本保存的集合/k1/b审计旧三件套；不重新选择latest，审计描述必须等于已选版本。此检查落实坏索引不能被force绕过的原合同；复用分支仍在原activate中审计，不重复增加一次健康审计。

批处理/存储不持有整个作业时长的目录写锁；最终 activate 继续使用原事务门禁。期间有别的写者激活时，本次候选明确冲突，不自动刷新基线/重试或覆盖别人刚提交的版本。

## 5. FileIntegrity 的具体比较合同

新 ingestion/file_integrity.py 是内部纯规划模块，隔离源合并/策略判断和 Pipeline 的 IO；不是重复实现 SHA256。内部 plan_ingestion 接收已选 active/base_bundle、本次 Documents、显式knowledge_base_id、目标切分/编码/分词/索引配置及 force，返回私有计划：merged_documents、added_ids、updated_ids、unchanged_ids、retained_ids、reuse_active。无数据库、网络、时钟、环境读取、回调或存储写入。

1. 输入 Document 深复制并复用现有严格文档/原文/相对路径校验；KB、稳定ID、重复路径/ID必须一致，禁止用文件名或目录级别猜角色/关联。旧包先由 BundleStore 完整核验。
2. 相同ID的 incoming 替换 base。same ID+same source_sha256 为 unchanged；same ID+different hash 为 updated；base 中不存在为 added；base 未出现在 incoming 中为 retained。四组按ID排序、互斥，和覆盖全部合并文档；merged_documents按ID排序。相同字节不同路径是不同ID，不合并。
3. 未提供的历史文档保留旧原文。目录空且已有 active 不表示清空；无 active 且目录空则构建合法活动空库。路径改名视为新增，旧路径仍保留；自动识别改名/移除另片。
4. reuse_active 必须同时满足：已有active；added/updated均空；合并源集合与旧集合完全一致；IngestionSettings 的 chunk_size/chunk_overlap 一致；EncodingSettings 的 model_space_id/representation_id 一致；实际 BatchProcessor.tokenizer_id 与旧结果一致；Chroma collection_name 和固定SDK/存储策略一致；BM25 k1/b和固定SDK策略一致；force=False。
5. 不用 mtime、bundle_id、文件内容hash单字段、数据库中“曾经成功过”代替上述组合。仅比较当前active，不在历史版本中命中后自行复活旧版。同路径回退为较旧内容也属于本次 updated；没有业务生效时间判断能力。
6. 编码 runtime 批大小/超时、Sparse缓存路径或Chroma写批大小本身不作为语义版本变化；实际 tokenizer_id/模型/表示身份仍必须一致。当前请求适用的新文档数、输入大小、批次数及安全资源限额仍先检查，不能因复用而绕过。当前EncodingSettings把query_prefix也纳入representation_id，沿用其现有身份语义，不在此拆分。

完全相同源下 profile 变化也进入完整构建分支，包括只改 BM25 k1/b 或集合名。现有底层可手动对同包构建另一索引，本片自动入口先不新增“只重建索引/只重分词/只重算Dense”的多级执行计划。

本前提依赖旧资料包能被当前代码完整核验。坏包、旧schema不兼容或索引损坏不能靠force绕过；应先明确报错，再用独立修复/迁移方案处理，不把有问题的基线作为正常空库。

## 6. 结果、失败与必要观察

新增严格 IngestionReceipt，精确字段：status、active、added_document_count、updated_document_count、unchanged_document_count、retained_document_count、encoding_report。

- status 复用实际 ActivationReceipt 的 activated/unchanged；active为该次真实返回的 ActiveVersion。force保证尝试完整处理，不保证物理结果一定不同/revision一定增长。
- 四个count为非bool非负整数，和等于active.version.document_count；反映源变化分类，profile变化不伪造updated数量。
- encoding_report为本次实际 EncodingReport 或None，深复制、严格to_dict/from_dict/JSON往返、安全repr，无原文/向量/词项/绝对路径。若执行编码，报告success/empty，paired_input_count等于当前active片段数；完全复用时None，不把旧包报告冒充本次用量。不新增total_cost=0等没有依据的字段。
- 本次报告和差异计数在激活前验证；收到合法ActivationReceipt后组装返回，不在提交后额外执行文件写入、事件回调或可选观测。

失败不返回部分成功回执。新增 `IngestionJobError(stage, code, *, encoding_report=None, candidate_bundle_id=None, activation_status='not_attempted')`，字段严格、安全repr/消息且防御复制：

- stage闭集：validate、select、load、plan、prepare、encode、bundle、vector、bm25、activate、finalize。
- code仅允许既有StorageError.CODES、编码报告ERROR_CODES，以及本片 `ingestion_invalid_request`、`ingestion_failed` 和 `ingestion_{stage}_failed`（上述stage）闭集。真实StorageError/EncodingJobError沿已知安全码保留；其他已知/意外异常映射所在阶段固定码，不拷贝str(error)、URL、异常栈或原始cause。错误对象不返回部分编码结果。
- encode抛EncodingJobError时保留它的实际报告；编码成功后下游失败，仍保留这次成功编码报告，整次摄取失败与编码成功分别表达。发生编码前/报告不可得时为None，不伪造零用量。candidate_bundle_id仅在save成功返回合法ID后填入，发布不确定时不能猜。
- activation_status闭集：not_attempted、not_committed、activated、unchanged、unknown。进入activate前失败为not_attempted；activate抛真实StorageError时，catalog_commit_uncertain为unknown，其余现有闭集码为not_committed，依据Spec0031当前代码对提交过程/提交后关闭失败的单独映射；激活阶段非预期未知异常保守为unknown。已收到回执后的意外组装失败保留实际activated/unchanged，不能写成未提交。阶段与状态一并校验：activate之前只接受not_attempted，activate错误只接受not_committed/unknown，finalize错误只接受已返回的activated/unchanged。未来激活错误合同变化时，必须同步本映射和测试。
- 每个失败记录固定stage/code/activation_status，底层已有安全日志保留；不空catch、静默降级、重试、修复索引或自动恢复旧active。KeyboardInterrupt/SystemExit不变成正常失败回执，继续传播并依赖既有事务资源清理；不因此保证中断时已知提交结果。

| 分支 | 本次效果及返回/异常 |
|---|---|
| 非法force、revision、配置或组件不一致 | run入口拒绝；force严格bool，revision非bool整数0..MAX_REVISION；不开始源扫描、编码或存储写 |
| 初次有效空库/空白文档 | 真实M3 empty报告，构建合法零片段版本，无模型请求；与损坏分开 |
| 完全重复 | 完整审计+事务门禁后unchanged；report=None，编码执行次数0 |
| 有变化或force | 候选全量编码/三件套成功后才报告实际activate状态 |
| 源扫描/编码/保存/单路构建失败 | 不调用activate，旧已提交版本继续可用；保留实际编码报告；不自动删除候选/pending |
| 构建期间别人激活 | 最终catalog_revision_conflict，不覆盖对方新版本；已花编码用量仍保留 |
| 提交结果不确定 | 报unknown，调用方通过原目录重读确认；不能声明旧版本必定保持或自动重提 |
| 旧库损坏/两路审计失败 | 明确失败；不因为源未变就跳过健康检查，不返回空库/正常unchanged |

不新增摄取历史表或自动报告持久化；活动目录是成功事实，当前阶段日志/返回报告是作业观察。跨进程作业历史、UI进度、取消、断点恢复另按真实消费者接入，不把本片叫完整生产作业系统。

## 7. 配置、影响文件与实现次序

沿既有 StorageSettings、IngestionSettings、BatchProcessor.settings/tokenizer_id、ChromaSettings、BM25Settings。实际示例已核：storage为max_documents=1000、max_chunks=10000、max_file_bytes=16777216、max_bundle_bytes=67108864、max_manifest_bytes=65536；Chroma knowledge_hub/batch_size=100；BM25 k1=1.5/b=0.75。这些是示例起点，不是新硬编码或最佳值声明。M1单源读取使用传入StorageSettings.max_file_bytes；资料包JSON/向量等依旧受现有完整存储限额控制。

在编码前检查合并文档数/单源大小、M2片段数和prepare_document_encoding_inputs/plan_encoding_batches当前限额；复用分支也对旧规范输入执行当前输入预检。包序列化及原生最终大小仍由原存储检查，可能在编码后才失败；如实保留费用/用量观察，不能承诺所有超限均零模型调用。

同一实例不支持配置热更新或并发run；每次run复核注入BatchProcessor及Dense/Sparse配置身份匹配，构造与数据复制规则不得假称隔离了调用方的所有并发修改。多进程竞争沿既有revision门禁检测，不新增长写锁/后台任务或全局ContextVar。

预计**9个源码/测试文件**，加必要阶段文档会超过8个总文件；全部限定本片。单源码文件不超过500行，先搜后扩展，无依赖/运行配置/存储schema/真实.env变更：

| 文件 | 具体职责 |
|---|---|
| naiyue_rag/ingestion/file_integrity.py（新） | 内部计划与纯源合并/profile比较；复用已有hash/文档校验，不另建历史库 |
| naiyue_rag/ingestion/pipeline.py（新） | 接线上述组件、阶段边界、编码前复用、整次失败与最终激活 |
| naiyue_rag/core/ingestion_types.py（新） | 严格IngestionReceipt及本片字段/状态校验，不放IO |
| naiyue_rag/core/errors.py | 增加IngestionJobError/本片安全闭集，复用EncodingReport校验 |
| naiyue_rag/__init__.py | 在现有基础导入完成后公开Pipeline/Receipt，核验无循环导入/experiments反向依赖 |
| tests/test_file_integrity.py（新） | 合并、源变化、策略、force、非法与空态纯测试 |
| tests/test_ingestion_types.py（新） | 回执/错误往返、计数/状态/报告、深复制和脱敏 |
| tests/test_ingestion_pipeline.py（新） | 主链/重复/更新/失败/报告/并发门禁的确定性测试 |
| tests/test_ingestion_pipeline_wiring.py（新） | 实际正式链及原生跨进程消费者，HTTP模拟与真实服务分开 |

Pipeline是新的真实应用消费者，不能从tests导入编排或借用旧实验入口；测试复用既有合成材料/SDK替身，不改conftest或建平行测试框架。ingestion/__init__.py维持底层加载/切分出口，避免其导入Pipeline后与storage.artifact_bundle形成循环；正式包顶层导出在现有基础导入后完成。

实现次序：DTO/纯计划先确认预期红灯；再接通首次摄取/重复/更新；补失败/报告/冲突；最后真实原生跨进程、旧回归与全量。发现合同需变更先改Spec。没有已被本入口替代且无消费者的旧源码；旧实验保存为对照，不在本片删除或整体搬迁。

## 8. 代价、替代方案与回退

最小路径就是本片的“无变化复用；有变化完整重建”。CPU/磁盘/编码成本随**候选全库**增长；没有实测库规模就不承诺延迟或费用。10倍资料量时，预计先受全库编码次数、原文/编码包读取及两路构建/审计成本影响，须实际测量。即使改一个参数也会重编码，属于首片可解释的一致性取舍。

更细粒度的候选方案是只编码变化片段并复用旧Dense/Sparse记录，但必须另外实现：以来源/正文双hash/模型/表示/分词身份核对复用；处理新文档加入后关系/派生视图变化；将既有记录溯源与本次请求用量分开；构建严格完整的新EncodingResult。当前BatchProcessor/EncodingReport是一次完整作业合同，不能把旧结果直接贴上新job_id或伪称此次已编码全部。该优化归后续独立Spec，在基础闭环和成本实测后再实施。

外部服务故障整次失败，保留可用旧active，无自动降级/重试；构建完成但激活未成功的候选保留，不自动清理。回退时停止调用新入口，继续用既有显式存储/激活链，无schema迁移。不自动回滚active、删除索引或恢复源文件；这些动作另有目标/范围确认。

本轮实施验收只用合成Markdown、测试隔离.env和HTTP MockTransport，真实服务预算0请求，不需要新Key/账号/MCP/第三方CLI。真实模型端到端、大库、生产并发/断电、真实材料质量、删除/改名、编码复用、M5检索和Agent均不作为本片实现或通过声明。

## 9. TDD与接线验收清单

先确认测试因缺少新入口/合同而红，不能把环境错误当功能红灯或放宽旧断言。关键路径必须有可独立运行的确定性测试：

1. DTO未知/缺字段、bool/负计数、四count总和、active/status/报告状态、当前报告paired数及JSON/深复制/安全repr；错误字段/code/stage/outcome严格闭集。
2. 新库完整M1→M4激活并被M4.5/open_active读取；零文档与有空白文档，report empty、模型0；无假文档/假用量。
3. 完全重复在BatchProcessor.process前被判定复用；禁止process/save/两个build，确认原activate仍执行审计/门禁；无新增版本/revision增长。独立进程重复也成立，不依赖内存缓存。
4. 同路径L1修订+新L2/新用例形成G2，历史A/旧用例保留、文档ID稳定/hash变化；G1可通过原底层资料包读取，G2当前片段不混入旧L1修订；M2关系按合并完整集更新。
5. 输入目录不含历史A/目录为空仍保留A；文件实际读取失败不回退旧内容。不同路径同字节为两个文档；路径改名新增且保留旧路径。只改mtime不重编码，真实字节/换行变化不靠mtime跳过。
6. 相同源下单独改变chunk_size/overlap、模型空间、表示/前缀、实际tokenizer_id、collection、k1/b，分别进入完整构建；只改执行批大小/缓存路径且实际身份不变，可复用但受新限额检查。force=True完整处理，force非bool/非法revision在run源扫描和写入前失败。
7. load/plan/prepare/encode/save/vector/bm25/activate各阶段故障停止后续调用，无部分成功；编码中断保留失败报告，编码成功后存储失败保留成功编码报告。原始合成正文/Key/异常信息不能进入日志、异常字符串或DTO。
8. 旧包/目录/索引损坏不当空库/正常unchanged，force不绕过。任何必要IO关闭失败仍可观察；不自动修复、删除、恢复旧指针或重试。
9. 候选构建期间实际激活另一个版本，最终revision冲突且不覆盖新版本；提交不确定标unknown、保留报告/已知候选ID，可由原目录重读确认。用事件/确定性故障注入，无短sleep断言。
10. 当前doc/chunk/input/请求/存储限额生效；编码前可判断的超限必须零请求；只能在编码后判断的包/原生超限明确整次失败且保留真实用量，不截断资料或放宽断言。
11. 新正式入口使用真实M1/M2/M3+OpenAI SDK MockTransport/真Sparse/Chroma/BM25；新进程重复及更新成功，另一消费者用active和详情ID回取完整用例/来源hash。正常、零片段、全空词项和混合分支有覆盖；socket阻断真实网络，Chroma只用测试隔离.env，模型请求计数与报告相符。
12. 老构造/activate/open_active/list/detail、BundleStore/两个索引的真实消费者保持；旧测试不改，依赖/配置不变，正式包不引experiments、不产生循环导入。旧原生SDK内部维护写仍沿已确认边界，不把新Pipeline当M4.5严格只读接口。

拟验证命令：新增四测试文件定向运行；现有M4基础八测试文件回归；`pytest -q tests --tb=short`全量；`compileall -q naiyue_rag tests`、`pip check`、`git diff --check`及新文件白空/文档链接。子进程用显式60秒超时；编码沿传入runtime的请求/时限，不新增生产超时默认值。项目无独立应用打包构建入口，不适用，不用compileall冒充打包成功。

L1是新入口/DTO/安全错误/导出存在；L2是源计划及完整执行并非占位；L3是正式Pipeline被独立进程真正调用，结果供既有M4管理/原生回取消费。三者与真实检索质量、生产验收及本人学习掌握分别记录。

## 10. 设计轮验证与当时下一步（历史）

本轮只修改阶段文档/本地调研证据，未编写上述新生产模块或测试；参考项目只读，未执行其Pipeline或测试。源码核对、本机Fake探针与历史参考局部执行分开登记。现有测试实际命令：

`.venv/bin/python -m pytest -q tests/test_storage_bundle.py tests/test_storage_bundle_wiring.py tests/test_index_versions.py tests/test_document_manager.py tests/test_document_manager_wiring.py tests/test_document_views.py tests/test_document_management.py tests/test_document_management_wiring.py --tb=short`

输出 **264 passed in36.55s**，仅证明本轮已存在的M4基础回归。1616全量是M4.5上一实施轮结果，本轮没有将其当作M4.6验证。最终编译/依赖/diff/文档链接与资产核对见 `data/research/spec0033-evidence/verification.json`；本轮没有模型POST、真实.env读改、依赖/配置/既有索引/其他仓库修改、删除、提交或push。

唯一下一步：用户确认本Spec细化的“输入集新增/替换并保留历史、当前源与策略未变则复用、有变化首版全量编码、完整构建后带revision激活”合同后，按第7/9节TDD连续实施M4.6。


## 11. M4.6实施与验收（2026-10-15）

用户明确接受本Spec后，按9个源码/测试文件范围实施。顶层公开IngestionPipeline/IngestionReceipt；ingestion.file_integrity为纯源比较；原DocumentManager、IndexCatalog、BundleStore、两路存储及编码公开签名/格式保持。Provider由调用方创建和关闭，不复制真实Key/环境。

### 11.1 红灯、实现细化与修正

- 新DTO/纯计划测试先因缺少公开IngestionReceipt与file_integrity模块失败，2 errors in0.19s、退出2，见red-contracts.txt；最小实现后40 passed in1.73s。
- Pipeline测试先因缺少正式入口失败，见red-pipeline.txt；接线后前三组69 passed in7.41s。原生四场景首轮4 passed in16.15s，增加失败/状态覆盖后83 passed in24.55s。
- 接线细化已先补入第4节：变化/force分支在编码前，用已选版本保存的集合/k1/b审计旧三件套，避免新构建掩盖坏旧索引。该检查未重选latest，也未改变旧管理入口。复用分支仍由原activate审计，未另加冗余完整审计。
- 收尾对照合同发现两处缺口并确认4项红灯：prepare阶段普通EncodingError误沿编码码传播，未按本Spec映射阶段固定码；IngestionJobError仅检查枚举，仍接受阶段/激活状态互相矛盾。red-error-contract.txt为4 failed in0.42s。分别修正Pipeline错误分类和错误构造校验；同4项4 passed in0.36s，见error-contract-fixed.txt。未放宽断言或修改旧测试，最终结果如下。

### 11.2 实际验证命令与输出

| 实际命令 | 本轮输出 |
|---|---|
| `.venv/bin/python -m pytest -q tests/test_ingestion_types.py tests/test_file_integrity.py tests/test_ingestion_pipeline.py tests/test_ingestion_pipeline_wiring.py --tb=short` | **86 passed in 27.13s** |
| `.venv/bin/python -m pytest -q tests/test_storage_bundle.py tests/test_storage_bundle_wiring.py tests/test_index_versions.py tests/test_document_manager.py tests/test_document_manager_wiring.py tests/test_document_views.py tests/test_document_management.py tests/test_document_management_wiring.py --tb=short` | **264 passed in 40.21s** |
| `.venv/bin/python -m pytest -q tests --tb=short` | **1702 passed in 170.29s** |

日志在data/research/spec0033-evidence/new-tests-final.txt、m4-regression-final.txt、all-tests-first.txt；早期输出保留。compileall、pip check、diff、新文件白空与文档链接的最终命令结果见implementation-verification.json。项目无独立应用打包构建入口，该项不适用，不把compileall当安装包构建。

### 11.3 L1/L2/L3与正常/失败分支证据

- L1：3新源码模块、2既有源码增加错误/公开导出、4新测试存在。无空函数/占位类；新入口不依赖experiments，也未复制参考代码。
- L2：plan_ingestion复用原严格文档校验与canonical digest，稳定ID合并、四类差异、策略比较、force和空态有测试；run实际调用原M1/M2/M3/两路/目录，未变分支禁止process/save/build仍完成原审计/门禁。当前输入限额在重复分支同样生效。
- L3：test_public_pipeline_restart_reuse_and_existing_chunk_consumer[normal/zero/all-empty/mixed]在隔离新进程使用正式顶层入口，真Loader/M2/BatchProcessor/Dense/OpenAI SDK MockTransport/真Sparse/Chroma/BM25完成首次激活；再一个进程重复时明确禁止process/Sparse.encode_batch，HTTP请求为0、活动描述相同。既有test_document_management_wiring的消费者在第三进程使用新Pipeline的active/详情ID回取完整用例及来源hash，不建平行消费者。
- 正常场景另进程更新L1、加入新需求和新用例，并把旧A/旧用例移出输入目录；新版本保留旧文档，旧包仍可读。当前新L1片段均绑定新source_sha256，M2关系按全合并集重建，当前编码报告paired数等于全库片段数；不是只编码修改文件。
- test_failure_stops_pipeline_and_retains_real_observations覆盖load/plan/prepare/encode/bundle/vector/bm25停止下游，失败不激活。Dense实际边界注入失败保留失败EncodingReport；成功编码后存储超限/两路失败保留成功报告，候选ID仅在save成功后已知，不伪造零成本。
- test_profile_change_executes_full_pipeline_with_pinned_old_audit验证切分、模型修订、集合和BM25参数分别重建；纯计划另覆盖overlap/前缀/tokenizer。只改执行批大小可复用、但新input限额仍生效。坏包/旧索引不能由force绕过，读取失败不回退旧内容。
- test_successful_encoding_is_retained_on_real_revision_race在编码后实际激活竞争版本，本次最终冲突且对方active保持；test_commit_uncertain_is_not_claimed_as_rollback实际提交后注入IO错误，报告unknown并由目录重读发现revision1。未知激活异常可在提交前或后，均保守unknown；finalize故障保留已知activated。控制中断继续传播。

### 11.4 资产、限制与下一步

实施前237项源码/测试/配置/文档资产与137安装包名称/版本快照已保存。实施后已有源码只改naiyue_rag/__init__.py与core/errors.py，新增3源码/4测试；旧测试、旧存储/管理源码、示例/运行配置与依赖版本不变，源码最大266行，见implementation-assets.json。原模块未被改造成实验兼容包装；旧实验仍有实际消费者，不执行代码/数据清理。没有真实模型POST、真实.env读改、既有索引/其他仓库修改、删除、提交或push。

完整代码课堂继续暂挂；本轮实现与测试不代表本人已掌握。当前入口库级串行编排，变化时仍完整重编码/构建，没有旧编码复用/断点恢复或持久作业历史。复用路径包含必要索引审计，可能发生原生内部维护写，不承诺M4.5管理只读的字节/mtime不变。真实业务资料/检索质量、大库成本/延迟、生产并发/断电、显式移除和M5均未由本片证明。

唯一下一步：对照参考DocumentManager.delete_document，先制定M4.7显式文档移除Spec，明确文档身份、revision保护、活动版本范围与历史快照保留，再确认实施范围。
