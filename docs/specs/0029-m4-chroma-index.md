# Spec0029：M4.2 正式 Chroma 写入、重开与来源回读

日期：2026-10-15。状态：用户继续授权按同进程/共享.env方向修订推进，**M4.2已实施并完成本轮本地验收**，见第11节。旧隔离worker建议已撤回，正式代码不创建存储子进程服务或监督协议。

## 1. 当前链路、目标与边界

当前M1 MarkdownLoader→M2 Chunk/关系→M3成对编码→IndexBundle→BundleStore五文件保存/重载已实现。旧root ChromaStore仍消费实验unit，未消费正式包。本片接上：BundleStore.load→VectorUpserter→ChromaStore/SDK→独立索引目录→重开审计→按ID返回完整Chunk。

输入例子：一条需求片段和一行完整用例，各自有item_id、源hash、实际SourceSpan、双文本hash和Dense向量。写入与读回ID保持不变，数据库正文/metadata严格一致，向量按已定浮点容差核验；完整case_fields/来源关系由资料包提供。

只做build/audit/get_by_ids，不接M5相似度查询、BM25S、RRF、重排、active指针、文档更新删除、Agent/MCP。串行单写者，不承诺断电、并发、大库性能或真实资料质量。

## 2. 参考与已核证据

参考：https://github.com/Jerry-ai-dev/MODULAR-RAG-MCP-SERVER ，main/f658c5a4011c8b826707a65a3b11ce9301b0626f；2026-10-15本地只读核对，远端未重查。[M4调研](../research/m4-storage-and-lifecycle-2026-10-14.md)追踪Pipeline:435–453→VectorUpserter.upsert→ChromaStore.upsert→collection.upsert。沿其职责链、PersistentClient和cosine；不复制源码（pyproject声明MIT，未找到独立LICENSE），参考未锁SDK默认值不猜为相同。

差异：保留M2/M3 item_id而不另造存储ID；复杂结构在包内无损保留，不list→str；allow_reset=False、embedding_function=None、遥测False；完整新索引建完才发布，M4.4再激活。batch_size示例100参考ingestion.batch_size起始值，可配置，不声称参考Upserter独立分批或实验最优。

合成共享.env探针8场景检查通过，见shared-env-probe.json：合法模型Key/Chroma字段可共存，未知字段忽略；非法布尔/整数/JSON在SDK导入阶段失败。不会仅因存在.env拒绝启动。原探针证明SDK业务读取仍改内部文件，且close后目录移动可跨进程重开。

## 3. 配置与初始化

新增严格ChromaSettings YAML两字段：collection_name（示例knowledge_hub，3–63位ASCII字母数字/下划线/连字符、首尾字母数字、拒绝IPv4形式）、batch_size（示例100，正整数非bool）。load复用严格64KiB YAML；未知/重复字段、alias/merge拒绝。此限制比SDK更窄，是项目边界。

沿既有YAML+.env分工，不迁移真实配置。API构造显式传project_root；只校验根目录，不读取Key。SDK惰性导入，同进程创建Settings(_env_file=project_root/'.env', allow_reset=False, anonymized_telemetry=False, chroma_api_impl='chromadb.api.rust.RustBindingsAPI')，PersistentClient显式传派生索引path。合法字段优先级：显式实参>进程环境>指定.env>SDK默认。模型字段不为SDK识别；集合名/批大小由本项目YAML消费。

导入SDK自身仍会解析首次导入时cwd/.env，非法已知值可能提前失败；不chdir、不改os.environ、不替换第三方类。导入/配置/客户端失败转固定安全码，不输出原异常或文件值。当前没有初始化硬截止承诺。SDK必须为已安装1.5.9，不升级依赖；参考SDK配置无法替代我们实际版本的验证。

公开API（storage包导出，不改旧root入口）：

