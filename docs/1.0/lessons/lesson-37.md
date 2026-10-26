# Lesson 37：阶段B·5.8 跨文档补读与再次检索

> 2026-10-25。目标：区分搜索候选、按ID读片段、按实际行号读原文、查看已有关系，以及未来Agent的补查判断。沿Spec0039和当前源码学习，不新增Agent循环。

## 场景与四种动作

教学示意：新L2修改某个开关，首次搜索命中历史L2的一段说明，但尚缺旧用例的前置条件和依赖模块的规则。应按缺口选择动作，而不是把所有不足都变成再做一次向量搜索。

| 已知信息与缺口 | 当前入口 | 结果 |
|---|---|---|
| 知道片段ID，要完整片段 | KnowledgeReader.read_chunk | 固定版本的完整Chunk及元数据 |
| 知道文档ID与实际行范围，要邻近正文/一段原文 | KnowledgeReader.read_lines | 同版本原文、SourceSpan、路径和SHA |
| 知道文档ID，要找已登记的引用/用例配对 | KnowledgeReader.related_documents | 双向关联边及出处，不返回关联文档正文 |
| 不知道相关材料在哪里，或需要换关键词/概念找遗漏 | HybridSearch.search | 新的一次查询准备、召回、融合；上层完整证据入口还有重排和打包 |

一次检索本来就可以命中多份文档；多轮检索是根据缺口发起新的查询。关系导航是第三种机制。它们可以配合，但不能互相等同。

## 实际数据流与合同

```text
HybridSearch.search(question)
  → QueryPipeline.prepare → PreparedQuery（版本、范围、查询编码）
  → Dense/Sparse → RRF → HybridResult（prepared、hits等）
                              │
                              ├─ read_chunk(prepared, chunk_id)
                              ├─ read_lines(prepared, document_id, ...)
                              └─ related_documents(prepared, document_id, ...)

未来知识库Agent：读结果 → 判断缺口 → 选择上面动作或新查询 → 判断是否继续
```

上图最后一行是职责设计，尚未实现正式Agent循环。当前Reader的公开方法由显式库调用/测试消费；ResponseBuilder另调用reader._bundle进行来源核验。RetrievalPipeline不会自动依次调用三个补读方法。

`prepared`是内部PreparedQuery对象，不是最终证据JSON。它带实际active、完整范围内document_ids/chunk_ids及内部查询编码。read_chunk检查的是范围内全部chunk_ids，不是只允许本次top_k或最终装入上下文的ID。已知、同范围的omitted片段ID也可以另行补读。

以下是库级调用形状，变量由现有查询装配产生，非独立可运行示例：

```python
found = search.search(question)
prepared = found.prepared
hit = found.hits[0]  # 调用方先处理无命中分支
full = reader.read_chunk(prepared, hit.chunk.id, max_characters=10000)
links = reader.related_documents(prepared, hit.chunk.source_ref, max_links=100)
span = hit.chunk.metadata['body_span']
excerpt = reader.read_lines(
    prepared, hit.chunk.source_ref,
    start_line=span['line_start'], end_line=span['line_end'],
    max_characters=10000,
)
```

10000/100只是示意调用预算，并非本课新增默认参数或推荐最优值。返回full为{active,chunk}；excerpt为{active,document_id,source_path,source_sha256,span,text}；links为{active,document_id,relations,omitted_by_scope}。完整ID实际是doc-/unit-加64位十六进制值，不能把示意短名直接传给接口。

最终证据JSON没有内部PreparedQuery。未来MCP如何保存/引用查询上下文、如何暴露读取入口仍需适配层设计；目前不能把输出JSON直接当reader参数，也不应让外部任意构造PreparedQuery充当访问凭据。

## 关键函数一：固定版本读取

`query/knowledge_reader.py:34–47`：

1. 校验PreparedQuery并复制，要求active存在。
2. 从prepared.active.version.bundle_id加载资料包，不重新选择catalog/latest。
3. 核知识库、文档/片段数量、来源指纹、模型/表示/分词身份及维度。
4. validate_prepared_scope核文档集合属于包，且chunk_ids恰好是这些文档的完整片段投影。
5. 返回prepared与bundle给三个读取方法。

因此活动指针切至G2后，已有G1 PreparedQuery仍读G1资料包。原始Markdown目录离线也可读已保存原文；不读.env，不调用Embedding或Chroma/BM25 SDK。读取仍有资料包IO和完整性校验，并非零成本单行数据库查找。文件缺失/损坏明确失败。

再次search会重新prepare/选择活动版本；expected_revision是检查当前修订是否符合预期，不是历史版本选择器。G2已经激活时，指定G1 revision不能通过它搜索旧版。未来跨轮版本一致性策略需上层显式处理；当前不声称整个多轮任务自动固定G1。

## 关键函数二：实际行号怎样取原文

`read_lines`第63–78行：校验文档ID、正整数起止/预算、start<=end，确认文档在当前范围；随后根据摄取时保存的line_starts换算字符区间。

教学手算，保存原文为：

```text
第1行 # 模块\n
第2行 \n
第3行 正文A\n
第4行 正文B\n
```

line_starts=[0,5,6,10]。读第3到4行时start=starts[2]=6，end=len(doc.text)=14；切片doc.text[6:14]得到`正文A\n正文B\n`。行范围两端都包含，字符切片右端不包含。LF/CRLF/CR由保存原文位置处理，不统一替换换行再套旧行号。

空文档只有1..1合法，返回text=''、span=None。行号越界、倒置、0/bool不是有效请求。表头手写行号过期时，Reader不会理解标题并自动校正；合法但错误的范围仍会读到那个位置。优先使用本版本实际body_span/结构定位，并核来源SHA。

