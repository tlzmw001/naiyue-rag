# Lesson 17：阶段B·2.5 用例表格识别与完整性

日期：2026-10-23，第2章共6节。目标：沿一行合成用例看文档分类、列名匹配、字段、上下文、原始正文和检索视图的关系；区分保留降级、异常和超长诊断。

## 输入输出与实际样本

输入为examples/core-demo/knowledge/L2_previous_测试用例.md，经MarkdownLoader→DocumentChunker(IngestionSettings(30,0))。本次本机实际得到2个test_case，TC-01含5列：编号、用例名称、前置条件、测试步骤、预期结果。

字段依次为TC-01、关闭折扣保持基础金额、单价10/数量2/discount_enabled=0的原单元格、创建订单<br>查询结算、基础金额20/实付20的原单元格。精确原文仍以文件为准，字段数组不替代证据正文。

TC-01的body_span=[113,198)、第9行，85字符，在本次30字符上限下oversize=True并有atomic_oversize诊断，没有截断。contexts为document_title、dimension、columns、column_separator；源文件没有本节规则适用的来源说明引用块，所以没有source_note，不伪造。

## 实际数据流

Document→scan_document分类/解析表格→_table_blocks表头与行适配→test_case结构块→DocumentChunker._chunk→可选ChunkRefiner labeled_case检索视图→后续成对编码。当前全部是规则处理，没有LLM猜测列含义。

## 两道识别条件

1. 文档分类：stem以_测试用例结尾，basis=filename_suffix；否则一级标题包含“用例”，basis=title_marker；否则普通text。不依赖L2目录或文件名前缀，也不推断历史状态或有效性。
2. 表格核心列唯一匹配：name、preconditions、steps、expected必须各匹配一列。别名见markdown_structure.py::ALIASES；编号可选，不要求TC格式；额外优先级、设计者、备注等列均保留。

例如5列表头匹配得到name=[1]、preconditions=[2]、steps=[3]、expected=[4]、id=[0]。字段由相应列下标对应，不能默认第1列就是用例名。当前核心列缺失/不唯一会落回一般table并告警；在已能识别核心列的路径中，可选编号别名重复会invalid_table，不能泛称所有重复列都同一种错误。

## 一行用例的核心机制

- markdown-it的tr_open/map提供原文行范围；按前节_interval转字符范围。
- _cells从原始行取单元格，处理转义管道符，不直接split('|')；单元格首尾空白被strip，但chunk.text始终原文切片。
- 原始每行列数需与表头一致，避免只信解析器单元格输出而静默丢列。
- 每个数据行生成test_case；表头和分隔行成为上下文，不生成虚构用例。
- case_columns和case_fields按原列顺序保存；业务case_id来自可选编号列，缺失时None，不生成TC编号。
- 相同case_id的两行仍是两个来源单元，Chunk.id按文档/版本/位置绑定，不按业务编号合并。

## 上下文的来源

_block先附文档标题和所属章节。_table_blocks把当前最深且级别>1的章节标为dimension，并附columns、column_separator。source_note来自当前章节标题之后、表格之前的blockquote原文；不自动补上级需求正文，也不证明说明内容正确。每个上下文独立保存span，正文不重复拼上表头冒充原始行。

## 原文与检索视图

ChunkRefiner.transform在text_mode=raw时保留原正文作为视图；在labeled_case时按zip(case_columns,case_fields)生成“列名：字段值”，包含全部列。无反引号且未转义的<br>/<br/>等可转为换行；一个单元格含反引号时，当前保守地保留整单元格，不精确猜测代码内外HTML。原始chunk.text及body_span始终保持，用于证据回取；retrieval_view另存文本及指纹，用于后续检索编码，编码布局到3.1再讲。

本次真实TC-01检索视图：

```text
编号：TC-01
用例名称：关闭折扣保持基础金额
前置条件：单价 10，数量 2，discount_enabled=0
测试步骤：创建订单
查询结算
预期结果：基础金额 20，实付 20
```

本次raw_body_unchanged=True；没有把排版调整声称为检索质量改善。

## 分支地图与已有测试

