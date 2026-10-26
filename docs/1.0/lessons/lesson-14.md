# Lesson 14：阶段B·2.2 Markdown结构与原文定位

日期：2026-10-20，第2章共6节。目标：理解语法标记、行区间、原文字符范围、标题路径和保护区域的关系。实际已安装markdown-it-py 4.2.0；本节使用已有测试文本及core-demo合成用例文件，不生成新业务材料。

## 本节数据流与边界

Document（原文＋来源）→scan_document校验→MarkdownIt语法标记/行区间→原文字符范围→text/code/table/test_case结构块＋诊断→后续DocumentChunker。

结构块还不是按chunk_size/overlap切好的最终Chunk。scan_document给出kind/start/end/headings/contexts等，正文仍由document.text[start:end]取得。普通区域不要求一段落一个块，当前按标题与保护区域边界划定，递归细分留到2.3。Markdown语法token不同于模型计费token；此处是有type/tag/map等字段的语法记录列表，不是LLM理解结果。

## 两份现有样本

1. `tests/test_markdown_structure.py::test_structure_uses_headings_and_code_maps`：# A、### B、围栏代码中的# inside code、正文。用现有document测试helper构造Document。
2. `examples/core-demo/knowledge/L2_previous_测试用例.md`：真实Loader读取的合成用例Markdown，标题/维度/表头/两条完整用例行。代码样本与表格样本分别观察，避免把刻意破损的边界夹具当作正常完整文档。

## 解析器实际行为

生产入口`ingestion/markdown_structure.py::scan_document`第145–146行：`MarkdownIt('commonmark').enable('table')`再parse(document.text)。显式启用table规则，不假定普通CommonMark自动支持业务表格。

源码核对：已安装markdown_it/main.py::parse创建StateCore并调用core.process；parser_core.py按normalize→block→inline等规则执行；rules_core/normalize.py把CRLF/CR规范化成LF并替换NUL；heading/fence/table规则设置token.map。Parser内部规范化的state.src不替换Document.text。不能用token.content的位置替代原文字符下标。

代码样本真实token投影：heading_open h1 map=[0,1]，heading_open h3 map=[2,3]，fence map=[4,7]、content='# inside code\n'。fence内部的# inside code不成为heading_open；语法规则先识别整个代码区，不靠逐行startswith('#')判断章节。token.level是语法嵌套深度；标题h1/h2级别从token.tag解析，不能混淆。

## 从行区间到原文字符范围

token.map=[a,b]按0起始、左闭右开行号描述，map=[4,7]对应人读的第5–7行。不是字符区间，也不是从第4行到第7行。

`_interval(document,line_map)`第49–57行：start=line_starts[a]；end=line_starts[b]，b到达文档结尾则用len(text)；仅向前收掉该区间末尾CR/LF。内部空白、换行和原始语法保留。

真实用例token：table_open map=[6,10]；表头tr_open [6,7]；TC-01 tr_open [8,9]；TC-02 tr_open [9,10]。分隔行属于table结构，但不是一条测试用例数据行。

TC-01换算：line_starts[8]=113，line_starts[9]=199；去掉区间末尾换行后end=198，所以正文=document.text[113:198]。SourceSpan为start_char=113、end_char=198、line_start=9、line_end=9。原文198位置是换行，199是下一行起点。

`source_span`第39–44行用bisect_right计算有多少行起点<=start；结束行使用end-1，因为end本身不属于正文。它将0起始半开字符范围映射为1起始包含结束的展示行号。bisect使用有序行起点，避免从头逐字符重新扫描；二分查找细节不是本节独立实现目标。

## 为什么从原文切取

真实LF代码块结构：kind=code、start=12、end=33，原文切片为三反引号开头、# inside code、三反引号结尾；token.content只有内部# inside code及换行，不含围栏。

本次同一样本改用CRLF在内存中运行：fence.map仍[4,7]，token.content不含CR，原文代码切片仍含CR；原文SourceSpan为[16,39)、第5–7行。DocumentChunker真实输出逐条满足chunk.text==doc.text[start_offset:end_offset]。另对真实Loader用例文件核对TC-01 slice[113:198]相等、实际第9行。

因此解析器提供结构/行映射，保存原文提供证据正文，两者不混为同一份文本。围栏、<br>、转义字符和表格写法不经渲染或重建而丢失。仍保留原文中的声明，不把文档内指令当系统授权。

