# Lesson 32：阶段B·5.3 TF、DF、IDF、长度归一化与BM25

日期：2026-10-23。第5章共8节，本节第3节。目标：用三条显式词项片段理解词频/稀有度/长度归一化，再核对当前bm25s Lucene实现和SparseRetriever调用链。本节先固定全库统计；已实现的global/scope差异留5.4，不更改参数或分词策略。

## 输入输出与统计单位

QueryPipeline.prepare已经生成query_terms；SparseRetriever消费同一PreparedQuery，使用固定BM25索引评分并返回SparseResult(prepared,top_k,statistics_scope,hits)，每个SparseHit为rank、完整Chunk、正分score。

BM25 SDK把每个索引行叫document，本项目一行对应一个Chunk。所以N/DF/avgdl按参与统计的片段计，不是Markdown文件数。doc_length是SparseEncoder保存的tokens数量，包含重复词；不是字符数，也不是模型计费token数。实际tokens来自retrieval_text，可能包括标题/结构上下文，不一定只有原文正文。

本节明确构造词项，不声称它们是某段真实文档的分词输出：

```text
P1 = [开关, 关闭, 回归]                     长度3
P2 = [开关, 开关, 开启]                     长度3
P3 = [回归, 日志, 参数, 接口, 超时, 重试]    长度6
查询词项 = [开关, 关闭]
```

N=3，avgdl=(3+3+6)/3=4。示意/现有测试取k1=1.5、b=0.75，不代表最优参数结论。

## TF与DF：同一个词的两种统计

TF(t,d)是某词在某片段出现的原始次数。DF(t)是有多少片段包含这个词，每片段最多计1。

| 词 | P1 TF | P2 TF | P3 TF | DF |
|---|---:|---:|---:|---:|
| 开关 | 1 | 2 | 0 | 2 |
| 关闭 | 1 | 0 | 0 | 1 |
| 回归 | 1 | 0 | 1 | 2 |

开关总出现3次，但DF=2；P2的重复词不让它变成两个含词片段。SparseEncoder用Counter(tokens)保存TF，BM25建库按各行统计DF。

## IDF：稀有词贡献更大

当前Lucene IDF：

```text
idf(t) = ln(1 + (N - df(t) + 0.5) / (df(t) + 0.5))
```

自然对数ln把比例转换成平滑权重；0.5与外层+1属于当前变体的平滑。代入本例：开关df2→idf0.470004；关闭df1→idf0.980829。稀有词更有区分力，但不代表它在业务上一定重要；平滑后即使某词所有片段都有，当前IDF也不是自动0。

## TF饱和与长度归一化

当前每个词对一个片段的贡献为：

```text
contribution(t,d) = idf(t) * tf(t,d) /
    [tf(t,d) + k1 * (1 - b + b * dl(d) / avgdl)]
```

先单看长度等于平均长度时：dl/avgdl=1，TF部分变成tf/(tf+k1)。k1=1.5时，tf1→0.4、tf2→0.571429、tf4→0.727273。次数越多通常贡献越大，但增长逐渐变慢，不按次数线性翻倍。这叫TF饱和，避免某词反复堆叠无限主导排名。

长度部分L=1-b+b*dl/avgdl。本例短片段dl3→L0.8125，长片段dl6→L1.375。其他条件相同，长片段分母更大，单词贡献更低；它在更长文本中偶然出现一次的区分力较弱。这是启发式，不保证短片段业务上更相关。

k1控制TF曲线；b控制长度修正强度，b0不按长度修正、b1按dl/avgdl完整参与。具体值经项目配置提供；不是调大越好，本节不修改。

同一个回归词在P1/P3中TF都1，IDF相同，长度不同，得分分别0.211833/0.153471，直接展示长度因素。

## 把查询各词的贡献相加

P1中开关/关闭的TF均1，长度相同，所以TF部分均为：

```text
1 / [1 + 1.5*(1 - 0.75 + 0.75*3/4)]
= 1 / 2.21875
≈ 0.450704
```

开关贡献≈0.470004×0.450704=0.211833。
关闭贡献≈0.980829×0.450704=0.442064。
总分≈0.653897。

