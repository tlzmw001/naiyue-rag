# Spec0034：M4.7 显式文档移除与历史版本保留

日期：2026-10-15。状态：**用户已确认，M4.7已实现/接线并完成本地验收**。依赖[Spec0031](0031-m4-same-version-activation.md)、[Spec0032](0032-m4-document-management.md)和已实施的[Spec0033](0033-m4-ingestion-and-updates.md)。第1–10节保留设计轮的源码对照、提案及当时验证；第11节记录本轮实施与接线证据。本轮只使用临时合成材料，不执行真实知识库移除。

**已确认的业务选择（2026-10-15）**：用户选择“允许再次摄取时重新纳入”。移除只改变活动快照；原 Markdown 仍在输入目录时，后续主动 run 将它作为新增重新纳入。不保存持续忽略标记。用户随后要求“继续”，本轮按本Spec连续实施。

## 1. 场景、语义与验收目标

活动 G1/revision=7 包含 `L1_Module、L2_A、L2_A_测试用例`。调用方从列表得到 L2_A 的完整 document_id，并明确请求移除该文档：

- 成功后 G2/revision=8 的文档、片段、关系节点/边、Chroma 和 BM25 均不包含该文档对应数据；L1 和用例继续保留，不级联移除。
- G1 的完整资料包、两个索引和版本记录保留；源目录的 L2_A.md 不改写、不删除。旧版本中的内容仍可通过已有底层显式 ID 回读。这是活动知识库成员变更，不是隐私擦除或访问撤销。
- 任一路构建失败，不激活不完整候选；若其他写者未提交新版本，原 G1 继续活动。并发冲突不覆盖其他写者；提交不确定须重读，不能宣称已回滚。
- 后续主动目录摄取若再次提供原 L2_A.md，按新增纳入；没有后台自动复活。若希望后续扫描也不再提供它，调用方需另行管理输入目录，本接口不移动源文件。

沿 Spec0028 已认可的完整版本构建/切换路线，首片不做原地 Chroma.delete、BM25 修改或旧目录清理。输入目录缺少文件仍不等于移除授权，原 run 的新增/替换语义保持。

## 2. 参考源码：谁调用、清理什么、失败怎样传播

