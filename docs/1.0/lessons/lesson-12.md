# Lesson 12：阶段B·1.4 正常、空结果与失败的完整链路

日期：2026-10-20。目标：沿真实查询边界区分正常证据、明确空态、预算遗漏和异常传播，并用现有Debug Test观察。第1章共4节，本节收束整体职责地图，不登记用户已掌握。

## 数据流与分支地图

`RetrievalPipeline.query`依次执行search→rerank→build，任一步抛异常且未被恢复，后续步骤不执行；该入口没有将异常转换为空证据的catch。

| 触发条件 | 结果 | 后续动作 |
|---|---|---|
| 候选存在且至少一个完整证据放得下 | 返回status=retrieved、非空evidence | 上层结合任务评估证据 |
| 本节案例scope_document_ids=[] | 准备状态empty_scope，不编码；两路空结果、融合空，关闭重排；最终status=empty | 不证明全库没有答案 |
| 候选非空但上下文预算一个也放不下 | 正常返回status=no_evidence_fits，omitted记context_budget | 可由调用方识别打包原因，当前不自动放大预算 |
| 关键词召回故障 | 抛QueryJobError(stage=sparse,code=bm25_query_failed) | 不进入融合、重排、证据组装 |
| 整个响应JSON超过硬上限 | 抛EvidenceError(code=evidence_response_limit) | 不返回正常证据字典 |

所有正常证据响应answerability仍为unknown。没有活动版本/空索引等其他准备空态在相应模块学习时展开，不能把空结果解释为业务无答案。

## 正常路线

测试`tests/test_evidence_response.py::test_pipeline_is_real_consumer_and_encodes_once`，无参数ID。

`build(job)`先准备builder并跑过一次测试准备链；随后测试清空两个编码替身的calls，才开始本次`pipeline.query(QUERY,expected_revision=1)`。最终非空evidence且文档无须重编码：查询Dense编码、Sparse编码和重排评分各一次。

Debug Test入口：测试第91行；F11进入`query/retrieval_pipeline.py::RetrievalPipeline.query`，可F10完成search、rerank，分别观察`len(hybrid.hits)`和`len(ranked.hits)`；它们只在赋值完成后产生。返回测试第92行后观察`result['status']`、`len(result['evidence'])`、`result['answerability']`。未知模块的内部实现暂用F10跨过，不重新执行query查看返回。

## 空范围路线

测试`tests/test_evidence_response.py::test_empty_states_do_not_invent_answerability`，无参数ID。

准备代码第67行`build(job)`本身有一次正常查询，不能用整个测试的calls判断空范围是否调用模型。实际空范围调用在第68行，QueryPipeline.prepare产生status=empty_scope、encoding=None；两路Retriever返回空集合，RRF为空；本测试关闭重排，报告disabled，最终status=empty、evidence=[]、answerability=unknown、observations.embedding=None。

Debug入口第68行；F5到`query/pipeline.py`的`if status=='ready'`分支，当前prepare栈帧观察`status`、`docs`、`encoding`，预期empty_scope、[]、None。不要把配置关闭重排的disabled误读为后端处理空候选的empty：本例走前者。回测试第70行后观察result的三个字段。

## 候选因上下文预算全部遗漏

测试`tests/test_evidence_response.py::test_context_budget_counts_rendering_and_does_not_cut_rows`，无参数ID。

先正常准备ranked，再将builder的内存测试设置max_context_characters置1，调用builder.build。源`response/builder.py`第68行对整条渲染证据判断预算；放不下则添加omitted并continue。对所有候选继续尝试，最终selected=[]但ranked.hits非空，因此status=no_evidence_fits；不截断表格行。后半段也检验大证据放不下时继续尝试后续较小证据。

Debug入口测试第45行；F11进入build后F5到builder第68行，当前build栈帧观察`cfg.max_context_characters`、`needed`、`len(selected)`；循环结束停第71行，观察`len(ranked.hits)`、`len(selected)`、`len(omitted)`。回测试第46行查看none。1字符仅用于触发确定性边界，不是生产参数建议，不改真实配置文件。

