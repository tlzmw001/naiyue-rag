# Lesson 11：阶段B·1.3 查询输入与结构化证据输出

日期：2026-10-20。目标：知道如何调用正式检索入口，以及结果中的身份、版本、定位、正文和引用各自负责什么。RAG概念按初学者解释，算法细节仍留在对应章节。

## 输入合同

实际签名为`RetrievalPipeline.query(query, *, scope_document_ids=None, exclude_document_ids=None, expected_revision=None)`，知识库通过构造时的组件/配置绑定，不是本函数新增的参数。

- query：非空字符串，当前按原问题准备编码；“只查某文档”的自然语言不自动变为过滤条件。
- scope_document_ids：None表示全部已纳入的文档，[]表示显式空范围；非空列表须提供真实文档ID，不接受把路径当ID。
- exclude_document_ids：从scope确定的集合中排除；None相当于不排除。未知/重复/非法ID明确失败。
- expected_revision：可选的当前活动修订检查，不是要求读取任意历史版本；不符则拒绝，防止列表/详情读取后活动版本已变而静默换用。
- top_k、后端和预算由已有组件配置提供，不是这个query函数的额外参数。

## 输出地图

ResponseBuilder.build返回字典，顶层为schema_version、status、answerability、active、query_sha256、context_text、evidence、omitted、observations。

| 字段组 | 作用 |
|---|---|
| status/answerability | 执行/打包结果与是否有足够依据回答分开；当前answerability固定unknown |
| active | 本次使用的活动revision及完整版本描述，包括知识库、资料包、双索引身份 |
| evidence | 机器可消费的结构化证据列表 |
| context_text | 从同一批已选证据渲染出的带引用上下文，不是生成回答 |
| omitted | 因上下文预算放不下而跳过的片段及原因，不代表全库所有未返回内容 |
| observations | 编码、检索、重排及打包等已核对报告，不是答案可信度 |

## 身份与版本

- document_id：同一知识库/相对路径的稳定文档身份；不是文档内容版本。
- chunk_id：片段身份，用于跨编码、召回、排序和回取绑定；使用时结合版本，不假定跨修订不变。
- source_path：便于人查找原始Markdown，相对知识库根目录。
- source_sha256：来源文件原始字节的内容指纹；用于约束定位所对应的原文版本。
- active.version：这次知识库资料包、向量索引与BM25索引的组合版本；active.revision是活动记录修订号。
- citation_id：E1/E2等，仅在本次响应中标记引用；不是永久文档或片段ID。

修改B而路径不变时文档ID保持、内容指纹通常变化；B的新片段归入新版本。查询/后续补读必须保持选定版本一致。

## 真实保存样本及位置

读取历史合成GLM实验产物`data/research/spec0042-evidence/quality-glm-01/Q1.evidence-current.json`。不是本次新请求：status=retrieved，answerability=unknown，active.revision=1，knowledge_base_id=core-demo。

TC-01证据：citation_id=E3，rank=3，source_path=L2_previous_测试用例.md，body为完整用例行。body_span为start_char=113、end_char=198、line_start=9、line_end=9；上下文包含文档标题、测试维度、列名与表格分隔行。

本次纯读取核对：保存原文`text[113:198] == evidence['body']`为True；当前合成文件字节SHA与证据source_sha256一致为True。字符区间是0起始、右端不含，行号是1起始、结束行包含；字符位置不是UTF-8字节位置。每个contexts元素亦有自己的来源span。文档表头人工标注的行号不替代这些实际位置；文件被再次修改后不能直接套旧span。

该样本的Dense第7、Sparse第10、RRF第9、重排后第3，属于历史单题结果；不同阶段rank与不同算法score不可混为同一刻度，更不等于业务正确概率。

## 正常、空态和失败

| 情况 | 对外行为 |
|---|---|
| 选出了证据 | status=retrieved；answerability仍unknown |
| 没有排序候选 | status=empty；具体准备/检索情况看报告 |
| 有候选但没有完整证据能放进上下文预算 | status=no_evidence_fits，omitted标context_budget |
| 参数、来源核对、网络/索引或整个JSON上限失败 | 抛对应异常，不构造伪成功证据 |

## 生产代码与测试入口

- `query/retrieval_pipeline.py::RetrievalPipeline.query`：原始问题传给search，结果传给reranker，再交给builder。
- `query/query_processor.py::QueryProcessor.process`：校验问题、ID列表与revision；没有IO或模型调用。
- `response/builder.py::ResponseBuilder.build`：回核已保存片段、生成引用、预算选择、返回响应。
- `tests/test_evidence_response.py::test_all_sources_citations_and_actual_spans`：核对所有引用、原文切片、内容指纹、上下文与排序来源。外部编码/评分和Chroma原生边界使用确定性替身，实际查询、BM25、证据构建与来源核对仍执行；不证明真实服务质量。

VS Code Test Explorer选择该测试的Debug Test。建议F5到`raw=builder.build(ranked)`所在行，以F10执行后停在断言；当前测试栈帧观察`raw['status']`、`raw['evidence'][0]['source_path']`、`raw['evidence'][0]['body_span']`，变量raw只在赋值完成后产生。后续F5到循环体观察e、span、doc，再比较`doc.text[span['start_char']:span['end_char']] == e['body']`；纯切片观察没有IO副作用。框架/fixture内部暂不展开；异常分支留在1.4。

## 本次验证

命令：`.venv/bin/python -m pytest -q tests/test_evidence_response.py::test_all_sources_citations_and_actual_spans`。

实际输出：`1 passed in 1.91s`。只运行这一项确定性合同测试，未重跑全量、未调用模型；`git diff --check`退出0。历史模型产物的纯读取/切片核对不是本次真实模型运行。

## 理解证据与下一步

本节讲解与助手测试/来源核对，不代表用户已调试或掌握；用户理解待反馈，独立能力未评估。文档级增量编码已按用户要求记入future-work，尚未实施。

下一节1.4：用现有确定性测试走正常、空结果与失败的分支，核对返回和异常如何传播。
