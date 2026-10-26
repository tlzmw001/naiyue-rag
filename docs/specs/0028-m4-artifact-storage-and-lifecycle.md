# Spec0028：M4存储生命周期路线与首片完整资料包持久化

日期：2026-10-14。状态：**用户已接受M4路线，M4.1首片已实施并完成离线验收**。实际命令、红灯与接线证据见第11节；后续M4.2–M4.4分别形成Spec。

## 1. 实施前数据流与缺口

```text
M1 MarkdownLoader → Document（原文、逻辑ID、source_sha256、实际行起点）
M2 prepare_knowledge_base → Chunk（正文/上下文/实际位置/派生视图）+关系+诊断
M3 prepare_document_encoding_inputs → BatchProcessor
   → EncodingResult（EncodedRecord.input + dense_vector + SparseRecord + EncodingReport）
M3 QueryEncoder → QueryEncodingResult（同模型/表示/分词器身份）

实施前：这些正式结果在内存；Spec0026只持久化安全验收观察，没有保存向量/原文。
旧ChromaStore另读legacy实验片段，尚未消费上述结果；旧A2入口未装配正式M4。
```

已核参考URL/分支/commit/日期、具体调用行和探针见[本轮调研](../research/m4-storage-and-lifecycle-2026-10-14.md)。固定快照main/f658c5a4011c8b826707a65a3b11ce9301b0626f，2026-10-14远端main核对相同。参考链为Pipeline→VectorUpserter→ChromaStore→BM25Indexer→FileIntegrity；查询SparseRetriever按共同chunk_id回取正文，DocumentManager协调删除。

设计轮重跑37项旧Chroma测试通过；1266全量及2次真实Embedding/91tokens为M3历史证据。设计时没有正式存储包/活动索引管理，不能从组件测试宣布M3→M4→M5接通；本片当前状态见第11节。

## 2. 总体M4路线及最小取舍（已接受）

| 切片 | 真实消费者和交付 | 退出条件 |
|---|---|---|
| M4.1，本Spec首片 | BundleStore保存/重载完整M1/M2/M3资料包，供后续两个索引构建器使用 | 不依赖experiments；来源/版本/位置/配对/身份/文件完整性跨进程一致；必要IO失败可见 |
| M4.2 | VectorUpserter把资料包记录按现有item_id写Chroma，ChromaStore重开并回读 | 显式向量/embedding_function=None/cosine/禁止reset；新正式 DTO；ID/hash/向量核验和SDK/.env边界经独立Spec及探针确定 |
| M4.3 | BM25Indexer从同包SparseRecord.tokens构建BM25S，保存并重开 | 不再分词；lucene/k1/b和保存参数显式配置；同片段ID、空词项、矩阵/映射/hash与一致性覆盖；精确分数对照 |
| M4.4 | 索引发布与DocumentManager：同版本原文、关系、Dense、Sparse核完后激活；列出/详情/重复/更新/显式移除 | 单一活动指针；失败保持旧版本；重启固定版本读取；历史L2保留、旧修订片段隔离；必要状态与异常有故障注入 |

总体建议：沿参考VectorUpserter/ChromaStore/BM25Indexer/DocumentManager职责；Chroma1.5.9+BM25S0.3.13继续沿已定A2，不升级依赖、不重写BM25。正式主线使用storage包，旧实验/旧适配保留为回归资产；不为旧实验增加新的转换包装。

三个以上组件的数据交换设计：

```text
Documents + Chunks + Relations + EncodingResult
  → M4.1 BundleStore → 版本资料包（原文/片段/关系/编码）
  → M4.2 VectorUpserter → 独立版本的Chroma
  → M4.3 BM25Indexer    → 同版本的BM25S
  → M4.4 一致性核验 → 元目录中单一活动版本指针
  → M5 打开一次活动版本 → 两路召回 + 规范片段/原文回取
```