- load_chroma_settings(path) -> ChromaSettings。
- VectorUpserter(storage_settings, chroma_settings, *, project_root).build(bundle_id) -> VectorIndexReceipt。
- ChromaStore(storage_settings, chroma_settings, *, project_root).audit(bundle_id) -> VectorIndexReceipt。
- ChromaStore(...).get_by_ids(bundle_id, ids) -> dict[str, Chunk]。

Receipt为schema_version/status/index_id/bundle_id/knowledge_base_id/document_count/chunk_count/verified_count/model_space_id/representation_id/tokenizer_id/dimensions/sdk_version；status=ready/unchanged/verified。不返回SDK连接，不新增模型usage。

## 4. 目录、身份与映射

<storage_root>/<sha256(kb)>/artifacts/<bundle_id>/五文件保持；同级vectors/<index_id>/ready.json与chroma/保存派生索引。候选为vectors/.pending-UUID，失败保留不删除。index_id=SHA256规范JSON(schema_version,bundle_id,collection_name,sdk_version,storage_policy='explicit-cosine-v1')；批大小不改变逻辑身份。

ready.json含Receipt的ready身份、source_fingerprint、有效collection configuration、规范业务记录逻辑指纹及native_files清单。后者只列发布时必要的相对文件名，不锁内部文件字节；重开前缺少这些文件即拒绝初始化，避免SDK自动建回缺失数据库。元数据/标记规范序列化和有界读写复用BundleStore；不为新后端复制第三套JSON实现。

每条：ids=item_id；embeddings=dense_vector（维度/有限/非零且float32可表示）；documents=retrieval_text；metadata=bundle_id、document_id、source_sha256、embedding_text_sha256、retrieval_text_sha256、chunk_sha256。collection metadata绑定KB/包/三身份/维度。get核实SDK数据后，返回资料包的Chunk私有副本；缺失不从包回填掩盖。

空包建零记录集合、标记期望维度，不声称SDK已绑定实际维度；不发送空upsert/get批次。ids=[]先校验包/完整索引标记再返回{}；未知/重复ID、超过batch_size请求报错。

## 5. 正常、失败与发布

1. 应用YAML/项目根/包/向量预检，错误发生在索引目录创建前。无效请求不调用SDK。SDK自身环境解析在惰性初始化阶段，若失败可能留下pending目录，但不会发布ready。
2. 同index_id已有完整索引，完整审计后unchanged，无upsert；坏索引报错，不原地修复。只读缺失不创建目录或集合。
3. 私有目录0700→pending→SDK create_collection(None/cosine)→按batch_size写；先检查SDK最大批次，不静默调整。第n批失败停止后批，整次失败。
4. count及分批get全量审计IDs/数量/正文/metadata/向量；向量比较现有float32合同rtol=1e-6/atol=1e-8，非仅方向。有效配置/模型身份一致。公开close；重开再审计、close。
5. SDK关闭后检查native目录无符号链接，文件权限收紧0600/目录0700，不改进程umask。ready.json短写检查/flush/fsync→目录fsync→rename（不覆盖已有目标）→父目录fsync→ready。rename后fsync失败publish_uncertain。没有active操作。
6. audit/get仅get_collection/count/get，不get_or_create/upsert/delete/reset。SDK可能写内部维护文件，故业务只读不代表字节不变、只读文件系统可用或native文件hash不变。包文件仍做字节校验。

失败沿StorageError闭集：chroma_runtime_mismatch/chroma_environment_invalid/chroma_open_failed/chroma_read_failed/chroma_write_failed/chroma_close_failed/chroma_index_not_found/chroma_index_incomplete/chroma_identity_mismatch/chroma_integrity_failed/chroma_invalid_request/chroma_batch_limit/chroma_publish_failed/chroma_publish_uncertain/chroma_path_invalid。配置走SettingsError。日志固定码，不含路径/Key/原文/SDK原异常或stack。已有主异常时close失败另记安全码、保留主异常；成功分支close失败不能发布ready。无静默重试、自动回填或pending清理。

