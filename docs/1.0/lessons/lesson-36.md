# Lesson 36：阶段B·5.7 完整证据、预算与引用

日期：2026-10-25。第5章共8节，本节第7节。目标：沿重排ID绑定原文/定位/版本，理解原子片段打包、引用编号、字符/JSON双预算与空态/错误；只学习现有实现，不补问答层或改预算策略。

## 输入输出：模型分数怎样回到原文

输入RerankResult.hits只列rank/chunk_id/score，完整候选仍在ranked.hybrid中。ResponseBuilder不使用模型生成正文，而是按ID取已验证Chunk，再与固定Bundle中的原件逐项核对。

```text
RetrievalPipeline.query
  → HybridSearch.search
  → CoreReranker.rerank
  → ResponseBuilder.build
      → 校验RerankResult及配置
      → KnowledgeReader._bundle(prepared)：固定包/身份/范围
      → 比较所有融合候选与保存Chunk的正文、元数据
      → 按重排次序构造证据与来源分数
      → _render后核上下文字符预算，整条加入或略过
      → 生成最终JSON并核UTF-8字节预算
      → 返回证据字典
```

最终结果顶层为schema_version、status、answerability、active、query_sha256、context_text、evidence、omitted、observations。没有最终自然语言答案；answerability当前始终unknown，不能从retrieved或空结果推断能否回答。

每条evidence保留：citation_id、原重排rank、document_id、chunk_id、source_path、source_sha256、body_span、body、contexts、kind、retrieval。active中保存共同工程版本/修订，source_sha256标识各文档内容；不是单靠文件名表示版本。retrieval有Dense距离/score、两路名次、BM25统计模式、RRF分数/原名次/k、重排分数和score_kind；无某路命中时对应原分数为None，不伪造0。

输出不带内部dense_vector、embedding_text、query_terms；保留实际编码/重排报告和配置，以解释工作量与排序。知识正文是本来要返回的证据，不能把“不输出内部向量”理解为可以省略材料访问边界。HTTP/MCP入口仍属后续阶段。

## 来源核验与引用边界

builder第47行reader._bundle只消费prepared.active.version.bundle_id，不重选latest、不再检索/调用模型，也不要求原始Markdown目录仍在线。固定包重载会执行既有完整性检查，reader进一步核KB/计数/来源指纹/模型与分词身份/范围投影。

第49–51行逐项对比融合候选与保存Chunk的to_dict，涵盖全部正文和metadata；不只检查ID格式存在，也不只核最终选中项。结构上合法但不等于保存原件的候选会报evidence_source_mismatch。

来源对应关系由现有测试明确断言：

```python
evidence['body'] == chunk.text
evidence['body'] == document.text[start_char:end_char]
evidence['source_sha256'] == document.metadata['source_sha256']
```

body_span是摄取解析生成的真实位置，不以文档头部手写行号为准；定位对应这个SHA的已保存文档。原文件之后编辑/行号移动，不会让旧证据变成新版文本，调用方应同时看版本和SHA。行号机制沿2.2，不在本节重讲解析器。

引用存在且能定位，证明来源绑定；它不证明未来LLM的某个主张被证据支持。后续问答层若生成答案，还要另验引用与主张的关系，当前没有自动生成或语义引用支持判定。

## _render怎样计算上下文

response/builder.py:25–28：

```text
[E1] 相对来源路径 L起始行-L结束行
标题/维度/表头等contexts文本
完整Chunk正文
```

context_text由已选证据渲染块用两个换行连接。因此预算不仅算body，还算引用头、路径、上下文和块间分隔。这里“完整”指当前原子Chunk及其结构上下文，不代表整份Markdown或已经收齐本需求全部跨文档知识；普通正文仍是分块。

citation_id按本次实际选中顺序生成E1/E2；不是全库永久ID。rank保留重排名次，跳过前两条时，首条输出可以是citation_id=E1、rank=3。跨请求引用应结合chunk_id/source_sha256/active，不能只保存E1。