建议每个索引版本使用独立目录；后续以SQLite元目录登记精确doc→chunk映射/构建状态/活动版本（参考已有SQLite文件历史的职责扩展）。先完整构建候选版本，再提交活动指针。查询打开后固定版本，不在每一路之间重新读取latest。失败时旧版本继续服务，无需假定Chroma与BM25支持共同数据库事务。

首期按知识库完整集合构建派生索引，增加磁盘、CPU和写放大，换取容易解释/验证的一致性。M4.4先复用调用方提供的完整成对结果，不宣称变更片段Embedding复用、摄取前零调用跳过或高效增量已实现；这些优化有单独消费者后再切片。规模扩大先测构建耗时/空间，再决定改增量。替代方案是原地顺序写、失败后禁用整库并修复，少一个版本副本但可用性和恢复更差，当前不推荐。

本方案假定本地单写者、一个KB版本内只有一套模型空间/表示/分词策略、可容纳新旧两份索引。后续M4.4必须程序约束同时写入，不能仅靠约定；分布式、多写者和跨机器共享目录不在这一阶段的验收承诺。完整构建超出资源上限时明确失败，不静默写半库。

## 3. 与参考项目保持和必须适配的地方

| 项目 | 参考源码事实 | 本项目建议及原因 |
|---|---|---|
| 写入模块 | VectorUpserter转存储记录→Chroma upsert | 保持职责；直接保留M2/M3 item_id，不在落库时生成第二套业务ID |
| 文档身份 | FileIntegrity按file_hash主键/should_skip | 使用KB+逻辑document_id+source_sha256，另绑定切分/模型/表示/分词策略；同字节不同文档不合并，换模型不能只按文件hash跳过 |
| 多存储一致性 | Chroma、BM25、图片、成功历史顺序写；BM25仅单JSON replace | 增加独立版本及活动指针；Markdown无图片链，不伪造跨存储事务 |
| 关键词索引 | 手写TF/倒排/IDF；doc前缀清理 | 保留BM25Indexer角色，消费正式SparseRecord并用已定BM25S；按确切文档/片段映射管理，不猜字符串前缀 |
| 更新/删除 | 正文变化生成新存储ID；局部探针显示doc前缀不匹配 | 同路径修订在新版本替换该doc片段；新L2是新doc；移除在新版本排除目标后切换，不先破坏活动库 |
| 来源载荷 | Chroma复杂metadata转逗号串/str | 索引只保存可过滤平面字段；规范资料包无损保存SourceSpan、表格字段、上下文和关系 |
| 参数 | 参考cosine、k1=1.5/b=.75；包版本仅下界 | cosine延续；k1/b作为后续配置初值可实验，BM25S lucene与参考原始IDF不当逐值一致；已安装版本保持 |
| 错误与空结果 | 某些管理辅助方法异常返回0/[] | 固定错误与空集分开；必要写入/校验失败不可激活；无需提前加入文档ACL |

历史例子：G1含`L1_Module(v1)、L2_A、A_测试用例`。加入L2_B并更新L1后，G2含`L1_Module(v2)、L2_A、A_测试用例、L2_B`；A仍是回归参考。G1保存用于工程恢复，不代表L2_A从当前库消失；RAG也不自动认定其规则仍现行。目录扫描少一个文件不自动授权删除；后续管理的移除需明确目标/预期版本，并经过调用边界确认。

## 4. M4.1首片：完整资料包的输入、输出和权威边界

仅库级本机文件IO；没有服务、模型Key、网络或Chroma初始化。应用调用方在M1/M2/M3之后调用prepare_index_bundle，再交BundleStore保存；新进程可load，返回同一完整资料包。该消费者链在接线测试实际装配，不增加旧实验CLI包装。

已实现API：

