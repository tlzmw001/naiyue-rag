# Spec0021：M3.1独立配置、编码输入和响应校验

日期：2026-10-13。状态：承接已确认Spec0020/ADR0005，已按规范/TDD实施接线：56新增、全量897通过。本片只完成准备/规范化合同，未执行Provider、Sparse或网络。

## 范围与链路

独立编码YAML→EncodingSettings→M2原始Document/Chunk→源及view核验→EncodingInput→批次计划→模拟OpenAI格式响应规范化。本片无SDK/Provider/Embedding请求、SparseEncoder/评分、数据库或Agent；响应输入明确simulated，不能把响应校验通过当模型接线。

编码配置三组全字段显式：embedding(provider=openai_compatible、base_url、model、expected_dimensions、request_dimensions可null、model_revision可null、allowed_response_models)；representation(document_text_mode、text_layout、document_prefix、query_prefix)；runtime(batch_size、max_inputs、max_input_utf8_bytes、max_batch_input_utf8_bytes、max_requests、timeout_seconds、deadline_seconds、max_response_bytes)。未知字段/Key明文拒绝。整数排除bool，时限有限正值；request_dimensions提供时须等于期望维度。URL仅明确http/https base_url，拒绝userinfo/query/fragment/控制字符。模型身份独立于时限/批大小；文本表示和最终输入hash分别记录。

复用并提取现有严格YAML读取规则到core/yaml_config.py，现有实验load_settings调用公共读取函数，不创建兼容包装。读取显式文件、64KiB上限、UTF8、重复键/alias/merge拒绝；不加载.env/网络或创建目录。

正式顶层包移除Snapshot/Bootstrap/旧retrieval/tracing导出（用户已取消实验API兼容）；原文件留作当前对照，不删除目录。6个旧测试消费者改为直接导入真实原模块或测试fixture组合，断言/故障注入不变，不放宽或skip。core包取消旧Settings导出。M2 Chunker改为直接接受独立IngestionSettings，不再validate整个快照配置；复用两字段和原切分逻辑，配置相关测试只迁移真实传参边界。正式M2→M3可不带dataset/corpus_run/vector_run。

## 接口与数据

- load_encoding_settings(path)/EncodingSettings.from_dict/to_dict：新正式入口，SettingsError固定code；安全repr、冻结组/响应模型tuple，序列化独立复制。
- EncodingInput：item_id、kind、knowledge_base_id/source_document_id/source_sha256/source_span（查询均null）、retrieval_text、embedding_text、两份text hash、model_space_id、representation_id、query_sha256（仅query）。固定字段JSON往返；SourceSpan仍是原始证据，不是拼接文本的位置。
- prepare_document_encoding_inputs(documents,chunks,settings)：Document登记表唯一同库、M2源/context/列字段核验、用Refiner重推view与给定字段精确比较；按view_only或contexts_then_view及前缀构造输入。空chunks合法，未知来源/重复Chunk/不完整view明确失败，输入不变。
- prepare_query_encoding_input(query:str,settings)：编码层只需要问题字符串，不要求scope/k或旧QueryRequest快照参数。保留原query/hash，Dense前缀另hash；非空UTF8资源边界显式。上层M5负责请求/过滤。
- plan_encoding_batches(inputs,settings)：唯一稳定按数量和文本UTF8字节分批计划，整批预检、max_inputs/max_requests及单项两限额；任何超限不截断且0模型请求。本片交付计划供M3.3实际执行，不建空BatchProcessor。
- normalize_embedding_response(payload,inputs,settings,source_kind)：原始dict为模拟或未来service；显式source_kind必填。恢复index顺序、绑定item_id/input hash、核model允许列表、数量/维度/有限非bool/非零范数。ProviderBatchResult记录vectors、输入ID/hash、模型身份、returned_model、usage及usage_status/source_kind；序列化无原响应扩展内容。无/非法usage保留未知并给明确状态/安全warning，不伪造0，不丢有效向量。

EncodingInput跨settings或前缀/身份不一致拒绝；每次消费重新核hash，防可变对象绕过。原文/view/layout分别保存，metadata不当指令。文本数组字节预算是本机资源界限，不冒称精确token或完整HTTP body字节数。响应dict序列化界限不等于已经实现网络有界读，后者M3.2负责。

## 文件与验收

拟core/encoding_settings.py、core/encoding_types.py、core/yaml_config.py、core/ingestion_settings.py；encoding/input_preparer.py、encoding/validation.py、encoding/__init__.py；改core/settings.py/错误/导出、DocumentChunker及实际测试调用。核心文件≤500；无新依赖/真实配置/缓存或其他仓库修改。

