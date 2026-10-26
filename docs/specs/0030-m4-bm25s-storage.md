# Spec0030：M4.3 从成对资料包构建、保存与重开 BM25S

日期：2026-10-15。状态：**用户已接受，M4.3已实施并完成本轮本地验收，见第11节**。沿Spec0028已接受路线，使用现有BM25S0.3.13；不重选后端、不复制参考倒排实现。实现前链路与实际验收分开记录。

## 1. 实现前链路与本片价值

当前：MarkdownLoader→M2 Chunk/关系→M3 EncodedRecord.input/dense_vector/sparse→IndexBundle→BundleStore。M4.2已把同包Dense写入Chroma，并支持重开/完整Chunk回读。正式Sparse尚未构建索引；旧experiments/keyword_index.py重新分词并消费实验unit。

本片：BundleStore.load→直接取SparseRecord.tokens→BM25Indexer→独立BM25S版本→保存→另一进程BM25Store.audit。保留与Chroma相同的item_id/bundle_id，建立M5关键词召回的持久基础。构建不要求Chroma先成功；两路是否能作为同一个完整版本激活由M4.4协调。

机制示例（示意数据，不是本轮实测）：

| 矩阵行/片段 | 已保存tokens | doc_length |
|---|---|---|
| chunk-A | 开关、开关、0.5 | 3 |
| chunk-B | 开关、关闭 | 2 |
| chunk-C | 空列表 | 0 |

这里N=3指**片段数**，不是Markdown文件数；avgdl=5/3；词项“开关”的DF=2。重复词项保留给TF，不能先把文档tokens去重。BM25S按词项预存各片段的贡献分，查询再累加相应列。chunk-C保留行/ID映射，在关键词路不产生命中；它仍可在向量路被召回。

## 2. 参考项目与本机资产核对

URL：https://github.com/Jerry-ai-dev/MODULAR-RAG-MCP-SERVER 。只读本地main/f658c5a4011c8b826707a65a3b11ce9301b0626f，2026-10-15工作区干净；本轮未查询远端，不声称远端最新。相关背景见[M4调研](../research/m4-storage-and-lifecycle-2026-10-14.md)。pyproject声明MIT而无独立LICENSE，此片独立实现、无参考代码复制。

参考实际链路：

1. pipeline.py:389取得BatchProcessor.sparse_stats，438写向量，443–451把向量库返回ID写入stat.chunk_id，再调用BM25Indexer.add_documents。
2. bm25_indexer.py:build（约100–185）从TF/doc_length算N/avgdl/DF/IDF及postings；add_documents:311起处理合并；_save:518–550写单JSON临时文件后replace。
3. query:225–290按词项累加postings分数，再排序/top_k；SparseRetriever:145–182调用它并按chunk_id到vector_store.get_by_ids回取正文。缺索引返回[]是参考行为，不作为我们的存储故障合同。

| 方面 | 参考事实 | 本项目方案与理由 |
|---|---|---|
| 输入 | SparseEncoder的TF/doc_length | 直接消费M3已验证tokens/TF/长度，不重新分词、不重复清洗/lowercase |
| 算法 | 自写倒排；IDF=log((N-df+0.5)/(df+0.5))；TF项含(k1+1) | 沿已定BM25S Lucene，IDF带log(1+...)，其TF项无(k1+1)。不声称逐值相等或“更先进” |
| 参数 | k1=1.5、b=.75 | 作为可配置起点；不声称对我们最优 |
| 存储 | 单JSON；与Chroma顺序写 | 原生5文件+行映射+ready，一整个新目录完成后发布；不冒充跨库事务 |
| ID | 在写向量后替换 | 一直使用M2/M3 item_id，保持来源和双路配对 |
| 空词片段 | build按输入条目计N；旧实验会拒绝空tokens | 合法空词片段保留，在同一行空间表示零贡献；不因过滤结果为空丢掉整个片段 |

