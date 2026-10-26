# Lesson 35：阶段B·5.6 LLM与CrossEncoder重排

日期：2026-10-25。第5章共8节，本节第6节。目标：区分RRF名次融合与模型重排，沿固定候选输入、两类评分后端、严格ID映射、预算和失败分支学习现有实现。只维护课堂，不调真实模型、加载实际CPU权重或变更配置。

## 重排解决什么

RRF只使用各路名次，不能读懂片段是否真正说明本次问题的条件/边界。重排让模型重新读取问题与已召回候选，给相关性评分，再排序/取top_k。它仍可能判断错误，不等于事实校验、需求生效判断或回答生成。

```text
HybridSearch → HybridResult（固定候选、同一快照）
  → CoreReranker：取原问题、构造完整候选、预检数量/字符
  ├─ disabled：按RRF原序截top_k，score=None
  ├─ enabled但无候选：empty，不调用score
  └─ enabled且有候选：backend.score(query,candidates)
       ├─ LLMReranker：一次Chat评分请求
       └─ CrossEncoderReranker：每条query/passage成对编码预测
  → 核所有候选恰好一项有限数值分数
  → 按新分数排序，同分保持原RRF次序
  → RerankResult → 后续ResponseBuilder（5.7）
```

只重排已有候选；两路均未召回的片段无法补回。查询编码/索引不变、没有新的搜索循环，核心仍独立于Agent/MCP。

## 输入输出形状

CoreReranker取hybrid.prepared.encoding.input.retrieval_text作为query，不加Embedding的query_prefix；候选text由Chunk.metadata.contexts的文本和retrieval_view.text换行拼接，保持整行用例/结构上下文。重排不是只看标题，也不把Chroma的score作为候选正文。

```python
query = "关闭 cvr_ltv 后哪些历史行为需要回归？"
candidates = [
    {"passage_id": chunk_b_id, "text": "标题/维度上下文\n候选B检索视图"},
    {"passage_id": chunk_c_id, "text": "标题/维度上下文\n候选C检索视图"},
    {"passage_id": chunk_a_id, "text": "标题/维度上下文\n候选A检索视图"},
]
```

这是接口示意，变量代指真实chunk.id，不是文档ID。后端输出scores列表，每项仅passage_id/score；例如人为赋B0、C1、A2，则重排A→C→B，top_k2输出A/C。此例与测试Backend按输入序号评分的机制一致，不是模型语义表现或真实材料结果。

返回RerankResult保存原hybrid副本、settings、provider/model、全部scores、选中hits(rank/chunk_id/score)、report。模型不返回新正文；最终证据仍从固定来源绑定，模型生成内容不能替换原文。

top_k只决定评分后保留数量；例如10候选/top_k5仍要给10条都打分，再保留5条。启用且只有1个候选仍调用后端。缺失/重复/未知ID、bool/NaN/嵌套分数、额外text字段等都会拒绝，不以列表位置代替LLM返回的ID配对。

## LLM评分机制与实际接线

LLMReranker把query和完整passages列表编码成JSON，作为user内容；system提示其仅做证据相关性评分，不调用工具、不生成答案、不改写片段。所有候选一起进入当前唯一一次请求，可利用需求/依赖/历史用例等语义，但JSON合法不保证排序质量。

源码reranking/llm.py使用OpenAI兼容Chat Completions接口（不是专用/rerank接口）：配置model/base_url/temperature/max_output_tokens/extra_body；SDK with_streaming_response.create用于有界读HTTP响应，实际stream=False，并非token流式生成。max_retries=0，当前无自动重试。

模型回复形状为{"scores":[{"passage_id":原ID,"score":有限数值},...]}。程序检查HTTP与结束状态、JSON唯一字段、完整ID集合/数量/数值，拒绝新增工具调用/说明/正文等非合同结果。候选作为数据；这些边界限制输出可做的动作，不能宣称提示词或ID校验保证模型永远不被文档内容误导评分。

usage若服务提供合法prompt/completion/total则记录，缺失为None，不估算费用；即使scores坏了，也尽量保留已经解析的有效usage。Embedding报告另保存在原hybrid或错误，重排用量不覆盖它。HTTP timeout/剩余deadline取较小值并在读取前后检查，这是同步IO边界，不是对任意阻塞Python代码的强杀。

## CrossEncoder：问题与片段一起输入

Embedding召回先分别生成问题/片段向量，再算距离；CrossEncoder把每一对(query,passage)共同送入模型，使两侧词项可在一次模型计算中交互，输出相关性标量。这里的一对是问题加一条候选，不是两条候选互相比胜负。

