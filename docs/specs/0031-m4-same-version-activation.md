# Spec0031：M4.4 三类持久产物的同版本激活

日期：2026-10-15。状态：**用户已确认，M4.4已实施并完成本轮本地验收，见第12节**。沿已接受的[Spec0028](0028-m4-artifact-storage-and-lifecycle.md)完整候选版本路线，复用已验收的[资料包](0028-m4-artifact-storage-and-lifecycle.md)、[Chroma](0029-m4-chroma-index.md)、[BM25S](0030-m4-bm25s-storage.md)。本片只完成版本登记、激活和固定版本重开，文档级管理另分片。

## 1. 当前问题与一个具体例子

示意：G1包含L1(v1)、历史L2_A及其用例。加入L2_B、更新L1后，候选G2的资料包和Chroma已就绪，但BM25尚未写完。此时若查询分别读取三个目录的“最新产物”，会组合G2正文/向量与G1关键词索引。

本片增加唯一活动指针：G2的三类产物全部重开核验成功，才由一次元目录事务将活动版本G1切换到G2。查询入口只读取一次活动版本，后续所有步骤使用该版本中的精确ID与配置。提交前失败继续使用G1；提交阶段发生无法确定的IO错误，明确报告“不确定”，重新读取确认，不谎称G1一定未变。

G2仍包含历史L2_A；历史需求保留与旧工程版本G1保留是两回事。激活本身不判断历史规则现在是否仍有效，不生成新的需求理解或测试结论。

## 2. 参考核验与证据边界

