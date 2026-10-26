# Lesson 41：阶段B·6.4 追踪、延迟和用量的证据边界

> 2026-10-26。目标：理解当前报告的生产者、消费者、计时范围、请求与用量口径，避免将未知当0、将局部时间当端到端、将调用成功当免费。沿真实代码与既有测试，不新增监控平台。

## 先看当前返回结构

最终证据observations包括retrieval、embedding、rerank、retrieval_configuration、rerank_configuration、packing。它们不是同一个计时器或同一份用量账本：

| 数据 | 生产者 | 范围/用途 |
|---|---|---|
| retrieval | QueryPipeline/HybridSearch→TraceContext | 请求预检、资源、查询编码、两路检索和融合，阶段ms/计数/安全状态 |
| embedding | QueryEncoder→BatchReport→EncodingReport | 本次查询成对编码的请求观察、用量、阶段/整体秒数 |
| rerank | 评分后端与CoreReranker | 本次重排状态、HTTP观察/可用usage、elapsed_seconds |
| packing | ResponseBuilder | 固定包来源检查及打包至该记录点的秒数、条数与字符 |

读取路径：RetrievalPipeline.query→HybridSearch.search→CoreReranker.rerank→ResponseBuilder.build。Builder复制已有报告，不再次计算服务token。查询embedding报告不包括历史建库用量；重排LLM的completion_tokens是评分输出，不是尚不存在的最终业务答案。

## 时间：先明确起止和单位

TraceContext使用UTC started_at/finished_at标记发生时间，time.monotonic差值算耗时。monotonic不是日期，不能转成北京时间；UTC时钟可能被系统校准，不能替代单调时钟做可靠持续时间。

TraceContext.record_stage未显式传elapsed_ms时，用距上一次记录的间隔；HybridSearch对Dense/Sparse/Fusion显式传各调用边界的ms，准备阶段则复制原记录。finish计算当前TraceContext创建到结束的total_elapsed_ms。记录列表不保证是完整分布式父子span，也不严格代表真实完成顺序。

HybridSearch在融合后finish，随后才创建/检查HybridResult并交给重排。因此retrieval.total_elapsed_ms不是RetrievalPipeline或CLI端到端时间，也不包括后续重排/打包、模型初始化或输出。ResponseBuilder的packing.elapsed_seconds始于build入口，含读取核验，止于packing记录；不包括其后的完整JSON校验/深拷贝或CLI打印。端到端若要测，须在所声明的入口和最终返回/输出边界计时，本课不新增该字段。

并行检索教学示意（非实测）：准备100ms，Dense80ms、Sparse60ms重叠，融合5ms。理想检索墙钟约100+max(80,60)+5=185ms加开销；逐阶段相加245ms会重复计入重叠。两路耗时含该调用的等待/IO，不是CPU耗时。池调度、磁盘、GIL和资源争用存在，不能保证真实并行恰等于max或一定快于串行。

Embedding的elapsed、它外层的编码elapsed、包含编码的retrieval elapsed相互嵌套，不能再相加。Rerank Core保留包含后端与校验的时间，与后端elapsed取最大，不代表两个独立相加阶段。

单次耗时只能描述这次调用。性能对照要固定材料/配置/并发与冷暖状态，区分初始化和稳态，多次记录并说明样本与分位数算法；不能从MockTransport/替身CPU时间推出真实服务p95、吞吐或优化收益。CrossEncoder首次加载与predict需分别定义边界。

## 计数：每个数字在数什么

| 字段/概念 | 实际含义 | 不能推出 |
|---|---|---|
| dense_calls_started | 编排器进入Dense适配器的次数 | 真实发出/服务端收到等量请求 |
| attempted_requests | HTTP transport调用底层handle_request前计数 | 请求已到达服务端、推理成功或计费确认 |
| http_responses_observed / http_status | 在本机边界看到了HTTP响应头 | 完整正文/业务结果已经合法 |
| response_bytes | 本机读取到的响应body chunk字节 | token数量、请求字节或完整网络流量 |
| eligible_count | 本次范围内可参与检索的片段数量 | HNSW实际比较了多少向量 |
| candidate_count / selected_count | 返回候选数/最终保留条数 | 这些内容相关或足够回答 |