## 上下文预算：装不下整条略过，继续往后试

第67–70行：

```python
rendered = _render(evidence)
needed = len(rendered) + (2 if parts else 0)
if characters + needed > cfg.max_context_characters:
    omitted.append({'chunk_id': uid, 'reason': 'context_budget'})
    continue
selected.append(evidence)
```

首次无分隔费，之后每块加2个换行字符。characters是已装入的总长度；候选先构造再核长度，超限不截body、不剪单元格，不加入parts/selected，而是记omitted后继续处理下一条。当前是顺序贪心，不是全局最优背包或保证业务证据覆盖的算法。

本轮实际合成探针：复用已有临时测试夹具和正式Builder，人工评分把渲染较长的候选排前（无真实模型相关性含义）。三条完整渲染长度为70、52、48；全部打包为174字符，包含两处2字符分隔。

```text
预算48：
rank1，70字符 → 略过，记context_budget
rank2，52字符 → 略过，记context_budget
rank3，48字符 → 完整保留，citation_id=E1

status=retrieved，context字符48，omitted2，answerability=unknown
```

探针逐条核保留body等于预算前原文。预算1时全部略过，status=no_evidence_fits、evidence=[]、omitted3；这是有候选但装不下，不是检索失败或问题无答案。打包不再补读/重排/召回更多候选；省略的重要证据如何补查在5.8讨论。

## 整个JSON预算：另一种单位、另一种失败

| 配置 | 计算对象与单位 | 超限动作 |
|---|---|---|
| max_context_characters | len(context_text)，Python字符数 | 整条略过并记录，可返回其余 |
| max_response_bytes | 最终完整JSON.encode('utf-8')长度 | EvidenceError(evidence_response_limit)，整次无成功响应 |

字符不是UTF-8字节，也不是模型token。中文开关为2字符、6个UTF-8字节；模型token数量取决于其tokenizer，当前配置不冒充LLM上下文token预算。

完整JSON还含evidence正文/contexts（与context_text可重复）、来源/定位、omitted及observations。探针一次完整结果context174字符，JSON8039字节（包含当次追踪/报告，非固定大小承诺），直观看出两者不等价。即使上下文装得下，也可能整体响应超限。

builder第77行使用ensure_ascii=False、紧凑分隔符、allow_nan=False序列化，然后核UTF-8长度；超限不会静默删metadata/observations、截JSON或返回部分evidence。错误保留已知安全观察信息，不携带半份成功证据。

## 状态与失败地图

| 情况 | 当前结果 |
|---|---|
| 至少一条完整证据装入 | status=retrieved，omitted可非空 |
| ranked.hits非空，但一条都装不下 | status=no_evidence_fits |
| ranked.hits合法空 | status=empty |
| 固定包读失败/身份或范围核验失败 | EvidenceError(evidence_read_failed) |
| 候选与保存原件不一致 | EvidenceError(evidence_source_mismatch) |
| 完整JSON超过字节上限 | EvidenceError(evidence_response_limit) |

三个成功状态的answerability均unknown。来源/格式/预算合格不等于检索业务质量通过，也未新增引用正确性模型评判。

## Debug Test：正常来源 → 字符预算 → JSON上限

### 原文绑定与字段

入口`tests/test_evidence_response.py::test_all_sources_citations_and_actual_spans`，无参数ID。Test Explorer点Debug Test，测试21行进入builder.build；可F5到response/builder.py:45跳过此前已学召回/重排。

第49行后saved已产生，选build帧观察len(chunks)、len(saved)、prepared.active.revision；第50行比较完整候选。进入55–66循环，第57–66行完成后evidence才产生，看evidence['chunk_id']、evidence['source_path']、evidence['body_span']、evidence['body'][:80]，不用展开整个原包。

