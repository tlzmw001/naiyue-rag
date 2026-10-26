# Lesson 22：阶段B·3.4 文档与查询编码的一致性

日期：2026-10-23，第3章共6节，本节第4节。目标：理解模型/文本表示/分词身份与维度怎样连接建库和查询，以及查询编码前后两道校验。只学习现有链路，不改配置或实现。

## 为什么维度相同仍不够

人工二维示意：模型M1中折扣文档A=[1,0]、日志文档B=[0,1]，折扣问题也是[1,0]。若另一模型M2旋转了表示，折扣问题成为[0,1]，直接查M1旧向量就会与日志B完全同向。两个模型都输出二维，仍不是同一个坐标体系。这是数学示意，不是embedding-3的真实输出或质量实验；同维不同模型的数值可计算，计算结果不因此具备可靠语义。

单位化只调整长度，不能把两个不同模型空间对齐。要改变模型/表示策略，应通过明确的新编码/索引版本处理；当前课堂不实施迁移。

## 三种身份和一项维度

| 字段 | 当前源码身份内容 | 不代表什么 |
|---|---|---|
| model_space_id | policy与完整embedding配置摘要：provider/base_url/model/expected_dimensions/request_dimensions/model_revision/allowed_response_models | 不是实际模型权重校验，不能证明服务端从未变更 |
| representation_id | document_text_mode/text_layout/document_prefix/query_prefix及policy摘要 | 不是正文hash，不代表两端输入文本相同 |
| tokenizer_id | jieba版本/词典hash/搜索模式/HMM/中文词长/小写/词法规则等摘要 | 不是缓存目录或Embedding服务tokenizer |
| dimensions | 当前期望与索引登记的向量维度 | 不能单独证明同一空间 |

源码core/encoding_settings.py:94–102只将embedding与representation分别做摘要，runtime不进入这两类身份。SparseTokenizer的语义身份也不含cache_dir与资源上限。身份是兼容合同，采用配置精确一致的保守判断；例如端点改变即使服务同一权重，当前也判model_space_id不同。

### 本机内存单变量探针

读取公开examples/core-demo/encoding.example.yaml，再在内存复制修改单个值，没有模型请求：

| 只改变 | model_space_id相同 | representation_id相同 | 维度相同 |
|---|---|---|---|
| timeout_seconds=45 | True | True | True |
| model_revision=lesson-revision | False | True | True |
| base_url=另一合成端点 | False | True | True |
| query_prefix=query: | True | False | True |
| text_layout=view_only | True | False | True |

更改分词长度/小写的现有测试还证明tokenizer_id改变；只换缓存路径/上限不改变该身份。这里的False证明配置身份不同，不证明新方案质量更差或每个向量值必然不同。

## 文档与查询一致，不等于处理文本完全相同

模型可能要求文档前缀passage:、查询前缀query:，这只是示意，当前公开core-demo两前缀为空。完整representation配置同时描述文档和查询两种角色，_input按kind选对应前缀；建库与查询使用同一份完整策略，实际输入可以不同。

文档使用标题/表头等上下文，查询是用户问题；文档Sparse保留重复供TF统计，查询从记录派生去重terms。这些是设计内的角色差异。

当前只改query_prefix也会改变representation_id并被旧版本拒绝，即使文档向量没有重算的数学必要。原因是现有索引绑定完整表示合同，未引入允许独立切换查询策略的兼容矩阵/对照入口。解释当前合同，不新增此优化或声称每次表示变化都必须按理论全量编码。

## 实际建库/查询链路

```text
建库：EncodingSettings / SparseTokenizer
  → EncodingInput / Dense / Sparse
  → EncodingResult与资料包
  → IndexVersion登记model_space_id / representation_id / tokenizer_id / dimensions
  → 激活版本

查询：QueryPipeline.prepare
  → 读取并固定ActiveVersion与资料包
  → _identity：比对四项，之后审计保存的三类产物
  → ready时QueryEncoder.encode
  → 编码结果再次核对问题文本/hash及四项身份
  → PreparedQuery绑定本次选定版本
```

IndexVersion保存标识不是保存密钥或重新运行模型。当前组件配置与选定索引不兼容，prepare在resources阶段报query_identity_mismatch，不调用查询Dense，不静默降到单路。空范围/空库也不被用来绕过已激活版本的身份检查。

QueryEncoder内部先准备查询、执行Dense与Sparse，再按输入ID、Dense的embedding_text hash、Sparse的retrieval_text hash、模型/分词身份及维度配对；完整批处理细节留到3.5。

## 两道检查分别防什么

第一道在query/pipeline.py:94–98：

```python
if (cfg.model_space_id, cfg.representation_id,
    self.tokenizer_id, cfg.embedding.expected_dimensions) != (
        version.model_space_id, version.representation_id,
        version.tokenizer_id, version.dimensions):
    raise QueryJobError('resources', 'query_identity_mismatch')
```

比较当前查询组件的编码合同与活动索引版本。配置已知不兼容，停止在查询编码前；不是停止所有磁盘读取。