## 关键词召回异常路线

测试`tests/test_hybrid_search.py::test_hybrid_errors_retain_stage_usage_and_never_degrade[sparse]`，参数ID=sparse。

- monkeypatch在测试第104行把`SparseRetriever.retrieve`替换为fail_sparse。
- 故障在测试第102行显式raise StorageError('bm25_query_failed')；没有访问真实BM25故障服务。
- `HybridSearch._sparse`第40行捕获并返回(None,耗时,异常)，这是保留失败信息交给主编排，不是成功空结果。
- `HybridSearch.search`第69–76行汇总两路结果、记录错误、重新抛出该异常；即使Dense正常，也不执行第78行融合。
- 第91行进入`QueryPipeline._fail`，第83行抛QueryJobError，保留stage/code、已选版本、编码用量和错误trace。
- 测试第117行pytest.raises捕获预期错误，第118行取caught.value。实际测试入口是HybridSearch边界；若从完整RetrievalPipeline调用，同一异常沿search抛出，后续rerank/build不执行。

优先Debug Test第117行，F5到hybrid_search第75行，在search栈帧观察`errors[0][0]`、`errors[0][1].code`、`report.status`，预期sparse、bm25_query_failed、success。再F5到query/pipeline.py第83行观察stage/code，再继续到测试第119行：观察`error.stage`、`error.code`、`error.encoding_report.status`。可选F5到测试第102行观察注入点，属于worker栈，不必反复进入线程池基础设施。

这里编码成功、召回失败并不矛盾：SparseEncoder处理问题词项，SparseRetriever读取/查询索引，是不同职责。并行失败不保证另一分支未执行，已发生编码/请求的成本仍需保留。

pytest.raises期望异常发生，因此预期raise被捕获时测试仍然通过；捕获范围内若没抛异常或类型不对，测试才失败。不要把错误对象trace_report.status=error误认为返回了status=error的普通证据响应。

## 整个JSON响应硬上限

测试`tests/test_evidence_response.py::test_whole_json_limit_is_not_context_limit`，无参数ID。max_response_bytes=10仅为测试触发值。builder第77–78行校验整个JSON的UTF-8字节数并抛EvidenceError；它与max_context_characters的上下文字符预算是不同合同。Debug入口测试第61行，F5到builder第78行，返回测试第62行看caught.value.code，预期evidence_response_limit。

## 测试替换与证据范围

查询Dense/Sparse编码、评分后端和Chroma原生client/query用确定性替身；BM25本地链、查询编排、报告、预算和证据组装沿生产实现执行。关键词失败例额外替换SparseRetriever.retrieve为故障函数。没有调用真实模型，也没有用这些测试证明真实资料召回或生产故障恢复。

## 本次验证

```zsh
.venv/bin/python -m pytest -q \
  tests/test_evidence_response.py::test_pipeline_is_real_consumer_and_encodes_once \
  tests/test_evidence_response.py::test_empty_states_do_not_invent_answerability \
  tests/test_evidence_response.py::test_context_budget_counts_rendering_and_does_not_cut_rows \
  'tests/test_hybrid_search.py::test_hybrid_errors_retain_stage_usage_and_never_degrade[sparse]' \
  tests/test_evidence_response.py::test_whole_json_limit_is_not_context_limit
```

实际输出：`5 passed in 5.31s`。本次只维护学习记录，未改源代码/配置、未重跑全量、未新增模型请求。文档检查另见git diff --check。

## 理解证据与下一步

第1章1.1–1.4已讲解，用户理解待反馈；上述测试由助手运行，用户尚未提供本人Debug Test、独立复写或实现证据。不逐回复强制检查题。

下一步第2章第1节（本章6节）：沿一份具体Markdown学习加载如何形成Document，原文、文档身份、内容指纹和读取失败怎样处理。
