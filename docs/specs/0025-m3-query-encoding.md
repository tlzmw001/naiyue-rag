# Spec0025：M3.4首片——正式查询成对编码

日期：2026-10-14。状态：按用户“先继续做”完成已确认M3路线的查询首片，已规范/离线TDD/接线。BatchProcessor课堂暂挂，不登记新增理解/独立实现证据。本片无新依赖/真实配置/真实模型/索引/M5检索或硬截止实现。

## 1. 当前调用链和参考

来源：https://github.com/Jerry-ai-dev/MODULAR-RAG-MCP-SERVER，本机main/f658c5a4011c8b826707a65a3b11ce9301b0626f，2026-10-14只读核验固定源码，不称远端最新/服务已验证。

参考QueryProcessor.process（query_processor.py:132–148）规范化/过滤/分词后返回ProcessedQuery(original_query原文,keywords,filters)。HybridSearch在串行分支（hybrid_search.py:407–418）把original_query交DenseRetriever，把keywords交SparseRetriever；DenseRetriever.retrieve（dense_retriever.py:142–169）直接Provider.embed([query])→vector_store.query，未经过摄取BatchProcessor。这与原Spec0020示意processed_query.query有出入：实际字段是original_query。本片保留查询独立职责，复用本项目严格编码；过滤/改写/召回归M5，不提前套参考默认停用词/关键词上限。

本项目prepare_query_encoding_input已保留原问题和query_sha，应用配置query_prefix生成独立embedding_text/hash。DenseEncoder单项返回ProviderBatchResult/七字段request_report；SparseEncoder已支持query输入并有query_terms。它们尚无统一查询结果/报告入口。Spec0024文档BatchProcessor只接document；不把查询塞入文档来源合同。

## 2. 本片最小路径

```text
调用方配置/初始化同一Dense、Sparse
→ QueryEncoder(settings, dense_encoder, sparse_encoder).encode(query:str)
  → 入口时间/job → prepare_query_encoding_input → 单项预检计划
  → DenseEncoder.encode_batch([input], remaining_seconds=实际剩余)
  → 验证并登记请求/usage
  → SparseEncoder.encode_batch([input])一次
  → 核唯一ID、分别核embedding/retrieval hash、kind、模型/维度/tokenizer
  → 从Sparse.tokens稳定去重query_terms → QueryEncodingResult/EncodingReport
失败 → EncodingJobError(code,report)，不交付单路向量或词项
```

使用Sparse单项统计派生query_terms，避免调用query_terms后再encode_batch重复分词。正常空terms合法；不能由此判业务无答案。输入示例“开关 关 开关 TC-01 cvr_ltv 0.5”：Dense送显式query前缀+原问题，Sparse看原问题；词项稳定去重为[开关,tc-01,cvr_ltv,0.5]，词频仍保留开关2。

## 3. 接口与边界

新增QueryEncoder与QueryEncodingResult，不改已存在的公开签名/文档批次策略/查询准备。encode接原字符串；M5以后可从QueryRequest.query调用，知识库scope/exclude不属于M3编码。空白、非法类型、坏UTF8、单项字节/请求规划限额在首次Dense前失败；query参数有一个提交槽，预检失败report.input_count=1、fingerprint/planned_batch_count按实际完成阶段为空，不把未准备问题存进report。

QueryEncoder构造核Dense.settings/Sparse.encoding_settings与settings一致，固定tokenizer身份；仍由调用方拥有初始化/关闭。不重试、不并行、不降单路、不回旧Snapshot。每阶段前后检查同一个deadline；协作截止只覆盖encode，不保证打断同步阻塞。

QueryEncodingResult字段：input:EncodingInput、dense_vector:list、sparse:SparseRecord、query_terms:list、tokenizer_id:str、dimensions:int、report:EncodingReport。

- input只能query，源文档/知识库/span均null；item_id=query-+原始query_sha256。
- model_space_id/representation_id从input取得，不重复另一套身份；与文档同配置保持一致。
- 单向量有限/nonbool/非零、长度=dimensions正整数。
- Sparse的ID/kind/retrieval hash与input对应，tokenizer_id相同；query_terms严格等于tokens第一次出现顺序的去重结果，禁止任意截断/补词。
- report只能success，input/planned/completed/paired均1、一个complete批且范围[0,1)，整体与批fingerprint匹配input；未知usage允许成功。
- 严格from_dict/to_dict、未知字段拒绝、深拷贝、消费时重校验、repr不含问题/词项/向量。结果是检索参数，报告无正文；结果不代表回答/证据已找到。

复用EncodingReport、BatchReport及EncodingJobError。报告负责合法单项执行事实，文档和查询共享此观察结构，任务编排分别由各自入口负责；不共享整条流程或加入泛型任务框架。只新增固定错误码invalid_query_encoding_result，其他失败复用既有闭集码。

## 4. 正常与失败

| 分支 | 行为 |
|---|---|
| 正常/数字标识符/重复词 | 一次Dense、一次Sparse；完整查询向量+词频+稳定terms和报告 |
| 原问题含首尾/多重空白 | 原文/hash保持，M3不strip/改写；前缀只进Dense |
| 合法无词项 | 向量与空Sparse/terms完整返回，M5决定召回动作 |
| 整体预检失败 | 0 Dense/Sparse调用，无模型请求 |
| Dense HTTP/超时/坏响应/非法观察 | 安全错误报告；可靠请求/状态保留，未知usage不补0，不执行Sparse |
| Sparse或配对失败 | 保留Dense已知请求/usage，整次报错，不返回部分结果 |
| 最终DTO或截止失败 | 保留已发生观察、无完整结果；BaseException原样传播 |

