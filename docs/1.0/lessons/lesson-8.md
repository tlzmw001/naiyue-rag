# Lesson 8：调用链是什么，BatchProcessor为什么要核成对结果

日期：2026-10-13。学习位置：M3批次完整性章节。用户说明不知道“调用链”在做什么，本节先讲这一概念及正常/失败数据变化。本节最初对照Spec0024设计，随后用户确认实施，正式BatchProcessor现已离线接线；参考探针用真实选定类/合成编码器，无模型/存储。讲解不替代用户理解证据。

## 1. 一个具体任务

把Markdown准备成5个片段C1–C5，每批最多2个，形成[C1,C2]、[C3,C4]、[C5]。每个片段要有两份派生数据：Dense的语义向量，Sparse的词项/词频。未来M4用同一片段ID把它们与原文关联。

调用链就是一次任务中谁调用谁、数据怎样变化、结果/异常交给谁。它用于确认接口是否真正接线、配置是否被使用、顺序和错误处理是否正确。分批便于请求限额/执行组织，不能凭它判断召回质量。

```text
文档准备层 → BatchProcessor.process(片段)
             → 每批DenseEncoder.encode → Provider.embed → 向量返回
             → 每批SparseEncoder.encode → jieba/Counter → 词频返回
             → 汇总结果返回准备层
准备层 → 存储层（参考实际已有；我们M4待接）
```

箭头表示调用；方法返回后，调用方拿到新数据继续执行。装配与执行分开：构造Pipeline/BatchProcessor时保存编码器和batch_size；调用process时才开始批次循环/模型请求。这里追摄取编码，查询和Agent重检索在另外的链路。

## 2. 参考真实源码的决定性四行

定位：[参考BatchProcessor.process](/Users/zmw/MODULAR-RAG-MCP-SERVER/src/ingestion/embedding/batch_processor.py:155)。以下摘取固定commit实际代码：

```python
batch_dense = self.dense_encoder.encode(batch, trace=trace)
dense_vectors.extend(batch_dense)
batch_sparse = self.sparse_encoder.encode(batch, trace=trace)
sparse_stats.extend(batch_sparse)
```

batch来自_create_batches：第二轮是[C3,C4]。dense_encoder是Pipeline装配给Processor的对象。第一行正常返回该批向量到batch_dense；第二行已经修改总列表。第三行才调用Sparse；如果这里抛异常，第四行不执行，异常进入process的except，而总向量列表不会自动恢复。

参考except将失败计数增加，随后继续第三批。教学校例/本机探针结果如下：

| 时点 | 总Dense对应ID | 总Sparse对应ID |
|---|---|---|
| 初始 | [] | [] |
| 第一批完成 | C1,C2 | C1,C2 |
| 第二批Dense返回并extend | C1,C2,C3,C4 | C1,C2 |
| 第二批Sparse失败 | C1,C2,C3,C4 | C1,C2 |
| 参考继续第三批 | C1,C2,C3,C4,C5 | C1,C2,C5 |

参考下游pipeline.py:443–444用zip按位置改Sparse ID，教学示意中C5的词频可能对应第三个向量C3。真实存储没有在探针中执行，不宣称已经损坏数据。VectorUpserter的数量检查在这个场景只比较5个chunk/5个vector，不能单凭它证明Sparse也齐。

## 3. 我们已经有的单批路径

[DenseEncoder.encode_batch](/Users/zmw/naiyue-rag/naiyue_rag/encoding/dense_encoder.py:17)接EncodingInput列表与remaining_seconds，返回(result,report)。输入里embedding_text送Provider，result里input_ids/input_hashes/vectors恢复对应顺序，report记录本次请求的安全观察。

[SparseEncoder.encode_batch](/Users/zmw/naiyue-rag/naiyue_rag/encoding/sparse_encoder.py:22)接相同输入，取retrieval_text分词，返回SparseRecord列表。前缀不会进入Sparse；每条带item_id及retrieval_text_sha256。这里两份文本hash职责不同，不能要求它们相等。

BatchProcessor按ID找两份结果并分别核hash，然后才把它们作为一条成对记录汇总。必要失败停止后批，抛带安全报告的错误，不交付部分编码数据。此前本机1004绿灯证明这些单批/源合同已有验证，不证明新BatchProcessor存在。

## 4. 为什么任务失败还要留用量

示意：第二批Dense已请求服务并拿到合法usage，随后Sparse失败。编码任务失败，远端请求已经发生；用量观察仍要保留。整次失败保证不给M4部分结果，不能撤销已发生的请求或费用。

示意两批usage为7和5：已发请求的已知总量12，即使任务失败；若第二批usage缺失，则已知小计7、总量未知。计数与观察来源是服务返回，不按字符猜、不均摊给片段。以上只是教学数字，当前课堂模型请求0。

## 5. 先用已有测试走一段

- tests/test_dense_encoder.py::test_actual_dense_path_preserves_source_and_reorders_indices[document]：真实M2→Dense/SDK→MockTransport→向量/报告，响应index反序恢复。
- tests/test_sparse_wiring.py::test_m1_m2_to_real_sparse_binds_ids_hashes_and_preserves_originals[raw]：真实Loader/M2→真实jieba/Sparse，ID/hash与原文保持。