| 场景 | 行为 | 入口（tests/test_document_chunker.py） |
|---|---|---|
| 识别到核心列，包含额外列 | 每行test_case，全部列保留 | test_variable_columns_and_non_tc_business_number |
| 没有编号列 | case_id=None，不伪造 | test_complete_case_has_columns_dimension_source_and_no_fabricated_id，newline=\n/\r\n/\r |
| 重复业务编号 | 独立Chunk与位置 | test_same_business_number_does_not_merge_distinct_source_rows |
| 用例文档但列名未识别 | 整表保留并unclassified_case_table告警 | test_unknown_case_columns_keep_table_and_diagnose |
| 列数不齐 | ChunkingError(invalid_table) | test_ragged_table_does_not_silently_drop_cells |
| 表格分隔结构损坏 | 明确invalid_table，不当普通正文切开 | test_malformed_case_table_not_silently_split_as_prose |
| 仅表头/分隔行 | 一般table，无test_case | test_empty_case_table_keeps_header_and_separator |
| 完整用例超过size | 保持正文、oversize诊断；后续限额另管 | complete_case测试及atomic边界测试 |

表格层识别只说明格式与字段规则匹配，不说明旧用例适用于新需求，也不证明用例业务正确。跨用例“沿用TC-01”等依赖当前作为原文保留，不自动展开；关系导航在2.6学习。

## Debug Test：先走无参数正常入口

`tests/test_document_chunker.py::test_variable_columns_and_non_tc_business_number`（无参数ID）。该测试含7列、编号CASE-A，与课堂5列TC-01样本不同，属于同一规则的另一输入。

1. 第91行Debug Test/F11进split_document；F5到markdown_structure.py第110行，选_table_blocks栈帧，观察raw_cells[0]、classification。
2. F5到第113行，再看已赋值的matched、recognizable。第123行循环进入第一数据行后观察values，再到第135行查看block['case_id']和block['case_fields']。
3. 返回DocumentChunker第55行确认kind!=text，直接_chunk并continue，不调用正文递归。回测试第93行看case.text、case.metadata['case_id']、case.metadata['contexts']的类型列表；不要重跑切分函数取值。

检索视图测试：`tests/test_chunk_preparation.py::test_view_preserves_raw_source_all_columns_and_serialization[labeled_case]`。F5到ChunkRefiner第105–109行，选transform栈帧观察text_mode、meta['kind']、生成后的text；返回测试看case.text和retrieval_view.text，前者原样、后者带标签。这些正常测试执行真实解析/切分/refiner，无模型替身或模型调用。

警告/失败入口按上表分别Debug Test。列数错误时_table_blocks第107行调用fail_chunking，第21行抛ChunkingError，pytest.raises捕获所以测试通过；没有monkeypatch生产解析。故障与未知列警告不能混为一个分支。

## 本次验证

```zsh
.venv/bin/python -m pytest -q \
  tests/test_document_chunker.py::test_complete_case_has_columns_dimension_source_and_no_fabricated_id \
  tests/test_document_chunker.py::test_variable_columns_and_non_tc_business_number \
  tests/test_document_chunker.py::test_same_business_number_does_not_merge_distinct_source_rows \
  tests/test_document_chunker.py::test_unknown_case_columns_keep_table_and_diagnose \
  tests/test_document_chunker.py::test_ragged_table_does_not_silently_drop_cells \
  tests/test_document_chunker.py::test_malformed_case_table_not_silently_split_as_prose \
  tests/test_document_chunker.py::test_empty_case_table_keeps_header_and_separator \
  tests/test_chunk_preparation.py::test_view_preserves_raw_source_all_columns_and_serialization \
  tests/test_chunk_preparation.py::test_cell_conversion_is_conservative_and_lossless
```

实际输出：17 passed in0.16s。另有完全合成TC-01的实际加载/Chunk/refiner探针，如上。源码/依赖/.env/运行配置未修改，无模型或索引写入，无真实资料质量结论。文档检查用git diff --check。

## 学习证据与下一步

2.5已讲解，助手测试不代替用户本人调试、复写和理解。用户掌握待反馈，没有强制复述题。下一节2.6：L0/L1/L2显式引用、需求/用例文件名配对、关系出处及跨文档补读边界。
