# Spec0019：M2第三切片——显式文档引用与需求／用例配对

状态：2026-10-12按用户“继续”完成规范后已TDD实施并接线：54新增测试通过，全量841通过。只验收本机合成结构及批次准备链；尚未持久化/进入新编码、索引、查询或证明检索质量改善。旧A3缓存及检索策略保持，实际结果见第10节。

## 1. 解决的问题与当前调用链

一个历史需求的用例可能需要需求正文、模块导航及其他模块背景。先保存可核对的文档关系，后续才能在命中一份文档后找到可补查的其他文档。这个阶段记录关系事实，不决定哪些关系与当前任务相关，也不自动把所有相邻文档塞入上下文。

实施前通用链为MarkdownLoader.load_all→Document列表；单文档prepare_document→DocumentChunker→ChunkRefiner→MetadataEnricher。原始Document/Chunk具有版本和实际位置，当时新链没有知识库级的关系输出。本片现在增加prepare_knowledge_base→build_document_relations→逐文档prepare_document，M3编码、M4索引及M5/M7消费新关系仍未实施。

已有experiments/relation_index.py:build_index先扫描来源，再建markdown_link和filename_pair；relation_probe→关系缓存build/load→expand→关系候选→融合。这条实验链有真实消费者，继续保留。它依赖旧corpus字典、manifest角色、dataset/knowledge及旧扫描器，不适合让新核心反向导入。复用其已确认规则与测试场景，新核心接M1 Document，不迁移或重写旧缓存/遍历/融合。

Modular参考URL：https://github.com/Jerry-ai-dev/MODULAR-RAG-MCP-SERVER；本机main固定commit f658c5a4011c8b826707a65a3b11ce9301b0626f。2026-10-12只读检查ingestion和core/query_engine相关路径，未见对应本业务的markdown_link/filename_pair模块；这是已检查路径的源码范围，不是对整个仓库不存在关系能力的证明。本片属于已确认的Markdown业务适配，仍位于参考摄取链的结构/元数据之后，不添加图数据库或模型关系抽取。

## 2. 一个具体例子

```text
L2/L2_A.md
  > 前置依赖：[模块](../L1/L1_M.md)

L2/L2_A_测试用例.md
  > 对应需求：[需求A](L2_A.md)

L1/L1_M.md
  - 功能A：[详情](../L2/L2_A.md)
```

输出三个有原文出处的markdown_link；另外记录测试用例→需求A的filename_pair，两种依据独立保留。用例命中后可以找其对应需求，需求可以找到模块背景。当前不执行这次扩展，更不能由共享模块推断另一个历史需求就是回归范围。

## 3. 本片范围与接口

新增两个入口，旧公开签名保持：

```python
build_document_relations(documents) -> dict
prepare_knowledge_base(documents, chunker, *, text_mode) -> (chunks, relations, chunk_diagnostics)
```

documents必须是同一knowledge_base_id的完整输入批次；仅以这批已加载文档建立登记表。可以传小样本，但未在批次中的目标只诊断为target_not_loaded，不能宣称磁盘缺文件。空列表正常返回空关系与空片段，不虚构库ID。相同ID、同路径或跨库混入拒绝；不同路径的相同正文仍是不同来源。

关系属于Document层，不能从带重叠的Chunk反复提取，也不能把Refiner后的派生文本当原文。新知识库装配入口先校验/构建关系，再逐文档调用现有prepare_document；成功返回三份结果。任何文档准备或关系构造失败整次报错，不交付“完整成功”的部分批次。本片仅内存计算，无外部IO、保存成功登记、网络、Agent或权限接口。

## 4. 关系输出与来源合同

关系结果为JSON可序列化dict：schema_version、policy_id、knowledge_base_id、source_fingerprint、nodes、edges、diagnostics。nodes至少含document_id、source_path、source_sha256；fingerprint覆盖按稳定顺序登记的源ID/路径/版本与关系策略。不能让同路径的修订继续冒充旧关系快照。

每条edge包含：edge_id、kind、from_document_id、to_document_id、两端source_sha256、quote、source_span、raw_target、canonical_target、fragment、declaration、derivation。edge_id由种类、两端ID/版本、依据位置或名称依据确定；重复出现的同一链接保留各自位置，不能因为目标相同丢来源。序列化与重复运行结果稳定，输入排序不改变结果。