- `load_storage_settings(path) -> StorageSettings`：复用read_yaml_mapping严格YAML；只读配置，不创建目录或读.env。
- `prepare_index_bundle(documents, chunks, relations, encoding_result, *, knowledge_base_id, encoding_settings, ingestion_settings) -> IndexBundle`。
- `IndexBundle.to_dict()/from_dict(data)`：严格字段/深副本/重校验，保留现有Document/Chunk/EncodingResult DTO，不更改它们的签名。
- `BundleStore(settings).save(bundle) -> StoredBundle`；`load(bundle_id) -> IndexBundle`，读缺失/坏包不创建补写。
- `StoredBundle`只含`bundle_id、status(ready|unchanged)、document_count、chunk_count、model_space_id、representation_id、tokenizer_id`，无正文/向量/Key/绝对来源路径；没有active字段。
- 新增`StorageError(code)`固定错误码及安全日志；不保存原异常字符串、堆栈或正文。配置错误沿现有SettingsError。

IndexBundle的数据字段为：knowledge_base_id、documents、chunks、relations、encoding_settings、ingestion_settings、encoding_result、preparation_diagnostics；后四项均有确定来源，不收任意扩展字段。ingestion_settings为明确两字段；encoding_settings是已有严格配置（无Key），result为既有DTO。preparation_diagnostics由现有M2重新校验产生，不能丢掉超长完整用例等诊断，也不能把警告自动当失败。

权威边界：Markdown快照是该包的原文事实；chunk/关系/词项/向量是绑定到快照的派生产物；M3报告记录编码请求事实。Bundle就绪只说明这些资料完整可读，**不等于Chroma/BM25已构建或可以激活查询**。源文件后来改变不修改已保存资料包。

## 5. M4.1完整绑定校验

校验顺序固定，任一步失败都不保存/不返回部分包：

1. 对配置、输入类型、字段、资源上限做严格检查；Document/Chunk/EncodingResult通过原DTO恢复到私有副本，不持有调用方可变别名。
2. 原文重新核UTF-8 hash、size_bytes、line_starts；文档ID必须符合现有M1的KB+相对路径算法。ID/路径唯一、所有文档同KB；同路径混入两个source_sha拒绝。不同路径即使内容相同也保留两份逻辑身份。
3. 用当前M2 `prepare_knowledge_base` 和传入IngestionSettings/text_mode确定性重算；按M3结果输入顺序对齐chunk，要求每个chunk全文结构/位置/上下文/派生视图相等、ID全集相等；关系必须与build_document_relations确定结果完全相等。保留M2诊断。依赖版本/算法改变导致重算不符时明确失败，不静默迁移旧包。
4. `prepare_document_encoding_inputs`重新生成期待输入；每个EncodedRecord.input与期待值逐字段一致，绑定原文版本、实际span、retrieval/embedding各自文本与hash。结果顺序/批次和EncodingReport原合同保持；不依列表位置盲配。
5. 全部记录同model_space_id、representation_id、tokenizer_id与维度；SparseRecord的TF/长度/词项及hash用现有DTO验证，不初始化jieba、不再分词；向量用现有有限非零/维度合同验证，不重新Embedding。已知usage和未知usage按原报告保留。
6. `encoding_result.report.status`只能success或empty；输入chunk的ID集合与编码结果完全相同，任意漏项/多项/query记录拒绝。非空result的KB等于本包KB；无chunk时只能empty结果。空文档仍保存，整包无文档也可在显式knowledge_base_id下表示空集合，identity沿M3 empty DTO，不能伪造向量。

首片load再次执行同样绑定校验，代价是重走一次确定性M2准备，利于来源完整性；不把其耗时当数据库检索延迟。未来若大库加载成为瓶颈，再根据证据优化校验层级，当前不增加可信缓存捷径。没有问答/关系业务有效性或召回质量判定。

## 6. M4.1配置、文件与身份

StorageSettings严格7字段，无隐藏运行默认值：