## 关键函数三：关系是候选线索

`related_documents`第80–91行扫描已保存edges，查询文档出现在from或to都算关联；两端必须都属于prepared.document_ids。范围外的边只增加omitted_by_scope，不泄露其端点和正文；合法边按edge_id排序。

边的kind包括markdown_link与filename_pair。共同保留两端文档ID/SHA；显式链接保留quote/source_span/原目标等，名称配对记录derivation规则及路径，不伪造一段原文引用。具体关系生产机制沿Lesson18。

例如L2→L1只说明原文引用存在；不能推出L1所有内容都需要精读，也不能推出两个历史需求互相覆盖或替代。即使没有显式边，也可能有相同功能的历史L2，需要根据内容再搜索。当前不自动多跳、不返回关联文档正文、不按关系改召回排序。

scope只含L2时，指向其他文档的边被过滤，可能relations=[]但omitted_by_scope>0。内部共享知识库的scope是检索范围，不是本期用户权限；Reader仍遵守调用方确定的范围，不自行扩大。若需要扩大，调用方须显式组织新的请求。

## 正常、超限与失败地图

| 情况 | 当前返回或异常 |
|---|---|
| 完整片段在范围内，预算足够 | {active,chunk}，包括用例全部字段/上下文 |
| 合法实际行范围，预算足够 | 保存原文切片及真实定位 |
| 没有范围内关系 | relations=[]；可能带omitted_by_scope计数 |
| ID格式/行范围/正数限额不合法 | QueryJobError(query_invalid_request) |
| 文档/片段在范围外，或范围投影被篡改 | QueryJobError(query_invalid_scope) |
| 正文字符数、关系数量或整个读取JSON超限 | StorageError(document_limit_exceeded) |
| 资料包IO/完整性失败 | StorageError，不伪装成空内容 |

read_chunk/read_lines的max_characters检查正文；_bounded另以StorageSettings.max_bundle_bytes核整个JSON。max_links超限整次失败，不只返回前N条。ResponseBuilder是从多个候选选择能放入的整条；Reader是明确读取指定对象，失败时不能假装已经给出完整对象，两者职责不同。

## Debug Test与关键观察

在VS Code Test Explorer选择下列测试的Debug Test；测试夹具准备部分已学，可F5到Reader生产边界后用F10/F11/Shift+F11走。

1. `tests/test_knowledge_reader.py::test_complete_case_and_actual_lines_without_sdk_or_latest`（无参数ID）。测试24行调用read_chunk；断点knowledge_reader.py:40，选择_bundle栈帧，执行后看version.bundle_id、len(bundle.chunks)；第58行观察chunk_id in prepared.chunk_ids；第60行执行前chunk已产生，看chunk.metadata['kind']、chunk.text[:80]、len(chunk.text)。返回测试帧25行看result['active']['revision']。第74行断点走read_lines，看start_line/end_line、start/end，执行切片后看text[:80]和span。不要在WATCH重跑read方法。
2. `test_scope_never_follows_references_automatically`（无参数ID）。测试51行只选择L2_A。断点Reader第87行，选related_documents栈帧，看ends<=scope、omitted、len(included)。返回测试54行核relations=[]，接着第56行读取另一文档，在Reader67行抛query_invalid_scope，由pytest.raises捕获，测试仍通过。
3. `test_read_budget_is_explicit_not_silent_truncation[chunk]`。测试64行max_characters=1；Reader60行len(chunk.text)>1抛document_limit_exceeded，测试63行捕获。对应[lines]/[links]分别覆盖正文和关系上限，断点76/89行。
4. `test_new_active_and_removed_sources_do_not_rebind_reads`（无参数ID）。测试86行实际激活G2、87行移开原目录；88行传旧ready。读后测试帧看new.revision=2、result['active']['revision']=1，核全文仍等于旧包。

单测使用已有编码/Chroma替身；真实Bundle读写、范围检查、行定位和SQLite版本切换执行。第一个测试将ChromaStore.audit/BM25Store.audit/catalog.read替换成pytest.fail，证明读取未触碰它们；故障测试test_missing_bundle_io_failure_is_not_empty在BundleStore.load替身抛错，Reader不吞掉错误。

`tests/test_knowledge_reader_wiring.py::test_native_hybrid_to_reader_in_another_process[normal]`另验证实际原生Chroma/BM25、Hybrid→序列化结果→新进程Reader。其他参数为[zero]/[all-empty]/[mixed]。源目录移开，读取进程禁QueryEncoder、SDK、catalog、.env及外部网络，比较全部存储文件字节和mtime保持。Embedding HTTP为MockTransport，真实模型请求0。

## 本次验证与进度

```sh
.venv/bin/python -m pytest -q tests/test_knowledge_reader.py tests/test_knowledge_reader_wiring.py
# 23 passed in 20.96s
```

L1：KnowledgeReader与三种读取方法存在；L2：实质范围/来源/预算及错误处理由源码和测试核验；L3：原生Hybrid结果在新进程被读取，实际行与完整用例对应，同版读取不依赖原目录/模型/SDK重启。仅本模块定向验证，不重跑历史全量2151项。

只维护学习文档，无产品源码、真实.env、运行配置、依赖或原索引修改；构建不适用，不运行全量套件。定向测试不证明真实业务质量/生产性能，也不代表用户独立调试能力。

5.8讲解覆盖；用户理解待反馈，独立调试/实现未评估。第1–5章共29/34节已讲解，余第6章5节。唯一下一步：6.1检索质量、回答质量与工程质量。