## 标题路径的小算法

`_headings_at`第80–86行从前往后扫描到当前块之前的标题，维护一个列表stack：遇到新标题，弹出级别>=新标题的栈顶，再追加新标题。这里列表承担后进先出的栈用途。

| 读到标题 | 当前路径 |
|---|---|
| # 系统 | 系统 |
| ## 计费 | 系统→计费 |
| ### 折扣 | 系统→计费→折扣 |
| ## 日志 | 弹出折扣、计费，得到系统→日志 |

这决定内容所属章节，不是文档间知识图谱。当前仅收集顶层heading_open；fence内部#不进入标题表。标题原文和标签同时保存：原文可含##，label供分类等使用。

## 普通、保护和异常分支

| 场景 | 扫描层行为 |
|---|---|
| 普通内容与标题 | 形成text区域，保存标题路径/上下文；内部可能有多段落 |
| 围栏/缩进代码 | 形成code保护区域，不混进普通正文递归切分 |
| 一般表格 | 形成table；不自动当成测试用例 |
| 识别为用例文档且列名匹配 | 当前适配成test_case行，附表头/维度等上下文，详见2.5 |
| 用例文档列名不识别 | 保留一般table并产生诊断，不能假称成功识别用例 |
| 空白文档 | blocks=[]和empty_source信息诊断 |
| 来源text/hash/大小/行起点不一致 | ChunkingError(invalid_chunking_document) |
| 解析器故障 | ChunkingError(structure_failed)，固定安全错误码 |

表头手写行号不参与实际定位。当前stale_header_line_range仅检测越界/倒置等明显异常，不能证明一个范围内的手写引用指向了语义正确的段落。

## Debug Test与观察路线

首选无参数测试：`tests/test_markdown_structure.py::test_structure_uses_headings_and_code_maps`。

- Test Explorer→Debug Test，在测试第12行断点。输入doc来自现有测试helper，生产MarkdownIt.parse和scan_document未替换。
- F11进入scan_document；F5到结构模块第147行，选scan_document栈帧。WATCH `[(t.type,t.map) for t in tokens if t.type in ('heading_open','fence')]`、`document.metadata['line_starts']`。
- 到第154行，在对应token.type=='fence'时F11进_interval；当前_interval栈帧看line_map、starts，start/end只在赋值后产生；返回时观察a/b。
- 回scan_document继续到第195–197行，观察`[(b['kind'],b['start'],b['end']) for b in blocks]`及document.text[12:33]，后者是纯切片。
- 回测试第14行看blocks；# inside code在代码正文中，未成为任何块的标题上下文。不要重新调用scan_document获取输出。

故障无参数测试：`tests/test_markdown_structure.py::test_parser_failure_has_safe_code`。第41行monkeypatch MarkdownIt.parse为fail，第40行raise RuntimeError；scan_document第200–201行捕获，fail_chunking第21行抛ChunkingError(structure_failed)，测试第42行pytest.raises捕获。普通结构测试没有替换解析器；仅故障测试替换。辅助CRLF用例来自`tests/test_document_chunker.py::test_complete_case_has_columns_dimension_source_and_no_fabricated_id`，参数newline分别为\n、\r\n、\r；不强制本轮走全部分支。

## 本次验证

1. `.venv/bin/python -m pytest -q tests/test_markdown_structure.py` → `4 passed in 0.18s`。
2. `.venv/bin/python -m pytest -q tests/test_document_chunker.py::test_complete_case_has_columns_dimension_source_and_no_fabricated_id tests/test_document_chunker.py::test_code_and_general_table_are_atomic_even_when_oversize` → `4 passed in 0.13s`。

两次独立测试组，不写成单次8项全量。另有上文纯本机解析/切片探针：版本4.2.0、CRLF map、原文切片与TC-01定位均核对。无模型/网络请求、无索引写入、未改源代码/真实配置，未验证真实资料质量。

## 学习证据与下一步

本节机制和源码入口已讲解；用户理解待反馈，本人调试、复写或实现未评估。课堂及助手测试不替代掌握。

下一节2.3：固定长度、重叠与递归切分；只展开普通text区域怎样继续分成可配置长度的Chunk，代码/表格/用例保护规则引用本节与2.5。