| 字段 | 示例提案 | 校验/含义 |
|---|---|---|
| storage_root | ./data/indexes | 相对配置文件所在目录解析或显式绝对目录；拒绝..、symlink、非目录；只操作此边界 |
| knowledge_base_id | demo | 明确同M1身份；Unicode可用，不当物理路径；文件夹使用UTF-8 KB ID的完整SHA256 |
| max_documents | 1000 | 正整数，含空文档；当前资源保护值，不是容量/性能证明 |
| max_chunks | 10000 | 正整数，完整用例不截断凑上限 |
| max_file_bytes | 16777216 | 单资料文件最多16MiB，读写双方先限制 |
| max_bundle_bytes | 67108864 | 整包含manifest最多64MiB；单文件/manifest上限不可超过它 |
| max_manifest_bytes | 65536 | manifest最多64KiB；无大对象先读后限 |

这些是首片资源模板值，不是最佳容量或性能结论，不修改任何现有运行YAML。示例放examples/storage.example.yaml，测试只使用临时根。分块大小继续取IngestionSettings，不硬编码1000/300；Embedding服务与参数继续取EncodingSettings，不复制.env。

磁盘边界：`<storage_root>/<sha256(kb_id)>/artifacts/<bundle_id>/`，bundle_id为64位hex；调用方只能给ID，不能传任意回读路径。包仅五个文件：

| 文件 | 精确内容 |
|---|---|
| documents.json | Document.to_dict列表，按文档ID排序；保存原始文本/实际行起点 |
| chunks.json | Chunk.to_dict列表，按EncodingResult.records输入顺序；完整上下文/表格/定位 |
| relations.json | 已核M2关系dict（含原文证据/诊断） |
| encoding.json | 严格四键：encoding_settings、ingestion_settings、encoding_result、preparation_diagnostics |
| manifest.json | schema_version=1、status=ready、bundle_id、knowledge_base_id、document_count、chunk_count、model_space_id、representation_id、tokenizer_id、source_fingerprint、files |

资料文件JSON编码为UTF-8，`ensure_ascii=False、sort_keys=True、separators=(',',':')、allow_nan=False`，尾随一个LF；不作换行/Unicode内容归一化。重复键、NaN/Infinity、未知字段、额外文件、非法UTF-8、truncated JSON均拒绝。`files`恰好登记前四文件的bytes和SHA256（文件名闭集）；manifest不能自包含hash。

bundle_id计算：对上述manifest字段中去掉bundle_id的规范JSON做SHA256（不加末尾LF）；source_fingerprint沿M2关系输出。资料文件中包含完整M3报告，所以不同job_id/usage/时间的再次编码可产生不同bundle_id；这是物理资料包身份，不是“源文件未变就跳过模型”的判据。后续元目录另按源版本/处理策略决定重复摄取，不能把本包ID当作业务版本号或历史有效性判断。

同一个已核IndexBundle再次save，得到相同文件/manifest身份：完整读取并核验已有包后返回unchanged，不覆盖、不增长。若同ID目录存在但缺失/损坏/不一致，明确报错，禁止静默修复。BundleStore初始化与load均无目录创建副作用；只有save创建必要目录。

## 7. M4.1正常与失败的IO链

```text
save：全绑定校验 → 有界规范序列化/总大小核对 → 检查目标
  已有完整同包 → 读核验 → unchanged
  已有坏包/路径非法 → 固定错误，不覆盖
  新包 → 私有.pending-UUID目录 → 逐文件独占写/flush/fsync
       → 最后写manifest并fsync目录 → 同一文件系统rename为完整包目录
       → fsync父目录 → ready
load：合法ID → 有界读manifest → 核字段/身份/文件集合与大小
     → 有界读四文件/hash → DTO与M1/M2/M3重校验 → 完整IndexBundle
```

目录0700、文件0600；拒绝路径各段及文件symlink，检查实际打开的普通文件，文件读取有上限。日志只写固定stage/code和必要计数，不写Key/原文/词项/向量/供应商body/原始路径或异常。构建目录与目标在同一文件系统；首片只支持单进程串行save，禁止把它宣传成多写者安全存储服务。