旧experiments/keyword_index.py:60–178已有显式Lucene/float64/int32/禁pickle、矩阵校验与save/load；180起是重新分词、范围内统计、排序。复用机制，正式包不导入旧实验Tokenizer/ProbeError/unit。旧19项回归仍保持，不能把新旧分词策略当成同一词表。

## 3. 明确范围与暂不决定的事情

本片仅有build/audit存储入口、完整行映射和数值审计。不新增面向用户的问题搜索、scope/exclude、top_k、RRF、重排、Agent、MCP、active切换、增量更新或删除。测试可通过内部原生装配函数核对确定性词项分数，不为了教学暴露原始SDK对象或建立平行检索框架。

**范围统计边界：**保存的是当前完整资料包的N/DF/avgdl。旧A2的pool_data会先筛scope/exclude后重建统计量；若M5仅对全库分数做结果过滤，分数/排序语义可能改变。M4.3不把“可重开全库索引”宣传为“受限scope与旧A2逐值一致”。M5必须对照范围内重算与全库统计+过滤的差异，在实现范围检索前明确合同。

最脆弱前提是M3 tokens确实表达所需词项；存储只能忠实保存，不能恢复上游过滤掉的词。真实文档上的漏召回仍靠后续固定评测发现，不能由索引测试全绿代替。

## 4. 配置、入口与回执

复用StorageSettings七字段/BundleStore；新增严格BM25Settings两字段：

- k1：默认模板1.5，有限数值且>0，bool拒绝。
- b：默认模板0.75，有限数值且0≤b≤1，bool拒绝。

数值规范化为float供身份与保存使用；复用严格64KiB YAML读取，未知/重复字段、alias/merge拒绝。原生固定policy：BM25S0.3.13、method/idf_method=lucene、backend/csc_backend=numpy、dtype=float64、int_dtype=int32、auto_compile=False、delta=0.5（Lucene不用该参数，固定并核验SDK保存值）。不配置多种未实现算法。

index调用create_empty_token=False；save/load均allow_pickle=False；load显式mmap=False/load_corpus=False，并覆盖SDK不保存的auto_compile=False/csc_backend=numpy。文件内参数先严格验证再调用SDK，避免仅依赖override掩盖错误配置。无网络、Key或.env需求。

拟公开入口（仅从storage包导出）：

- load_bm25_settings(path) → BM25Settings。
- BM25Indexer(storage_settings, bm25_settings).build(bundle_id) → BM25IndexReceipt。
- BM25Store(storage_settings, bm25_settings).audit(bundle_id) → BM25IndexReceipt。

构造/读取配置不创建目录；build只收已保存且可重载的bundle_id。回执字段：schema_version、status(ready/unchanged/verified)、index_id、bundle_id、knowledge_base_id、document_count、chunk_count、tokenized_chunk_count、empty_chunk_count、vocab_count、avgdl、verified_count、model_space_id、representation_id、tokenizer_id、sdk_version。verified_count指完成来源/矩阵配对核验的片段数，包含空行；不伪造模型用量。

## 5. 空数据与数值合同（已接受并实施）

| 情况 | 预期存储状态 |
|---|---|
| 无片段 | N=0/avgdl=0；空行映射，native_state=empty，不调用BM25S.index |
| 有片段、全部tokens为空 | 保留全部ID，N>0/avgdl=0；native_state=empty，不调用BM25S.index；不能与无片段混淆 |
| 部分tokens为空 | 全部片段参与N/avgdl与行映射，空片段为零分行；正常构建原生矩阵 |
| 正常非空词项 | 重复保留；词表、TF、DF、长度、词项贡献一致 |

本机SDK探针：混合空行可建库/重开；全空及零行的index能产生空矩阵并出现warning，随后get_scores(['alpha'])报ValueError；get_scores([])在非空库报IndexError。所以正式代码明确表示词表为空状态，M5遇空查询/词表应短路，不能直接交给这个原生方法。

Lucene逐词项贡献核验：idf=log(1+(N-df+.5)/(df+.5))；weight=idf*tf/(tf+k1*(1-b+b*dl/avgdl))。其中N/df按片段，avgdl包含零词片段；非空词表时avgdl必>0。每个term只在含词片段上有一个posting，TF由重复tokens计算，空行无posting。

