# Lesson 24：阶段B·3.6 超限、整次失败与真实用量

日期：2026-10-23，第3章共6节，本节最后一节。目标：区分输入/响应资源界限、请求与总截止、任务失败与用量完整性。本节开始前共34节已讲15节，含本节剩19节；本节后第1–3章讲解覆盖16节，剩第4章5节、第5章8节、第6章5节，共3章18节。讲解覆盖不等于掌握。

## 实际执行链

EncodingInput→plan_encoding_batches整体数量/字节/批次预检→BatchProcessor逐批检查剩余时间/请求观察→DenseEncoder→Provider/SDK→BoundedTransport观察HTTP尝试、状态、响应字节与截止→响应usage校验→Sparse/配对→EncodingReport终态。失败EncodingJobError携带安全报告、不含部分records；基本交付机制见Lesson23，不重复展开。

## 限制分别保护什么

公开examples/core-demo/encoding.example.yaml当前runtime：batch_size32、max_inputs1000、max_input_utf8_bytes32000、max_batch_input_utf8_bytes128000、max_requests4、timeout_seconds30、deadline_seconds60、max_response_bytes4194304。都是配置值，不是业务最优值或模型token上限。

| 配置 | 当前约束 |
|---|---|
| max_inputs | 一次任务总输入项数 |
| batch_size | 每批最多多少独立输入，不重新切片 |
| max_input_utf8_bytes | 每项embedding_text（含前缀）的UTF8字节 |
| max_batch_input_utf8_bytes | 一批输入文本UTF8字节之和，不等同HTTP JSON完整大小 |
| max_requests | 计划批次数及实际请求观察限制；各限制共同生效 |
| max_response_bytes | 响应体字节，包括成功/错误HTTP正文 |
| Sparse max_terms_per_input/max_resource_bytes | 候选词项数与词典/缓存读取界限，见Lesson21 |

实际示例len('开关')=2，len('开关'.encode('utf-8'))=6。字符数、UTF8字节数、jieba词项数、Embedding服务token数是不同单位，不能互相当成真实服务用量。当前字节预检不保证模型token限额一定满足；服务拒绝要沿请求错误处理。

数量/字节超限时拒绝或提前换批，不悄悄裁短输入。整体计划请求数过多在编码前失败；空输入合法，调用0次，不等于已取得服务token=0的响应。

BoundedTransport覆盖错误正文：_BoundedBody逐块先计response_bytes，再检查deadline与字节上限，超限不yield该块到应用累积缓冲，关闭响应。Content-Length可提前拒绝，但缺失/虚报小时仍按实际流计数。收到越界网络块后才检查，不能宣称网络层从未接收超限字节。

## 用量：观察完整性与任务结果分开

ProviderBatchResult.usage来自服务响应字段并经校验，缺失为unknown_missing，格式错误为unknown_invalid；未知不补0。实际账单/费用不在此计算，不能把服务token观察当账单证明。课堂下列数值均为替身/模拟响应，没有真实模型请求。

### 任务成功，但用量不完整

三批人工usage=[7,None,3]，本机编排探针真实输出：

```text
job_status=success
attempted_requests=3
known_usage_requests=2
known_total_tokens_sum=10
unknown_usage_requests=1
usage.status=partial
usage.total_tokens=None
```

可以报告已知小计10，不能报告总计10，缺失那次可能消耗token。三个usage都未知时status=unknown、总量None；三个都明确0时status=complete、总量0。任务无请求时status=no_requests、请求数0、token总量None。这些状态已由确定性测试区分。

### 任务失败，但用量完整

5输入/每批2项：第1批Dense返回7，Sparse/配对成功；第2批Dense返回5，随后Sparse抛错，第3批不执行。实际探针输出：

```text
job_status=failed
error.stage=sparse，batch_index=1（第二批）
completed_batch_count=1，paired_input_count=2
attempted_requests=2
usage.status=complete，usage.total_tokens=12
异常has_records=False
```

complete只说明已经尝试且有可靠报告的请求，其用量都已知；不表示全部计划完成。报告保留12，不因编码失败归零，也不交付前批records。此探针用普通RuntimeError注入，所以归一为encoding_stage_failed；真实SparseTokenizer的固定错误码可沿已有码表保留。

## 请求次数也有已知与未知

attempted_requests由HTTP传输边界记录，表示尝试，不证明远端一定收到或计费；http_status为空可能是连接失败。dense_calls_started表示进入Dense执行器多少次，不能自动当HTTP次数。

若某次Dense直接异常且没有有效请求报告，是否真的请求过无法确定。summarize_observations保留attempted_requests_known_sum，但总attempted_requests=None，并记录observation_unknown_dense_calls；不能把无报告当作0次请求。未知次数场景也不能杜撰unknown_usage_requests的具体数量。

core/encoding_report.py:80–98取各批request_report与已知usage：有未知观察则不交付完整请求总量；只有所有已尝试请求用量完整时才设置total_tokens，否则只保留已知小计。它不重新执行请求，也不重新计算模型token。

## 超时与截止的三层边界