错误码闭集：invalid_storage_settings、invalid_index_bundle、bundle_scope_mismatch、bundle_identity_mismatch、bundle_source_mismatch、bundle_limit_exceeded、invalid_bundle_id、bundle_path_invalid、bundle_not_found、bundle_incomplete、bundle_integrity_failed、bundle_read_failed、bundle_write_failed、bundle_publish_failed、bundle_publish_uncertain。边界异常映射到所属固定码并保留异常链隔离；不以空对象/空列表冒充成功。

失败不自动删除pending或已有目录；load不发现/采用pending。rename前失败不发布完整包；rename后父目录fsync失败返回bundle_publish_uncertain，不能声称磁盘绝对未写入或已就绪，后续只读核验可判断文件状态。首片没有活动查询指针，因此不能把包发布不确定解释为线上索引已经切换。断电持久性/真实磁盘故障不由mock fsync测试证明。

回退是停用新BundleStore；既有实验、索引、文件不变。清理本片自己产生的临时/旧包也不作为自动动作，真实清理另获范围授权。

## 8. 影响文件和接线范围

本片8个源码/测试/模板文件，无新依赖/服务：

1. core/storage_settings.py：严格配置/加载/资源上限。
2. storage/__init__.py：仅导出本片入口，不修改根包旧公共导出。
3. storage/artifact_bundle.py：IndexBundle/prepare_index_bundle与跨M1/M2/M3绑定。
4. storage/bundle_store.py：有界文件写读、manifest、物理身份与StoredBundle。
5. core/errors.py：只新增StorageError，不改已有错误签名。
6. tests/test_storage_bundle.py：配置/合同/配对/边界。
7. tests/test_storage_bundle_wiring.py：真实M1/M2/M3离线链、文件与子进程重载/IO故障。
8. examples/storage.example.yaml：空凭证的资源参数模板，获实施确认后再创建。

单源码文件≤500行；超过先修订Spec按职责拆分。当前搜到的旧save/load均在experiments，正式主线按ADR0005不导入；使用其严格manifest/hash/映射等机制作为设计参考，不搬整套旧实验框架。没有调度器、插件注册表、缓存层或通用事务包装。

L1–L3计划验收：文件存在→真实写读/校验→接线测试从Loader/M2/真实BatchProcessor（仅Dense底层模拟）实际save/load→新进程恢复同一DTO；新索引构建器下一片才成为生产消费者，本片不标已接通Chroma/M5。

## 9. TDD与验证覆盖（实际结果见第11节）

| 分支 | 固定输入与期望 |
|---|---|
| 正常跨层 | 小型合成L1/L2+含表格用例；真实M1/M2/BatchProcessor/Sparse，Dense用现有SDK MockTransport；包保存/重载全部正文、位置、表格、关系、向量、词项、三身份/报告相等，网络0 |
| 跨进程 | 独立Python进程只加载包；原源文件不读、Key不读；完整DTO指纹与原进程一致 |
| 重复 | 同一个完整包save两次，第二次unchanged，资料文件字节/hash/mtime保持；不重新编码、不新建pending |
| 空 | 零文档/只有空文档时配M3 empty结果；显式KB、0记录、完整原文目录；无伪造向量 |
| 来源坏 | 原文hash、实际行起点、chunk span/上下文/用例列、关系出处或版本不一致，保存前失败；文档中手写行号陈旧本身不报错，仍按真实span保存 |
| 配对坏 | 少/多/重复记录、混query、ID/各自hash错、混KB/策略/维度/tokenizer、报告不符，0写入 |
| 同字节不同路径 | 保留两个逻辑文档；不能仅因hash一样去掉其中一个 |
| 修订和历史 | 保存两版L1及保留L2_A/新增L2_B的两个独立资料包；旧包可读，新包只含本次输入的L1修订，两个L2均保留；不据此声称已激活/增量更新 |
| 大小 | 参数可配置；单文件/总大小/manifest/文档/片段超限均明确失败，不截断完整用例 |
| 路径/内容损坏 | symlink/../非法ID/非普通文件、缺文件/多文件、坏UTF-8/重复JSON键/坏hash/错误字节数/额外字段：read失败不补写 |
| 关键IO | 创建/写/flush/fsync/rename/读失败均明确固定码；rename前无完整目标；rename后目录fsync失败uncertain；pending保留且不被load |
| 安全与所有权 | 合成敏感哨兵不进日志/receipt，存储数据可按本片私有目录读取；DTO深副本；不改.env、不触发SDK、权限0700/0600 |