## 6. 文件、来源与身份

目录：<storage_root>/<sha256(kb)>/bm25/<index_id>/；与artifacts及vectors同级。index_id=SHA256规范JSON的schema_version、bundle_id、规范化k1/b、sdk_version和storage_policy='bm25s-lucene-v1'。同一包不同参数生成不同候选，不覆盖旧索引；M4.4再登记两路的精确组合。

正常词表下共7个文件：rows.json、原生data.csc.index.npy/indices.csc.index.npy/indptr.csc.index.npy/vocab.index.json/params.index.json、ready.json（1个映射+5个原生文件+1个完成标记）。

rows.json与M3 records顺序一致，逐项包含item_id、source_document_id、source_sha256、retrieval_text_sha256、doc_length、unique_terms。不复制一套tokens正文，直接从同包重载；规范tokens/TF/长度整体指纹写入ready。

ready.json绑定完整KB/bundle/三身份/source_fingerprint、回执统计、算法参数、native_state、词项指纹和严格files清单（字节数/SHA256）。原文、SourceSpan、完整case_fields、Dense仍在资料包。原生BM25S不存corpus.jsonl或pickle正文。

## 7. 构建、重开和完整性检查

1. load包并校验SparseRecord/身份，M3 records逐ID与Chunk配对；统计N、avgdl、DF/TF、预计nnz与行映射。拒绝超StorageSettings数量/字节限制和int32边界；不调用分词器/模型/Chroma。
2. 已有同index_id：完整audit后unchanged，无index/save/改mtime；坏索引不修复。只读缺失不创建目录。正常集合恰为rows.json、ready.json及5个原生文件；empty态恰为rows.json/ready.json。未知/缺失文件、symlink/FIFO拒绝。
3. 私有pending目录0700；词表非空调用BM25S.index/save，空态只写映射。检查原生输出字节上限、关闭句柄，所有数据文件0600；flush/fsync必要文件，ready最后写。文件读取沿BundleStore的有界/no-follow/固定码机制复用。
4. 核验原生params严格字段/版本/参数、vocab完整词集合及0..V-1双射；不得凭名字/文件hash认为接通。词表编号可能因SDK集合遍历顺序不同而变化，audit按词→列映射核对，不比较另建库的原始字节。
5. 在np.load之前检查NPY magic/header版本、dtype、shape、预计payload字节及文件大小。data=float64/indices=int32/indptr=int64；数组一维，offsets长度V+1且单调从0到nnz，indices在[0,N)，每列无重复行号。nnz恰为各片段unique_terms总和，非有限/非正权重、缺/多posting拒绝。
6. 按同包TF/DF/长度和显式参数计算预期Lucene权重，逐term/行检查，rtol=1e-12/atol=1e-15。这是来源数值审计，不增加一套线上BM25评分器；测试另有手算独立期望。重算文件hash也不能掩盖正数错矩阵/错行。
7. 重开audit通过→目录fsync→rename发布→父目录fsync。rename前任何失败留pending、整次错误、不返回部分结果；rename后fsync失败publish_uncertain。保留旧索引，无自动清理/重试/激活。BM25S是内存数组文件接口，无须仿造Chroma.close或新进程服务。

## 8. 错误与可观察性

沿SettingsError/StorageError固定码模式，拟加bm25_runtime_mismatch、bm25_invalid_request、bm25_index_not_found、bm25_index_incomplete、bm25_identity_mismatch、bm25_integrity_failed、bm25_path_invalid、bm25_limit_exceeded、bm25_read_failed、bm25_write_failed、bm25_publish_failed、bm25_publish_uncertain。原包错误保留原码；SDK/IO异常安全转换，不记录词项、原文、路径、SDK原异常/stack。正常空词态与故障明确分开，不返回空命中掩盖坏库。

## 9. 影响文件与TDD验收范围

