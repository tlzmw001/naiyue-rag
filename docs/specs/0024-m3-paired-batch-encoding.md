# Spec0024：BatchProcessor成对编码、整次失败与用量报告

日期：2026-10-13。状态：已按用户继续指令完成离线TDD、成对编码与报告接线；不改现有编码器签名/依赖/真实运行配置，不请求真实模型。沿Spec0020–0023已确认路线：单一分批、按批Dense→Sparse、必要失败整次报错。

## 1. 为什么需要这条调用链

调用链记录一次任务中谁调用谁，数据怎么转换，结果返回给谁，异常在哪里捕获。例如5个片段每批2个，处理顺序为两项、两项、一项；每批都需要得到同一组片段的向量和词频。代码有两个编码器并不能证明它们处理的是同一输入，也不能证明失败后不会返回混合数据，须核实际调用顺序和消费点。

这里是摄取后、建索引前的编码主链。文档/片段准备在M1/M2，存储/激活在M4；一次知识查询与Agent决定重检索分别在M5/M7。本片范围不扩到这些阶段。

## 2. 固定参考的真实接线

参考：https://github.com/Jerry-ai-dev/MODULAR-RAG-MCP-SERVER；本机main/f658c5a4011c8b826707a65a3b11ce9301b0626f，2026-10-13核验。相关文件为src/ingestion/pipeline.py、embedding/batch_processor.py/dense_encoder.py/sparse_encoder.py、storage/vector_upserter.py及BM25Indexer调用点。只读源码，不运行其setup/完整应用/真实服务。

```text
装配：IngestionPipeline.__init__
  EmbeddingFactory.create(settings)
  → DenseEncoder(embedding, batch_size=settings.ingestion.batch_size)
  → SparseEncoder()
  → BatchProcessor(dense_encoder, sparse_encoder, batch_size)

执行：IngestionPipeline.run
  已准备chunks
  → BatchProcessor.process(chunks, trace)
      → _create_batches（按数量切）
      → 对每批 DenseEncoder.encode
          → chunk.text数组 → 内部按batch_size切 → embedding.embed
          → 检查向量数
      → 立即extend到dense_vectors
      → SparseEncoder.encode → jieba/Counter
      → extend到sparse_stats，成功计数增加
      → 异常时失败计数增加，继续后续批
  → BatchResult(dense_vectors, sparse_stats, counts)
  → VectorUpserter.upsert(chunks, dense_vectors)
  → zip(sparse_stats, vector_ids)改chunk_id
  → BM25Indexer.add_documents(sparse_stats)
```

定位：pipeline.py:167–179装配，385执行，388–389读结果，438写向量，443–444按位置改稀疏ID，448–452写关键词；batch_processor.py:150–170串行/聚合/捕获继续，202–209返回，211起分批；dense_encoder.py:115–133内层分批；vector_upserter.py:100–104检查chunk/vector数量。

源码注释称Parallel Encodings，但上述实际process是串行。参考返回两条平行列表，BatchResult没有本片拟建的成对ID/hash合同或usage汇总。不能据缺口断言参考整体不存在其他追踪，更不能拿自述原子性当这条存储链的事务事实。

### 本机局部探针

抽取原BatchProcessor/BatchResult两类，Dense/Sparse替身处理C1–C5，每批2个；网络禁止，模型/存储不运行。正常向量5/词频5；第二批Sparse失败时，Dense总列表仍含C1–C5，Sparse只含C1/C2/C5，第三批继续，成功计数3/失败2。

按位置zip的教学示意会把C5词频配给第三个向量ID（C3）。这是代码行为产生的潜在错配路径；探针未运行真实VectorUpserter/Chroma/BM25，不报告真实数据损坏或线上缺陷。data/research/spec0024-evidence/reference-batch-results.json保留调用顺序、commit及源码SHA。

## 3. 设计时本项目已有边界（实现前）

