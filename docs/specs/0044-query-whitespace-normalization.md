# Spec0044：优化分片1／查询首尾空白与指纹合同

日期：2026-10-26。状态：已实现/接线/本地验收；D1/D2/D3均已确认。验收结果见末尾记录。

## 1. 授权、目标与依赖

用户要求先依次编写7个分片Spec，讨论实际决策点，再逐片实施；每片结束解释下一片做法。本轮授权包含Spec编写和讨论后的实施，不包含发布、push、旧数据删除或真实配置修改。

本片实现future-work的查询首尾strip：原始输入可核验，Dense/Sparse/重排使用同一实际查询。内部空格、换行、Unicode、数值、URL和技术语法保持，不增加查询改写、缓存或索引重建。

当前QueryProcessor.process→prepare_query_encoding_input只以strip检查非空，实际仍编码原字符串；QueryPipeline将该字符串的hash绑定PreparedQuery；重排消费encoding.input.retrieval_text；ResponseBuilder输出同一query_sha256。

## 2. 已确认D1：实际查询指纹与原始输入指纹

推荐：query_sha256在新执行结果中统一表示实际查询的SHA256；新增raw_query_sha256表示原始输入。原始全文只在内存查询上下文保留，不自动加入最终证据、报告或日志。最终证据schema_version从1增至2，以标识新增字段和明确的清理语义。

另一可行方向是保留最终query_sha256为原始输入hash，另加retrieval_query_sha256；代价是最终结果与EncodingInput.query_sha256需要使用不同含义。推荐统一实际查询语义，避免两路与重排引用不同hash。

2026-10-26，先用带首尾空格/不带空格两次查询解释原始输入与实际查询、两个指纹及最终结果格式版本，用户明确回复“我觉得你的方案没问题”，确认采用上述推荐合同。该确认包含本片查询字段语义及最终证据schema2调整；不代表确认切分或存储格式D2/D3。后续D2在0046、D3在0048，按一问一答讨论；讨论后沿已有实施授权逐片执行，不再重复确认D1。

## 3. 输入、输出与调用链

正式执行顺序：验证原始字符串类型/UTF-8→保存raw_query及其hash→仅strip首尾→拒绝空文本→按实际查询及query_prefix检查输入预算→固定活动版本/范围→一次Dense/Sparse编码→重排→最终证据。

QueryProcessor的私有结果增加raw_query；query为清理后文本。QueryEncoder.encode和prepare_query_encoding_input的字符串入参签名保持；直接使用它们也采用同样strip语义，不能只在CLI清理。低层EncodingInput继续只持有实际检索文本及现有两文本hash，不向文档编码输入添加查询字段。

QueryEncodingResult及PreparedQuery各增加keyword-only、可省略的raw_query_sha256；新生产路径显式填写，旧构造路径省略时只按旧输入自身hash解释，不声称恢复了丢失的原始输入。原始全文由调用方输入及QueryProcessor私有上下文持有；hash只能供比对，不能还原全文。

QueryPipeline把processed.raw_query传给QueryEncoder.encode；后者在调用prepare_query_encoding_input清理前保存raw hash。编码后的retrieval_text必须等于processed.query，两个结果中的raw hash必须等于processed.raw_query的hash。不能把已清理的query传给编码器后再误标它为原始输入。

EncodingInput.query_sha256、query-前缀item_id、retrieval_text_sha256及任务input_fingerprint都根据实际查询产生；embedding_text_sha256根据配置前缀+实际查询产生。raw hash不混入编码任务input_fingerprint，否则等价查询会产生不同编码身份。

ready态要求QueryEncodingResult与PreparedQuery的实际hash、raw hash分别一致；unactivated/empty_scope/empty_index也保存两个hash，不虚构编码报告。不存在本次原始全文落日志或自动持久化的路径。

## 4. 兼容与失败

旧QueryEncodingResult/PreparedQuery JSON可由from_dict识别原有精确字段集合；旧数据的query_sha256按保存时文本解释，raw hash补为同一值。旧序列化数据加载时不重新strip、不重算历史向量和报告。新数据使用扩展精确字段集合，任意其他未知字段仍拒绝。

to_dict输出新合同；旧构造调用保持可用，历史JSON读取兼容不代表旧消费者能读取新JSON。最终输出schema2的兼容边界须在README说明。旧最终证据JSON不自动重写。