encoding/bounded_transport.py:62在底层transport前attempted_requests+=1，64行取到response后写http_status；发送超时可出现attempted=1/status=None，HTTP200后读取正文超时可出现attempted=1/status=200，但无成功向量。此时服务端是否已执行/计费未知。

当前Embedding与LLM评分SDK显式max_retries=0，避免隐藏SDK重试；调用方或第三方网关的行为需另有证据。HTTP次数不等于输入条数：一个批请求可包含多个文档片段；一次LLM重排可评分多条候选。CLI检索+LLM重排通常涉及两种模型工作，但条数/实际请求要读各自报告，空态和关闭策略可能不发请求。

## 用量：任务状态和账本完整性独立

core/encoding_report.py::summarize_observations分开保存：已知HTTP尝试小计、缺少请求观察的Dense调用数、已知usage小计和完整总数。若还有未观察调用，attempted_requests=None；已知小计0不代表总请求为0。若有未覆盖用量，total_tokens=None，已知小计仍可保留。

usage.status：

- no_requests：有足够观察证明没有请求，不是假定token为0；当前总token字段仍为None。
- complete：观察覆盖了相关请求，可以报告总用量；合法0仍是已知值。
- partial：有已知usage，但存在未覆盖部分，小计不是总计。
- unknown：无法提供完整总数且没有已知usage可用。

本课实际用现有QueryEncoder和合成Dense/Sparse夹具运行四种情况：

| 情况 | 任务status | started | attempted_requests | HTTP观察 | usage.status | total_tokens |
|---|---|---:|---:|---:|---|---:|
| 合法已知0 | success | 1 | 1 | 1 | complete | 0 |
| HTTP有报告、usage缺失 | success | 1 | 1 | 1 | unknown | None |
| 适配器进入后抛未知异常，没拿到报告 | failed | 1 | None | 0 | unknown | None |
| Dense成功后Sparse失败 | failed | 1 | 1 | 1 | complete | 7 |

第三行attempted_requests_known_sum=0、observation_unknown_dense_calls=1；HTTP观察0不代表服务端没收到。第四行没有成功查询向量结果，但已知Dense用量保留，不能失败后清零。以上请求/7token均为替身模拟报告，真实模型请求0；不能因为字段看起来像服务用量就当真实账单。

LLMReranker先解析usage，再验评分内容：格式错误/ID缺失仍可在RerankError.report保留已知usage；usage缺失为None。CrossEncoder本地predict成功时report.attempted_requests=0、usage=None，不代表零CPU成本或已统计所有本地token；max_pair_tokens是输入限额，不是账单。当前字段未提供模型下载/加载/电量账本。

同一份encoding报告可能同时出现在查询结果或异常副本、retrieval安全摘要中；不能按字段出现次数重复累计。不同调用的job_id/trace_id用于标识对应记录，但本项目未建一个覆盖所有阶段/分布式调用的统一账务树。

## 费用为何仍是未知

usage是服务返回的计数，本机通常不能独立证明服务端计量/结算。估算还需明确模型和计价版本、输入/输出/缓存等类别、实际网关收费规则；实际账单需服务端/账务证据。当前smoke.report.cost_cny=None，不根据字符、延迟或缺失token编造费用。无费用数据时未知，不能写免费。本课不查询当前价格或调用计费服务。

## 有报告不等于已持久化、全链路追踪

当前M5/M6主链在返回JSON的observations带报告；CLI app.py执行pipeline.query并打印，未调用TraceCollector.collect。历史显式retrieve_with_trace入口具备JSONL持久化、写失败保留结果并标记的策略；存在此组件不能推断当前CLI已自动落盘或已形成统一全链路追踪。

Hybrid追踪构造/校验失败会按当前严格合同报query_trace_failed，不等同历史“可选落盘失败”策略；错误中可能trace_report=None但encoding_report仍保留。描述报告/可选保存/关键校验的不同职责，不自动迁移旧包装或实施新系统。

正式TraceContext是封闭字段：版本标识、计数、安全状态/代码，不接收任意正文、Key、原始请求/响应。排查具体片段需明确边界，不能把完整知识内容塞入通用日志。source_kind='service'等是适配器来源分类，真实SDK+MockTransport测试仍不是远端实测。