第二道在query/pipeline.py:132–135：编码返回后，确认encoding.input.retrieval_text等于processed.query、query_sha256对应此问题，且结果的四项身份与固定版本相同。防止返回其他问题的编码或被污染的结果。失败阶段embedding，保留已获得的成功编码报告，不交付可继续检索的PreparedQuery，也不伪造“没有发请求”。

QueryPipeline._fail统一记录阶段/固定错误码，异常通过QueryJobError传给调用方。trace里将身份失败映射为invalid_resources；业务异常仍保留query_identity_mismatch。当前原始查询hash合同保持，用户已要求的首尾strip仍是future-work，实施时须同步这些绑定。

## 正常与失败分支

| 情况 | 当前行为 |
|---|---|
| 四项匹配且有候选范围片段 | 执行一次QueryEncoder，再核返回结果 |
| 换模型/前缀/分词/维度与索引不符 | resources阶段失败，查询Dense调用0 |
| 仅更改批大小等runtime并正确重新装配组件 | 不改变索引编码身份，查询可继续；运行限额仍会生效 |
| 同一个pipeline内偷偷替换组件/设置 | _validate拒绝；runtime可变不等于可原地混装 |
| 编码返回另一问题/另一身份 | embedding阶段失败，保留已观察到的编码报告 |
| 服务端同URL/模型名下静默换权重 | 当前配置指纹本身不能识别；可用revision字段/版本核验取决于服务能力，未实现权重验证 |

没有自动同义词映射、跨模型对齐或单路回退。配置一致也不证明文本召回正确、服务可复现到每个数或生产质量通过。

## Debug Test入口

### 正常

`tests/test_query_preparation.py::test_ready_scope_projection_encoding_and_trace`无参数。测试第48行调用prepare，进入生产后F5到_identity，选_identity帧看cfg与version的四项；返回prepare第129行编码，再到第132行看encoding.input.retrieval_text、processed.query及encoding.tokenizer_id。不要在WATCH重调用encode。返回测试result后才可观察result.active/result.encoding。

### 编码前拒绝

`tests/test_query_preparation.py::test_encoding_profile_must_match_active[representation]`，精确参数ID=representation；另model/tokenizer/dimensions。第120行只改query_prefix，第123行装配新编码器，第126行调用prepare。production _identity第96–98行观察模型身份相同、表示身份不同，抛QueryJobError；第128行dense.calls=[]证明查询Dense未执行。pytest.raises捕获，测试通过。dimensions参数也改变model_space_id，不能把它当独立绕过模型身份的探针。

### 编码后拒绝

`tests/test_query_preparation.py::test_post_encoding_failure_keeps_successful_encoding_report[wrong-profile]`，精确参数ID=wrong-profile。第205行monkeypatch包装QueryEncoder.encode；包装先调用原encode，再在第202行把结果tokenizer_id与SparseRecord中的tokenizer_id一起改成另一合法hash。数据对象内部仍一致，但与固定IndexVersion不一致。prepare第133–135行拒绝，_fail保留已成功的report，测试第210行确认report.status=success。另wrong-query返回另一问题编码，被文本/hash核对拒绝。

### 测试替身边界

这组QueryPipeline测试使用真实QueryEncoder/QueryPipeline、资料包/BM25/活动目录；Dense/Sparse执行器是test_query_encoding.py的确定性替身，Chroma client在prepared fixture中替换为FakeClient。正常SparseTokenizer身份测试另用真实jieba。没有真实模型或原生Chroma检索，本节测合同，不测服务语义。

## 实际验证

```sh
.venv/bin/python -m pytest -q \
  tests/test_encoding_settings.py::test_standalone_yaml_hashes_and_output_isolation \
  tests/test_sparse_encoder.py::test_configured_minimum_and_lowercase_share_cache_but_not_token_identity \
  tests/test_query_preparation.py::test_ready_scope_projection_encoding_and_trace \
  tests/test_query_preparation.py::test_encoding_profile_must_match_active \
  tests/test_query_preparation.py::test_runtime_change_and_manager_defaults_do_not_rebind_indexes \
  'tests/test_query_preparation.py::test_post_encoding_failure_keeps_successful_encoding_report[wrong-query]' \
  'tests/test_query_preparation.py::test_post_encoding_failure_keeps_successful_encoding_report[wrong-profile]'
# 10 passed in 3.62s
```

只维护学习记录；无源码/依赖/真实.env/运行配置/原索引修改。L1已有身份/版本/查询文件；L2真实摘要与前后校验；L3定向测试验证正常/预检失败/结果错绑三条路径，外部执行按上述替身边界。构建不适用，不跑全量测试；git diff --check退出0。

## 学习证据与唯一下一步

3.4已讲解，助手完成内存探针与定向验证；用户理解待反馈，本人独立调试/实现未评估。下一节3.5：成对批处理、ID与hash配对，沿同一批片段说明Dense/Sparse如何合并为完整记录。
