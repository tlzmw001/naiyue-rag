# Lesson 18：阶段B·2.6 显式引用、文件名配对与跨文档关系

日期：2026-10-23，第2章共6节，本节为最后一节。目标：说明关系从何而来、保留哪些依据、如何保存并由同版本Reader消费；不把引用、排名或目录当业务真相。

## 实际数据流

MarkdownLoader的完整Document列表→prepare_knowledge_base先调用build_document_relations→在文档层解析关系/诊断，再逐文档准备片段→IndexBundle保存nodes/edges/diagnostics→激活的版本绑定该资料包→KnowledgeReader.related_documents/read_chunk/read_lines消费PreparedQuery选定版本。

关系在Document层建立，避免重叠Chunk重复抽取和派生检索文本冒充原文。build_document_relations仅处理显式加载注册表，无文件/网络IO；存储层会从来源重新核验关系与资料包一致。

## 本次真实合成样本

examples/core-demo/knowledge共5份文档，实际build_document_relations得到markdown_link=5、filename_pair=1，diagnostics=[]。引用原文切片核对True；文件名配对无伪造quote/span核对True。

- L1_module.md→L2_new.md：[新需求](L2_new.md)
- L1_module.md→L2_previous.md：[历史需求](L2_previous.md)
- L2_new.md→L1_module.md：[上级](L1_module.md)
- L2_previous.md→L1_module.md：[上级](L1_module.md)
- L2_previous_测试用例.md→L2_previous.md：[需求](L2_previous.md)
- 同一用例文件→历史需求另有filename_pair，依据后缀名称规则。

日志文档无关系，仍是独立节点。两类边可以指向同一目标，保留不同依据，不把6条关系当6份目标文档。

## 关系记录的合同

node：文档ID、相对路径、原文内容指纹。
edge：edge_id、kind、from/to文档ID、两端内容指纹、quote/source_span、raw_target/canonical_target、fragment、declaration、derivation。

markdown_link有可逐字回读的原文引文与源位置；filename_pair没有正文引文，quote/span为None，derivation记录精确后缀规则与两端路径。edge方向来自原文或名称规则，不因读取入边而改成逆向语义。

declaration只保留原文表头字段标签等声明，例如“前置依赖”，不是已经验证的depends_on、替代或生效关系。L0/L1/L2分类不强制为树，也不会据层级推断所有上下级文档；可以记录双向引用、自环/环，但当前只描述边，不启动递归读文档。

## 显式链接的解析与边界

原生Markdown解析器识别同一物理行直接链接，局部rule记录原文起止并保护代码、图片/HTML示例，不能把正则扫到的代码样例升级为关系。完整实现的闭包捕获用于原生parser回调留存位置，普通课堂先理解输入/输出，不展开全部inline框架机制。

_resolve以来源文档目录为基准归一化路径：L2/A.md中的../L1/M.md可解析为同库L1/M.md；越库路径/绝对路径等被blocked_target。它只查已加载文档的路径登记表，不打开目标、不联网、不扫描其他目录。

- 已加载的普通本地目标：生成markdown_link。
- 未在输入注册表中的目标：target_not_loaded，不能据此断言磁盘缺文件。
- HTTP/HTTPS：external_reference，不抓网页。
- 本文件锚点：local_anchor，不扩成另一文档。
- 已加载文档带#fragment：保留文档边，记fragment_unresolved，不承诺目标章节已定位。
- 当前不支持的复杂/参考式/跨行链接：unsupported_reference，保留原文与诊断，不能猜目标。

## 名称配对的小算法

仅对识别为用例文档且stem以_测试用例结尾的来源，去掉该后缀，在完整已加载注册表中找stem相同的非用例文档。按NFC规范化后精确匹配、区分大小写，不只查同目录、不限定L2来源，也不使用标题相似度。

例如L2/L1_A_测试用例.md可以配到L1/L1_A.md。0个候选missing_pair，多个候选ambiguous_pair，不选择最近目录猜测。仅标题含“用例”但文件名不符合配对后缀，诊断unsupported_naming，不妨碍已有显式链接保存。

若用例表头明确“对应需求/对应模块”的声明与唯一名称候选冲突，或对应声明无法可靠解析，记pair_conflict并不生成filename_pair。仍保留能核验的显式Markdown链接，不悄悄决定哪份需求正确。普通依赖链接/正文链接不自动覆盖名称配对。

## 知识读取与检索边界

当前Reader库接口接收PreparedQuery，不直接把最终evidence JSON当作读取上下文；实际例子由测试提供。_bundle消费selected active.version.bundle_id，不重新挑latest，不重新读源目录或调用模型/Chroma/BM25检索。

