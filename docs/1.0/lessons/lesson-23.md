# Lesson 23：阶段B·3.5 成对批处理、ID与hash配对

日期：2026-10-23，第3章共6节，本节第5节。目标：从3个输入/2批说明BatchProcessor怎样把Dense/Sparse合为完整记录，为什么分别核两种文本hash，以及整批次/整任务交付边界。请求上限/时限/用量详细机制留到3.6。

## 模块职责和实际消费者

IngestionPipeline._build_and_activate先prepare_knowledge_base→_inputs→batch_processor.process(inputs)，完整EncodingResult返回后，才交prepare_index_bundle/保存/建双索引/激活。BatchProcessor不读原Markdown、不建索引、不打开或关闭调用方拥有的Provider。

process只接document类EncodingInput，查询由QueryEncoder独立编排。它的职责是整体预检、单一分批计划、按批执行Dense→Sparse、身份配对、收齐全任务结果与执行报告；当前同步顺序执行，不并行、不重试、不降单路、不做断点续跑。

## 3片段/2批：具体状态

本机探针复用test_batch_processor的inputs(count=3)/setup，使用真实BatchProcessor与确定性Dense/Sparse替身。C1/C2/C3是合成测试ID，来源字段人工构造，不宣称已从原文件核验。测试batch_size=2，字节上限足够；公开core-demo batch_size=32，不把本课2当推荐最佳参数。

```text
输入快照：[C1,C2,C3]
计划：batch0=[C1,C2]，batch1=[C3]
batch0：Dense → Sparse → 按ID/hash配对 → 暂存R1/R2
batch1：Dense → Sparse → 按ID/hash配对 → 暂存R3
finalize：整体结果/来源/批次指纹核对 → 返回EncodingResult
```

替身故意反序返回同批记录，探针实际输出：

| 原输入ID | dense_vector第一项 | sparse.item_id | batch_index |
|---|---:|---|---:|
| C1 | 1.0 | C1 | 0 |
| C2 | 2.0 | C2 | 0 |
| C3 | 3.0 | C3 | 1 |

completed_batch_count=2、paired_input_count=3。向量[1,2,3]/[2,2,3]/[3,2,3]由替身按ID构造，只说明编排/归属，不表示真实语义。

## 先整体预检，再开始第一批

_preflight对每个EncodingInput序列化再校验、复制为私有输入；仅document，同一知识库，同一source_document_id只能有一个source_sha256。plan_encoding_batches进一步核输入ID唯一、文本/hash与配置、数量/UTF8字节/计划请求数。

因此，最后一个输入坏了，也在第一批Dense之前拒绝，不等跑完前面再发现。空列表合法，返回empty结果/records=[]，两路调用0；不是把空列表直接交给要求恰好一批的DenseEncoder。

计划按数量和embedding_text UTF8字节共同限制，可能不足batch_size就提前换批。批次不重新切分片段、不改变chunk_size、不把几个片段合并成一份语义文本；同一批仍是多份独立输入。

输入复制保证调用方后来修改原列表/对象，不改变本次私有快照；不等于已经验证磁盘原文件，来源回读在M1/M2完成。后续最终指纹还会拒绝编码器篡改私有输入来源的情况。

## 成对记录与两种hash

```text
EncodedRecord(
    input=原始EncodingInput的独立副本,
    dense_vector=对应向量,
    sparse=对应SparseRecord,
    batch_index=本次批次编号,
)
```

EncodedRecord由_pair核对后创建，最终EncodingResult保存records、三类身份/维度与报告，不维护两份无归属的平行列表。

| 配对依据 | 验证内容 |
|---|---|
| 两路ID集合=当前batch输入ID集合 | 无缺失/额外记录；重复ID另由已有类型校验和Sparse字典构建拒绝 |
| Dense input_hash=embedding_text_sha256 | 对应实际Dense输入，包含前缀 |
| Sparse retrieval hash=retrieval_text_sha256 | 对应实际Sparse输入，不含Dense前缀 |
| 模型身份、维度、kind、tokenizer_id | 编码合同一致 |

ID说明属于哪份输入，hash说明绑定的是该输入的哪份文本。只核数量，会漏掉乱序/重复；只核ID，会漏掉同ID却用旧文本的记录。两端文本可能因前缀不同，不能拿同一个hash硬套两路。

## _pair的实际过程

batch_processor.py:46–65：先重校验ProviderBatchResult与SparseRecord，Dense按ID建by_dense，Sparse按ID建by_sparse。wanted为本批输入ID集合；集合匹配后按原batch遍历，通过item.item_id取两端数据，核对各自hash与身份，再构造EncodedRecord。

```python
for item in batch:
    sha, vector = by_dense[item.item_id]
    row = by_sparse[item.item_id]
    # 核对两种hash及编码身份
    records.append(EncodedRecord(item, vector, row, index))
```

因此合法乱序可以接受，最终仍按原始输入顺序输出。内部zip(dense.input_ids,input_hashes,vectors)是遍历同一已校验Dense结构的对应列，不是把两路结果靠位置盲配。

这些检查验证来源与编码合同，不证明模型语义正确。若底层给错向量却同时附上完全一致的ID/hash/维度，不能仅靠这些元数据发现模型内容错误；不能从向量反算原文hash作语义证明。

