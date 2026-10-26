# Lesson 21：阶段B·3.3 分词、词频与稀疏表示

日期：2026-10-23，第3章共6节，本节第3节。目标：从具体字符串追踪SparseTokenizer→SparseEncoder→SparseRecord，理解词项、原始TF、长度、查询去重与BM25前置数据。本节不展开BM25完整公式。

## 职责与数据流

业务问题里常有discount_enabled、TC-01、0/1/0.5等精确字面量。当前Sparse路径提取这些词项及出现次数，供后续BM25使用；它不调用Embedding/聊天模型，不理解参数绑定或判断需求生效。

```text
EncodingInput.retrieval_text
 → SEGMENTS提取中文连续串/ASCII数字与技术标识符
 → 中文进入jieba搜索分词，ASCII匹配片段整体保留
 → 中文最小词长过滤、可配置小写
 → tokens（保留顺序与重复）
 → Counter(tokens)、总词项数、不同词项数
 → SparseRecord（输入ID/hash、tokenizer_id、上述统计）
 → 后续资料包/BM25索引
```

Dense消费embedding_text；Sparse消费retrieval_text，不把Dense前缀作为关键词。这里的分词也不是Embedding服务内部的tokenizer，两者计数不能互当服务token用量。

## 本机真实分词例子

输入：`开关 关 开关 TC-01 cvr_ltv route=1 threshold=0.5`。

当前公开示例为min_chinese_term_length=2、lowercase=true；实际jieba0.42.1、搜索模式、HMM=False。本机输出：

```python
tokens = ['开关', '开关', 'tc-01', 'cvr_ltv', 'route', '1', 'threshold', '0.5']
term_frequencies = {'开关': 2, 'tc-01': 1, 'cvr_ltv': 1,
                    'route': 1, '1': 1, 'threshold': 1, '0.5': 1}
doc_length = 8
unique_terms = 7
```

retrieval_text_sha256与输入相同，核对True。只改派生记录，不改输入文本/原文。

### 中文与ASCII的不同分支

- 开关：jieba识别出的两字词，满足长度2，保留；不是先把每个汉字永久拆开后再拼回。
- 单独关：分词产生后因词长1被过滤；最小词长不是整段中文的长度，更不是所有词的统一限制。
- TC-01：ASCII词法片段整体保留，小写后tc-01；不拆tc/01。
- cvr_ltv：内嵌下划线保留。
- 0、1、0.5：不套中文最小长度，单字符数字仍保留。
- route=1：得到route和1，等号不作为词项；本层没有建立键值结构或执行参数判断。

另一本机输出：`0 0.5 0.50 -1 +2 1e-3 v1.2 module.path _`→`['0','0.5','0.50','-1','+2','1e-3','v1.2','module.path']`。

0.50和0.5分别保存，未做数学等价归一；单独下划线被过滤。大小写转换只影响派生词项，原始来源仍保留。中文单字可能漏召回，这项已确认取舍不能当质量最佳；词项匹配也不证明数字属于哪个参数。

## 搜索模式：为什么人工智能有三个词项？

本机输出`人工智能`→`['人工','智能','人工智能']`，doc_length=3。

已核对安装的jieba0.42.1源码__init__.py：get_DAG/calc及__cut_DAG_NO_HMM使用词典候选与词频路径选择；cut_for_search先调用cut，再对长词补充词典中存在的2字/3字子词，最后yield原词。并非把所有长度为2的组合无条件输出，也不是只按最长词切。

当前HMM=False不启用HMM新词识别分支。搜索模式输出可以重叠：人工、智能、人工智能覆盖同一段原文，但都是独立词项，均参与后续统计。HMM概率模型内部不在本节展开。

cut_for_search返回生成器，调用时得到可迭代对象；在生产for term in candidates循环请求下一项时，jieba才逐项yield输出。上限按实际产生的候选数量计数，在中文长度过滤前增加，超限抛错，不保留一个截断成功结果。

## TF、长度与稀疏表示

本模块TF是原始出现次数：TF(开关)=2，其他上述词各1；不是除以总长度后的频率。doc_length=len(tokens)=8，包含重复和搜索模式子词；unique_terms=len(set(tokens))=7，不是字符数或唯一词数当作总长度。

为什么叫稀疏：概念上，全库词表的每个词可对应一个坐标，大部分词在单个片段中出现次数为0。例如小词表[开关,tc-01,日志]，人工文档[开关,开关,tc-01]可写成[2,1,0]，只存非零项就是{'开关':2,'tc-01':1}。此为解释用的小词表，不是当前实际索引维度。

当前SparseEncoder实际保存词项及计数，还没有在此函数中计算BM25权重、构建完整矩阵或对查询评分。后续BM25会结合文档频率、长度等统计；完整公式留到第5章。词频越多不意味着相关性可无限增加。

与Dense相比，本项目的稀疏坐标对应显式词项，Dense坐标是模型学到的表示；不把所有Sparse算法都说成词频，当前路线明确为词项统计→BM25。

## 查询去重、空结果与失败

query_terms先生成正常SparseRecord，再按第一次出现的顺序去重：`['开关','tc-01','cvr_ltv','route','1','threshold','0.5']`。文档tokens与TF仍保留重复；查询记录也保留原始重复，query_terms只是供后续查询消费的派生列表。当前查询重复词不通过该列表重复累计评分，不是所有检索模型都必须这样做。