- markdown_link：quote是完整原链接；SourceSpan来自实际字符/物理行，必须能逐字回读。fragment原样保留但不声称目标章节已验证。
- filename_pair：quote/source_span/raw_target/fragment为null；derivation记录精确后缀规则、两端实际路径及匹配stem。名称规则没有正文出处，不能伪造引文或SourceSpan。
- declaration：只保留明确表头字段的标签及实际位置，如“前置依赖”“对应需求”；其他普通链接为null。标签描述原文声明，不升级为已验证业务依赖。
- metadata.document_info的层级、文档日期、链接方向和检索排名不能替代关系依据。未生成修改/替代/生效关系。

## 5. Markdown链接解析边界

首片沿A3已核的普通同一物理行直接链接范围：[label](relative.md)，包括表头块引用、普通列表及导航表格。复用已安装markdown-it-py的块结构/行map保护代码及识别标题，复用M1 line_starts和已有source_span计算原始位置；不恢复旧扫描器只认识三反引号的局限，不自己实现完整Markdown框架。

实现前已核本机markdown-it-py4.2.0的link/image原生rule及Ruler.at：link会从state.pos解析到结束位置，token没有字符范围；image的alt使用另一个inline state。拟仅在局部解析器的原生rule边界收集原始起止，再调用原生实现，限定当前物理行/root state、排除图片内子解析。该回调的实际调用方是原生inline tokenizer，必要性是保留原文offset；普通token字段/全局find不能可靠区分代码里的样例和重复链接。对代码/图片/HTML token的原文范围只用于遮罩诊断，不添加通用插件注册层或业务回调。parseInline后的原链接须逐字回读，再按本片支持范围判断。块级html_block也不当正文链接，避免注释或HTML中的样例误建边。

红灯复现后补充边界：逐物理行解析之前，整篇原生inline解析须保护跨行代码/图片/HTML范围。记录原生范围的原始quote，并只在所属inline token.map的局部原文窗口中唯一回读；不能唯一对应则保守跳过该段并诊断unsupported_reference，不用全局首个find猜位置。跨行保护覆盖相关物理行，因此同一行的其他引用可能暂不提取；表头明确对应声明若受此保护影响，不能静默认定名称配对一致。此为防止误建边的规则，不扩充跨行链接支持。

围栏及缩进代码、行内代码、图片不建文档边；HTTP/HTTPS链接只记external_reference，不请求网络。纯本文件锚点只记local_anchor，不触发文档扩展。暂不支持参考式、跨行、嵌套目标括号、带title或复杂转义等链接；无法可靠解析时登记unsupported_reference并保留原文，不截成一个看似有效的目标。复杂行内代码无法安全确定边界时整行不建边并给诊断。代码中的链接样例不作为关系。

目标相对来源文档目录做纯路径归一化，仅在输入登记表查找，不打开链接目标、不扫描磁盘、不跟随符号链接。允许../到同库其他目录，但越出知识库根、绝对路径、Windows驱动/反斜杠、协议相对路径、未知scheme、NUL、带query及非法或重复百分号编码均blocked_target。UTF-8百分号解码一次；不能由解码绕过边界。根内无登记项为target_not_loaded；已登记但fragment未核验则保留文档边并记fragment_unresolved。M1负责载入时的实际路径/符号链接边界，关系层不重新开展文件IO。

手写Lxx-Lyy只是文档内容，不用于目标正文定位。本片不校验锚点/章节、不修手写行号、不展开其他用例的复用条件。

## 6. 名称配对与冲突

沿用户已说明及A3精确规则：stem精确以_测试用例结尾，去一次后缀，经NFC规范化后与登记表中唯一同stem的非用例文件匹配，区分大小写。可以从L2目录配到L1文档；目录层级不限制配对。不按近似标题、同模块、日期或共享上级猜配对。

唯一匹配→用例指向来源文档的filename_pair；无匹配missing_pair；多个匹配ambiguous_pair；名称后缀与可核对的用例分类不一致时给diagnostic。当前不依赖manifest中的historical_requirement/module角色，不凭文本分类宣称历史或当前有效。