先搜后写：可复用BundleStore私有IO/规范JSON/发布机制、正式Chroma的按包绑定经验、旧keyword_index的矩阵/参数核验；不引入新的工厂/worker/回调/通用注册框架。若共享JSON/路径代码出现第三次实质重复，优先提取实际三消费者需要的最小辅助模块，并先更新本Spec的影响范围。

实施新增core/bm25_settings.py、storage/bm25_store.py（包绑定/行映射/发布/公开入口）、storage/bm25_backend.py（原生参数/NPY/矩阵数值审计），每文件≤500行；扩展errors.py/storage.__init__导出。后两者分别负责版本编排与原生数据格式，沿现有Chroma分层。新增examples/bm25.example.yaml模板（非实际运行配置）及配置/矩阵故障、真实接线三文件测试（test_bm25_store、test_bm25_integrity、test_bm25_native）。扩展bundle_store._parse私有函数的canonical开关以读取SDK原生JSON，保留旧默认严格规范字节合同；第三个存储消费者出现后，扩展BundleStore._path私有namespace/error_code参数，Bundle/Chroma/BM25共用KB目录与symlink校验，namespace严格白名单；仅迁移chroma_index._path这一调用，公开签名/默认artifacts合同不变；不复制第三套JSON解析。无新依赖、升级或真实.env修改。

验收顺序：预期红灯→最小实现→下列分支回归。

- 配置：k1/b边界、bool/NaN/Inf、未知/重复字段、alias/merge；参数改变改变index_id；同参数float规范化稳定。
- 成对接线：真实M1/M2/M3+SDK MockTransport/真Sparse→BundleStore→BM25Indexer→另进程audit，按词项核对分数/片段ID；不同原始输入顺序不能错绑。patch分词/模型/Chroma执行入口为禁止调用，证明重开只消费现有词项。
- 空数据：N=0/全空/混合空保留映射、统计和零行；原生无词表不调用index/get_scores；数字0/1/0.5、技术标识符及中文词原样保留，不重复套长度过滤。
- 保存：重复无写、空态无伪造native、截断/损坏/未知文件、错误版本/参数/词表/映射、非有限/越界/错offset/重复posting、重算hash后的正数错权重或错行均拒绝；只读无文件变化，不回填。
- 边界：NPY对象dtype/超大header/伪造shape/payload截断在SDK数组分配前拒绝，超限及路径/symlink/FIFO可观察；短写、SDK.save半写、fsync/rename/发布不确定不冒充成功，旧资料包与Chroma版本不改。
- 评分：两小片段手算、重复查询词用M3 query_terms去重后比对、OOV零分、保存前后/另一进程精确相等。此为存储与数值验证，不提供M5搜索API、不宣称检索质量通过。
- 回归：旧keyword19、资料包/Chroma、全tests、compileall/pip check/diff，所有源码≤500行。旧keyword/vector/A2仍有实际消费者，只有替换后确无消费者的代码才沿已授权范围删除，不为删旧代码增加转换包装。

## 10. 历史调研证据与学习状态（实现前）

- `.venv/bin/python docs/research/probes/bm25s_storage_probe.py`：expected_checks_passed=true，原生0.3.13保存/重载，正常词项手算误差5.551115123125783e-17；另进程分数精确相等，成功场景重开未改文件。空数据失败阶段与warning如第5节，完整结果sdk-probe.json。
- `.venv/bin/python -m pytest -q tests/test_keyword_index.py --tb=short`：**19 passed in4.13s**。这是旧实验回归；本轮未实现正式BM25入口、未写新功能测试、未重跑1389全量。
- 来源hash、语法/依赖/链接/diff检查在data/research/spec0030-evidence/verification.json。真实.env读/改0、模型请求0、无依赖/旧索引/其他仓库修改，无提交/push。

本轮说明Sparse→统计→矩阵→持久化的职责；完整代码课堂仍暂挂，无本人独立调试/实现新证据。唯一下一步：按本Spec完成正式BM25S存储的TDD、接线和回归；M4.4活动版本及M5范围评分另行Spec。


