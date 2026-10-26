# Lesson 20：阶段B·3.2 Embedding和向量空间

日期：2026-10-23，第3章共6节，本节第2节。目标：理解文本向量、维度、向量长度与余弦相似度，并沿真实Dense路径核对输出合同。本节不调用真实模型、不写索引。

## 从问题到向量

业务示例：问题“取消折扣后，哪些历史行为需要回归？”希望找到历史折扣需求/用例。Embedding模型把每段文档检索文本、查询编码为固定维数的数值向量，供相似度检索使用；不在这一步生成回答或选择历史文档。

可表示为f(text)→[v1,...,vd]。这是模型训练得到的表示函数，不是逐字ASCII编码、关键词词频表或可逆压缩。训练可使相关文本表示更接近，但具体模型训练细节本节未验证，不能把这种目标当成每次检索正确的保证。真实单个坐标通常不能直接命名为“折扣程度”等业务含义；坐标含义由整个模型空间共同决定。

2048维是每段文本输出2048个数，不是2048个token、2048段文档或2048字符窗口。相同模型/配置空间下，不同长度输入仍有相同输出维数；内容细节可能在表示中损失。维度更高不自动意味着业务检索更好。

## 手算与本机数值演示

以下二维向量由课堂人工指定，文字关系只是帮助理解，不是embedding-3输出，也不是语义质量测量。

q=[1,0]；A=[3,1]；B=[0,2]；C=[-1,0]。

- 点积q·A=1×3+0×1=3。
- 长度||q||=sqrt(1²+0²)=1；||A||=sqrt(3²+1²)=sqrt(10)。
- cos(q,A)=(q·A)/(||q||×||A||)=3/sqrt(10)≈0.948683。

| 向量 | 与q的点积 | 向量长度 | 余弦相似度 | 余弦距离1-cos |
|---|---:|---:|---:|---:|
| A=[3,1] | 3 | 3.162278 | 0.948683 | 0.051317 |
| B=[0,2] | 0 | 2 | 0 | 1 |
| C=[-1,0] | -1 | 1 | -1 | 2 |
| 10A=[30,10] | 30 | 31.622777 | 0.948683 | 0.051317 |

最后一行说明：正比例放大向量，点积和长度变大，但方向不变，因此余弦相似度不变。取值范围[-1,1]；几何上的反方向不等于自然语言中的业务否定。零向量无方向，余弦公式分母为0，当前编码合同拒绝零向量。

本机用标准库math.hypot与乘积求和运行，得到上表六位小数。没有模型参与。

单位化是v/||v||，会把长度缩放为1；两个非零单位向量的点积等于原余弦相似度。项目normalize_embedding_response中的normalize指响应整理，不执行这一数学缩放，实际vector用list(vector)保存。不要把响应规范化与向量单位化混同。

## 当前项目的真实数据流与边界

```text
上一节EncodingInput.embedding_text
 → DenseEncoder.encode_batch(inputs, remaining_seconds)
 → OpenAICompatibleEmbedding.embed(texts, timeout_seconds)
 → SDK embeddings请求 / 响应JSON
 → normalize_embedding_response
 → (ProviderBatchResult, request_report)
 → 上层BatchProcessor或QueryEncoder消费
```

DenseEncoder负责单批执行与校验，不自行分块、不选择文档。Provider负责按协议调用服务。向量模型在服务端执行；当前项目没有实现或训练Embedding神经网络。后续Chroma消费显式提供的向量并建立相似度索引，当前collection的embedding_function=None、hnsw.space=cosine；检索时消费查询向量。存储/ANN机制和距离到score的适配留到第4/5章。

实际公开core-demo配置model=embedding-3、expected_dimensions=2048、request_dimensions=null。expected_dimensions只检查返回长度，不能把3维向量补成2048维；request_dimensions非空时才发送dimensions参数。null表示不主动发送该参数。可用维度由具体模型/服务接口决定，不能任意改个期望值就获得新维度。

本节测试使用synthetic-model、expected_dimensions=3；不能拿其人工数值表示真实模型语义效果。

模拟原始响应顺序：index=1→[2,1,0]，index=0→[1,0,0]。规范化后：

```text
vectors = [[1,0,0],[2,1,0]]
input_ids = [第一份输入ID,第二份输入ID]
input_hashes = [第一份embedding_text指纹,第二份embedding_text指纹]
model_space_id = 当前模型配置身份
returned_model / source_kind / usage / usage_status
```

normalize_embedding_response通过vectors[index]放回输入顺序，不能直接按响应数组位置绑定来源。第二个向量长度sqrt(5)，返回后仍是[2,1,0]，没有单位化。request_report另外记录请求次数、HTTP状态、响应字节、耗时和固定错误码，不与服务token观察混为一谈。

## 主要分支