编码前先确认新测试因缺模块/预期合同失败，再最小实现，旧失败不放宽/skip。首片实施命令：

```zsh
.venv/bin/python -m pytest -q tests/test_storage_bundle.py tests/test_storage_bundle_wiring.py --tb=short
.venv/bin/python -m pytest -q tests --tb=short
.venv/bin/python -m compileall -q naiyue_rag tests
.venv/bin/python -m pip check
git diff --check
```

当前没有项目打包构建入口，以上compileall不当安装包构建或生产验收。无真实模型请求，不需要新API Key/账号/服务预算；原Chroma/BM25S在本机已装，不安装或升级。M4.2前由本会话制定SDK/.env初始化边界并完成合成探针；M4.3/4.4前分别定索引配置与元目录并发/发布合同，不把这些后续实现承诺为本首片已有功能。

## 10. 设计阶段交付状态（历史）

已完成：参考/本地源码对照、参考BM25局部合成探针、37项旧Chroma回归、本Spec和调研记录。未实施：上列8文件、资料包读写、正式Chroma/BM25装配、版本激活及DocumentManager；未读真实.env/未发模型请求。没有新课堂或本人独立能力证据。

唯一下一步：确认“完整新版本构建后再激活”的M4路线及本Spec M4.1首片范围；确认后连续完成首片TDD和离线接线，不直接进入数据库更新/删除实现。

实施授权补充：用户明确接受本Spec，并允许新版本完成后清理已被替代且无消费者的旧代码。本片先完成M4.1再核消费者；已有Chroma/A2实验仍有真实消费者且未由资料包替代，不能据此删除整个旧实验/结果。清理仅限已完成替换的代码与对应迁移测试，不触碰真实.env、原始文档、索引数据或其他仓库。

实施模板路径澄清：storage_root示例使用./data/indexes（相对examples/storage.example.yaml），其生成目录examples/data/indexes已由现有data/忽略规则覆盖。这样保持配置相对路径且不需..或机器绝对路径，避免示例默认产物被误纳入Git；没有创建该数据目录或修改真实运行配置。

## 11. M4.1实施与验收（2026-10-14）

用户接受后按上述8文件实施。公开入口在naiyue_rag.storage，核心只追加StorageError；旧正式DTO/编码器/公共签名、旧测试、根包导出和安装版本保持。新源码最大218行，没有引入新依赖、模型请求或服务，也没有读取/修改真实.env。

### 实际接线

测试test_actual_sdk_sparse_and_new_process_reload从合成3份Markdown（模块、历史需求、测试用例）开始，真实Loader→M2结构/完整用例/来源关系→真实BatchProcessor/DenseEncoder/OpenAI SDK的MockTransport+真Sparse→prepare_index_bundle→save→load。文件保存五项资料/manifest，原文、用例字段/上下文/实际行号、显式关系、Dense/Sparse/两种文本hash与报告均保持。单独子进程只接收存储配置与包ID，禁Python socket，未传Key或原材料路径；原材料在保存后被改写，子进程仍恢复旧包完整DTO，且未导入chromadb/openai SDK。

save：来源/配置/配对→有界规范JSON→私有pending/逐文件flush/fsync→manifest最后写入→目录fsync→rename→父目录fsync→ready；同包再次save重载核验后unchanged，mtime/内容不变、不增加pending。load缺失/坏包不创建或修复，重算M2和M3输入以核对来源；正文里的陈旧L999-L1000仍原样保存，实际span另外核验。