## 11. M4.3实施与验收（2026-10-15）

实际交付core/bm25_settings.py、storage/bm25_backend.py、storage/bm25_store.py，examples/bm25.example.yaml及三个测试文件。正式入口由storage导出。BundleStore._parse增加默认不变的canonical开关；第三个路径消费者出现后，BundleStore._path共用KB目录/符号链接校验，Chroma只迁移这一私有委托。新源码最大157行，项目源码最大266行。

红灯：red-formal.txt记录缺少BM25Settings正式导出。首轮复用了M4.1故意输出空Sparse的测试替身，未命中“正常原生写入”分支；新测试明确提供非空词项后，原写入/回执断言保持不变。没有放宽/skip原测试，没有改conftest或旧测试；不把测试样本问题记作生产bug。

实际验证：

- 相关存储命令：`.venv/bin/python -m pytest -q tests/test_bm25_store.py tests/test_bm25_integrity.py tests/test_bm25_native.py tests/test_storage_bundle.py tests/test_storage_bundle_wiring.py tests/test_chroma_index.py tests/test_chroma_native.py tests/test_chroma_store.py tests/test_chroma_probe.py tests/test_keyword_index.py --tb=short` → **232 passed in22.91s**，为补原生半写门禁前的相关回归。
- `.venv/bin/python -m pytest -q tests/test_bm25_store.py tests/test_bm25_integrity.py tests/test_bm25_native.py --tb=short` → **54 passed in8.71s**。
- `.venv/bin/python -m pytest -q tests --tb=short` → **1443 passed in111.38s**（最终门禁）。
- `.venv/bin/python -m compileall -q naiyue_rag` → exit0；独立应用构建不适用。
- `.venv/bin/python -m pip check` → **No broken requirements found.**；安装freeze前后相同。
- `git diff --check` → exit0；链接/行数/源码变更核验见implementation-verification.json。

L1存在：配置、正式索引器/存储与原生审计、模板及测试均落盘。L2实质：真实index/save/load、完整空态、文件字节与格式检查、TF/DF/行位置的数值审计、私有目录/完成标记发布，无空占位实现。L3接线：真实Loader/M2→BatchProcessor/DenseEncoder/OpenAI SDK MockTransport+真Sparse→BundleStore→BM25Indexer→真实BM25S文件；另一进程从YAML/包重开audit，行ID和词项分数精确相等。正常/零片段/全空/混合空四路径均通过，禁止存储阶段调用分词、Dense和网络；重开进程没有openai/chromadb模块。

保存/回读合同覆盖：重复无写、参数变更独立版本、未知/缺失文件、坏marker、错身份/映射、版本/参数/重复JSON/词表错绑、NaN/非正/错误正数权重、越界及有效范围内错行/重复posting/offset、FIFO/symlink/超限描述、object/大shape/截断/错dtype在np.load前拒绝。原生两片段手算及OOV零分有独立断言。短写、半途save、marker写、rename和发布后fsync失败不返回ready；不确定发布可显式audit核验。

既有资产核验：除errors/storage导出/bundle_store私有辅助和Chroma路径委托四文件外，实施前所有既有Python源码/测试hash保持。旧keyword_index仍被a2_snapshot、hybrid_probe、chroma_probe等实质调用，当前删除候选0；不造旧unit→新Sparse兼容包装，不删除旧结果或索引。

边界：真实.env读/改0，模型真实请求0；MockTransport数据不当服务结果、原生存储通过不当检索质量通过。没有新依赖/运行配置/其他仓库修改、提交或push。串行本地构建、完整资料包与矩阵审计，无容量、并发、断电或绝对硬截止承诺。M4.4跨库激活/M5范围统计与查询仍待。完整代码课堂继续暂挂，本人调试/复写/独立掌握无新增证据。

唯一下一步：对照参考DocumentManager/FileIntegrity和现有三类持久产物，写M4.4同版本激活的Spec，明确包/向量/BM25必须全部核验后才能切换活动版本。