原生SDK与独立公式逐项对照结果：

| 查询词项 | P1 | P2 | P3 |
|---|---:|---:|---:|
| 开关 | 0.211833 | 0.292041 | 0 |
| 关闭 | 0.442064 | 0 | 0 |
| 回归 | 0.211833 | 0 | 0.153471 |
| 开关+关闭 | 0.653897 | 0.292041 | 0 |

P2虽然开关出现两次，仍不及同时命中稀有关闭词的P1；P3没匹配这次查询，0分。P2的开启并不会被BM25自动理解成否定关闭需求；未匹配关闭贡献0，而不是语义冲突扣分。BM25主要按词项统计，不理解条件、顺序或历史规则有效性。

query_terms已由M3去重；Sparse查询入口也拒绝重复词，不另加查询词频权重。保存的文档tokens仍保留重复，以计算TF。

## 为什么公式和一些教材不同

核对本机bm25s0.3.13，scoring.py:115/125的TF部分为tf/(tf+k1*L)，190行IDF为上式。项目storage/bm25_backend.parameters显式method='lucene'、idf_method='lucene'、float64，audit_model也按同一公式重核；固定delta字段不进入本Lucene公式。

一些常见BM25写法分子还有(k1+1)。当前SDK公式没有它；同一固定k1与相同其余公式下，额外乘(k1+1)只是统一正比例缩放，不改变该次候选排序，但会改变原始分数/阈值尺度。不能据此声称所有BM25变体等价；跨实现比较必须核IDF、TF与长度公式。

BM25分数不是0–1概率，不与Dense score直接相加。本项目结果带score_kind=bm25s_lucene_global_v1或scope_v1标识统计口径；融合在5.5展开。

## 真实查询链：谁算统计，谁选结果

```text
HybridSearch._sparse传sparse_top_k/statistics_scope
  → SparseRetriever.retrieve(prepared)
      → 校验固定版本、范围、三类产物
      → 从prepared.encoding取query_terms，不重编码/分词/选latest
      → BM25Store.query
          → _prepare/_load_index：原包与已存权重审计
          → 按document_ids选择候选行
          → 本节global：model.get_scores(query_terms)
          → 核float64/数组形状/有限非负
          → 只保留范围内且score>0的行
          → rows[index].item_id映射固定Bundle的完整Chunk
          → (-score,chunk.id)排序，截取top_k
      → SparseHit从1排名 → SparseResult
```

global中N/DF/avgdl及每个词-片段贡献已在M4建库时计算/保存；查询主要取相关倒排列，按行累加，不每次重新扫描正文算TF。bm25s.BM25.get_scores在本机__init__.py:622把词转ID，再调用581行get_scores_from_ids消费data/indices/indptr；前述手算是解释这些预存权重，不代表在线逐片段重算公式。

Sparse返回正文直接来自固定Bundle，不把Chroma当唯一正文库；上层仍审计Chroma，保持三产物合同。scope模式已实现但需在内存重建局部统计，其排序影响在5.4专讲，本节不推断与global等价。

## 正常、空态与失败

| 情况 | 当前行为 |
|---|---|
| 合法匹配词 | 累加词贡献，返回正分完整Chunk，数量≤top_k |
| 查询词项为空/全部OOV/无正分 | 合法空hits，不说明问题业务无答案 |
| 范围为空/无词表 | 审计后空结果，不掩盖坏索引 |
| 重复/非法query_terms或未知文档ID | 明确参数错误 |
| 得分shape/dtype不符、NaN、负数或SDK异常 | 整次报错，不返回部分结果或假空态 |

本项目Lucene正权重路径只保留score>0，所以不像Dense按数量取近邻那样总有足量候选。空terms在model.get_scores前返回；当前SDK该方法会访问query_tokens_single[0]，不应直接调用空列表。未知词不贡献，不是“IDF被设成0”的同义说法。

## Debug Test入口

### 从保存权重到结果

`tests/test_sparse_retrieval.py::test_native_scores_match_hand_formula_and_scope_before_top_k[global]`，精确参数ID=global。Test Explorer点Debug Test，先在测试61行停；此时临时包/原生BM25已保存，手算scores已准备；F11进入BM25Store.query→storage/bm25_query.py:8，不必重新走全部建库。