纯空白、非字符串及非法UTF-8在网络之前失败。输入字节上限覆盖前缀+实际查询，不能拿清理前字节数冒充模型输入；原始查询不新增未要求的长度限制。原有范围、revision、固定版本、用量和错误stage合同保持。

## 5. 影响文件

生产：query/query_processor.py、query/pipeline.py、encoding/input_preparer.py、encoding/query_encoder.py、core/query_encoding_types.py、core/query_preparation.py、response/builder.py；检查reranking/core.py实际消费者。测试：test_query_processor.py、test_encoding_inputs.py、test_query_encoding.py、test_query_preparation.py、test_query_preparation_wiring.py、test_evidence_response.py、test_core_app.py。超过8文件，无新服务/依赖/配置改动。

只按新需求更新“保留首尾空白”的旧合同断言；保留完整性、预算、来源、错误及序列化断言，不放宽验证、不改测试基础设施。

## 6. 红灯、验收与回退

先补失败用例：首尾空格/制表/换行、Unicode首尾空白、无空白、多行及内部双空格、TC-01/cvr_ltv/0.5；证明等价输入的实际编码文本/两路输入/编码指纹相同，raw hash不同。覆盖直接编码、正式Pipeline、四态、重排实际query、schema2最终JSON与两类旧JSON往返。纯空白证明两路调用0。

L1检查影响文件；L2检查实际清理/双hash/严格验证；L3由原生索引+SDK MockTransport验证正式入口到最终证据，外部模型请求0。不把strip合同通过当真实检索质量提升。

计划命令（尚未执行本片新功能验收）：

```sh
.venv/bin/python -m pytest -q tests/test_query_processor.py tests/test_encoding_inputs.py tests/test_query_encoding.py tests/test_query_preparation.py tests/test_query_preparation_wiring.py tests/test_evidence_response.py tests/test_core_app.py --tb=short
.venv/bin/python -m pytest -q tests --tb=short
.venv/bin/python -m compileall -q naiyue_rag experiments tests
.venv/bin/python -m pip check
git diff --check
```

无打包构建命令，构建不适用；compileall仅语法检查。回退只涉及本片代码，不改索引/原材料/旧结果；有其他未提交工作时不得执行自动git回滚。完成后讲解0045如何先保证旧切分策略可读，再进入中文标点行为。

## 7. 2026-10-26实施记录

新增tests/test_query_normalization.py，先执行得到8 failed in1.54s，失败点为未清理、缺raw字段、预算按未清理文本计算和最终schema仍1；随后最小实现得到8 passed in2.56s。再补旧含空格JSON保持原输入/向量/报告及未激活双hash两项，现共10项新增测试。

实际接线为prepare_query_encoding_input统一strip→QueryEncoder记录raw hash→QueryPipeline用原始字符串调用编码器并分别核实际/raw绑定→PreparedQuery→ResponseBuilder schema2。两个结果类型增加keyword-only可选raw hash，旧精确JSON形状可读，显式null/未知字段拒绝；文档EncodingInput/EncodingResult和索引格式保持。

按批准的新行为同步原“保留首尾空白”的合同断言，未放宽错误/完整性断言、未改conftest或公共测试helper。额外核对test_query_encoding_wiring.py的真实SDK模拟HTTP输入、test_reranking.py的backend实际query，以及test_core_app.py的真实CLI双hash。新增测试文件和这些消费者比初稿影响表更完整，本节明确补入实施范围。

实际定向命令：

```sh
.venv/bin/python -m pytest -q tests/test_query_normalization.py tests/test_query_processor.py tests/test_encoding_inputs.py tests/test_query_encoding.py tests/test_query_encoding_wiring.py tests/test_query_preparation.py tests/test_query_preparation_wiring.py tests/test_reranking.py tests/test_evidence_response.py tests/test_core_app.py --tb=short
# 236 passed in 72.56s (0:01:12)
```

之后在新进程准备的四态测试中补双hash实际值断言，已纳入本片全量命令，不将前述236结果冒充新增断言已经单独运行。compileall退出0；pip check为No broken requirements found.；工作区/暂存区diff检查退出0。

上轮实际收尾命令`.venv/bin/python -m pytest -q tests --tb=short`得到2161 passed in413.27s（0:06:53），此前中断未及时补记，本节补齐该历史运行结果，不称为本轮新跑的全量。当前第2片已继续实施，其完成需单独等待覆盖新增策略测试的最新全量结果。第1片L1/L2/L3齐全，未修改索引/真实配置、未发真实模型请求，不把输入清理合同通过声明为真实资料检索质量提升。
