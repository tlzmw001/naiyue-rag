# Lesson 19：阶段B·3.1 原文、检索文本与编码输入

日期：2026-10-23，第3章共6节，本节为第1节。目标：沿同一份用例，区分原始证据、派生视图、布局后的检索文本和模型编码文本，以及各自的来源与指纹。

## 模块位置与真实调用链

摄取路径：IngestionPipeline._inputs→prepare_document_encoding_inputs→ChunkRefiner重核原文及视图→按布局组合文本→_input生成EncodingInput→后续BatchProcessor消费。

查询路径：QueryEncoder.encode→prepare_query_encoding_input→_input生成查询EncodingInput→后续Dense/Sparse消费。准备函数只构造和校验输入，不调用模型、不写索引。

```text
Document + Chunk.text（原文行）
  → ChunkRefiner：retrieval_view.text（raw或labeled_case）
  → prepare_document_encoding_inputs：布局组合成retrieval_text
  → _input：模型前缀 + retrieval_text = embedding_text
                         ├ retrieval_text → SparseEncoder → 词项与词频
                         └ embedding_text → DenseEncoder → Provider → 向量
```

Sparse与Dense消费同一EncodingInput的不同字段。两路内部算法分别留到3.2/3.3；成对组织与异常报告留到3.5/3.6。

## 本机合成样本与四步表示

来源examples/core-demo/knowledge/L2_previous_测试用例.md，TC-01原文为：

```text
| TC-01 | 关闭折扣保持基础金额 | 单价 10，数量 2，discount_enabled=0 | 创建订单<br>查询结算 | 基础金额 20，实付 20 |
```

实际原文范围为[113,198)，第9行。source_span仍定位这一行；上下文另有自己的来源位置，不能拿拼接后的文本长度反推原文坐标。

labeled_case视图为：

```text
编号：TC-01
用例名称：关闭折扣保持基础金额
前置条件：单价 10，数量 2，discount_enabled=0
测试步骤：创建订单
查询结算
预期结果：基础金额 20，实付 20
```

ChunkRefiner使用case_columns和case_fields逐项配对，给全部列补上列名；规则允许时将单元格中的<br>转换行，不生成业务摘要、不调用LLM。普通正文在此模式下仍使用原始chunk.text。

当前公开示例encoding.example.yaml的representation配置：document_text_mode=labeled_case，text_layout=contexts_then_view，document_prefix=''，query_prefix=''。

因此本例retrieval_text实际在上述视图前按序增加4份原文上下文：文档标题、维度标题、表头、表格分隔行。retrieval_view.text不等于最终retrieval_text。view_only则只取视图，不添加这些上下文。

embedding_text=配置前缀+retrieval_text；示例前缀为空，所以两份字符串与两份文本hash相等，这是合法状态。测试里的passage:/query:只用于验证前缀接线；不能据此说embedding-3或所有模型需要这些前缀。前缀是模型输入格式的一部分，不是生成问答的提示词。

## 输入对象与指纹

EncodingInput保留item_id、kind、knowledge_base_id、source_document_id、source_sha256、source_span、retrieval_text、embedding_text、两份text hash、model_space_id、representation_id和query_sha256。

| 字段 | 核对什么 |
|---|---|
| source_sha256 | 完整原始文件字节版本，不是这一个Chunk的hash |
| retrieval_view.text_sha256 | Refiner派生视图文本 |
| retrieval_text_sha256 | 布局组合后的实际检索文本 |
| embedding_text_sha256 | 包含前缀的实际Dense输入文本 |
| model_space_id | 当前embedding配置的身份；不证明服务端模型永不变化 |
| representation_id | 文本模式、布局及两类前缀配置的身份 |

文本hash使用SHA256(UTF-8字节)，用于精确一致性校验，不度量语义相似度或业务正确性。不能只根据文本hash相同，就判断不同模型产生的向量可混用。

本次仅在内存中将document_prefix由空串改为passage:，重新准备输入，实际结果：source_hash_unchanged=True、retrieval_hash_unchanged=True、embedding_hash_changed=True、representation_id_changed=True。未修改任何配置文件，也未请求模型。

查询示例'  检查折扣开关  '：非空校验使用strip，但保存原字符串，因此两端空格仍保留；本示例空前缀使embedding_text与它相同。查询没有文档来源，source_document_id/source_span等均为None，query_sha256标识查询原文。其余查询范围与版本由上层查询对象处理。

## 正常、空态与失败分支