在query_index第22行观察len(records)、len(selected)、query_terms、statistics_scope。global选择全部行作为统计映射；第29行执行后才产生scores，此时先观察scores.shape、scores.dtype和scores[:5].tolist()，第32–33行检查后才可作为有效得分。第35–37行跟一行index/score，看rows[index]['item_id']与保存Chunk的对应；第38行按高分优先排序，未重取词项或编码。

回测试62–65行观察[h['score'] for h in result]与手算字典scores，先选择测试栈帧再看scores（与生产帧同名但含义不同）。本测试真实BM25S保存/加载/评分，文档编码为替身、材料为合成；手算函数第41–50行独立表达公式，未替换生产get_scores。

### 从准备结果进入SparseRetriever

`tests/test_sparse_retrieval.py::test_retriever_pins_scope_and_keeps_encoding[global]`，参数ID=global。在retrieve调用行断点，F11到query/sparse_retriever.py:23；第40行左右看prepared.encoding.query_terms，第43行后看hits。catalog.read被pytest.fail替换，编码计数仍各1次（来自prepare）；不是第二次Embedding/分词。完整Chunk/score_kind与模式一起返回。

### 故障不是零命中

`tests/test_sparse_retrieval.py::test_native_score_faults_are_not_empty_results[nan-global]`，精确ID=nan-global。测试118行把真实bm25s.BM25.get_scores换成bad；第116行注入NaN。query_index第33行核非有限得分失败，StorageError传到SparseRetriever边界，包装QueryJobError(stage=sparse,code=bm25_integrity_failed)，保留已知active/encoding_report。测试122行pytest.raises捕获，因此该异常测试通过。io-global在bad第112行抛OSError，期望bm25_query_failed；不要把测试成功解释为生产没有异常。

## 本次实际验证

标准math独立公式与bm25s.BM25原生内存索引逐项对照，np.allclose(rtol=1e-12,atol=1e-15)通过；三片段输出见上表，实际N3/avgdl4，最终[0.653897,0.292041,0]。这只是教学数值探针，不是用户真实业务标注。

```sh
.venv/bin/python -m pytest -q \
  tests/test_bm25_integrity.py::test_hand_scoring_matches_persisted_model \
  'tests/test_sparse_retrieval.py::test_native_scores_match_hand_formula_and_scope_before_top_k[global]' \
  'tests/test_sparse_retrieval.py::test_retriever_pins_scope_and_keeps_encoding[global]' \
  tests/test_sparse_retrieval.py::test_sparse_empty_terms_unknown_terms_and_empty_scope \
  'tests/test_sparse_retrieval.py::test_native_score_faults_are_not_empty_results[nan-global]' \
  'tests/test_sparse_retrieval.py::test_native_score_faults_are_not_empty_results[io-global]' \
  'tests/test_sparse_retrieval_wiring.py::test_native_sparse_modes_after_restart[normal-False]' \
  'tests/test_sparse_retrieval_wiring.py::test_native_sparse_modes_after_restart[all-empty-False]'
# 13 passed in 10.39s
```

两个wiring场景从真实临时Bundle/Chroma/BM25/SQLite与SDK MockTransport编码开始，源目录移开后新进程实际跑global/scope并核完整Chunk与手算，禁止额外编码/目录重选/网络；BM25文件字节和mtime不变，model_requests=0。all-empty验证全空词项；不当真实资料质量或性能通过。

L1 SparseRetriever/BM25Store.query/结果合同已存在；L2实际消费保存词项、原生预存权重、范围及正分排序；L3有13项与数学探针证据。只改学习记录，没有源码/依赖/真实.env/原索引修改；构建不适用，未跑全量，git diff --check退出0。

## 学习证据与唯一下一步

5.3已讲解，助手核当前SDK源码/数值/接线；用户理解待反馈，本人独立调试/实现未评估。讲解覆盖24/34节，余10节（第5章5节，第6章5节）。唯一下一步：5.4全库与范围统计，固定同一查询/候选，比较统计母体改变如何影响N、DF、avgdl与排序。