- plan_encoding_batches：整体输入/hash/表示重校验，按数量+Embedding文本UTF8字节计划，检查max_inputs/max_requests；空列表返回[]，不发模型请求。
- DenseEncoder.encode_batch(inputs, remaining_seconds=...)：恰好一批；Provider一次有界SDK请求；返回ProviderBatchResult及七字段安全request_report。result有input_ids/input_hashes/model_space_id/vectors/returned_model/source_kind/usage/status。
- SparseEncoder.encode_batch(inputs)：恰好一批，真实jieba统计；返回每项SparseRecord，包括item_id、kind、retrieval_text_sha256、tokens/TF/两长度/tokenizer_id。query_terms另走单项查询；空词项记录合法。
- EmbeddingExecutionError有code/report；普通EncodingError只有code。Dense规范化失败时没有可取得的有效ProviderBatchResult.usage，此时用量未知，不能猜为0。
- 当前两个演示脚本外层for不是正式BatchProcessor；尚无完整编码任务结果、成对记录或任务报告。Spec0023历史全量1004不当本片已验证。

## 4. 推荐完整路径与接口

```text
已初始化Dense + Sparse + 同一EncodingSettings
→ BatchProcessor(settings, dense_encoder, sparse_encoder)
→ process(document EncodingInput列表)
  → 建job_id/单调起点 → 克隆并整体预检 → 唯一批次计划
  → 每批：剩余预算/时限检查 → Dense → 登记请求与usage
         → Sparse → 按ID/hash核对 → 暂存成对记录
  → 全部完成/最终重校验 → EncodingResult(records, report)
  → 任一步失败：停止 → EncodingJobError(code, report)，无records
```

首期同步顺序执行，不加入并行/重试/断点恢复/索引写入。构造时核settings与Dense.settings/Sparse.encoding_settings一致，固定同一tokenizer_id；不创建/关闭调用方持有的编码器和Provider。报告覆盖process内部，外层初始化/客户端关闭保留各自现有异常渠道，不宣称覆盖整个摄取服务生命周期。

process只接受文档输入；查询走现有单项Dense/Sparse，完整QueryEncodingResult归M3.4。整体预检用EncodingInput.from_dict/to_dict创建独立副本，然后调用已有计划；拒绝重复item_id、query/mixed kind、混知识库、同一source_document_id出现多个source_sha256、跨模型/表示、篡改/超限。源文件实际回读已由M1/M2准备层完成，本片不从hash推断自己读过原文件。

同批接收的数据先重新调用已有to_dict校验，再按ID建映射：两路ID集合须等于计划输入集合且无重复；Dense的每个input_hash对该项embedding_text_sha256，Sparse的hash对retrieval_text_sha256；kind、model_space_id、tokenizer_id均匹配。输出始终按原输入顺序。允许合法响应列表重新排序，不允许靠位置盲配或改ID；TF空记录可配对，缺一条记录则失败。

### 已实现数据合同

| 类型 | 字段及边界 |
|---|---|
| EncodedRecord | input:独立EncodingInput、dense_vector:list、sparse:独立SparseRecord、batch_index:int。input带原文来源/span/两文本和hash，Sparse再次核ID/hash；向量有限/非bool/非零范数。无重复的第二套输入ID或源路径推断 |
| EncodingResult | knowledge_base_id（空任务null）、model_space_id、representation_id、tokenizer_id、dimensions、records、report。记录唯一、全部document、同库/版本/身份，向量维度一致；report只能success/empty，记录数等于输入数 |
| EncodingReport | job_id、status、input_count、input_fingerprint、planned_batch_count、completed_batch_count、paired_input_count、elapsed_seconds、requests、usage、batches、error。只白名单数字/固定枚举/hash，不包含正文/词项/向量/原文档ID/URL/Key/原异常 |
| EncodingJobError | 新EncodingError子类；固定code及独立report，不附部分records、底层异常或异常链到报告，不改现有异常签名 |

三个结果/报告数据类提供严格from_dict/to_dict、未知字段拒绝、复制和消费时重校验；Error.report是报告的安全dict副本，保持现有错误观察方式。字段按实际调用/序列化/测试同步，本片无DB映射；M4必须消费同一记录合同，不能用测试通过推定它已接线。

input_fingerprint为有序输入ID、kind、知识库/源文档ID、源版本/span、两文本hash及模型/表示身份的规范摘要，不在报告保留原列表。batch_index用于将记录关联到批次观察，来源数据留在结果input中，日志只报固定stage/code和数量/hash。

