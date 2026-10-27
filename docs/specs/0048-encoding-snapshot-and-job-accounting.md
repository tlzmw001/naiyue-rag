# Spec0048：优化分片5／完整编码快照与本次作业报告

日期：2026-10-26。状态：已实现/接线/本地验收，本片完整回归2220项通过；D3已由用户确认，实际增量接线见0049。

## 1. 已有合同与问题

EncodedRecord包含input、dense_vector、sparse、batch_index；EncodingResult强制records与同一EncodingReport的数量、整体指纹和批次范围一致。IndexBundle持有这个任务结果；Chroma/BM25及查询/管理读取它。IngestionReceipt和RemovalReceipt又要求本次报告paired_input_count等于新版本全部片段数。

将只编码B/D的新报告与A/C旧记录拼接，会违反上述实质校验；改报告计数或复用历史tokens会伪造本次执行。不能放宽EncodingResult来掩盖问题。

## 2. D3：推荐新增持久编码快照，保留原任务合同

推荐新增EncodingSnapshot及IndexBundleV2，保留原EncodingResult/EncodedRecord/IndexBundle及v1读写合同。BundleStore显式识别schema1/schema2，允许保存两类已验证资料包。BundleStore.load的新返回类型包含V2，这是公开数据合同扩展，需讨论确认，不默改原对象的report含义。

2026-10-26，向用户以110片段完整快照、50新编码/60复用的假设例子说明独立本次账务、完整数据自包含及新程序读新旧包/旧程序不能读新格式的兼容边界，用户明确回复“同意”，确认推荐方案。D1/D2/D3均已确认，按先前授权从0044开始逐片实施；不再询问是否开始，不包含发布/push/真实配置修改或数据删除授权。

替代是将现有IndexBundle.encoding_result扩成联合类型；代码改动可能较少，但既有消费者访问.report会遇到语义歧义。推荐明确新类型与版本，代价是更多接线文件，整体超过8文件，不加新服务或依赖。

## 3. 新类型与本次报告

EncodingSnapshot字段为knowledge_base_id、model_space_id、representation_id、tokenizer_id、dimensions、records、origins。records为StoredEncodedRecord列表，每项仅input、dense_vector、sparse，不携带“当前批次”伪义。严格复用既有EncodingInput/SparseRecord校验、唯一ID、单文档单源版本、维度/有限/非零向量及身份检查。

origins与记录ID一一对应，条目为{item_id,kind,source_bundle_id,source_job_id,source_batch_index}。kind为encoded/reused；encoded绑定本次真实EncodingResult的job/batch且source_bundle_id=null；reused记录本次取用的已审计基线bundle_id及其原始job/batch来源。来源hash/ID只作审计链，不是重新发起请求或真实模型正确性证明。

从v1提取时用原EncodingResult真实job/batch；从v2复用时保留最初job/batch，并把source_bundle_id记录为本次直接取用的已审计基线。新资料包包含全部当前input/向量/词项；读取不递归加载祖先包、不读取原材料、不发模型请求。来源参考保留但不作为运行依赖，不复制已移除文档的正文或编码记录。

创建快照时逐条与已审计基线/本次结果比对，再转换为独立副本；加载时以manifest文件hash及全量源/input/profile/配对核验验证快照，不声称能在祖先缺失时重新证明历史HTTP用量。

新增IngestionEncodingSummary字段total_chunk_count、encoded_chunk_count、reused_chunk_count、job_report。三数量为非负整数且后两者和等于总数；job_report仅本次实际EncodingReport，paired_input_count等于encoded_chunk_count。没有需要编码的片段时不调用BatchProcessor，job_report=null；本次模型调用确定0，通过summary说明，不伪造历史tokens为本次0。

回执保留encoding_report字段作为本次job_report，增加keyword-only encoding_summary；新快照激活但没有新编码时允许report=null。v1回执读取仍按旧精确字段与旧断言；新回执按新精确字段及summary断言。RemovalReceipt沿同一汇总合同，不复用旧作业费用。

## 4. 资料包与消费者接口

IndexBundleV2字段沿v1的knowledge_base_id/documents/chunks/relations/encoding_settings/ingestion_settings/preparation_diagnostics，将encoding_result替换为encoding_snapshot；严格from_dict/to_dict。新增prepare_index_bundle_v2，不更改原prepare_index_bundle参数签名或返回合同。