沿A3冲突策略：首次二级或更深标题之前，明确“对应需求/对应模块”表头链接若不能可靠唯一核对到命名候选，记pair_conflict并停用名称边；可确认的显式链接仍保留。普通“上层引用/前置依赖”链接不与名称配对竞争；正文同样文字也不覆盖表头配对。停用只影响这条候选名称边，不删除文档、不否认原链接事实。多个对应声明若指向同一命名候选，不制造冲突；去重后多个不同目标不能擅自挑一个。遇到未支持语法的明确对应声明，不能假定它与命名候选一致。

## 7. 正常、诊断与失败分支

| 分支 | 处理 | 输出性质 |
|---|---|---|
| 源绑定及唯一登记合法，链接目标已加载 | 建版本绑定文档边 | 可回读的引用事实 |
| 目标不在批次、锚点未核、复杂语法、名称缺失/歧义/冲突 | 诊断；只生成有依据的边 | 未解决线索，不是系统崩溃或业务无答案 |
| 空知识库/无关系文档 | 空关系结果，正常结束 | 没有伪造关系 |
| 文档hash/行起点非法、重复身份/路径、跨库、解析器或准备阶段失败 | 固定RelationError或既有明确异常，整次失败 | 不返回部分完整成果 |

错误日志固定stage/code，不记录原文、目标字符串、绝对路径或异常正文；诊断结果可含已授权原文依据，不能直接当日志正文。只处理Exception，不吞BaseException；不重试、隐式换解析器或猜目标。

## 8. 影响文件与验证计划

拟新建ingestion/document_relations.py负责提取/核对；新建ingestion/knowledge_preparation.py负责批次装配，因为已有chunk_preparation是单文档两阶段职责，不把关系/批次控制混入它。扩展core/errors.py与ingestion/包导出；新建tests/test_document_relations.py、tests/test_knowledge_preparation_wiring.py。源码每文件≤500行。旧实验、测试、缓存、依赖、真实.env/YAML及其他仓库不改。

先新测试确认新增入口缺失红灯，再最小实现。固定结构验收：

1. 完整合成链、跨L1/L2名称、双向原文引用、自引用/环、重复链接不同位置及顺序稳定。
2. 所有链接quote/span回读；LF/CRLF/CR、重复链接文字、不同围栏和代码保护；不把手写行号作位置。
3. 编码路径/越界/根内未加载/外部URL/图片/本地锚点/复杂语法各分支明确，无目标IO/网络。
4. 缺失/歧义/冲突以及正文不覆盖表头的名称规则；显式边与名称边保持不同依据。
5. ID/路径/版本/行起点/跨库失败；返回对象隔离、JSON往返、修改源版本导致关系身份改变；错误不泄露合成敏感标记。
6. Loader→真实关系构造→现有prepare_document实际接线、空批次和一文档失败不交付部分结果；mock只用于故障注入。
7. 12现有Mock按新登记表核验全部关系来源。旧A3只载入11历史文档，新输入含12文档，因此不硬套23边数量；差异逐条按来源解释。标注为合成结构验收，不是检索效果验证。

命令：目标pytest、全量pytest、compileall、pip check、git diff --check及资产hash核验。未设应用构建，compileall仅语法检查。Spec阶段仅运行相关既有测试核对旧规则，不称为新功能TDD或验收。新验证结果完成后写本节，不提前填成功。

规范准备阶段实际命令（2026-10-12）：

```sh
.venv/bin/python -m pytest -q tests/test_relation_index.py
# 26 passed in 0.32s
git diff --check
# exit 0
```

这26项是既有A3实验测试，覆盖其链接/配对/缓存/有界遍历等行为；没有新核心代码、没有新入口调用或新切片红灯，不把它们记成本片已实现/接线/验证。此轮未重跑全量，M2第二片787是上轮运行记录；没有应用构建。

## 9. 回退边界与下一阶段

只增加新的关系/批次入口；原prepare_document和旧A2/A3实验继续可用。本片不持久化关系、迁移索引、执行多跳遍历、改召回/RRF、重新评估A3收益、建知识图谱或接Agent。M4保存与激活同版本关系；M5/M7再按任务范围和预算消费它。