失败前可能还未完成预检：input_count仅在输入是list时可知，input_fingerprint/planned_batch_count在各自校验完成前为null，不能写假hash/假批次；completed_batch_count/paired_input_count初始0是实际尚未执行。error=null或固定结构{stage,code,batch_index}，batch_index在未进入批次时null。批次stage终态只取dense/sparse/pairing/complete，顶层另允许preflight/finalize，status只success/empty/failed。

## 5. 整次失败、请求预算与截止

| 场景 | 输出与动作 |
|---|---|
| 空输入 | EncodingResult(records=[], knowledge_base_id=null, status=empty)，批0/请求0，不调用编码器；usage为无请求状态 |
| 整体预检失败 | EncodingJobError，stage=preflight，Dense调用/请求0；不先处理前几项再发现后面坏数据 |
| 一批全部正常 | 先登记Dense合法观察，再Sparse和配对；只有配对通过才增加completed_batch_count/paired_input_count |
| Dense失败 | 保存其合法request_report（如有），停止；不调用该批Sparse或任何后批 |
| Dense成功、Sparse失败 | 保留该批请求及有效usage，停止；不返回该批向量或此前成对数据 |
| 配对/最终序列化检查失败 | 保留已有合法用量/请求观察，停止，无部分结果 |
| 合法空词项 | 记录tokens=[]/TF={}，仍算成对成功；不视作异常或自动判无答案 |
| 未知Exception/非法返回结构 | 固定安全错误，不能复制str(exception)；缺少可靠调用观察则显式未知，不捏造请求0 |
| KeyboardInterrupt/SystemExit | 原样传播，不包装成功/普通失败；本切片不保证该路径完整用量报告，也不声明已取消远端计算 |

completed_batch_count/paired_input_count在失败报告里只是已在内存验证的计数，不是已返回/已保存/已激活数量。“整次失败”不意味着撤回已经执行的远端Embedding或退款。

max_inputs、单项/批次字节、batch_size、max_requests复用现有配置。计划先检查总批数；每次调用Dense前为其最多一个请求检查剩余预算。当前Provider无重试，成功每批至多一次请求；实际报告若越预算，立即失败且不再调用，不能宣称已经撤回额外请求。

deadline_seconds只覆盖process，从入口单调时间计时，包含复制/预检/Dense/Sparse/配对/最终检查；资源构造和M1/M2不在该时间窗。每阶段前后检查，给Dense传真实剩余时间，禁止每批重新获得完整deadline。Sparse阻塞和同步网络不能被本方法硬中断；硬截止监督另在M3.4，此处只承诺协作截止。

## 6. 请求与用量报告合同

每批batches保存index、input_start/end（左闭右开）、input_count、input_fingerprint、stage终态、elapsed_seconds、已验证request_report或null、returned_model/source_kind或null、合法usage或null、usage_status、固定error_code或null。接收正常Dense结果后先核并记合法usage，再执行Sparse/配对，因此这些失败不丢已知用量。原七字段request_report不扩签名，所有码经闭集白名单映射；未知异常/码归encoding_stage_failed等固定码。

requests字段：dense_calls_started、attempted_requests（完整可知时为整数，否则null）、attempted_requests_known_sum、observation_unknown_dense_calls、http_responses_observed。有效request_report记录实际次数和HTTP终态；没有headers的网络失败不编HTTP200。缺失/非法report只记已知小计和未知调用数，停止；不能把Dense函数调用次数直接等同HTTP次数。

usage字段：known_usage_requests、known_prompt_tokens_sum、known_total_tokens_sum、unknown_usage_requests（次数可靠时为整数，否则null）、observation_unknown_dense_calls、status、total_prompt_tokens、total_tokens。无已知usage时known小计null；仅当全部已发请求的usage可知才填总量。status=complete/partial/unknown/no_requests，失败任务也可以对已发请求有complete用量。

| 教学示意（非真实服务） | 报告含义 |
|---|---|
| 两批分别返回7和5 tokens，第二批Sparse失败 | 编码status=failed；已发请求2，known小计/总量12；用量complete只针对已发两次，不估算未发第三批 |
| 第一批7、第二批响应缺usage | 已知小计7，unknown_usage_requests=1，总量null、status=partial |
| 有一Dense调用却无可靠request_report | dense_calls_started增加，attempted_requests=null、已知次数小计保留；用量计数的未知另标，不能补0 |
| 空任务 | 请求0、usage status=no_requests，小计/总量null，无模型账单推断 |