`list(dict.fromkeys(record.tokens))`等价于逐个读取词项，只在首次出现时加入输出列表。保留顺序方便稳定复现，不表示词项已经按重要程度排序。

| 情况 | 返回/异常 |
|---|---|
| 正常文本 | tokens/TF/长度与来源身份绑定的SparseRecord |
| 只有关或标点/下划线 | tokens=[]、TF={}、长度0；编码正常，无占位词 |
| 中文最小长度/小写规则改变 | 词项可能改变，tokenizer_id改变；不能混用旧分词索引 |
| 超词项资源上限 | sparse_term_limit，不截断 |
| jieba调用异常 | sparse_tokenization_failed，固定码日志，不静默返回[] |
| 词典/缓存读取、初始化失败 | 对应明确错误，不静默改用另一套分词规则 |
| 输入/hash/模型表示身份不符合编码合同 | 校验失败，不返回部分记录 |

空词项不证明业务无答案；后续关键词路可能无命中，Dense仍可能提供候选。它也不是“知识库为空”。大小写/词典/词长策略必须在文档和查询两端一致。

tokenizer_id覆盖jieba版本、词典内容hash、词法策略、search/HMM、词长与小写规则；缓存路径/资源上限不改变词项语义身份。初始化核词典与缓存，词项生成使用真实jieba，不是占位分词器；本节仅说明资源边界，不展开缓存完整实现。

## 关键代码与Debug Test

核心文件：encoding/sparse_tokenizer.py:130 tokenize；encoding/sparse_encoder.py:22 encode_batch与:36 query_terms；core/sparse_types.py:21 __post_init__核对Counter、长度和指纹，序列化再次校验。

正常入口：`tests/test_sparse_encoder.py::test_real_terms_tf_query_dedup_prefix_and_roundtrip`，无参数。测试第24行调用encode_batch，Test Explorer→Debug Test，F11进入生产；F5到sparse_encoder.py:29可跳过暂不学习的缓存/配置启动。

- 选encode_batch栈帧，看item.retrieval_text；此时tokens尚未赋值。
- F11到SparseTokenizer.tokenize，在第134行执行后看value；第135行后看走ASCII列表还是中文生成器。
- 第137行后term/generated才存在；第141行判断单字关，continue时不append；第142行后看terms。
- 返回encode_batch后tokens产生，F10到第31行后看records[-1].tokens/term_frequencies/doc_length/unique_terms。
- 回测试第29行调用query_terms，查看record.tokens与返回的去重列表；不要在WATCH重复执行编码函数。

搜索重叠入口：`tests/test_sparse_encoder.py::test_complete_numbers_identifiers_and_search_overlap`，无参数；第38行人工智能断点，必要时进入jieba.cut_for_search，看词典命中的子词和最后yield w。

空词项入口：`tests/test_sparse_encoder.py::test_empty_terms_are_valid_not_execution_failures[关]`，文本关，正常返回空统计；pytest可能在界面转义中文参数ID，按原始参数值关选择对应项。

故障入口：`tests/test_sparse_encoder.py::test_terms_and_resource_limits_and_library_failure`，无参数。第141行a b c触发上限2，第3个词在tokenize第138行抛sparse_term_limit。第143行定义故障函数，第144行monkeypatch替换该实例engine.cut_for_search，第145行调用，异常被tokenize第145行转为sparse_tokenization_failed；pytest.raises捕获，测试通过。正常路径使用真实jieba，只有此故障注入路径替换库方法。

接线测试：`tests/test_sparse_wiring.py::test_m1_m2_to_real_sparse_binds_ids_hashes_and_preserves_originals[labeled_case]`，参数ID=labeled_case（另raw）。真实Loader/M2→72输入/12用例→Sparse，来源/hash/统计与原片段不变；无模型和索引写入。

## 本次实际验证

```sh
.venv/bin/python -m pytest -q \
  tests/test_sparse_encoder.py::test_real_terms_tf_query_dedup_prefix_and_roundtrip \
  tests/test_sparse_encoder.py::test_complete_numbers_identifiers_and_search_overlap \
  tests/test_sparse_encoder.py::test_configured_minimum_and_lowercase_share_cache_but_not_token_identity \
  tests/test_sparse_encoder.py::test_empty_terms_are_valid_not_execution_failures \
  tests/test_sparse_encoder.py::test_terms_and_resource_limits_and_library_failure \
  tests/test_sparse_wiring.py::test_m1_m2_to_real_sparse_binds_ids_hashes_and_preserves_originals
# 8 passed in 4.20s
```

单独分词探针读取公开示例YAML，只在内存指定临时缓存。首次临时路径包含macOS符号链接父目录，被sparse_resource_path_invalid明确拒绝；确认父级符号链接后，以Path.resolve得到实际临时目录再运行成功，没有修改或绕过生产校验。缓存写入仅在临时目录，无.env/运行配置/原索引/源码变更。

L1已有Tokenizer/Encoder/Record文件，L2真实分词与统计，L3八项测试含真实M1/M2→Sparse输入/来源配对。本次证明规则及接线，不证明真实知识库召回质量；无模型调用。构建不适用，不跑全量测试；git diff --check退出0。

## 学习证据与唯一下一步

3.3已讲解，助手完成真实分词和定向测试；用户理解待反馈，本人独立调试/实现未评估。下一节3.4：文档/查询编码与模型一致性，解释为什么文本、维度相同也不能任意混用不同编码配置。