| 情况 | 负责层与结果 |
|---|---|
| 合法文档与片段 | 重推视图、核对来源、按配置布局/前缀，返回EncodingInput列表 |
| 空片段列表且文档登记合法 | 返回[]，准备阶段不发请求 |
| 非空查询 | 返回一个kind=query的EncodingInput |
| 纯空白查询 | invalid_encoding_input |
| 原文、上下文、视图、来源或ID不一致 | invalid_encoding_input；不把受损内容交给编码器 |
| 输入UTF-8字节超限 | encoding_input_limit；不静默裁剪，细节见3.6 |
| 已准备对象文本/hash被改 | 再次序列化/批次校验时拒绝 |
| 对象配置身份与当前设置不一致 | encoding_identity_mismatch |

失败通过fail_encoding记录固定阶段/错误码并抛EncodingError，不把敏感正文拼入错误信息。prepare_document_encoding_inputs返回前还会做批次预检，具体批次数与用量机制后续展开。

## 核心代码地图

- ingestion/chunk_preparation.py:95–118，ChunkRefiner.transform：来源校验后，在副本上建立视图；原始Chunk.text不变。
- encoding/input_preparer.py:19–37，prepare_document_encoding_inputs：建立文档登记、重算视图、核对已有视图、按布局组合，再调用_input。
- encoding/input_preparer.py:9–16，_input：选文档/查询前缀，构造两个文本及hash、来源与身份。
- core/encoding_types.py:37–57：__post_init__/to_dict核对字段与hash，序列化时再次检查可变对象。
- encoding/dense_encoder.py:26与encoding/sparse_encoder.py:29：实际消费者分别读取embedding_text和retrieval_text，形成字段接线证据。

## Debug Test入口

### 正常布局

`tests/test_encoding_inputs.py::test_real_m2_to_encoding_preserves_source_and_layout[labeled_case-contexts_then_view]`

另有raw-view_only、raw-contexts_then_view、labeled_case-view_only，均为已收集到的精确参数ID。测试使用合成Markdown与真实M2/输入准备，没有Provider替身，因为根本不进入Provider。

Test Explorer选该参数→Debug Test。在测试第23行断点；若暂不展开M2，F5到这里。F11进入prepare_document_encoding_inputs，F10到第30行赋值后：

- 选prepare_document_encoding_inputs栈帧，看chunk.text、expected.metadata['retrieval_view']['text']。
- 第32行执行后看text，此时加入contexts，比较两份字符串。
- 第33行F11进入_input；第11行执行后看kind、prefix、text、embedded。
- Shift+F11回调用方，F10完成append，再看output[-1].retrieval_text/embedding_text/source_span。
- 回测试第25–33行看item、chunk及断言，确认原文与before一致。item只有进入for循环后才存在。

只观察现有变量，不在WATCH重新调用准备/编码函数。passage:来自该测试config，不来自公开core-demo配置。

### 被修改的视图

`tests/test_encoding_inputs.py::test_invalid_document_input_never_becomes_encoding_text[view]`

第41行注入错误view，第50行调用真实生产准备；在生产第29行看到保存view与重推expected不相同，抛ValueError，经第37行归一成invalid_encoding_input。pytest.raises捕获预期异常，测试仍通过；没有模型或存储调用。

### 查询与空态

`tests/test_encoding_inputs.py::test_query_preserves_raw_text_and_empty_documents`，无参数。第56行创建查询并返回item，随后检查空格保留/source=None、空片段返回[]、空白查询抛错。production prepare_query_encoding_input第43行只用strip判空，第44行传原query。

## 本次验证与证据边界

```sh
.venv/bin/python -m pytest -q \
  tests/test_encoding_inputs.py::test_real_m2_to_encoding_preserves_source_and_layout \
  'tests/test_encoding_inputs.py::test_invalid_document_input_never_becomes_encoding_text[view]' \
  tests/test_encoding_inputs.py::test_query_preserves_raw_text_and_empty_documents \
  tests/test_encoding_inputs.py::test_mutated_hash_or_profile_cannot_bypass_validation
# 7 passed in 0.15s
```

本机公开合成样本沿真实Loader→prepare_document→prepare_document_encoding_inputs运行；chunks_unchanged=True。另收集正常测试4个参数ID，4 tests collected in0.18s。只验证输入准备合同，没有真实模型调用、向量生成或业务质量评测。未修改源码、依赖、.env、运行配置或索引。

构建：本节无实现变更，不适用；不重跑全量测试。文档检查git diff --check退出0。L1/L2：已有输入准备和类型文件、真实校验/组合实现；L3：本次合成调用与7项测试消费真实准备函数，源码确认两路分别取约定字段，未在本节执行两路编码。

## 学习证据与唯一下一步

3.1已讲解并由助手核验；用户理解待反馈，本人调试、复述与独立实现未评估。下一节3.2：Embedding和向量空间，先用小型数字例子解释向量/相似度，再看实际Dense输出合同。