本片规范完成后的唯一下一步：按此Spec完成新失败测试→最小实现→结构/接线验收。后续再进入M3编码Spec，不把关系输出等同于跨文档检索效果已改善。

## 10. 实际实施与验收

TDD：首次新增两测试文件因RelationError/prepare_knowledge_base不存在而2 collect errors，符合预期。最小实现第一次40 failed/9 passed：backticks从包导入是module，独立合成探针确认TypeError，改为原生backtick函数。随后47 passed/2 failed，修正HTTPS先于netloc的分类顺序；另新测试预期定位的全局index误命中缩进代码，改成明确正文行前缀定位，保留所有原文/代码保护断言，不修改既有测试或放宽断言，49通过。

随后跨行inline code/image样例误建边的2条回归先确认红灯，增加全篇原生范围保护后51通过。百分号编码驱动/协议分类2条回归先红灯，解码后再核scheme边界；另加入解析器故障安全测试，54通过。一次pytest -k筛选含%语法无效，没有运行测试，随后改为运行完整新测试文件取得真实红灯。没有将失败/未运行命令当成功。

```sh
.venv/bin/python -m pytest -q tests/test_document_relations.py tests/test_knowledge_preparation_wiring.py --tb=short
# 54 passed in 0.20s
.venv/bin/python -m pytest -q tests
# 841 passed in 59.24s
.venv/bin/python -m compileall -q naiyue_rag experiments tests
# exit 0，无输出；仅语法检查，应用构建不适用
.venv/bin/python -m pip check
# No broken requirements found.
git diff --check
# exit 0
```

实际L1：document_relations.py/knowledge_preparation.py及两份新测试存在；L2：原生解析范围、登记表、纯路径核对、版本绑定边与名称冲突处理均为实质实现；L3：知识库入口实际调用关系构造及现有单文档主链，接线测试仅包装观察这两个真实方法，mock只用于故障注入。

12现有结构Mock→72片段/12完整用例/24原文链接/3名称配对，关系诊断0，保留1条既有手写行号警告。正文/context/链接/字段标签总计286处回读通过，模型请求0，服务usage=null，检索质量not_evaluated。与旧A3共同11文档另组实际23边（20链接/3配对），两组路径/quote/版本/SourceSpan签名完全一致；新12文档比旧多4链接：当前需求引用两个模块，两个模块导航引用当前需求。登记范围不同，不能归因于召回优化。

结果与资产保护记录：data/research/spec0019-evidence/validation.json、relations.json、legacy-parity.json。106既有源码/实验/测试/Mock/锁文件hash保持，另3既有文件只加错误类与导出；135分发版本保持。新源码266/25行，测试215/68行，旧测试未改；无真实配置/旧向量/其他仓库/提交/push。新模块直接import不依赖experiments，但父包仍加载旧查询兼容入口，不声明整个包已经独立。

学习入口：

- tests/test_knowledge_preparation_wiring.py::test_mock_library_calls_real_stages_and_keeps_relation_quotes：VS Code Debug Test，从prepare_knowledge_base入口F10/F11；build_document_relations返回后relations变量才有值，可观察len(relations['nodes'])、[(e['kind'],e['from_document_id'],e['to_document_id']) for e in relations['edges'][:3]]。接着F11进入prepare_document；两个方法均为观察包装后调用真实实现。
- tests/test_document_relations.py::test_filename_pairing_ambiguity_and_header_conflict_are_explicit[conflict]：在build_document_relations配对循环看corresponding[did]及matches[0].id，验证保留显式边、停用名称边。正常返回，不抛异常。
- tests/test_knowledge_preparation_wiring.py::test_unexpected_stage_fault_is_safe_no_partial_return[document]：第二份文档在fail_second抛RuntimeError，knowledge_preparation捕获后固定RelationError，pytest.raises捕获因此测试通过；第一份只是局部临时结果，没有完整批次返回或落盘。不要在WATCH重新执行有副作用的方法。

范围/数据流已说明，源代码课堂及本人走读、独立实现尚未评估。唯一下一步：M3编码模块Spec，明确文档/查询编码、可配置Provider身份、批处理及输入视图合同，再TDD实现。