## Debug Test入口

1. `tests/test_tracing.py::test_monotonic_clock_and_closed_lifecycle`（无参数ID）：Test Explorer→Debug Test。测试25–26行将monotonic替为10、10.125、10.5，实际等待0。TraceContext第145行起点10；record_stage第159行算125ms；finish第177行算500ms。测试31行断言，说明阶段间隔和总耗时不同；这不是实际性能。
2. `tests/test_query_encoding.py::test_unknown_usage_and_zero_are_distinct[None]`与`[0]`：测试139行调用QueryEncoder，断在core/encoding_report.py:90，选择summarize_observations帧，前89行后看unknown/known_sum/known/prompt/total；返回测试帧看report['usage']。None和0两条分支均通过，但意义不同。
3. `test_dense_protocol_observation_is_safe[unknown-exception]`：测试120行替身抛RuntimeError，QueryEncoder73–77行包装EncodingJobError；测试129行捕获。看report['requests']['dense_calls_started']=1、attempted_requests=None，而known_sum=0。不得据此报告0网络请求。
4. `test_failure_keeps_request_and_usage_with_no_query_result[sparse]`：测试81行注入Sparse OSError，在QueryEncoder63行调用抛出，73–77行捕获；测试87行后看status='failed'与usage.total_tokens=7。异常被pytest.raises捕获，测试通过；7是替身，不是本次收费数据。
5. `tests/test_openai_embedding.py::test_timeout_single_attempt_and_unknown_status_when_no_headers[send]`、`[read]`：MockTransport handler在145行发送或Body读取注入ReadTimeout。断点bounded_transport.py:62、64，只有read分支走到64写200；测试148行捕获EmbeddingExecutionError。真实SDK/transport观察，未连外部服务。

WATCH只查看当前帧已产生report或已知小计，不再次encode/score/请求。SDK初始化等旧逻辑可F5到这些边界，F10/F11/Shift+F11追观察传播。

## 本次实际验证

```sh
.venv/bin/python -m pytest -q \
  tests/test_tracing.py::test_monotonic_clock_and_closed_lifecycle \
  tests/test_query_encoding.py::test_unknown_usage_and_zero_are_distinct \
  'tests/test_query_encoding.py::test_dense_protocol_observation_is_safe[unknown-exception]' \
  'tests/test_query_encoding.py::test_failure_keeps_request_and_usage_with_no_query_result[sparse]' \
  tests/test_openai_embedding.py::test_timeout_single_attempt_and_unknown_status_when_no_headers \
  tests/test_hybrid_search.py::test_trace_accepts_explicit_eligible_count_without_inventing_ann_work
# 8 passed in 0.78s

.venv/bin/python -m pytest -q \
  tests/test_llm_reranker.py::test_real_sdk_config_reaches_wire_and_usage \
  tests/test_llm_reranker.py::test_missing_usage_stays_unknown \
  'tests/test_llm_reranker.py::test_bad_output_is_atomic_and_usage_is_preserved_when_known[missing]'
# 3 passed in 0.81s
```

另有临时Python标准输入脚本直接导入tests.test_query_encoding.setup与生产QueryEncoder，运行四种上表分支，真实输出与表一致；未知异常输出安全error日志，不抛出原始敏感内容。两次测试共11项，各自命令/耗时分列，不声称单次全量；真实模型0。模拟LLM usage20已知/缺失/评分错误保留由真实SDK+MockTransport覆盖。

L1：TraceContext/EncodingReport/RerankReport/observations存在；L2：实质时钟/请求边界/小计和未知处理执行；L3：既有生产函数由测试/探针消费，当前最终返回接线及未自动落盘由源码核验。本课无新监控/统一账务/端到端字段。仅学习文档修改；源码、.env、运行配置、依赖不改，构建不适用，未跑全量/真实性能或费用实测；git diff --check与git diff --cached --check退出0。

## 学习证据与唯一下一步

6.4已讲解，用户理解待反馈，独立调试/实现未评估。讲解覆盖33/34节，余6.5一节。唯一下一步：6.5从Debug Test走完整分支并独立定位一次问题；是否取得独立能力证据以用户实际调试结果为准。