参考URL：[MODULAR-RAG-MCP-SERVER](https://github.com/Jerry-ai-dev/MODULAR-RAG-MCP-SERVER)。本轮只读本地`/Users/zmw/MODULAR-RAG-MCP-SERVER`，分支main，commit `f658c5a4011c8b826707a65a3b11ce9301b0626f`，2026-10-15工作区干净。本轮未查询远端，不声称最新远端版本。来源指纹见`data/research/spec0031-evidence/source-review.json`。pyproject声明MIT、仓库无独立LICENSE；独立编写本项目实现，不复制参考代码。

### 2.1 两条真实调用链

**摄取/文件历史：**`src/ingestion/pipeline.py:141`创建SQLiteIntegrityChecker；`run:238–245`计算文件SHA256并查询should_skip；`:438–451`先写Chroma，将返回ID按位置回填Sparse stats，再写BM25；`:523`最后mark_success；异常分支`:545–548`记录失败。这里描述源码顺序，没有运行第三方Pipeline。

`src/libs/loader/file_integrity.py:171–203`初始化SQLite/WAL和ingestion_history；`:184–193`主键是file_hash；`:243–266`只依据hash对应status是否success决定跳过；`:270–322`写成功，`:324–375`写失败；`:377–425`删除/列出记录。查询没有同时检查模型、切分表示、分词策略或知识库版本。

**管理消费者：**`src/observability/dashboard/services/data_service.py:50–75`装配Chroma、BM25、ImageStorage及SQLiteIntegrityChecker，然后构造DocumentManager；`src/ingestion/document_manager.py:98–187`用成功历史查列表/详情并到各存储计数；`:189–268`顺序删除Chroma、BM25、图片、历史，收集部分失败；`:301–355`若干辅助查询出错返回0/空列表/None。

### 2.2 保持职责与必要区别

| 事项 | 参考源码事实 | 本项目设计及原因 |
|---|---|---|
| DocumentManager | 跨存储管理，Dashboard通过DataService消费 | 保留协调角色；先增加activate/open_active，列表/详情/更新/移除在后续切片接入 |
| FileIntegrity | SQLite文件hash、成功/失败与处理时间 | 复用SQLite登记思想；已有资料包负责原文/位置/文件hash，不另建同义FileIntegrity类或复制一份文件历史 |
| 完整成功 | 多个后端顺序写，最后标文件成功 | 三个已完成产物重新核验后，登记精确版本绑定并切换一个指针 |
| 原子边界 | 上述运行链未见共同活动版本提交；删除支持部分失败 | 原子性仅承诺SQLite内版本登记与活动指针，不把Chroma/BM25/SQLite称作共同事务 |
| 跳过条件 | 单个file_hash的success | 不能据此跳过新模型/新表示的构建；本片仅同一完整绑定已激活时返回unchanged |
| 异常 | 部分辅助查询将失败表示为空 | 缺失/损坏/忙/不确定均有固定错误，合法未激活与故障分开 |
| SQLite日志 | 参考显式WAL | 本片本地串行激活、短时元目录读取，先显式DELETE日志/FULL同步；无需长期快照读事务或checkpoint管理 |

参考README:300宣称DocumentManager幂等与更新一致性，DEV_SPEC:194–212描述按文件hash前置跳过，:284–310描述管理模块。本节结论来自上述运行源码，不能用这些宣称证明跨库激活。此前参考局部BM25重复/移除探针见[M4调研](../research/m4-storage-and-lifecycle-2026-10-14.md)，本轮未重跑，也不将其扩大为参考整条Pipeline实测。

SQLite机制核对：[事务及BEGIN IMMEDIATE](https://www.sqlite.org/lang_transaction.html)、[隔离与日志模式](https://www.sqlite.org/isolation.html)、[synchronous](https://www.sqlite.org/pragma.html#pragma_synchronous)、[Python3.12 sqlite3](https://docs.python.org/3.12/library/sqlite3.html)。独立连接只看到已提交内容；BEGIN IMMEDIATE争用可能返回BUSY；COMMIT自身也可能失败。FULL是同步策略，不代替本项目断电/文件系统验收。

## 3. 我们三类产物的实际接线

```text
MarkdownLoader → M2 Chunk/关系 → M3 EncodingResult
                           ↓ prepare_index_bundle
BundleStore.save/load ── artifacts/<bundle_id>/五文件资料包
        ├─ VectorUpserter.build(bundle_id) → vectors/<vector_index_id>/
        │     ChromaStore.audit/get_by_ids → 原生Chroma和规范Chunk回取
        └─ BM25Indexer.build(bundle_id) → bm25/<bm25_index_id>/
              BM25Store.audit → 行映射、原生矩阵或明确empty状态

本片已接入：DocumentManager.activate
        → 重开资料包 + Chroma.audit + BM25.audit
        → SQLite登记IndexVersion + 切换active（同一事务）
DocumentManager.open_active
        → 一次读取已提交绑定 → 关闭目录连接 → 三类重开核验
        → 返回固定ActiveVersion；M5随后按此描述装配两路和原文
```

| 产物/源码 | 实际保存与核验内容 | 本片复用与缺口 |
|---|---|---|
| storage/bundle_store.py、artifact_bundle.py | 原文Document、Chunk/SourceSpan/完整用例、关系、M3成对编码及配置/报告；manifest含KB/三身份/source_fingerprint；load重做来源绑定 | load作为规范事实；同包重存unchanged，尚无active状态 |
| storage/chroma_index.py | VectorUpserter逐批写正式item_id/原向量/检索文本/平面来源；ready记录bundle/KB/三身份/维度/配置，audit核验count/get与资料包 | 同包索引ID还取决于collection_name、SDK和策略；receipt不含集合名，重启需保存它；batch_size只影响执行 |
| storage/bm25_store.py、bm25_backend.py | 直接消费同包Sparse.tokens；保存行映射/词表/CSC/统计，audit重开并按TF/DF核验；空行/全空词表有明确状态 | 索引ID还取决于k1/b、SDK和策略；receipt不含k1/b，重启需保存；无公开查询入口 |

共同字段：bundle_id、knowledge_base_id、document_count、chunk_count、model_space_id、representation_id、tokenizer_id；source_fingerprint由已核资料包及两路marker绑定。Chroma维度必须等于EncodingResult.dimensions；两路verified_count均等于chunk_count。BM25的N/avgdl是完整包的片段统计，空词片段不从共同ID空间消失。

实施前：三类产物都已实质实现、由真实消费者测试接线；当时尚无正式DocumentManager、SQLite目录、版本描述或活动指针。旧A2仍用实验装配，不在本片假装已经迁移M5查询。

## 4. 范围与最小实现

新增DocumentManager协调器与内部SQLite元目录；只接受已经保存/构建的候选，缺任一产物立即失败，不隐式调用模型、分词、构建、修复或降为单路。显式激活是必要控制写入，不能套用可选trace写失败仍成功的策略。

本片不实现文件扫描摄取总调度、列表/详情/统计、文档增量更新/删除、旧版本清理、HTTP/MCP、Agent、RRF、重排或问答。取消实验接口兼容的决定保持；本片无已替代消费者，不删除旧实验存储/结果。

沿Spec0028采用完整候选/旧版本保留，不做全量重建效率声明。当前不把doc→chunk映射再复制进SQLite：已核资料包是权威映射，后续文档管理先消费它；索引式查询目录有实际性能需求时再单独设计，避免维护第二份相同事实。

## 5. 新公共合同（已实现，均从storage导出）

- `DocumentManager(storage_settings, chroma_settings, bm25_settings, *, project_root)`：验证已有严格配置；构造不建目录、不读真实.env、不导入Chroma执行SDK。
- `activate(bundle_id, *, expected_revision) -> ActivationReceipt`：使用构造时选定的Chroma/BM25候选配置；expected_revision是调用方最近看到的目录修订号，首次0；必须为非bool的非负整数。
- `open_active() -> ActiveVersion | None`：无目录或合法无active行返回None；目录坏了或活动产物坏了报错。一次读取固定版本并核验三类产物，不返回部分可用或自动退回旧版。
- `IndexVersion.to_dict()/from_dict`严格字段、类型、深副本及身份核验；`ActiveVersion`和`ActivationReceipt`亦需安全JSON往返。

IndexVersion精确字段：schema_version=1、version_id、knowledge_base_id、bundle_id、vector_index_id、bm25_index_id、document_count、chunk_count、source_fingerprint、model_space_id、representation_id、tokenizer_id、dimensions、chroma_collection_name、chroma_sdk_version、bm25_k1、bm25_b、bm25_sdk_version。

version_id = 对去掉version_id后的上述字段作规范UTF-8 JSON（无末尾LF）SHA256。version/bundle/vector_index/bm25_index四类ID必须小写64位hex；计数非bool非负、维度正整数；模型/表示/分词身份沿已有合同；KB与当前配置相同；集合名和k1/b复用已有配置校验。SDK版本与当前固定运行版本匹配，不接受伪造回执替代真实audit。

ActiveVersion仅含`revision`（正整数）和`version: IndexVersion`。ActivationReceipt仅含`status=activated|unchanged`及`active: ActiveVersion`。不放绝对路径、原文、词项、向量、凭证、原始异常；不加入实际未测的延迟或费用。

**配置重开规则：**候选激活使用构造时配置；open_active使用版本记录内的collection_name/k1/b，Chroma审计批大小沿当前chroma_settings.batch_size。即使当前默认集合/参数已改，也不能拿这些新值代替活动版本的身份参数。batch_size不参与IndexVersion身份；改变它不生成新的逻辑版本。project_root只用于已定Chroma SDK装配，不写入版本描述，不改变SDK/.env既有边界。

open_active返回的是已核验版本描述，无长期SDK/SQLite连接或原生对象；后续调用使用它的bundle_id及存储配置。M5负责实际查询消费者；本片接线测试用描述重开BundleStore/ChromaStore/BM25Store，核对同一ID/来源并回取完整用例，不添加平行查询实现。

## 6. SQLite元目录、路径和资源合同

固定布局（格式规则，非新增运行配置）：`<storage_root>/<sha256(knowledge_base_id)>/catalog.sqlite3`。与artifacts/vectors/bm25同级；复用BundleStore已有KB祖先校验，不放宽其namespace白名单或接受任意用户路径。目录0700、目录文件0600；拒绝符号链接/非普通文件与非法祖先；检查SQLite已存在的journal同类路径。私人目录下不承诺抵御拥有同用户文件修改权限的恶意并发替换。

元目录只含两张业务表，`PRAGMA user_version=1`：

| 表 | 字段/约束 |
|---|---|
| versions | version_id TEXT PRIMARY KEY；descriptor_json TEXT NOT NULL，规范JSON、受max_manifest_bytes约束；只登记完成核验的版本 |
| active | singleton INTEGER PRIMARY KEY且只能1；version_id非空外键→versions；revision正整数；初始可以没有行 |

首次activate才可独占创建目录文件，验证KB目录已存在，再用O_EXCL/0600创建；仅创建者可以初始化schema并提交一个合法无active目录。已存在文件一律核验schema/版本/完整性，不用CREATE IF NOT EXISTS掩盖错误、不自动重建或reset。首次初始化被中止可能留下不完整文件，后续须明确报错并经独立恢复流程处理，不自行覆盖；初始化成功而候选失败可以留下合法无active目录。

sqlite3使用参数化值、每次操作独立且用毕关闭的连接、显式事务（isolation_level=None），不使用executescript隐式提交。显式外键ON、read_uncommitted OFF、trusted_schema OFF；写入DELETE日志/FULL同步，timeout=0争用立即失败，不隐藏重试。这里0表示既定“忙即报错”的控制策略，不是检索可调参数。

open_active仅`mode=ro`/query_only连接，目录不存在不创建；一次JOIN读取active及其版本描述并结束连接，完整SDK审计在目录连接关闭之后执行，避免把目录读事务持有到漫长IO结束。需SQLite自身恢复但只读打不开时明确报catalog_read_failed，不能返回空库。

核验已知表结构/约束、无额外触发器或视图、user_version及SQLite完整性；目录文件上限沿max_bundle_bytes、单描述沿max_manifest_bytes，超过显式catalog_limit_exceeded，不自动清理。原始SQL对象/字符串不来自用户；不声称SQLite内部内存与整个审计有绝对硬上限或硬截止。目录只记录活过的完整版本，不记录虚假的pending/failed历史，不建设任务队列。

## 7. 激活、重复与并发分支

1. 校验请求/配置/路径，必要时完成上述首次空目录初始化。
2. `BEGIN IMMEDIATE`取得当前KB目录的写入资格；锁持续到完成审计、登记及COMMIT/ROLLBACK。并发activate得到catalog_busy，不同时审计/改指针。此策略牺牲激活并发，符合本地单写者；不是只靠口头约定串行。
3. 读取当前revision：无active视为0；与expected_revision不同立即catalog_revision_conflict，不能覆盖较新的选择。即使候选恰好已激活也不能吞掉冲突。
4. BundleStore.load候选；ChromaStore.audit；BM25Store.audit；交叉核对第3节字段及两个派生index_id，组装IndexVersion。任一失败ROLLBACK，传播原安全存储错误；不继续后一后端，不登记半成品。
5. 若同version_id已在versions，严格比较完整规范描述；不一致报catalog_integrity_failed。若当前active即该version，完成三类审计后结束未改数据的事务并关闭连接，再返回unchanged，revision不变，不执行业务INSERT/UPDATE；该分支关闭失败报catalog_cleanup_failed，不伪装正常返回。
6. 新完整描述登记versions；同一SQLite事务中active指向它，revision从r变r+1。两步任一失败回滚，不允许指针找不到版本记录。
7. COMMIT及必要close/首次目录发布同步均确认后返回activated。所有路径关闭连接，回滚/关闭双失败保留原安全码并记录独立清理失败码；不输出原异常。

revision解决的是“基于旧活动版本提交”的冲突，不是模型/文档业务版本；受SQLite有符号64位整数约束，超界输入拒绝，递增越界报catalog_limit_exceeded。即使以后允许G1→G2→G1，revision也递增，持有旧revision的调用不能用同一个version_id绕过检查。本片不提供自动回滚命令；对真实数据重激活旧版仍按项目高风险确认规则执行，合成测试可覆盖此分支。

**提交不确定：**COMMIT抛IO错误、COMMIT成功后close或目录同步失败，返回catalog_commit_uncertain；这时指针可能已经变更。禁止自动激活旧版或声称旧版必然保持。调用方重新open_active，检查version_id/revision后决定后续动作。明确的SQLITE_BUSY且回滚确认成功可报catalog_busy；无法确认则按不确定处理。

旧版本目录和versions行均保留；当前open_active读取描述后，即使另一调用激活新版本，后续仍按已返回描述读取旧的完整三件套。持有描述不会删除旧文件；本片无清理功能。目录锁只序列化本协调器的激活，M4.2/M4.3独立构建仍遵守既有串行调用边界；不冒充已处理所有SDK并发、外部篡改或分布式写入。

## 8. 正常、空态与故障合同

| 触发 | 返回/异常与副作用 |
|---|---|
| 首次完整候选、expected=0 | activated，revision=1；三类原文件不重建 |
| 当前相同版本、expected匹配 | 审计后unchanged；版本行不增加、revision不变 |
| 新完整候选、expected匹配 | 一次提交新绑定与指针；旧资料/索引仍在 |
| 合法0文档/0片段，或全部Sparse为空 | 沿已有明确空态核验，可显式激活；这不自动授权按扫描结果删文档 |
| 一路缺失/坏包/坏marker/缺词表或错ID | 原安全错误；当前指针不变，未发生提交时不登记候选 |
| 模型/表示/分词器/维度/KB或来源不符 | 原有身份错误或catalog_identity_mismatch；不降级、不只比较片段数量 |
| 目录不存在、无active | open_active返回None，零创建；与目录损坏不同 |
| schema/描述hash/外键/指针损坏，SDK版本不支持 | catalog_integrity_failed或catalog_schema_unsupported；不返回[]/0，不自动迁移 |
| 同时激活/陈旧revision | catalog_busy / catalog_revision_conflict，旧活动选择不被覆盖 |
| 提交前SQL/磁盘失败，回滚可确认 | catalog_write_failed；旧活动不变；初始化空目录可能保留 |
| COMMIT/提交后清理无法确认 | catalog_commit_uncertain；重新读取判定，不伪造回滚成功 |
| 已激活后某产物被外部改坏 | open_active明确失败，不自动改指针、不回退或重建 |

新增固定码：catalog_invalid_request、catalog_path_invalid、catalog_limit_exceeded、catalog_schema_unsupported、catalog_integrity_failed、catalog_identity_mismatch、catalog_read_failed、catalog_write_failed、catalog_busy、catalog_revision_conflict、catalog_commit_uncertain、catalog_cleanup_failed。底层已有bundle/chroma/bm25错误保留，不把所有故障压成一个空结果。沿StorageError安全日志，只记固定码/安全阶段，必要目录提交与可选追踪分开。

## 9. 实施文件与TDD验收计划

拟影响8个源码/测试文件（其中3个新源码，均≤500行），加README/交接/计划/地图/索引等必要文档；无新服务、依赖升级、环境变量或真实配置修改：

| 文件 | 职责 |
|---|---|
| naiyue_rag/storage/version_types.py（新） | IndexVersion/ActiveVersion/ActivationReceipt严格合同与规范身份 |
| naiyue_rag/storage/index_catalog.py（新，内部） | 路径/schema/连接/有界目录读取、事务登记与revision |
| naiyue_rag/storage/document_manager.py（新） | 两个公共入口、三类审计、跨层绑定与异常清理 |
| naiyue_rag/storage/__init__.py | 正式导出，无实验包装 |
| naiyue_rag/core/errors.py | 追加闭集安全错误码，原行为保持 |
| tests/test_index_versions.py（新） | 类型/身份/序列化/目录格式/缺失只读/路径资源边界 |
| tests/test_document_manager.py（新） | 激活/重复/空态/失败注入/冲突/提交不确定，关联明确分支 |
| tests/test_document_manager_wiring.py（新） | 真实三类产物同包重开、独立进程及受控并发 |

先搜已有入口（本轮尚无catalog/active/DocumentManager实现）；优先复用BundleStore.load、两路audit和配置from_dict，不复制统计/原文审计。编码实现阶段如必须改已有公共签名或扩大文件范围，先修订Spec说明原因。本片不清理尚有真实消费者的旧代码。

必须先确认以下预期红灯，再最小实现：

1. DTO未知/缺字段、bool计数、非有限k1/b、非法ID/KB/三身份、描述篡改和JSON往返；batch_size变化不改变version_id。
2. 缺目录open_active为None且无创建；损坏文件、错schema、悬空active、超大描述/目录、符号链接/非普通文件均明确失败。
3. 真实三件套首次激活→另进程重开→三ID/来源/完整用例一致；后续当前构造配置改名/改k1/b仍按已激活身份重开，执行batch_size可变。
4. G1已激活，G2缺BM25/坏Chroma/错来源或身份→不能登记G2/切换指针；修复前不能报成功。用底层真实故障和协调器注入分别证明传播/门禁，不只造假回执。
5. 相同版本反复激活行数/revision不增长；changed revision即使同version也冲突；换候选revision+1；旧目录仍可按原描述重开。
6. 激活前就拿到G1的固定描述，激活G2后仍用G1读三产物；fresh open得到G2，无跨路再读latest。
7. 两进程用事件握手：首个持BEGIN IMMEDIATE，第二个明确busy；首个提交后第二个旧expected明确conflict。不用sleep紧时间窗口。保证子进程关闭/回收，无长期挂锁。
8. SQL登记失败/指针写失败/COMMIT前失败→旧指针保持；模拟提交已成功但报告失败→不确定，另进程可读确定结果；回滚/close双失败保留主错误、另记清理失败。
9. 正常/零片段/全空Sparse/混合空词可重开；候选不存在/缺一路均不是合法空态；不调用build/tokenizer/Dense/网络，不向模型发送原文。
10. 已激活后产物损坏→读失败、不回退；后端关闭错误可观察；真实项目.env禁止读取，原生测试仅隔离进程内合成.env；旧测试/公开入口不回归。

接线测试必须复用已有真实M1/M2/M3+Embedding SDK MockTransport/真Sparse、Chroma1.5.9和BM25S0.3.13；原生SDK自身在测试子进程隔离合成环境，生产库仍同进程运行。缺包不skip；全量通过才能声称本片验收。无需真实模型Key或外部API账户，真实模型POST为0。

## 10. 限制、回退边界与实施出口

最脆弱前提是发布后的三个版本目录不再被业务原地修改，并有空间保留新旧两套；SQLite只能原子切换记录，无法锁住人为删除或外部进程篡改的Chroma文件。读时重新审计、缺失即失败降低混用风险，不承诺敌对同用户进程下无竞态。

完整审计可能多次load/重做M2，Chroma业务只读也可能维护内部文件；本片复用已验机制，不增加缓存/回调/原生文件全量hash。10倍材料的审计延迟、目录增长、磁盘和SDK并发仍需后续测量；未测不写容量或性能承诺。

SQLite事务只控制元目录登记与激活；不做断电/网络文件系统/分布式/多写者生产验收。未提交的失败不会触碰旧活动选择；提交不确定先重读，不自动回退。开发中停止使用新入口即可保留现有三类存储功能；真实旧版本重激活、目录删除或数据恢复另按项目授权执行，本片不自动做。

M5消费此固定版本后，仍须明确A2范围内重算BM25统计与全库计分后过滤的区别；本片不决定查询评分、RRF或重排参数。完整文档管理尚未完成，不把本片叫做整个M4生产验收。

出口：给出失败测试→实现→相关/全量回归/compileall/pip check/diff与资产变更核验，附实际运行输出；L1文件、L2实质事务、L3真实三产物/重开消费者分别举证。工程与学习记录分开，Lesson8完整课堂仍暂挂，不登记本人独立掌握。

## 11. 设计轮验证（历史，非M4.4实现验收）

本轮只核对源码并重跑已有三类存储接线测试。实际命令、结果、来源指纹见`data/research/spec0031-evidence/`；1443全量为Spec0030上一轮记录，本轮未重跑全部测试。新的激活API、目录事务、并发门禁与故障测试尚不存在，不能宣称通过。

唯一下一步：确认本Spec后，按第9节完成同版本激活和固定版本重开的TDD实现。


## 12. M4.4实施与验收（2026-10-15）

实际交付第9节8个源码/测试文件：version_types三个严格冻结DTO、index_catalog的实际SQLite事务/路径与资源门禁、DocumentManager两个公共入口，以及导出/固定安全码与三个测试文件。已有Python只修改storage/__init__.py和core/errors.py；旧测试未改，新源码分别107/211/81行，项目源码最大266行。未升级依赖、未新增配置或服务。

### 12.1 红灯、修正和实际命令

- red-formal.txt：新增合同测试因缺IndexVersion/DocumentManager正式导出失败，随后最小实现；首组65 passed in7.27s，真实三产物/进程接线5 passed in9.17s。
- red-commit-boundary.txt：已成功COMMIT后注入带BUSY码的异常，错误报告catalog_busy；_abort修正为仅“确有事务且实际回滚成功”返回确认，提交后无事务保持catalog_commit_uncertain。另有真实SQLite读事务阻止COMMIT测试，确认普通BUSY会回滚、无指针或版本行残留。
- 首轮全量1530 passed in127.77s。最后核对第6节只读恢复合同，补出red-read-boundary.txt两个失败：注入SQLITE_IOERR和SQLITE_READONLY_ROLLBACK被误报完整性损坏；仅收紧_validate分类，真正CORRUPT/NOTADB仍报完整性，其他读取错误报catalog_read_failed，保持不补写/不返回空库。
- `.venv/bin/python -m pytest -q tests/test_index_versions.py tests/test_document_manager.py tests/test_document_manager_wiring.py --tb=short` → **89 passed in19.22s**（final-new-tests.txt）。
- `.venv/bin/python -m pytest -q tests --tb=short` → **1532 passed in127.11s**，为修正后最终全量（full-tests-final.txt）。
- `.venv/bin/python -m compileall -q naiyue_rag` → exit0；独立应用构建不适用。
- `.venv/bin/python -m pip check` → **No broken requirements found.**；前后137个安装包的名称/版本相同。
- `git diff --check` → exit0；未跟踪新文件另核语法/尾部空白/文档链接。来源、命令、资产差异和入口行号在data/research/spec0031-evidence/implementation-verification.json与implementation-source-review.json。

### 12.2 存在、实质与接线

L1：三个新模块和storage导出真实存在，公开DTO严格JSON往返；未建空占位模块。

L2：SQLite规范schema/参数化SQL、BEGIN IMMEDIATE、版本登记+active同事务、expected_revision、unchanged、只读重开、大小/路径约束和必要清理均为实质代码；未知提交结果不当普通忙或回滚成功。FileIntegrity的文件事实职责由已有资料包承接，未加一张重复文件历史表。

L3：test_document_manager_wiring.py::test_native_three_artifacts_activate_and_restart[normal/zero/all-empty/mixed]实际调用M1/M2/M3、Embedding SDK MockTransport、真Sparse/Chroma1.5.9/BM25S0.3.13；首次激活、重复、另进程改默认配置后重开、三个ID/来源/完整用例回取均一致。编码和网络在存储阶段被阻断；仅测试子进程隔离合成.env，生产库仍同进程运行。

事件握手双进程覆盖未提交版本不可见、同时激活busy、后续陈旧revision冲突；没有依赖极紧sleep。真实L1修订/新增L2_B的合成测试确认：BM25未就绪时仍读G1，完成后切换G2；历史L2_A/用例仍在，L1逻辑ID稳定、源hash变化，旧包及旧片段仍可按已取得描述读取。

故障覆盖目录未激活、格式/描述/外键/路径损坏、初始化中断、来源/身份错配、后端关闭、页数上限、SQL拒写、提交前后失败、回滚/关闭双失败和revision越界。坏活动产物不自动回退/修复，必要错误只输出安全码，无原文/Key/原始异常。

### 12.3 边界和下一步

真实模型POST0，真实项目.env读/改0，未修改已有索引或其他仓库；无删除、提交、push。清理复核：旧root Chroma/keyword/vector/a2_snapshot仍有实验与回归消费者，本片无替代关系，删除候选0。此前设计证据与首轮全量保留，最终门禁以上述1532为准。

本次为库级存储协调的本地工程验收，不是M5双路召回/业务质量或完整M4生产验收。完整审计延迟、目录增长、断电/分布式/SDK并发与真实材料效果未验；Chroma业务只读仍可能维护内部文件。列表/详情/更新/显式移除未实现。完整课堂继续暂挂，仅说明职责和验证结果，本人复写/独立调试/面试追问无新证据。

唯一下一步：对照参考DocumentManager.list_documents/get_document_detail，先写M4.5基于活动版本的只读文档列表/详情Spec，再按确认范围实施。