VS Code Test Explorer选Debug Test；F5到DenseEncoder.encode_batch或SparseEncoder.encode_batch边界，然后F10/F11/Shift+F11。Encoder帧先看inputs；调用返回后才能看result/report或records。WATCH只投影[i.item_id for i in inputs]、result.input_ids、report['attempted_requests']、records[0].item_id/doc_length。不要重跑函数取返回值。

Dense测试仅替换HTTPTransport为MockTransport，并用固定生产边界时钟；真实SDK/编码器仍执行。Sparse是实际jieba；两个入口各自独立，是总Processor实施前的两个独立课堂入口。参考演示的Dense/Sparse为替身，证据分开。

## 6. 正式实现的分支地图与调试入口

当前[BatchProcessor.process](/Users/zmw/naiyue-rag/naiyue_rag/encoding/batch_processor.py:67)链路：入口时间/job→独立输入副本/整体计划→每批Dense→先记合法请求/usage→Sparse→ID/hash配对→记录与批完成计数→最终合同→返回。错误捕获在同函数109行，快照后抛EncodingJobError；没有返回部分records的分支。

| 分支 | 独立确定性测试（tests/test_batch_processor.py） | 输入与预期 |
|---|---|---|
| 正常/逆序恢复 | test_success_pairs_by_id_and_restores_input_order | C1–C5/批2，两路逆序，恢复5条原输入顺序记录 |
| 全部预检 | test_whole_preflight_failure_makes_no_calls[last-hash] | 第5项hash不符，首次Dense前整次报错，0请求 |
| 第二批Dense失败 | test_second_batch_failure_stops_third_and_keeps_usage[dense] | 第二批失败HTTP503替身，2请求、已知小计7/总量未知、不跑Sparse/第三批 |
| 第二批Sparse失败 | test_second_batch_failure_stops_third_and_keeps_usage[sparse] | 第二批Dense已知5tokens，Sparse抛异常；第一批7+第二批5=12保留，第三批不跑 |
| 配对失败 | test_second_batch_failure_stops_third_and_keeps_usage[pairing] | 第二批Sparse少一条，整次失败，不把缺项补为空记录 |
| 截止 | test_cooperative_deadline_checks_after_stages[sparse] | 固定时钟在Sparse后越10秒，保留Dense观察，整次报错 |
| 最终合同失败 | test_final_validation_failure_keeps_all_issued_usage | 最终结果边界故障，3批已完成但不交付数据，已发用量15保留 |

正常返回的一条EncodedRecord有input（ID/源版本/span/两份文本hash）、dense_vector、sparse（ID/hash/TF）、batch_index。配对在_pair，分别比较embedding_text_sha256和retrieval_text_sha256，两hash不用相等。completed_batch_count是内存中已验证批数，不是索引已保存数。合法空TF仍配对成功。

从VS Code Test Explorer选第二批Sparse失败的[sparse]参数实例，点Debug Test。不改IDE/装调试依赖。测试Dense/Sparse为确定性边界替身；真实接线另用tests/test_batch_wiring.py::test_real_pipeline_produces_72_pairs_with_no_network[raw]，只有HTTPTransport/生产Dense边界时钟替换，实际SDK、Loader/M2与jieba执行。

建议断点：生产process第67行（入口）、第97行（Sparse调用）、第111行（失败报告返回值赋给report后单步停112行）、测试fault的第91行（n==2抛RuntimeError）。F5先到入口，然后F10/F11/Shift+F11。第二批用batch投影确认[C3,C4]。别在WATCH再次调用编码函数。

- process栈帧，预检后观察[i.item_id for i in inputs]，循环后观察index/[i.item_id for i in batch]。
- Dense返回赋值后观察dense.input_ids与request['attempted_requests']；登记后观察observations.current['usage']及observations.started。
- Sparse故障前：records含C1/C2、completed_batch_count=1、当前批usage=5；sparse变量还没有本批正常返回值，可能仍是前批值，不据它判断成功。
- fault栈帧：n==2、batch为C3/C4；第91行抛出，回到process的except。F10到112行时report才产生，投影report['error']、report['requests']、report['usage']。
- 回测试caught帧：caught.value.report，requests=2、usage.total_tokens=12、completed_batch_count=1/paired_input_count=2，无records。预期异常被pytest捕获，测试通过正是正确失败行为。

验证：97新增/1101项目全量通过，12Mock/72成对记录/36模拟HTTP、外部模型0。这里只证明工程接线，检索质量未评估。正式完整源代码课堂/用户Debug Test结果尚未收取；下面学习证据不因实现绿灯而升级。

## 7. 学习证据

- 已讲解：调用链含义、装配/执行、5项三批、extend副作用与异常路径、ID/hash配对、失败后保留用量。
- 用户自述理解：本节尚未确认。
- 本人复述/调试/改动/独立实现/可应对追问：未评估，没有练习结果。
- 精读函数：参考BatchProcessor.process的Dense→extend→Sparse→except；本项目两个encode_batch仅说明输入输出和返回消费，内部尚未完整带读。
- 待复习：单批函数返回与任务总结果、两文本hash、局部已完成计数与整体失败、未知usage不能当0。

不强制本轮检查题；用户未懂时先用更小的两批状态表继续。当前设计及唯一实施下一步见[Spec0024](../../specs/0024-m3-paired-batch-encoding.md)，不把课堂说明记为用户已掌握。