- related_documents(prepared,document_id,max_links)：返回与该文档直接相连的入/出边，保留原方向与出处；两端必须都在当前范围内，范围外关系计入omitted_by_scope；max_links按边条数，超限明确失败，不静默截断。
- read_chunk：按片段ID回取完整保存片段。
- read_lines：按该保存文档的实际行号取正文及来源位置。

关系导航不会自动修改HybridSearch召回、RRF或重排；不会因查到A链接B就自动读取B。上层未来可先检索→看关系→决定补读或补查；知识库Agent/MCP当前未接线，不声称已有自动推理循环。

检索范围是过滤，不是人员授权体系。若当前仅限定A，Reader不沿引用自动扩成B；范围扩大由调用方显式发起，并遵守版本检查。链接说明值得查看的来源，不证明这份来源一定相关、最新或业务正确；历史规则变化仍需读内容。

## 分支和Debug Test入口

### 正常来源与配对

`tests/test_document_relations.py::test_links_pairs_cycle_and_repeated_quotes_have_exact_positions[LF]`，参数ID=LF（另有CRLF/CR）。测试用简化文档ID A/M/T、真实Markdown解析，无生产解析替身。

Test Explorer→Debug Test，在第55行build_document_relations调用处断点，进入后F5到document_relations.py第205行；选_scan栈帧，看quote、canonical、target和span，span在调用source_span赋值后才有。到build_document_relations第246–250行看wanted、matches、corresponding；进入第256行后检查filename_pair的derivation。回测试result观察kind分组与引文来源，不重新调用构造函数取输出。相同链接多次出现时保留各自位置，边数不等于唯一目标数。

### 名称与声明冲突

`tests/test_document_relations.py::test_filename_pairing_ambiguity_and_header_conflict_are_explicit[conflict]`，参数ID=conflict。输入文件名L2_A_测试用例.md、候选A，但表头对应需求指向B。第142行调用，F5到生产第250–254行，看matches[0].id='A'、corresponding[did]=['B']、category='pair_conflict'；回测试第143–144行看到无filename_pair，但T→B原文边保留。属于诊断正常返回，不是抛异常。

### 同版本读取与范围

`tests/test_knowledge_reader.py::test_both_directions_and_name_pairing_keep_provenance`无参数。第38行进入KnowledgeReader.related_documents，在第84–89行看document_id、ends、scope、included/omitted；它们逐边产生，不展开完整对象树。

范围用`test_scope_never_follows_references_automatically`（无参数）：只选L2_A文档，关系指向范围外则不返回，omitted_by_scope记录；直接read_lines范围外文档会抛query_invalid_scope。完整Chunk/行补读用test_complete_case_and_actual_lines_without_sdk_or_latest：该测试额外把Chroma/BM25 audit与catalog.read替换为forbidden，证明Reader不重选latest/查索引；fixture准备阶段使用编码/索引替身，读取本身沿实际BundleStore。

解析失败测试test_parser_exception_is_observable_without_original_payload第211行替换模块_parser，第210行raise，外层build_document_relations第265–266行转换RelationError(relation_parse_failed)，测试pytest.raises捕获。不要混同为普通链接未解析的诊断分支。

## 本次验证

```zsh
.venv/bin/python -m pytest -q tests/test_document_relations.py \
  tests/test_knowledge_reader.py::test_complete_case_and_actual_lines_without_sdk_or_latest \
  tests/test_knowledge_reader.py::test_both_directions_and_name_pairing_keep_provenance \
  tests/test_knowledge_reader.py::test_scope_never_follows_references_automatically \
  tests/test_knowledge_reader.py::test_read_budget_is_explicit_not_silent_truncation
```

实际输出：55 passed in2.69s。另运行core-demo 5文档真实加载/关系探针，5条显式链接＋1条名称配对，原文quote与无伪造配对span核对True。以上本地确定性/合成验证，无模型、真实资料、图质量或生产保证。本次仅维护学习记录，未改源代码/依赖/.env/运行配置，未重跑全量。git diff --check作文档检查。

## 本章收束与学习证据

第2章2.1–2.6讲解覆盖：加载与Document→Markdown结构/定位→递归切分→结构/语义区别→用例表格→显式文档关系。本人理解、调试、复写/实现仍待用户证据，助手测试不替代掌握。中文标点与文档级增量仍仅后续优化，未实施。

下一步第3章第1节（第3章共6节）：原文、检索文本和模型编码输入怎样分开，沿用例retrieval_view追踪字段、上下文布局、前缀和身份hash。