| 条件 | 执行与结果 |
|---|---|
| 合法非零有限向量、维度/模型/数量/index正确 | 绑定输入ID/hash并返回ProviderBatchResult与report |
| 空批次/多批次/错误输入身份或超时参数 | Dense预检拒绝，不发请求；空任务由上层处理 |
| 长度不等于expected_dimensions | invalid_embedding_response，不补零、不裁剪 |
| bool、NaN/Infinity或零向量 | invalid_embedding_response，不进入索引 |
| 重复/缺失/非法index，数量或模型不符 | 整批响应拒绝，不返回部分向量 |
| 请求成功但usage缺失/非法 | 有效向量保留，usage未知，不能虚构token或费用 |
| 网络/执行失败 | EmbeddingExecutionError携带安全请求观察；重试/预算细节见3.6 |

相同维度只是可比较的必要条件之一，还必须模型/表示空间兼容；即便维度相同也不能混用两个不同模型的向量。向量相近不证明需求生效、规则正确或足以回答；“开关开启生效”和“开关关闭生效”主题相近，关键条件相反。精确数字/编号/否定条件仍须检索后读证据，双路/重排帮助改善但不提供正确性保证。

## 关键代码与Debug Test

正常响应：`tests/test_encoding_validation.py::test_response_restores_index_and_binds_ids_hashes`，无参数。Test Explorer→Debug Test；测试第25行入口断点，F11进入validation.py:70。第78行执行后vectors=[None,None]；第80行后观察index/vector，第86行后看vectors的槽位；循环完成得到按输入排列的两行。第91行返回ProviderBatchResult，Shift+F11回测试看result.vectors/input_ids。无模型/网络替身，因为直接传人工payload，不发请求。

Dense完整协议路径：`tests/test_dense_encoder.py::test_actual_dense_path_preserves_source_and_reorders_indices[query]`，参数ID=query。输入两问“开关正常”“异常条件”，编码前缀由测试配置提供，响应为反序的[1,2,3]/[2,2,3]。第23行断点，F11进DenseEncoder.encode_batch；第26行执行后观察payload['data']，第27行进入normalize_embedding_response，再回测试第24–29行查看结果和wire['input']。可F5直达生产边界，暂不展开SDK启动内部。

该测试调用真实Dense/Provider/SDK，但factory在test_openai_embedding.py:64把httpx.HTTPTransport替换成httpx.MockTransport派生类，并固定生产边界时钟。没有联网/真实Key；report里的HTTP200和usage=7来自人工响应。source_kind='service'是生产路径字段，不等于真实服务验证。

故障路径：`tests/test_encoding_validation.py::test_bad_response_never_becomes_vectors[zero]`，参数ID=zero。第46行注入[0,0,0]，第49行进入生产；validation.py:84执行后norm=0，第85行抛ValueError，第94行转换EncodingError(invalid_embedding_response)，被测试pytest.raises捕获，测试通过。其他精确ID：dimension/bool/nan。

跨层失败：`tests/test_dense_encoder.py::test_bad_vectors_keep_transport_observation_without_result[zero]`，模拟HTTP200后返回零向量；validation失败被DenseEncoder的EncodingError分支包装为EmbeddingExecutionError，保留attempted_requests=1/http_status=200；没有成功result。WATCH观察已有变量，不重执行encode_batch或Provider方法。

## 实际验证

```sh
.venv/bin/python -m pytest -q \
  tests/test_encoding_validation.py::test_response_restores_index_and_binds_ids_hashes \
  'tests/test_encoding_validation.py::test_bad_response_never_becomes_vectors[dimension]' \
  'tests/test_encoding_validation.py::test_bad_response_never_becomes_vectors[bool]' \
  'tests/test_encoding_validation.py::test_bad_response_never_becomes_vectors[nan]' \
  'tests/test_encoding_validation.py::test_bad_response_never_becomes_vectors[zero]' \
  'tests/test_dense_encoder.py::test_actual_dense_path_preserves_source_and_reorders_indices[query]' \
  'tests/test_dense_encoder.py::test_bad_vectors_keep_transport_observation_without_result[zero]'
# 7 passed in 0.66s
```

本节只运行数值演示与上述确定性测试，没有真实模型调用/向量库读写/真实资料质量评测。L1存在和L2实质由已有Dense/Provider/响应校验源码核对；L3由真实SDK+MockTransport测试确认输入文本、响应index与来源绑定接线，不能外推为真实服务语义质量。本节不改源码、依赖、.env或运行配置；构建不适用，不跑全量测试。文档git diff --check退出0。

## 学习证据与唯一下一步

3.2已讲解，助手完成手算核对与定向验证；用户理解待反馈，独立调试/实现/追问未评估。下一节3.3：分词、词频与稀疏表示，从中文词、数字和技术标识符进入SparseEncoder；暂不展开BM25完整评分公式。