官方[Cross-Encoders说明](https://www.sbert.net/examples/cross_encoder/applications/README.html)解释联合输入及先召回再对候选评分的结构；当前项目的分数域以实际配置与源码为准，不把文档泛例0–1范围强加给项目。

```text
[(query, B.text), (query, C.text), (query, A.text)]
  → 每对用真实模型tokenizer检查完整长度
  → predict(pairs, batch_size=配置值)
  → [s_B, s_C, s_A]
  → 按原输入顺序zip回候选ID
```

它不会产生一份可提前独立存入向量库、与任意问题复用的“片段最终相关性分数”；问题变化后需要重算对应pair。因此一般先用检索缩小候选，再重排，当前不对全库逐对推理。

本机版本核验：sentence-transformers6.1.0、transformers5.20.0、torch2.14.1、openai2.54.0。读取当前安装cross_encoder/model.py:568之后predict主体：preprocess整对、按batch运行self(features)、取scores、应用activation、恢复输入顺序，再输出数组。项目传torch.nn.Identity()，保留原始标量，可为负或大于1；与LLM自评分不横向比较绝对数值，不当概率。

项目reranking/cross_encoder.py先审计本地manifest/文件身份，local_files_only=True、trust_remote_code=False、CPU/批大小按配置；缺模型明确失败，不查询时自动下载。先读取模型自然容量，核max_pair_tokens不过限，再设置max_seq_length，避免配置先覆盖容量后形成自我比较。

## 两层输入预算与完整性

1. Core共有预算：候选数量≤max_candidates；len(query)+全部候选text字符总量≤max_input_characters。不包含所有JSON/提示词开销，不冒充精确LLM token预算；超限在score前整次拒绝，不缩小池或截行。
2. CrossEncoder额外预算：对每对query+text包含特殊标记分词，truncation=False；所有pair预检完成后才predict。任一超过max_pair_tokens就整次失败，前面合法pair也不先推理。字符数与此模型token数不是同一单位。

LLM还有输出token/响应字节与请求时间边界；服务上下文限制仍可能产生明确HTTP错误，不能把共有字符检查当全部上下文保证。CrossEncoder本地运行不产生HTTP请求；report.attempted_requests=0、usage=None，仍有CPU/内存成本，不代表没有执行模型。

空候选不调用backend.score；但app.execute在查询前装配后端，本地模型可能已经加载，因此不宣称空查询整程零初始化成本。关闭重排时app按none分支不装配评分后端，并保持RRF原序截top_k。

## 分支与异常传播

| 情况 | 当前结果 |
|---|---|
| enabled=False | disabled，不调用score，按原序取top_k，分数None |
| enabled=True且无hits | empty，不调用score |
| 有候选且完整有效分数 | success，按分数降序；同分保持原RRF顺序 |
| Core候选/字符或Cross pair超限 | rerank_input_limit，无本次评分调用/预测 |
| LLM HTTP429/超时/坏JSON/结束原因length/ID不全 | 明确RerankError，无自动重试或回退RRF成功 |
| Cross缺权重/预测失败/输出NaN或形状错误 | 明确RerankError，不自动转LLM |

Core第36–40行保留后端已知报告和前序Embedding报告；错误没有部分hits。评分成功也不保证业务正确，最终answerability仍需证据判断；5.7讲来源与预算，完整质量对照放第6章。

## Debug Test：先统一合同，再看两个后端

### Core输入与排序

`tests/test_reranking.py::test_actual_hybrid_rerank_mapping_roundtrip_and_copy`，无参数ID。Test Explorer点Debug Test；在测试37行进入Core.rerank，F5可到reranking/core.py:26跳过已学混合检索启动。

第29行前query/candidates已产生，选rerank帧看query、len(candidates)、candidates[0]['passage_id']、candidates[0]['text'][:100]；这些文本来自已验证contexts/retrieval_view。第31行调用测试Backend（非真实LLM），按序号0/1/2评分。第32行scores/report才存在，观察每个ID恰好一次。

进入core/rerank_results.py::ranked_hits看by_id和ordered：从hybrid原顺序按新分数排序，同分稳定；top_k只在最后切。回测试38–44行核反序选前2、原query/完整候选集合与上下文；hybrid没有被改写、Dense/Sparse编码各仍1次。不要在WATCH重跑backend.score。

### LLM请求与严格返回

`tests/test_llm_reranker.py::test_real_sdk_config_reaches_wire_and_usage`，无参数ID。测试47行score入口→LLMReranker.score。请求构造后选其帧看content（仅本测试合成内容）、ids；响应解析后scores/report.usage产生。回测试49–58行看模拟请求的URL/model/messages/stream=False及20 tokens（12+8），这20是合成响应数字，不是真实服务消费。factory把HTTPTransport替换为受控Transport，保留真实OpenAI SDK与字节读取链。

`test_bad_output_is_atomic_and_usage_is_preserved_when_known[missing]`：模拟遗漏一个ID，validate_scores拒绝；usage已先解析，错误报告仍有模拟20 tokens。`[length]`模拟生成未正常完成，不能把不完整JSON当成功；HTTP429测试核仅1次请求，不重试。pytest.raises捕获后测试通过。

### CrossEncoder成对输入与超限

`tests/test_cross_encoder_reranker.py::test_tokenizer_and_predict_are_real_consumers_of_config`，无参数ID；测试33行进入score，cross_encoder.py第73行后pairs产生，75行后tokens产生，76行核长度；77行调用Model.predict替身，返回[-2,3]，81行按顺序绑定a/b。当前试验的Tokenizer/Model都是替身，不能当真实CPU forward证据。

`test_oversize_is_rejected_before_predict_without_truncation`：测试44行令Tokenizer返回513个ID，配置上限512。score第76行抛rerank_input_limit，未执行77行predict；pytest.raises在45行捕获，46行model.calls==[]。不是截成512后继续推理。真实pair tokenizer与forward历史验收见Spec0043，本次不重跑权重。

## 本次实际验证

```sh
.venv/bin/python -m pytest -q \
  tests/test_reranking.py::test_actual_hybrid_rerank_mapping_roundtrip_and_copy \
  tests/test_reranking.py::test_empty_does_not_call_backend \
  tests/test_reranking.py::test_disabled_and_equal_scores_keep_original_order \
  tests/test_reranking.py::test_limit_is_preflight_before_model \
  'tests/test_reranking.py::test_whole_failure_never_falls_back_or_leaks[unknown]' \
  tests/test_llm_reranker.py::test_real_sdk_config_reaches_wire_and_usage \
  'tests/test_llm_reranker.py::test_bad_output_is_atomic_and_usage_is_preserved_when_known[missing]' \
  'tests/test_llm_reranker.py::test_bad_output_is_atomic_and_usage_is_preserved_when_known[length]' \
  tests/test_llm_reranker.py::test_missing_usage_stays_unknown \
  'tests/test_llm_reranker.py::test_http_fail_no_retry_no_raw_error[429]' \
  tests/test_cross_encoder_reranker.py::test_tokenizer_and_predict_are_real_consumers_of_config \
  tests/test_cross_encoder_reranker.py::test_oversize_is_rejected_before_predict_without_truncation \
  tests/test_cross_encoder_reranker.py::test_bad_predict_is_safe_atomic \
  tests/test_cross_encoder_reranker.py::test_missing_local_model_is_explicit_no_download \
  tests/test_cross_encoder_reranker.py::test_model_capacity_is_read_before_config_can_override_tokenizer \
  'tests/test_cross_encoder_app.py::test_cli_local_backend_whole_chain_and_failure[normal]'
# 22 passed in 15.26s
```

CLI场景用实际app/原生Bundle/Chroma/BM25/SQLite、模拟Embedding HTTP及替换的sentence_transformers.CrossEncoder，验证配置到本地适配器/最终证据的接线；本地权重文件为临时合成内容，不是真实加载。真实服务/CPU模型验收是Spec0041–0043历史记录，本轮只有合同/SDK模拟/适配器接线证据，真实外部模型请求0、实际CPU权重未重跑。未改本项目真实.env或运行配置。

L1 Core/LLM/CrossEncoder及结果合同已存在；L2有完整输入、实际SDK/预测接口和严格输出；L3由上述22项核实际消费者/失败报告，不能替代真实资料相关性通过。仅维护学习文档，无源码/依赖/原索引修改；构建不适用，未跑全量，git diff --check退出0。

## 学习证据与唯一下一步

5.6已讲解，助手核当前代码/已安装框架/官方说明及定向测试；用户理解待反馈，本人独立调试/实现未评估。讲解覆盖27/34节，余7节（第5章2节、第6章5节）。唯一下一步：5.7完整证据、预算和引用，沿RerankResult到ResponseBuilder解释模型分数怎样绑定真实原文，以及完整用例装不下时如何处理。