### TDD及真实运行输出

- 初始红灯：ModuleNotFoundError: naiyue_rag.storage，1 error in0.19s，见red-contracts.txt。
- 首批81测试通过后，新增两个具体合同回归均确认红灯：parents=True中间目录不是0700；短写未抛错会继续发布。分别最小修复为逐级创建私有目录、检查write返回字节数，两项各自转绿（0.12s/0.15s）。red-publishing.txt保留失败证据。
- 最后补齐配置读取失败的可观察性：原读取器抛安全SettingsError但未日志，新增测试确认红灯（1 failed in0.24s），仅在Storage配置入口记录固定码后重跑；最终91项与1357全量结果如下，先前90/1356输出仍保留。
- 额外核验已重新计算文件hash/manifestID仍无法绕过原文绑定；现配置读取上限生效；fdopen失败时原始fd关闭。没有放宽旧断言、skip或改测试基础设施。

```zsh
.venv/bin/python -m pytest -q tests/test_storage_bundle.py tests/test_storage_bundle_wiring.py --tb=short
# 91 passed in 4.76s
.venv/bin/python -m pytest -q tests --tb=short
# 1357 passed in 98.29s
.venv/bin/python -m compileall -q naiyue_rag tests
# exit 0
.venv/bin/python -m pip check
# No broken requirements found.
git diff --check
# exit 0
git check-ignore --no-index examples/data/indexes/probe.json
# examples/data/indexes/probe.json
```

安装包freeze保持；144份既有源码/测试/依赖资产中仅errors.py变化，原有内容hash可从前缀恢复一致，只追加StorageError。当前所有源码文件≤500行。本片没有独立打包构建入口，compileall属于编译检查。

### 旧代码清理核对

用户已授权新版本完成后删掉被替代的无用代码。本片核对4个相关旧模块：旧chroma_store有experiments/chroma_worker构造和原生回归消费者；keyword_index与vector_index仍被A2/图/关系等实验消费；a2_snapshot仍用于冻结检索与相应回归。M4.1资料包没有替代上述索引/检索职责，故本片删除候选为0，不为留下旧接口新增包装或转换。具体导入位置及已检查调用在cleanup-audit.json；这不是全仓死码审计，也不意味着这些模块将永远保留。到M4.2–M5实际替换消费者后，在原授权内迁移必要测试并删除被替代、无消费者的代码。

### 证据与限制

本轮输出目录data/research/spec0028-evidence/含red-contracts、red-publishing、red-settings-observation、targeted-tests-final、full-tests-final、verification和cleanup-audit，先前绿灯输出保留。L1新文件存在；L2来源绑定/有界真实文件IO/完整校验均已实现；L3上述真实组件接线与新进程重载已跑通，Formal storage源没有experiments依赖。当前生产索引构建器尚未消费包，不能标M3→正式Chroma/BM25→M5已经接通。

只支持本机串行save；资料包含必要原文/词项/向量，存储在私有目录，日志/receipt无上述数据。重新编码造成不同报告时可生成不同物理包，此ID不是业务生效版本或预编码去重键。加载会重走确定性M2，未验大库性能、真实磁盘/断电持久性、多写者或真实业务资料。rename后目录fsync失败返回uncertain；旧包和pending不自动删除。完整新索引构建/激活与文档管理仍按后续片验收。

学习：本片保存/重载职责、正常与失败边界已简述，用户安排的完整代码课堂仍暂挂；没有本人独立调试、复写或面试能力新证据。

唯一下一步：制定M4.2正式VectorUpserter/ChromaStore的Spec，先以合成.env核实SDK导入与配置边界，再确定资料包→Chroma写入/只读重开/ID与向量回读合同；不在未定该差异前修改旧guard或删旧消费者。