usage按请求/批统计，不按字符平摊到片段。无价格/真实账单数据时不增加费用数字，不额外复制配置base_url/requested_model；returned_model只接受配置允许的已验证响应别名，不能收任意供应商文本。source_kind=service只是现有协议入口标记，验证报告必须另说明MockTransport，不能据字段认定真实模型/费用。Dense在无有效result的失败中未提供usage，按当前合同记未知，本片不读被丢弃的供应商正文恢复费用。

报告正常随结果返回，失败随EncodingJobError返回；只在内存，不自动写日志文件/数据库。M0可选追踪持久化到实际消费者切片再接，写观察失败的既定策略继续保留，不新增ContextVar/回调/通用事件系统。

## 7. 文件、测试与回退边界

预计11个源码/测试文件：新增core/encoded_types.py、core/encoding_report.py、encoding/batch_processor.py、encoding/batch_report.py；改core/errors.py、encoding/__init__.py、包__init__.py；新增test_encoded_types.py、test_encoding_report.py、test_batch_processor.py、test_batch_wiring.py。4组件交换数据，职责/无环调用图见第4节；报告Builder只被处理器在成功/失败/终态三个以上真实位置复用，数据类负责序列化，不建插件框架。若接近500行按职责拆分并先更新Spec。

无新依赖/服务/运行配置/Key或外部调用；真实测试用现有SDK+MockTransport、真实jieba。失败注入在真实组件边界，不为产品建立模拟Provider。借鉴参考模块职责、用已实现核心机制，不复制参考源码到产品。

验收：

1. 正常5项/批2→3批/5成对记录；数字/vector/词项与源ID/hash对应，逆序返回按ID恢复，不按位置换源。
2. 全部预检红灯，包括末项坏hash、混库、重复ID、同Doc双版本、query混入、输入/请求超限；任何一项坏都0模型请求。
3. 第二批Dense/Sparse/配对故障，停止第三批、无部分返回；Sparse故障保留第二批已知usage，原文/Key哨兵不入日志/报告。
4. known/missing/invalid usage、无可靠request_report、HTTP无终态、未知Exception、资源关闭外层边界；未知值不补0。
5. 空任务、合法空词项、预算耗尽、阶段后超期、最终合同篡改；固定时钟/事件，不依赖sleep极紧窗口。
6. 传入源对象在模拟请求时被调用方修改，任务仍消费自己的预检副本；结果/报告JSON往返/独立复制/字段联动。
7. 独立YAML→真实M1/M2→72输入→本片处理器→SDK/模拟HTTP与真Sparse→72成对记录及报告；禁止socket网络，模型0。M4存储/业务质量不在本片。

先写失败测试确认缺组件/指定行为的红灯，再最小实现；验证目标pytest、全量pytest、compileall、pip check、diff检查、旧资产/包版本保持。构建未设立，语法检查单列。不自动写索引、恢复中途批次、更新真实配置/旧缓存或删除任何资产；回退是停用新入口，无存储回滚。代码未完成/未接线时如实记录。

## 8. 设计轮证据与当时下一步（历史）

```sh
.venv/bin/python data/research/spec0024-evidence/reference_batch_probe.py
# success_dense=5、success_sparse=5
# failure_dense=5、failure_sparse=3、failure_sparse_ids=[C1,C2,C5]
# third_batch_executed=true、model_requests=0、real_storage=not_run
```

上述探针执行固定参考真实Batch类，编码器是合成替身；不能作为我们的成对编码/失败策略/报告功能测试。L1：本Spec/参考探针存在；L2：源码顺序与部分数据风险已核；L3：本项目BatchProcessor尚未接线。上一轮1004是历史证据，本轮全量未重跑，不改产品源码/依赖/真实配置/索引/其他仓库或发布。

本轮复用课堂已有两入口实际验证：

```sh
.venv/bin/python -m pytest -q 'tests/test_dense_encoder.py::test_actual_dense_path_preserves_source_and_reorders_indices[document]' 'tests/test_sparse_wiring.py::test_m1_m2_to_real_sparse_binds_ids_hashes_and_preserves_originals[raw]' --tb=short
# 2 passed in 1.19s
git diff --check
# exit 0
```

它们分别证明现有单批Dense及真实Sparse可走读，不证明总Processor；未新增产品测试或产生本片TDD红/绿灯。构建不适用，本轮设计/课堂没有产品源码修改。