V2另持有encoding_summary并持久化本次实际报告，避免新格式丢失已有本次执行观察。encoded来源记录按本次输入顺序投影，必须与job_report的整体指纹、各batch指纹/范围及数量一致；reused不参与本次报告，空编码时job_report必须为null。首次全量V2的全部记录均encoded；读取后不把本次报告提升为全历史账单。

schema2仍使用现有documents/chunks/relations/encoding四文件及manifest的限额、hash与原子保存机制；encoding.json的精确字段为encoding_settings/ingestion_settings/encoding_snapshot/encoding_summary/preparation_diagnostics。manifest结构保持现有字段，schema_version=2；bundle_id仍由含schema的规范manifest身份生成，不能冒充v1。

共同只读视图bundle_encoding读取两类包的身份/records，由Chroma、BM25、查询、管理、激活审计三个以上消费者共用；返回视图不能提供虚假统一report。旧v1存储物化字节不变。索引/SQLite活动指针格式除非源码证明必须变化，否则不改。

BundleStore.save/load在本片完成V2实际往返，Chroma/BM25/DocumentManager/查询读取也必须消费V2；使用合成全新编码结果构造V2证明接线。生产IngestionPipeline在0049才改为生成V2，不把可保存类型当增量已经生效。

## 5. 影响与验证

新增core/encoding_snapshot.py、core/ingestion_encoding_summary.py、storage/artifact_bundle_v2.py、storage/bundle_encoding.py；扩展bundle_store、document_manager/views、chroma_index/backend/query、bm25_store/backend/query、file_integrity及query读取处的实际类型检查；core/ingestion_types.py及公开导出。实施前rg全量检查IndexBundle/encoding_result/encoding_report/batch_index的真实消费者，任何新增影响先同步本Spec。

新增tests/test_encoding_snapshot.py、tests/test_storage_bundle_v2.py；扩展test_ingestion_types.py和既有storage/query消费者测试。严禁替换旧v1夹具为v2后声称兼容。

红灯覆盖新旧记录合并、重复/缺失/跨库/源版本混用、坏hash/向量/tokenizer、origin错配、伪造本次报告计数、零编码有变化、空快照、超限、未知schema/字段、文件损坏。原生V2保存→新进程加载→两索引构建/审计→PreparedQuery/Reader消费，模型使用MockTransport。

计划命令：

```sh
.venv/bin/python -m pytest -q tests/test_encoding_snapshot.py tests/test_storage_bundle_v2.py tests/test_storage_bundle.py tests/test_storage_bundle_wiring.py tests/test_ingestion_types.py tests/test_query_preparation_wiring.py --tb=short
.venv/bin/python -m pytest -q tests --tb=short
.venv/bin/python -m compileall -q naiyue_rag experiments tests
.venv/bin/python -m pip check
git diff --check
```

L1新类型/视图存在；L2记录/来源/本次账务实质校验；L3V2完整存取和现有消费者实际使用。构建不适用，不做真实API请求。旧代码不能读取schema2；代码回退须保留schema2读取支持，不自动切换活动版本/删除数据。完成后讲解0049如何只编码变化文档并完整构建新索引。

## 实施前调用核对

V2完整快照校验需要逐项输入限额与本次作业总量限额分开，符合0049预算合同：encoding/input_preparer.py保留公开prepare_document_encoding_inputs签名及行为，增加私有完整快照输入验证分支，不对复用记录重算本次max_inputs/max_requests。V1资料包继续原严格路径；V2的本次encoded子集仍完整执行原批次预算核验。实际影响因此增加该编码输入模块及对应边界测试，无新配置/依赖或行为范围扩大。

## 2026-10-26实施记录

新建快照/汇总/V2资料包及读取入口；先21 failed in0.18s，最小实现21 passed in2.20s。加入回执旧形状兼容、本次零编码汇总与快照/本次预算分离后24 passed in2.45s；相关旧存储/移除/查询等187 passed in34.85s。真实本机双索引→管理→查询准备→Reader已在新进程消费V2，模型服务请求0。V1生成/读取合同保持，生产run尚未改成增量，下一片才启用。

Snapshot不持有伪造job_report；Summary用encoded来源投影重建原EncodingResult进行指纹/批次绑定校验，reused来源不纳入本次任务。V2完整输入验证保留单项字节限额，本次encoded集合继续原批次规划/请求限额，未修改公开输入准备签名。回执只有提供新summary才采用新计数合同，否则严格保留旧字段/校验。第5片完整回归2220 passed in435.89s（0:07:15），语法/依赖/diff检查退出0。