| 层次 | 当前行为与限制 |
|---|---|
| 单次HTTP timeout | Provider传min(剩余时间,配置timeout)给SDK/HTTPX，约束网络等待；不是整个任务的硬计时器 |
| BatchProcessor协作截止 | process起点固定，用monotonic计算remaining，阶段前后/Provider流块间检查；不能打断任意阻塞函数 |
| 独立监督验收入口run_check | 子进程运行编码，父进程等待超时后kill并wait，读取已持久化观察；不等于所有生产入口已接此监督 |

10秒示意：第1批开始剩10秒，该批耗2秒，第2批剩8秒，第3批剩6秒，不每批重置10秒。已有测试用固定时钟得到Dense remaining=[10,8,6]，无真实sleep窗口。

协作截止只有执行到检查点才知道超时。若Sparse内部一直阻塞，BatchProcessor无法凭_remaining强制打断；验证工具的独立父进程能终止本机worker，但不能证明远端推理/账单已取消。run_check监督从prepare_job之后计时，清理另有cleanup_seconds；不声称涵盖模型初始化之外的全部摄取生命周期或毫秒级准时结束。

当前Provider/HTTP transport显式禁自动重试；HTTP429等一次失败整次报错，不悄悄增加请求。并发/重试/断点恢复均未在本节加入。

## Debug Test与替身边界

用量入口：`tests/test_batch_processor.py::test_missing_and_zero_usage_are_distinguished[usages0-partial]`，已collect核对精确ID；另usages1-unknown/usages2-complete。测试第111行执行process，F5到core/encoding_report.py:80；选summarize_observations帧，第85行后看known，第87–91行后看prompt/total/unknown_usage/status，第97行后看usage。多次snapshot都会进入，最终回测试report才是完整三批终态；可在最终finalize snapshot时进入或回测试看最终投影，避免把第一批中间汇总当总结果。

失败保留用量：`tests/test_batch_processor.py::test_second_batch_failure_stops_third_and_keeps_usage[sparse]`，精确ID=sparse。测试第90–92行hook在第二次Sparse调用抛RuntimeError；生产process第97行异常，进入第109–113行构造failed报告。Dense报告已在第87/94行登记，所以已知7+5保留。pytest.raises捕获，测试通过。Dense/Sparse为现有确定性替身。

剩余截止：`tests/test_batch_processor.py::test_remaining_deadline_is_not_reset`，无参数。第170行hook每次Dense把测试时钟加2秒，生产_remaining第27行看start/当前单调时间/remaining；实际值10、8、6。`test_cooperative_deadline_checks_after_stages[sparse]`模拟Sparse返回时越过总截止，阶段检查拒绝；不证明能打断永久阻塞。

响应体：`tests/test_openai_embedding.py::test_actual_byte_limit_covers_success_and_error[absent-500]`，精确ID=absent-500。MockTransport返回HTTP500、无Content-Length，三块各32字节、上限48；_BoundedBody第38行依次32/64，第40行第二块超限，响应关闭，异常embedding_response_too_large被测试捕获。HTTP/SDK是真实路径、响应是人工数据。

监督：`tests/test_encoding_check_wiring.py::test_real_blocking_child_is_killed_reaped_and_keeps_dense_usage`。真实子进程执行worker/检查点，Dense替身返回7，Sparse替身Event永久等待；就绪管道握手后，测试包装communicate显式抛TimeoutExpired，验证父进程真实kill/reap与保留检查点usage。证明超时清理机制，未实测依靠墙钟自然到点的精度；没有真实模型调用，也不读改本项目真实.env，只使用测试临时项目合成配置。

## 本次验证

```sh
.venv/bin/python -m pytest -q \
  tests/test_encoding_inputs.py::test_batch_count_bytes_and_whole_job_limits \
  tests/test_batch_processor.py::test_second_batch_failure_stops_third_and_keeps_usage \
  tests/test_batch_processor.py::test_missing_and_zero_usage_are_distinguished \
  tests/test_batch_processor.py::test_unknown_second_call_preserves_first_observation \
  tests/test_batch_processor.py::test_empty_is_no_requests_not_zero_tokens \
  tests/test_batch_processor.py::test_remaining_deadline_is_not_reset \
  tests/test_batch_processor.py::test_cooperative_deadline_checks_after_stages \
  'tests/test_openai_embedding.py::test_http_failure_single_attempt_safe_report[429]' \
  'tests/test_openai_embedding.py::test_actual_byte_limit_covers_success_and_error[absent-500]' \
  tests/test_encoding_check_wiring.py::test_real_blocking_child_is_killed_reaped_and_keeps_dense_usage
# 17 passed in 0.91s
```

另3个usage参数ID collect，3 tests collected in0.20s。L1已有输入计划/传输/报告/独立监督文件，L2真实限额/截止/汇总实现，L3本次17项测试覆盖准备→执行→失败报告及监督清理，但外部服务按上述替身边界。无真实模型/源码/依赖/运行配置/原索引修改；构建不适用，不跑全量；git diff --check退出0。

## 第3章收束与唯一下一步

3.1文本表示→3.2 Dense向量→3.3 Sparse词项→3.4编码身份→3.5成对批处理→3.6资源/失败/用量，六节讲解覆盖。用户理解待反馈，本人独立调试/实现/追问未评估。剩余3章18节为当前计划，不承诺固定日期。

下一节4.1：原文、资料包与索引的区别，从本章EncodingResult追到BundleStore、Chroma与BM25持久产物，开始第4章5节。