课堂“调用链是什么/为什么追”见Lesson8，只登记已说明/已讲解；用户自述理解、本人复述/调试/独立实现与追问能力未评估。唯一下一步：审阅本Spec新增结果/报告合同后，按规范实现BatchProcessor离线TDD；已确认单一分批、Dense→Sparse和整次失败不重新选择。

## 9. 实施澄清

预检指纹同时覆盖知识库/源文档ID及span，防止编码器在预检后重分配来源；仍只输出摘要。成功批必须观测到恰好一次且无执行错误的请求；failed/preflight不能含已执行批，failed/finalize仅允许所有已进入批完成，计划已形成时必须已有合法整体指纹。异常请求次数的事实可保留，但不能给不一致的请求附会完整usage。

HTTP错误码白名单显式包含有限集合embedding_http_100至embedding_http_599，匹配现有Provider的实际错误输出；仍拒绝任意供应商文本/任意后缀。HTTP失败保留已观察次数/状态，用量未知，不将这些合法错误报告当作缺失观察。

## 10. 实施与实际验证（2026-10-13）

新增4个实质源码/4个测试文件、修改errors及两个公共导出，按第7节11文件范围完成。单源码最长184行；旧95份源码/测试/依赖文件快照仅errors/导出3处变化，所有原测试与依赖文件hash保持，pip freeze前后一致。没有新增依赖/真实配置/其他仓库修改/提交或push。

红灯：初次test_batch_processor因正式模块不存在出现ModuleNotFoundError。随后新增合同回归分别证实异常请求次数导致报告二次异常、来源被编码器重分配未拒绝、终态不一致未拒绝及合法HTTP错误码被当坏观察；保持断言，修正生产校验/登记顺序/来源指纹与有限错误码集合后转绿。中途新接线测试误引不存在的sparse_data，仅修正为既有sparse_config.to_dict，未改变断言或旧测试基础设施。

```sh
.venv/bin/python -m pytest -q tests/test_batch_processor.py tests/test_encoded_types.py tests/test_encoding_report.py tests/test_batch_wiring.py --tb=short
# 97 passed in 4.26s
.venv/bin/python -m pytest -q tests --tb=short
# 1101 passed in 74.91s (0:01:14)
.venv/bin/python data/research/spec0024-evidence/wiring_probe.py
# documents=12, chunks=72, complete_cases=12, paired_records=72, batches=36
# mock_http_requests=36, reported_attempted_requests=36
# mock_usage_status=complete, mock_total_tokens=72, json_roundtrip_records=72
# provider_closed=true, network_attempts=0, real_model_requests=0, index_writes=0
.venv/bin/python -m compileall -q naiyue_rag experiments tests
# exit 0；仅语法检查，应用构建未设立/不适用
.venv/bin/python -m pip check
# No broken requirements found.
git diff --check
# exit 0
```

全量曾误用未限定目录的pytest，收集research内第三方测试导致96项collection errors；保留full-tests.txt，按README既定tests入口重跑，未修改pytest配置/skip/第三方文件。项目全量证据在project-tests.txt。

L1：BatchProcessor/EncodedRecord/EncodingResult/EncodingReport/EncodingJobError及测试文件存在并公共导出。L2：实际预检/一次分批/两路调用/ID与各自hash配对/截止检查/失败报告与JSON校验，无占位。L3：独立YAML→Loader→prepare_knowledge_base→prepare_document_encoding_inputs→BatchProcessor→真实SDK的MockTransport与真jieba→72成对记录→JSON往返真实执行，客户端由调用方关闭。

本片97项覆盖第7节全部离线验收分支。报告里的service仅协议标记；72 tokens是明确合成的HTTP用量，不是服务账单。检索质量未评价、真实材料/模型未验证；协作截止无法硬中断阻塞。报告只在内存，外层初始化/关闭与可选持久化不归本报告。文档成对完成不代表M3全部完成：查询成对结果、真实服务/硬截止仍待；M4索引/激活未接。

课堂入口更新Lesson8，学习证据只记本片职责/分支已说明；用户自述理解未新增，本人调试/独立实现未评估。唯一下一步：用第二批Sparse失败测试走读正式process→报告→EncodingJobError，随后继续M3查询切片。