## 暂存与交付、失败路径

每批_pair全部成功后才返回paired，process随后records.extend(paired)、observations.complete；当批半途失败，_pair局部列表不交付。前批records仍可能暂存在process内存中，但后批失败会抛EncodingJobError，异常不带records，后续批停止，外层调用方得不到部分EncodingResult。

| 情况 | 结果 |
|---|---|
| 所有批完成、最终核验通过 | 返回完整EncodingResult |
| 整体预检失败 | Dense/Sparse均0次调用 |
| Dense失败 | 当前Sparse不执行，后续批停止 |
| Sparse/配对失败 | 整次抛错，不交付部分记录；已发生的Dense观察保留 |
| 最终整体指纹核验失败 | 不交付结果，即使各批曾完成；保留执行报告 |
| 空任务 | empty/records=[]/请求0，用量状态no_requests |

最终EncodingResult还核对完整ID唯一/知识库/文档版本、模型/表示/分词身份、维度、各批范围/batch_index与输入指纹。input_fingerprint包含有序输入ID、来源/span/版本、两种文本hash和身份；不只统计条数。

此处的“整次失败”是编码结果交付合同，不是数据库事务，也不会撤销服务端已执行的请求或费用。报告中的completed_batch_count/paired_input_count是执行事实，不表示部分记录已发布到索引。第3.6再讲失败时用量与时限。

## Debug Test入口

正常：`tests/test_batch_processor.py::test_success_pairs_by_id_and_restores_input_order`，无参数。此测试用5项/3批验证同一机制，C1–C5输出顺序和batch_index=[0,0,1,1,2]。Test Explorer→Debug Test，在第52行入口断点；F11到process，F10到_preflight返回后，看inputs的ID与batches的ID列表。可F5到batch_processor.py:99，然后F11进入_pair。

选择_pair栈帧：第54行后观察list(by_dense)、list(by_sparse)，先后顺序可能与batch不同；第55行后看wanted；第60行后看item.item_id、sha、row.item_id，确认按ID取得两路。第64行执行后records才新增一个；Shift+F11回process，第100行执行后再看len(records)、observations.data['paired_input_count']。观察现成变量，不重新调用process/编码函数。

错误hash：`tests/test_batch_processor.py::test_pairing_faults_do_not_return_partial_records[dense-hash]`，精确参数ID=dense-hash。第192行故障包装把一个Dense input_hash改成合法格式但错误的64位0；第203行调用process。_pair第61–63行发现与embedding_text_sha256不同，抛encoding_pairing_failed；process第109–113行捕获并转EncodingJobError，pytest.raises捕获，测试通过。报告保留人工Dense用量7，无records。

第二批缺记录：`tests/test_batch_processor.py::test_second_batch_failure_stops_third_and_keeps_usage[pairing]`，精确参数ID=pairing。第95–98行包装Sparse，第二批返回rows[:-1]；wanted与by_sparse键集不同，在_pair第56–57行失败。测试第101–106行证明只调用2批Dense/Sparse，第3批不执行，前1批完成、2项已配对，但异常没有records。

上述正常/故障均使用现有Dense/Sparse测试替身，BatchProcessor/结果/报告合同是真实实现；测试输入来源是合成字段，不冒充原文IO证明。finalize来源篡改另由test_encoder_cannot_reassign_source_identity_after_preflight验证。

## 实际接线验证

```sh
.venv/bin/python -m pytest -q \
  tests/test_batch_processor.py::test_success_pairs_by_id_and_restores_input_order \
  'tests/test_batch_processor.py::test_whole_preflight_failure_makes_no_calls[last-hash]' \
  tests/test_batch_processor.py::test_pairing_faults_do_not_return_partial_records \
  'tests/test_batch_processor.py::test_second_batch_failure_stops_third_and_keeps_usage[pairing]' \
  tests/test_batch_processor.py::test_empty_is_no_requests_not_zero_tokens \
  tests/test_batch_processor.py::test_input_snapshot_survives_callers_mutation \
  tests/test_batch_processor.py::test_encoder_cannot_reassign_source_identity_after_preflight \
  'tests/test_batch_wiring.py::test_real_pipeline_produces_72_pairs_with_no_network[labeled_case]'
# 14 passed in 1.19s
```

最后一项使用真实Loader/M2/输入准备、BatchProcessor、Dense/Provider/SDK、真实jieba，HTTP由MockTransport返回人工反序向量；12文档/72片段/12完整用例→72对，测试配置每批2项，所以模拟HTTP36次；模拟usage每次2、合计72，不是真实服务token。输入原文保持、JSON往返与Provider由调用方关闭都核对。模型真实请求0，不写向量库/BM25索引。

L1已有BatchProcessor/EncodedRecord/EncodingResult；L2真实预检/计划/配对/最终核验；L3本次14项测试覆盖实际输入到成对结果，主摄取调用已沿源码核对。无源码/依赖/真实.env/运行配置/原索引修改，构建不适用，不跑全量；git diff --check退出0。

## 学习证据与唯一下一步

3.5已讲解，助手完成3项探针与14项定向验证；用户理解待反馈，本人独立调试/实现未评估。下一节3.6：超限、整次失败与真实用量，区分实际请求、已知/未知用量、超时和硬截止，收束第3章。