## 6. 影响文件、清理和回滚边界

先搜已有实现后新增core/chroma_settings.py、storage/chroma_backend.py（惰性SDK/关闭）、storage/chroma_index.py（映射/审计/发布/公开入口）；每文件≤500行。扩展core/errors.py、storage/__init__.py，复用bundle_store已有IO；新增examples/chroma.example.yaml模板（非真实运行配置）。不依赖experiments，不新增依赖或通用框架。

测试分配置/合同/故障、真实原生接线，复用已有make_bundle等样本。旧Chroma、A2与实验的实际消费者需重查；替换后无消费者的才按既有授权删。旧unit消费者不等于正式Chunk消费者，不为删除而增加兼容转换。不删除实验产物/真实材料/旧索引，不执行回滚、提交或push。

## 7. TDD与验收

- 先预期缺少正式入口红灯，再最小实现；配置/边界非法、未知/重复字段和输入副本覆盖。
- 来源/完整用例/双hash/三身份/乱序ID、缺失/多余/错绑定/向量错误；空包/空请求区分故障。
- 正常多批/重复无upsert/中途失败停止/close失败主异常保持/坏标记不修复/短写及发布不确定；路径与符号链接、目录权限覆盖。
- 原生验证在测试子进程内用合成.env保护真实Key；被测正式库自身同进程调用SDK。Loader/M2→SDK MockTransport+真Sparse/M3→BundleStore→VectorUpserter→新进程audit/get；None/cosine/禁reset、业务只读和另一cwd显式project_root有效均断言。模型POST=0，不把mock或本地向量库当服务/质量通过。
- M4.1与旧Chroma回归，再跑完整tests；compileall/pip check/diff/≤500行，版本不变。记录L1存在/L2实质/L3接线、消费者核验和已知限制；课堂按用户安排暂挂，无新增独立掌握证据。

## 10. 历史调研证据（实现前）

可重复命令：`.venv/bin/python docs/research/probes/chroma_env_probe.py`。只创建临时合成.env/向量库，子进程最小环境、禁止Python socket connect；真实项目.env读取0、模型调用0。完整结果在data/research/spec0029-evidence/sdk-probe.json，SDK四关键源码hash也记录其中。

| 合成情况 | 实测 |
|---|---|
| 无.env导入 | 成功，.env open=0 |
| ALLOW_RESET=true | 成功，导入后allow_reset=True，显式实例False，.env open=7 |
| 仅未知合成Key | 成功，但仍open=7 |
| ALLOW_RESET非法值 | 导入ValidationError，open=1 |
| 两条显式向量写入/另一进程重开 | count=2；源正文/ID准确；cosine/None/禁reset；公开close完成 |
| 零记录集合写入/另一进程重开 | count=0；cosine/None；无空upsert |
| 关闭后目录rename，再以另一进程重开 | 非空/空库均成功，验证发布路径可移动；不外推运行中移动安全 |
| 仅count/get重开 | 本次非空及空库的chroma.sqlite3内容hash变化；较早探针还出现HNSW文件变化 |
| 浮点 | 原向量回读最大误差5.960464477539063e-08，满足既有rtol/atol；不是逐字节相等 |

曾提出“回读是否成为单位向量”的诊断假设，实测与单位向量最大差约0.292893，不成立；失败的研究假设输出保留在normalization-hypothesis-rejected.json。未据此修改生产向量/放宽生产测试，不新增归一化策略。最终expected_checks_passed=true，Python网络尝试0；底层原生网络独立观测未知，不宣称完整网络审计。

本轮旧Chroma回归：`.venv/bin/python -m pytest -q tests/test_chroma_store.py tests/test_chroma_probe.py --tb=short` → **37 passed in2.08s**。M4.1回归：`.venv/bin/python -m pytest -q tests/test_storage_bundle.py tests/test_storage_bundle_wiring.py --tb=short` → **91 passed in4.12s**。语法/依赖/文档检查见verification.json；全量1357是上一片历史结果，本轮没有重跑全量。探针验证SDK行为，不是新VectorUpserter已实现、正式M3→Chroma已接线、检索质量通过或生产验收。