Dense报告先校验次数，正常必须恰好1且无执行错误；预算越界保留合法次数事实但用量未知，立即失败。returned_model核配置别名后才能入report。未知异常只固定码；不记录原异常/Key/问题/词项。来源service只协议标记，本片真实SDK仍用MockTransport。

## 5. 影响和验收

新增core/query_encoding_types.py、encoding/query_encoder.py及tests/test_query_encoding.py、tests/test_query_encoding_wiring.py。修改core/encoding_report.py有限错误码、两个公共导出；不修改BatchProcessor或它的合同/原测试。共7源码/测试文件，每源码≤500行；如发现实质设计分歧先更新Spec。

有意义TDD：先模块缺失红灯；覆盖正常/同配置文档-query身份/原文保留/数字标识符/空terms、预检0请求、Dense/Sparse/配对/最终故障、已知/未知usage/非法request report/真实SDK HTTP错误、剩余时间及阶段后超期、JSON复制/消费篡改，已有tests全量回归。

真实接线：独立两个合成YAML→正式QueryEncoder→真实SDK MockTransport+真jieba→QueryEncodingResult→JSON，socket禁连接；同一调用方Provider可同时用于文档批次和新问题，并由调用方关闭。没有向量库查询，不报告召回率/答案正确/费用。编译语法检查与应用构建不适用分开；pip freeze/旧资产hash保持。验证入口固定pytest tests目录，避免收集第三方研究源码。

回退边界：停用新增入口，原文/实验/索引不改，不做删除或存储回滚。真实服务/硬截止在后续明确凭证、目标、请求数与截止后单独验收；旧临时Key和取消实验预算不迁移为本轮授权。

## 6. 实施与验证证据

新增2个实质源码/2个测试文件；仅修改原encoding_report的有限错误码集合及两个公共导出。符合7个源码/测试文件范围；新源码77/60行。原103份源码/测试/依赖快照仅上述3文件变化，旧测试、BatchProcessor及依赖文件保持，pip freeze前后一致。没有修改真实.env/运行配置/第三方仓库、提交或push。

预期红灯为正式包不能导入QueryEncoder；最小实现后54项合同/编排测试转绿，再真实SDK MockTransport+真jieba接线，合计66项。未放宽断言/skip或改测试基础设施。

```sh
.venv/bin/python -m pytest -q tests/test_query_encoding.py tests/test_query_encoding_wiring.py --tb=short
# 66 passed in 5.61s
.venv/bin/python -m pytest -q tests --tb=short
# 1167 passed in 80.88s (0:01:20)
.venv/bin/python data/research/spec0025-evidence/wiring_probe.py
# documents=12, document_pairs=72, document_mock_requests=36
# query_results=1, query_mock_requests=1, total_mock_http_requests=37
# shared_model_space/shared_representation/shared_tokenizer=true
# query_raw_text_preserved=true, query_source_span=null
# query_token_occurrences=5, query_unique_terms=4
# query_mock_usage_status=complete, query_mock_total_tokens=7
# query_json_roundtrip=true, caller_closed_client=true
# network_attempts=0, real_model_requests=0, index_writes=0
.venv/bin/python -m compileall -q naiyue_rag experiments tests
# exit 0；仅语法检查，应用构建未设立/不适用
.venv/bin/python -m pip check
# No broken requirements found.
git diff --check
# exit 0
```

L1：QueryEncoder/QueryEncodingResult与测试存在并公共导出。L2：实质输入预检/配置身份/单Dense和Sparse/配对/稳定去重/截止/安全错误与严格JSON合同。L3：独立合成两YAML→M1/M2/正式文档Batch→同Provider/Dense/Sparse的QueryEncoder→单项查询结果/JSON实际调用；同一客户端由外层关闭。M5未消费该新结果，不宣称新问题已检索、回答或Agent接通。

合成HTTP返回7 tokens仅验证usage字段，不是账单或推算。Probe明确source_kind=service只是协议入口、外部模型请求0；检索质量not_evaluated。模型空间/表示/词典身份一致是后续同索引查询的必要条件，不自动证明Embedding相关性、召回、业务质量或相同revision真实已知。同步协作截止、仅内存报告/外层生命周期的边界保持。

## 7. 后续代码学习入口（尚未课堂走读）

用户本轮先开发，Lesson8课堂暂挂，不新建完成课堂或本人理解记录。后续Test Explorer可Debug Test：

- tests/test_query_encoding.py::test_query_retains_raw_input_pair_and_stable_terms：两路是确定性替身，原问题→前缀→角色hash→向量/TF/去重/报告。
- tests/test_query_encoding.py::test_failure_keeps_request_and_usage_with_no_query_result[sparse]：Sparse.hook故障注入OSError，QueryEncoder.encode末尾except接住并抛EncodingJobError；原问题不入日志/报告，已知usage7保留。pytest捕获预期异常时测试通过。
- tests/test_query_encoding_wiring.py::test_yaml_sdk_sparse_result_shares_document_identities_and_client：真Loader/M2/SDK/jieba，仅HTTPTransport及Dense/Provider时钟被已有factory替换，不是真模型。

入口断点QueryEncoder.encode:40，Dense返回赋值后:55、Sparse调用:63、_pair:30、except生成report后停:76。QueryEncoder栈帧投影item.kind/item.query_sha256、dense.input_ids、request['attempted_requests']、row.doc_length、terms、report['usage']；变量只在赋值后观察，不要重跑有副作用函数。字段/分支地图和真实测试已准备，不登记本人走读/独立实现或面试能力。

唯一下一步：制定M3真实服务验收/硬截止的具体Spec，明确合成材料、实际模型/目标、凭证注入、请求数和截止；未确认这些边界前不调用外部服务。生产M4/M5仍按模块路线后续推进。