新失败测试覆盖独立YAML/危险语法/字段边界、ID/模型与表示指纹、原文/context/view篡改、空文档、两布局/前缀、中文UTF8/超长完整用例、稳定分批、序列化隔离、反序index/异常向量/model/usage、安全异常。Loader→独立IngestionSettings→M2真实准备→新配置/输入/计划/模拟响应真实接线；子进程import检查正式入口未加载experiments或旧Snapshot；旧测试迁移仍跑原真实实现。

命令：目标pytest→全量pytest、compileall、pip check、git diff --check及未触碰资产hash。新组件不存在为预期红灯，旧测试入口迁移是结构变更，不当TDD红灯。无应用构建、真实模型或检索质量验收。完整异常代码/调用方/消费点按实际实现核验后补结果。

## 分词讨论接续与下一步

“开关”在现有分词器中是整词；此前示例“开 关”不同。中文最小词长可配置，2作为候选，数字/ASCII单字不能直接套全局len>=2；具体词项规则和对照留M3.3，不本片实现或宣称最佳。双路仍Embedding+BM25S+RRF，正式Chroma归M4。

本片完成后唯一下一步：M3.2首个Provider/DenseEncoder的SDK版本与增量依赖准备。所有实现、接线、测试和学习掌握状态分别登记。

## 实际实施与证据

先写三个新测试文件，确认缺encoding_settings/EncodingInput/EncodingError导致3 collect errors；最小实现51通过，全量892通过。随后按既有规范补5个明确边界红灯：空query/fragment URL标记、时限超大整数、来源越界路径、结果序列化再校验。修源后56/全量897通过；既有断言未改、不skip。

```sh
.venv/bin/python -m pytest -q tests/test_encoding_settings.py tests/test_encoding_inputs.py tests/test_encoding_validation.py --tb=short
# 56 passed in 0.26s
.venv/bin/python -m pytest -q tests --tb=short
# 897 passed in 58.07s
.venv/bin/python -m compileall -q naiyue_rag experiments tests
# exit 0，无输出；应用构建未设立，这只是语法检查
.venv/bin/python -m pip check
# No broken requirements found.
git diff --check
# exit 0
.venv/bin/python data/research/spec0021-evidence/probe.py
# 12文档/72原始Chunk/12完整用例→72EncodingInput→36批→72模拟向量；另1查询输入
# model_requests=0，unknown_usage_batches=36，retrieval_quality=not_evaluated
```

probe实际读取无快照字段的synthetic-encoding.yaml，M2使用独立IngestionSettings，调用真实准备/分批/规范化函数；原始响应刻意反序index，返回ID/vector与输入逐项对应，全部source_kind=simulated。没有Provider调用，不能把36批视作36真实请求。当前最大输入1507 UTF8字节仅属于此样本/配置，不是通用上限或最佳参数。timeout/deadline只加载/校验，实际执行截止和网络有界读取在M3.2接线；Sparse词项未生成。

L1存在：新增yaml_config/ingestion_settings/encoding_settings/encoding_types及encoding两个功能模块/导出；L2实质：配置schema、原文与view重核、两布局/前缀/hash、数量/字节分批、响应index/向量/model/usage、序列化均真实实现；L3：独立YAML→M2→输入→计划→模拟响应真实消费，子进程import证明正式入口未加载experiments或旧Snapshot。

101既有资产hash与135包版本保持；12个既有源码/测试按范围修改，无其他仓库/真实配置/旧向量/依赖/模型/提交/push变化。data/research/spec0021-evidence/validation.json记录清单。现有7个测试文件只迁移import、两个旧API fixture及Chunker实际参数，AST比对所有已有assert相同；理由是已确认取消实验公开入口和改独立摄取参数，不放宽业务/异常断言、不引入产品兼容包装。test-migration.json保留比对。旧文件仍可直接导入测试，新公开包不再导出其入口。

测试学习入口：test_real_m2_to_encoding_preserves_source_and_layout（四模式组合）观察完整来源/view/layout链；test_response_restores_index_and_binds_ids_hashes观察输入ID/hash与反序恢复；test_unknown_usage_preserves_vector_and_explicit_status观察usage=null及unknown状态；test_formal_package_import_does_not_load_experiments_or_snapshot是独立进程导入检查。VS Code选Debug Test，入口断点prepare_document_encoding_inputs及normalize_embedding_response；从测试帧看source/chunks/cfg，函数返回后inputs/result才产生，WATCH仅投影embedding_text[:80]、source_span、input_ids、usage_status。不重跑函数取返回值。

学习状态：范围和主链已说明，本人源代码走读/独立调试/实现未评估，未预填课堂完成记录。唯一下一步仍是M3.2 SDK版本/增量依赖与Provider执行机制准备。