来源：[MODULAR-RAG-MCP-SERVER](https://github.com/Jerry-ai-dev/MODULAR-RAG-MCP-SERVER)，本机只读目录 `/Users/zmw/MODULAR-RAG-MCP-SERVER`，分支 main，commit `f658c5a4011c8b826707a65a3b11ce9301b0626f`，2026-10-15 核对工作区干净。本轮未查询远端或运行参考测试/Pipeline/setup/Skill。README、DEV_SPEC、pyproject 和相关源码/测试指纹在 `data/research/spec0034-evidence/source-review.json`；pyproject 声明 MIT/Python>=3.10，依赖范围不等于实际锁定安装版本。本片借鉴职责与流程，独立实现，不复制第三方代码。

```text
Dashboard ingestion_manager:132–138 删除按钮
  → DataService.delete_document:168（装配当前 collection 的 stores）
  → DocumentManager.delete_document:189
      source_hash：优先参数；否则读文件算hash；失败再按历史路径查hash
      → Chroma.delete_by_metadata({'doc_hash': source_hash})
      → BM25.remove_document(source_hash, collection)
      → ImageStorage.list_images(doc_hash) → 逐张 delete_image
      → FileIntegrity.remove_record(source_hash)
      → DeleteResult：计数、各项bool、errors；有捕获错误则success=False
```

[DocumentManager](https://github.com/Jerry-ai-dev/MODULAR-RAG-MCP-SERVER/blob/f658c5a4011c8b826707a65a3b11ce9301b0626f/src/ingestion/document_manager.py#L189) 四步各自 try/except，某步异常不会阻止后续清理。没有共同事务、补偿或历史快照保留机制；甚至 Chroma 失败后仍会尝试删除摄取记录。原始 PDF 未在该方法 unlink，图片派生产物另有物理清理。

| 证据类别 | 当前查到的事实及限制 |
|---|---|
| 项目自述 | DEV_SPEC:285–313 描述跨四存储管理，历史记录移除后允许重新摄取；其中向量过滤写 metadata.source，实际代码用 doc_hash，应以当前源码为准 |
| Chroma 源码 | chroma_store.py:336 按当前 collection 的 metadata 取 IDs 后删除；单库删除不等于跨存储原子性 |
| BM25 源码 | bm25_indexer.py:364/394 按 chunk_id.startswith(doc_id) 移除；管理器传完整内容hash，而 vector_upserter.py:143–166 产生的是路径hash前8位+序号+内容hash前8位，身份不一致，不能凭 DeleteResult 声称真实链路已全部清除 |
| 摄取记录源码 | file_integrity.py:377 参数化 DELETE 按 file_hash 提交；记录移除成功不能证明两个索引都已清除；路径fallback:336遍历记录且未按collection筛选 |
| 图片源码 | image_storage.py:393 先删索引记录再尝试unlink；文件unlink异常被忽略，返回值仍可能true，因此images_deleted不能证明图片文件全部消失 |
| 参考测试源码 | unit/test_document_manager.py:278–329 通过Mock表达成功/部分失败；missing-file测试有 `or True` 恒真断言，不能当完整fallback结果证据；本轮未执行这些测试 |
| 历史本机证据 | M4调研已有局部BM25身份探针，不是本轮运行或整个参考Pipeline实测；见[存储调研第4节](../research/m4-storage-and-lifecycle-2026-10-14.md) |
| 本轮真实服务 | 无参考服务、模型POST或删除服务调用；不评价参考生产可用性 |

## 3. 我们现有链路与可复用资产

```text
IngestionPipeline.run(expected_revision)
  → DocumentManager._document_bundle：一次选active + 同包完整核验
  → MarkdownLoader.load_all
  → plan_ingestion：按稳定ID合并（未提供旧文档仍保留）
      ├─ 未变：原activate完整审计 + revision门禁 → unchanged
      └─ 变化：旧版本健康审计 → 全库M2 → BatchProcessor
          → BundleStore.save → VectorUpserter.build → BM25Indexer.build
          → DocumentManager.activate：短SQLite事务登记版本/切换active

DocumentManager.list_documents/get_document_detail
  → 一次active/资料包读取 → 文档摘要、片段ID（不启动检索SDK）
DocumentManager.open_active
  → 固定一次active → 同资料包/双索引审计
```

- 逻辑文档 ID 是 `doc-` + SHA256([knowledge_base_id, 规范相对路径])；source_sha256 标识内容修订。相同字节、不同路径是不同文档；移除必须使用逻辑 ID，不用文件名、前缀或当前磁盘内容hash猜目标。
- BundleStore 存原文、完整片段/来源、关系和成对编码报告；load 不依赖原 Markdown，完整验证且重算 M2。坏包不当空库。
- IndexCatalog 保留版本登记，只切换 active；底层没有自动GC或文档移除。M4.6没有持久忽略清单。
- 当前未实现正式 M5 双路查询。M4.7只能验收新活动版本成员/两路ID空间，不能宣称新查询结果、Agent问答或业务质量通过。
- Chroma审计可能执行SDK内部维护写，不承诺旧索引文件字节/mtime完全不变；承诺旧快照的业务成员/来源/编码数据保持可回读。

本轮合成探针从已保存三文档包，在内存排除 L2_A 后调用现有 prepare_knowledge_base：保留2文档/6片段，用例仍在；目标节点/边消失，出现 missing_pair、target_not_loaded；源文件及旧资料包仍含原文。另有原有 atomic_oversize/stale_header_line_range 诊断。它证明现有 M2 的候选集合语义，**没有实现移除入口、索引重建或激活**。首次探针因导入路径误写 preparation 失败，核对现有 knowledge_preparation 后重跑；未改源代码绕过错误。

## 4. 推荐入口与参考差异

新增库级接口：`IngestionPipeline.remove_document(document_id, *, expected_revision) -> RemovalReceipt`。不修改现有构造、run、DocumentManager公开签名、配置schema、资料包/索引/SQLite格式。

| 职责 | 参考 | 本片建议及原因 |
|---|---|---|
| 入口 | DocumentManager.delete_document(path,collection,hash) | IngestionPipeline.remove_document(id,expected_revision)；重建需要该对象已有的M2/M3组件，不让存储管理器反向持有模型/Pipeline |
| 定位 | 内容hash/磁盘/历史路径fallback | M4.5列表的稳定ID + 必填revision + 一次活动快照；不跨KB查找 |
| 执行 | 逐存储原地清理 | 从已核完整包排除一份源，完整新版本构建/激活；复用原串行编排 |
| 历史 | 清除成功记录 | 历史版本继续保留；不引入第二份成功表或物理回收 |
| 用例/引用 | 没有本项目业务合同 | 不级联、重算M2，保留原文中的引用文本并记录关系缺口 |
| 返回/失败 | DeleteResult部分成功和异常文本 | 严格RemovalReceipt或整次安全IngestionJobError；保留本次用量和已知激活状态 |

这是与参考的有意差异，需随本Spec确认。拒绝另建删除服务/Agent、通用任务框架或让Manager通过回调重新调用Pipeline。

构造沿用当前合同：仍需要存在且合法的 knowledge_base_root，以及调用方装配的实际 BatchProcessor；构造会校验该目录，不能声称完全脱离源目录启动。remove 方法不执行 load_all、遍历或打开原 Markdown，只消费已存快照，因此目录内文件已变化/移走不影响选定目标；目录本身失效则现有构造会拒绝。Provider生命周期仍由调用方持有。

## 5. 正常与空态分支

```text
validate：严格document_id / expected_revision / 现有配置与组件
  → select：_document_bundle(expected_revision)，固定active+base
      ├─ 未激活：not_found，previous_active=None，active=None；不创建空版本
      └─ 已激活：plan，目标配置身份核对
          ├─ ID不存在：原activate(旧bundle,expected_revision)
          │    审计+最终revision检查 → unchanged → not_found
          └─ ID存在：从base提取摘要，按完整ID排除一份文档
               → 审计选定旧三件套（不重新选latest）
               → 全保留集M2/M3 → 完整新包/双索引
               → 原activate(新bundle,expected_revision)
               → removed + previous_active/active + 实际编码报告
```

1. document_id必须是现有闭集格式 `doc-`+64小写十六进制字符；revision必须非bool整数0..MAX_REVISION。非法值在任何目录/源扫描前拒绝，错误stage=validate、code=ingestion_invalid_request。
2. select只读一次目录，先拒绝已知陈旧revision；同包身份损坏沿原StorageError安全码失败。未激活仅接受revision=0，返回该次读取时的未激活事实；这是一次快照读取，不承诺返回后仍无其他写者。该分支无finalactivate/建库/模型请求，回执组装失败记plan/not_attempted。
3. 已激活的两分支都要求处理身份匹配：IngestionSettings、model_space_id、representation_id、实际tokenizer_id、collection_name、Chroma/BM25固定SDK策略、BM25 k1/b，与M4.6复用判据一致。运行批大小/超时、缓存目录不作为语义身份；当前限额仍适用；原目录/资料包读取也会先以当前文档/片段限额约束旧基线，不能因为移除后数量可能变小而绕过旧版本核验。不同则stage=plan、ingestion_profile_mismatch，编码/保存0；不把移除顺便变成模型或切分迁移。先通过明确的run重建，再用新revision请求移除。
4. not_found在已选活动版本上通过原activate完成健康审计/最终revision门禁，无编码/save/build、revision不增长。不得因为ID未找到掩盖坏索引；陈旧revision仍报冲突。合法但属于别的KB的ID只在当前KB查找，结果not_found。
5. found复用project_detail(active,base,id)的纯投影得到DocumentInfo；不调用会再次选latest的公开详情。其余源按ID排序，全量重新M2、预检、编码和构建，与M4.6变化分支一致；新文档数严格少1。
6. 移除最后一文档构建有活动版本的空库：真实EncodingReport.empty、两个合法空索引，revision增长，无Embedding POST；不把它变成未激活。空白文档/无chunk文档仍按文档ID移除，不能只按向量条数判断目标存在。
7. 本次不级联移除用例或其他引用方；不改写引用文本、表头行号或业务有效性。重算关系只保留剩余文档节点/边，断开目标记录target_not_loaded，用例原需求不在时记录missing_pair，不为历史资料缺引用整次失败。
8. 同一个ID再次移除，用新revision得到not_found；用旧revision得到冲突。批量移除、强制绕过完整性、自动重试/恢复/追随latest不在本片。

## 6. 返回值与整次失败合同

新增严格 `RemovalReceipt`，仅以下六字段；防御复制、闭集校验、to_dict/from_dict严格JSON往返、安全repr：

| 字段 | 合同 |
|---|---|
| status | removed / not_found |
| requested_document_id | 此次请求的合法完整逻辑ID |
| previous_active | 此次一次选定的ActiveVersion或None |
| active | 真正激活后的ActiveVersion；not_found为已审计旧active，未激活为None |
| removed_document | removed时为选定旧快照的DocumentInfo（含路径、旧源hash、字节数、旧片段数），否则None |
| encoding_report | removed时为本次实际success/empty报告，否则None；不挪用旧包报告 |

removed约束：两版本同KB，revision正好+1，新版本文档数比旧少1；removed_document.id等于请求，文档ID/相对路径与旧KB绑定且旧片段数不超过旧总数；报告paired_input_count等于新版本片段数。候选版本必须不同，实际ActivationReceipt为activated；否则明确合同错误，不捏造removed。

not_found约束：previous_active==active（允许同时None），removed_document/report均None。记录中的字节/片段数描述退出新快照的数据，不是释放磁盘量；无physical_deleted_count、token费用估算或可信度字段。序列化不能带原文、向量、词项、Key、绝对路径或原始异常。

整次失败沿用 `IngestionJobError`，仅增加安全闭集码 ingestion_profile_mismatch，不新增另一套失败协议：

- stages复用validate/select/plan/prepare/encode/bundle/vector/bm25/activate/finalize；remove不执行load。编码前失败report=None；编码错误保留实际失败报告；编码成功后下游失败保留本次成功报告，不把整次失败伪装成编码失败。
- candidate_bundle_id只在save成功返回合法ID后可知；pending/发布不确定不能猜。激活前not_attempted；真实StorageError在activate中按原合同映射not_committed或catalog_commit_uncertain/unknown；非预期激活异常unknown；已收到回执的finalize异常保持activated/unchanged。
- 共享内部执行错误原样传播，不让外层以plan等阶段重包覆盖报告/候选/激活状态。未激活not_found回执组装在plan阶段完成，避免给原finalize异常合同塞入不真实的unchanged。
- 用固定日志stage/code/activation_status观察失败，保留原必要IO日志；不记录str(error)、响应正文/URL/栈/原文。KeyboardInterrupt/SystemExit继续传播，不自动重试或承诺中断等于回滚。
- 坏旧包/坏一路不得靠移除修复；先明确报错。预检/编码/构建失败不触碰旧版本业务内容；并发writer胜出时保留对方active。提交结果未知时调用方重读catalog/list，不能自动恢复旧版本或擅自再次移除。

## 7. 最小内部复用与影响文件

先搜现有入口，优先复用：BundleStore/load/save、DocumentManager._document_bundle/_audit/activate、project_detail、prepare_knowledge_base和BatchProcessor均有真实消费者。不新建独立删除存储或清理算法。

- 将pipeline.run变化分支已有的prepare→encode→bundle→vector→bm25→activate整理为私有 `_build_and_activate(documents, *, expected_revision)`，实际供run变化和remove命中两个入口调用。返回经验证的ActivationReceipt、本次EncodingReport和已知候选ID，内部保留精确阶段/错误观察；不引入回调/注册器/ContextVar或可变跨请求状态。
- 未变/未命中所用原activate的相同异常边界按实际两消费者共用小私有方法；原IngestionReceipt、run公开参数和失败合同保持，原测试继续约束。旧基线健康审计使用已选版本描述及其保存参数，不重新取latest。
- FileIntegrity中把已有处理身份比较提为内部纯谓词，供plan_ingestion和remove的身份门禁两处使用；比较规则不变，不扩展完整合并规划为移除模式。
- 来源限额/当前编码限额沿用现有_source_limits/_inputs。无论操作目标大小，完整新包的限额都需满足；不因移除某份文档绕过其他保留源的坏状态。

拟改5个源码：ingestion/pipeline.py、ingestion/file_integrity.py、core/ingestion_types.py、core/errors.py、顶层__init__.py（导出RemovalReceipt）。拟扩展test_ingestion_types.py，新增test_document_removal.py与test_document_removal_wiring.py，共8个源码/测试文件；加阶段文档会超过8个文件，**范围限本片职责**。源码单文件≤500行。原存储管理实现、格式、依赖/真实.env/运行配置不改。

此重用有具体代价：改动run内部控制流，可能让原阶段/报告/提交状态失真，必须用原86项摄取测试和本片故障注入验证；不以“去重”为由顺带改其他入口。旧实验仍有消费者，本片不替代它们，无删除候选。

## 8. TDD与接线验收清单（设计轮拟定，实施结果见第11节）

先加测试确认缺少remove_document/RemovalReceipt的预期红灯，再实现；故障注入断言具体阶段/状态/调用次数/当前版本，不放宽断言或skip。复用现有fixture/FakeClient/MockTransport及跨进程消费者，不新造平行测试框架。

| 场景 | 关键断言 |
|---|---|
| 移除L2、L1、用例 | 每次只退出指定ID；其他文档原文/hash/完整用例字段保留，关系重新计算；两路ID与新bundle严格同集 |
| ID身份 | 同内容不同路径只移除目标；非法ID/路径/前缀/bool revision提前拒绝；其他KB合法ID只在当前KB查找 |
| 未激活/不存在/重复 | revision0时不建库，None空态；已有版本not_found无模型/save/build、原activate审计，revision不增长；旧revision冲突 |
| 空白/最后文档/全空词 | 文档存在不能用向量数量判断；移除最后源后活动空库及empty报告；空词/混合空行ID完整 |
| 源文件独立 | 方法运行时禁止loader.load_all/读取源Markdown；源原文已改或移走仍按选定存储快照；构造源根约束单独覆盖 |
| 关系与历史 | 保留用例出现missing_pair，保留引用方出现target_not_loaded；旧包/两个索引和版本记录仍可用，不级联 |
| 后续再次摄取 | 用户已确认：源文件仍在时显式run按added纳回；移除本身不启动run |
| profile/限额 | 模型/表示/分词/切分/collection/k1/b/SDK策略不符提前失败；仅runtime批量/缓存变化不迁移语义；当前源/输入/片段/批次限额继续有效 |
| 必要IO/下游失败 | select/prepare/encode/save/vector/bm25注入失败；旧active保持（无其他writer），成功或失败编码报告/候选ID按真实阶段可知；安全日志无敏感内容 |
| 坏旧版本 | 旧包/单路缺失或损坏整次失败；ID未命中不能隐藏坏索引，不自动修复 |
| 并发/提交 | 真实catalog revision竞争不能覆盖胜出者；commit_uncertain为unknown；收到回执后组装失败保留已知状态；无自动重试/回滚 |
| 中断/DTO | BaseException传播、必要清理保持；回执严格字段/数量/KB/ID/版本/报告/深拷贝/JSON一致，拒绝矛盾输入 |
| 原生三存储跨进程 | 首进程真实M1/M2/M3（SDK MockTransport+真Sparse）及Chroma/BM25，第二进程执行remove，第三进程管理/完整chunk ID消费者回读新旧版本；外部网络阻断 |
| 原路径回归 | 原run首次/重复/更新/force/profile变化、阶段错误/用量/提交未知和空态保持；全量tests通过 |

本机TDD/接线用Fake或SDK MockTransport、真实Sparse/Chroma/BM25与SQLite；真实模型POST预算0，无需新Key/MCP/服务/CLI。实际部署时found操作需要现有配置的Embedding服务，并全量重编码保留集；因此凭证/接口不通会整次失败，旧active不因它自动降为单路。另行真实服务验证须明确材料/模型/请求和截止时间，既有Key配置不构成本轮调用授权。

## 9. 成本、保留与回退边界

首版移除一文档仍读取/核验旧完整包并重编码保留的全部片段，重建BM25全库统计和Chroma，再审计激活；大库成本/时间可能显著，服务usage未知不能写成0费用。复用旧Dense/Sparse、只重排索引、GC等是独立优化，不能将新报告与旧记录拼在一起跳过当前合同。

依赖前提是“允许保留历史，移除仅改变当前成员”。若需求是所有版本不可再读，当前方案不满足，须重新设计物理擦除/引用/读者与保留策略，不能把本方案改名声称完成。

实现前只有文档可回退，无数据变化。实现后新候选未激活可保留待诊断，不自动清除；已激活版本若要恢复，需经独立明确授权的版本激活操作、核验旧版本参数并使用最新revision，恢复会产生新revision，不是倒写revision。没有一键撤销/自动rollback承诺。本片不新增恢复API/历史浏览/物理GC/目录删除，原文件也不处理。

## 10. 设计轮实际验证（历史，非M4.7功能验收）

- 现有10文件回归：`.venv/bin/python -m pytest -q tests/test_ingestion_types.py tests/test_file_integrity.py tests/test_ingestion_pipeline.py tests/test_ingestion_pipeline_wiring.py tests/test_index_versions.py tests/test_document_manager.py tests/test_document_manager_wiring.py tests/test_document_views.py tests/test_document_management.py tests/test_document_management_wiring.py --tb=short` → **259 passed in 57.80s**。
- 合成内存候选集探针：3文档→保留2文档/6片段；源文件和旧包保持，目标节点/边退出、用例保留及诊断符合现有M2规则。结果 `data/research/spec0034-evidence/current-removal-boundary-probe.json`。不是新remove入口或参考删除运行。
- 本轮没有全量1702重跑；1702 passed in170.29s是Spec0033实施的历史结果。无打包/build入口，以compileall检查当前Python编译；依赖、资产、链接与diff结果见 `data/research/spec0034-evidence/design-verification.json`。
- L1：本Spec与证据存在；L2：移除入口/回执仍是提案；L3：M4.7未接入生产链。源码事实、本机确定性验证及未来验收清单分开记录。
- 完整课堂继续暂挂；本轮仅说明职责/数据流，用户独立走读、调试或实现能力无新增证据。

**实施顺序**：本轮已获继续授权，按上述单一切片完成预期红灯、最小实现与接线回归；验收结果追加于本文末尾。

## 11. M4.7实施记录（2026-10-15）

用户确认再次主动摄取允许纳回，随后要求“继续”，本轮按本Spec进入实施。现已接线：

```text
remove_document(id, expected_revision)
  → 一次_document_bundle → profiles_match → project_detail/保留集
  → _audit_base → _build_and_activate（与run变化分支共用）
  → prepare_knowledge_base → BatchProcessor → BundleStore.save
  → VectorUpserter.build → BM25Indexer.build
  → _activate_existing → 原DocumentManager.activate
  → RemovalReceipt（已知提交状态后的组装错误仍保留状态）
```

not_found的已激活分支复用_activate_existing，审计/最后revision检查后原版本不增长；未激活分支不创建存储。共享内部方法分别拥有阶段和错误边界，调用方不在外层重包其错误；_fail只归一化当前边界，保留已有错误码/本次报告/候选/激活状态。配置一致比较从原plan_ingestion抽出profiles_match，两个真实入口消费，不改变旧run的比较语义。

### 11.1 TDD与测试接入修正

- 实现前移除测试52项因不存在remove_document或RemovalReceipt而红灯，日志removal-red.txt；DTO新增22项因缺公开RemovalReceipt红灯（2 failed/20 fixture errors），日志receipt-red.txt。均为新功能缺失，不跳过。
- 首轮组合156项中151通过，5项失败：新测试把超过batch_size=2的全部旧ID一次交给Chroma.get_by_ids；另两项使用收紧限额的reader验证旧active，该reader会按已有合同拒读超限旧版本。核对实际源码后，测试改为分批汇总所有ID、用原reader断言旧active；完整ID/成员/版本断言保持，没有改Chroma或Catalog绕过保护。原生接线首轮3过/1失败亦为同一批量调用错误，按原合同分批读取。原始日志保留。
- 当前限额先约束旧基线读取的事实已补入第5节；不能声称“移除后小于限额”即可绕过旧快照完整核验。没有放宽断言、skip、修改旧测试基础设施或安装依赖。

### 11.2 本轮已运行的切片与接线

命令：`.venv/bin/python -m pytest -q tests/test_document_removal.py tests/test_ingestion_types.py tests/test_file_integrity.py tests/test_ingestion_pipeline.py tests/test_document_removal_wiring.py --tb=short`。

实际结果：**160 passed in 40.56s**，其中新增78项（移除52、DTO22、原生接线4），既有82项同时回归。日志slice-tests.txt；全量结果以本轮最终implementation-verification.json和下方验收摘要为准。

- 确定性入口test_remove_one_document_preserves_sources_and_old_indexes[L1_Module.md/L2_A.md/L2_A_测试用例.md]：原文/历史包/双索引完整保留，目标退出新集合，引用缺口明确。
- test_removed_source_is_added_by_next_explicit_ingestion：移除后revision2，再次主动run将原源按added=1纳回revision3。
- test_dense_failed_report_is_not_lost_in_shared_builder、test_revision_race_keeps_winner_and_current_encoding_report、test_commit_uncertain_requires_catalog_readback：失败报告、胜出版本与提交不确定有实际断言。
- 原生test_native_removal_preserves_old_version_and_existing_consumer[normal/zero/all-empty/mixed]：第一进程沿现有公开摄取构建，第二进程remove，既有管理ID消费者在新进程回取完整用例，另一进程审计并完整回读旧版本；Embedding SDK为MockTransport，Sparse/Chroma/BM25/SQLite为真实本机组件。所有子进程阻断外部网络，仅临时合成.env；四场景均在上述160中通过。

### 11.3 修改与验证边界

186项实施前资产比对：仅5个既有源码修改（pipeline、file_integrity、ingestion_types、errors、顶层导出），test_ingestion_types只追加用例，另新增两个测试文件；其余既有测试、实验、存储源码、配置/锁文件保持。137安装包名称/版本不变，生产源码最大266行。

L1公开RemovalReceipt与remove方法存在；L2真实完成规划/重建/激活/严格回执；L3公共入口到双索引和既有消费者的跨进程接线已验证。无真实模型POST、真实.env读取或修改、真实业务资料移除、旧索引清理、提交/push。临时合成测试不代表远端材料质量、大库性能、断电恢复或生产并发通过。

完整课堂仍暂挂，无本人独立调试或复写新证据。唯一下一步：对照参考QueryProcessor/HybridSearch与现有QueryEncoder、A2和正式活动版本，先梳理M5查询链并制定M5.1 Spec；不在本片提前实现召回。

### 11.4 最终验收结果

- 全量命令 `.venv/bin/python -m pytest -q tests --tb=short` → **1780 passed in201.57s (0:03:21)**，退出0；full-suite.txt保存原始输出。
- `.venv/bin/python -m compileall -q naiyue_rag tests`退出0；无独立打包构建入口，compileall是语法编译检查。`.venv/bin/python -m pip check`输出No broken requirements found.；`git diff --check`退出0。
- 8份阶段文档相对链接/空白检查通过；新文件额外检查，旧test_ingestion_types原内容hash保持、只追加22测试。资产/包版本/来源指纹核对及实际命令在implementation-verification.json和implementation-assets.json。无参考源码执行或第三方代码复制。
- 本轮模型POST0、真实.env读改0；无真实资料操作、删除、提交/push。后续唯一下一步仍为M5查询链对照及M5.1 Spec，完整课堂按用户安排暂挂。