## 11. M4.2实施与验收（2026-10-15）

实际交付：core/chroma_settings.py、storage/chroma_backend.py、storage/chroma_index.py；扩展errors与storage导出；examples/chroma.example.yaml模板；test_chroma_index.py和test_chroma_native.py。新源码最大189行，项目源码最大266行。正式包不导入experiments或创建worker；原生测试使用隔离测试进程以免读取真实.env。

红灯与修正：red-formal.txt记录缺少ChromaSettings正式导出；red-sdk-failure.txt记录SDK包缺失漏出PackageNotFoundError，随后new_client将版本读取失败转chroma_runtime_mismatch。首轮另有测试故障计数复用错误（第二次构建未命中write_at=1），修正下一写入的注入位置并新增断言确认命中，原主异常保持断言不变；不把它记录为生产bug。

实际命令及输出：

- `.venv/bin/python -m pytest -q tests/test_chroma_index.py tests/test_chroma_native.py --tb=short` → **32 passed in6.33s**。
- `.venv/bin/python -m pytest -q tests --tb=short` → **1389 passed in99.55s**。
- `.venv/bin/python -m compileall -q naiyue_rag` → exit0（语法检查；独立应用构建不适用）。
- `.venv/bin/python -m pip check` → **No broken requirements found.**；freeze与M4.1前基线相同。
- `git diff --check` → exit0。最终链接/源码上限/包版本检查见implementation-verification.json。

L1存在：上述源码、模板及测试均落盘。L2实质：分批upsert、count/get逐记录核验、公开close、必要文件清单、私有权限/ready发布均有实现；无空占位。L3接线：真实Loader/M2→真实BatchProcessor/DenseEncoder/OpenAI SDK MockTransport+真Sparse→BundleStore→VectorUpserter→原生Chroma；另进程从YAML/保存包重开audit/get，禁止SDK业务创建/upsert/delete/reset，返回的Chunk/完整用例字段逐值相同。空包真实原生往返也通过。

共享配置接线：合成.env含模型Key与原生字段；ALLOW_RESET=true仍被显式False覆盖，真实client.get_settings确认遥测False/文件内存字段值。读进程换cwd，显式project_root仍消费指定.env。非法已知值在导入阶段转固定码，日志无合成私密值、未创建数据库。Python网络调用被阻断，模型真实POST=0；底层原生网络未独立观测，遥测已关闭。不声称真实用户.env、远端服务或业务质量通过。

正常/失败合同覆盖乱序ID/缺失/向量/正文/metadata错绑、额外记录、错误身份/距离、缺失必要文件/符号链接、空/重复/超量ID、空库、超SDK批次、第2批失败停止、双失败保持主异常、close失败、marker写/rename/发布后fsync失败。发布不确定可显式audit核验，不自动重试/补写/删除。

清理核验：旧root chroma_store.py仍被experiments/chroma_worker.py实际构造，并被chroma_probe验证和旧测试使用。新正式Chunk入口未替代legacy unit消费者，不增加转换包装；当前删除候选0。cleanup-audit.json记录证据，没有删除旧源码/产物。

限制：同进程SDK阻塞无硬截止；业务只读仍有SDK内部写；串行构建与全量来源/索引审计，性能/并发/断电未验；空库维度仅期望；M4.3 BM25S/M4.4激活/M5召回未接。真实.env未读取或修改、依赖未升级、无提交/push。课堂继续暂挂，仅记录机制/职责说明，没有本人调试/复写/独立掌握新证据。

唯一下一步：对照参考和既有BM25S资产梳理M4.3，先写从同一资料包SparseRecord.tokens构建/重开的Spec。