回测试28–32行，选择测试帧观察span和doc；执行到31行核body==保存doc.text切片，32行核SHA。测试35行核最终JSON没有内部向量/编码文本/查询词项。夹具Chroma/编码/评分为替身，Bundle/BM25/SQLite与Builder来源核验真实执行；材料为合成，不是用户真实资料。

### 字符预算走分支

`tests/test_evidence_response.py::test_context_budget_counts_rendering_and_does_not_cut_rows`，无参数ID。测试44行把本测试对象预算设1，45行调用build。Builder第67行执行后看len(rendered)、needed、characters、cfg.max_context_characters；到第69行所有候选记omitted/continue，第70行不执行。最后第71行status=no_evidence_fits，回测试46–47行检查空正文与省略数量。

该测试还覆盖预算恰等于完整context时全保留，以及较小预算下已保留body不截断。课堂另用70/52/48探针明确观察“前两条略过、第三条保留”；不把探针名单冒充这个测试的原始排序。不在WATCH重跑build，因为会重复读包与记录耗时。

### JSON超限与已知观察

`tests/test_evidence_response.py::test_whole_json_limit_is_not_context_limit`，无参数ID。测试60行设max_response_bytes=10，61行build。正常打包后Builder第77行发现全JSON过限，78行抛EvidenceError；pytest.raises捕获，所以测试通过。error.observations['rerank']仍等于原报告，但无error.evidence。

### 来源变更与版本切换

`test_stored_source_audit_rejects_valid_but_changed_chunk`给同一候选及两路副本都加入合法结构字段，使DTO结构检查通过，但保存原件未变；Builder第50–51行实质比对拒绝，不能只凭to_dict合法判来源正确。

`test_activation_during_rerank_keeps_original_evidence_snapshot`在评分替身hook中实际激活新版，Builder仍读旧prepared.active的包，响应active与证据保持旧版。当前单次逻辑快照沿4.4；没有长时间数据库读锁，也没有自动切到最新内容。

## 本次实际验证

```sh
.venv/bin/python -m pytest -q tests/test_evidence_response.py \
  'tests/test_core_app.py::test_cli_real_assembly_sdk_and_native_indexes[query]'
# 12 passed in 13.34s
```

另有临时合成探针，复用test_document_manager.prepared/test_query_preparation.job及native_query夹具、CoreReranker和正式ResponseBuilder；人工按render长度评分以固定分支。首次macOS默认临时路径含符号链接，被既有StorageSettings拒绝（invalid_storage_settings），尚未建库；只把探针路径改成Path(directory).resolve()后通过，未放宽生产规则。实际输出：

```text
full: evidence_count3, context_characters174, response_utf8_bytes8039
rendered_sizes_in_rank_order: [70,52,48]
packed: budget48, status=retrieved, context_characters48,
        citations=[('E1',3)], omitted_count2, answerability=unknown
budget_1: status=no_evidence_fits, selected0, omitted3
```

CLI用真实原生Chroma/BM25/SQLite与实际SDK+MockTransport，源目录移开后新进程query返回完整证据；Embedding/重排两次模拟HTTP，不调用真实服务。单测/探针是FakeClient与评分替身，不冒充原生ANN质量。已知服务报告为合成数据，真实外部模型请求0。

L1 ResponseBuilder/EvidenceSettings/入口已存在；L2实质原文核对/引用/完整片段及双预算；L3由12项与探针覆盖来源/边界/版本及原生消费者。只维护学习文档，无源码/依赖/真实.env/运行配置/原索引修改；构建不适用，未跑全量，git diff --check退出0。真实知识库质量、主张支持判定和生产性能不在本次验收内。

## 学习证据与唯一下一步

5.7已讲解，助手核源码/临时探针/测试；用户理解待反馈，本人独立调试/实现未评估。讲解覆盖28/34节，余6节（第5章1节、第6章5节）。唯一下一步：5.8跨文档补读与再次检索，区分read_chunk/read_lines/related_documents和新增检索，明确核心与上层Agent边界。
