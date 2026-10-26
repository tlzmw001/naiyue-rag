# Lesson 33：阶段B·5.4 全库与范围统计及排序影响

日期：2026-10-23。第5章共8节，本节第4节。目标：区分返回候选范围与BM25统计母体，复现仅改变母体的排名反转，并走读global/scope真实分支及行映射。只学习已实现双模式，不重新选型或修改配置。

## 两个范围是两件事

候选范围：本次允许哪些文档的片段进入结果，由PreparedQuery.document_ids及投影chunk_ids确定，含此前scope/exclude计算。
统计范围：用哪些片段计算N、DF、avgdl，进而确定词项权重，由statistics_scope决定。BM25的统计单位仍是片段，见Lesson32。

| 模式 | 计算N/DF/avgdl用哪些行 | 可以返回哪些行 |
|---|---|---|
| global | 固定版本已保存的全库索引行 | 仅本次候选范围 |
| scope | 本次候选文档对应的片段行 | 仅本次候选范围 |

global不等于取消文档过滤，scope也不等于沿业务关系自动扩大范围。两者均能返回多个L1/L2的片段，前提是这些文档已在允许集合中；不能凭模式名称推断跨文档推理能力。

## 固定候选和平均长度，只改变稀有度

人工词项例子，不是真实文档质量样本。全库原始行顺序为[A,X,B]：

```text
row0 A = [开关, 开关]    允许返回
row1 X = [开关, 说明]    范围外，不允许返回
row2 B = [校准, 说明]    允许返回

query_terms = [开关, 校准]
selected = [0, 2]
top_k = 2；k1 = 1.5；b = 0.75
```

两种模式中的查询、候选A/B、TF、分词、k1/b和top_k均相同。所有片段长度都2，刻意使两边avgdl也都2，便于只观察稀有度变化。

| 统计量 | global | scope |
|---|---:|---:|
| N | 3 | 2 |
| avgdl | 2 | 2 |
| DF(开关) | 2，A/X | 1，仅A |
| DF(校准) | 1，仅B | 1，仅B |
| IDF(开关) | 0.470004 | 0.693147 |
| IDF(校准) | 0.980829 | 0.693147 |

沿上一节公式：A对开关的TF部分2/(2+1.5)=0.571429；B对校准的TF部分1/(1+1.5)=0.4。

| 模式 | A分数 | B分数 | 仅A/B中的排名 |
|---|---:|---:|---|
| global | 0.268574 | 0.392332 | B → A |
| scope | 0.396084 | 0.277259 | A → B |

global把开关视为较常见词，因此校准的高IDF让B领先；scope内两个查询词同样稀有，A的TF2带来优势。X从未进入返回结果，却参与global统计并影响排序。

这不是过滤泄漏、也不能单凭反转判断哪种更正确。它证明两种排名语义不同。实际语料里片段长度不一定相同，avgdl也可能改变，进一步影响归一化；scope不是只重新算IDF。

## 代码分支：复用全库权重或内存重建局部权重

当前storage/bm25_query.py实际顺序：

```text
_prepare与Bundle.load
  → 校验参数
  → _load_index：先加载/审计已保存全库索引
  → selected：按候选文档选择原始行号
  → 空范围/空词项/空词表时返回空
  ├─ global：保留已加载模型；mapping=全部原始行号
  └─ scope：local=已保存records中的selected行
            全部空tokens则空结果
            新建同参数BM25，在内存index(local.tokens)
            mapping=selected
  → model.get_scores(query_terms)
  → 核float64/长度/有限非负
  → 还原原始行号，过滤范围内正分
  → 按(-score,chunk.id)排序后截top_k
```

global查询可计算全库得分，但第36行过滤后才在第38行截top_k；不是先拿全库top_k再删范围外结果。这与5.1的“范围在结果截断前生效”一致。

scope局部建模直接消费保存的tokens，不重新调用Sparse分词/Embedding、不改活动版本、不保存新BM25文件。既有原包加载/审计步骤仍存在，不能把整个请求说成只读取几条局部记录或零IO。局部模型每次建立，尚未缓存，有额外CPU/内存成本；没有本节性能测量。

## mapping为什么不能直接用局部下标

本例global的得分数组长度3，对应[A,X,B]，mapping=[0,1,2]。scope的得分数组长度2，对应[A,B]，mapping=[0,2]。

```text
scope局部位置0 → 原行0 → A
scope局部位置1 → 原行2 → B
```

第35行zip(mapping,scores,strict=True)把每个局部分数配回原行号，再由rows[index]['item_id']找到完整Chunk。若把局部位置1直接当原行1，就会把B的分数配到X，造成来源错误；当前实现显式维护mapping，并核数组长度与mapping一致。

## 配置从哪里来

独立SparseRetriever配置：SparseQuerySettings(top_k,statistics_scope)，通过load_sparse_query_settings严格YAML加载。示意：

```yaml
top_k: 20
statistics_scope: scope
```

这是教学示意，没有修改本项目实际运行配置。独立示例examples/sparse-query.example.yaml当前为global。

完整Hybrid链使用HybridSettings.bm25_statistics_scope；HybridSearch._sparse第38行把它转换为SparseQuerySettings(cfg.sparse_top_k,cfg.bm25_statistics_scope)，再到SparseRetriever→BM25Store.query→实际分支。不要把单独Sparse配置文件与完整入口Hybrid配置字段混为同一个加载入口。

SparseResult保存statistics_scope，score_kind为bm25s_lucene_global_v1或bm25s_lucene_scope_v1，避免输出省略计分语义。均不改变PreparedQuery的版本/范围/查询词；切换口径不是重新摄取或另选向量模型。

## 如何理解取舍与边界

- global复用已存完整矩阵，适合把词的区分力放在整库背景下判断；范围外文档变动后，新版本统计可影响同一候选排序。
- scope基于局部集合重新统计，适合比较局部语境下的区分力；有效范围改变时，排名也可能变化，且有内存建模成本。范围内各文档的片段数仍可能不同，不意味着按Markdown文件等权。
- 候选范围覆盖全库时，两者统计母体一致；不同子集时不应期待相同分数或顺序。
- 空scope仍是空，不回退global全库候选；局部全空tokens不进入avgdl除法，返回空hits；scope保留范围内空词行，不偷偷丢掉它们重定义N。
- 两种模式都先审计保存索引，scope不能绕过全库索引损坏。局部建立/评分失败明确报错，没有失败后自动改成global的分支。

沿已确认设计保留global默认、scope可选，不重新让用户二选一。真实比较应固定同一查询/候选/版本/标签与其他参数，只改模式，观察证据覆盖、排名、延迟和内存；当前反转例没有业务标签，不能判定哪个质量更好。原始分数不当概率，不跨模式直接套同一个置信度阈值。

## Debug Test：配置 → 分支 → 行映射

### 同一PreparedQuery切换配置

入口：`tests/test_sparse_retrieval.py::test_strict_yaml_roundtrip_and_actual_mode_switch`，无参数ID。Test Explorer点Debug Test，断点放测试第31行。先前第28行已prepare，29–30行循环写临时YAML，先global再scope；不会改真实配置。

F11进load_sparse_query_settings，返回后查看cfg.statistics_scope、cfg.top_k，再进入SparseRetriever.retrieve→BM25Store.query。F5也可先到storage/bm25_query.py:22，避免重复展开已学Bundle审计。

在query_index栈帧：第22行执行后看statistics_scope、selected、mapping、len(records)。第24行global不进if；scope在第25行产生local，第28行index完成后看len(local)与model.scores['num_docs']。不要调用model.index/get_scores作为WATCH。

第29行评分完成后看scores.shape与mapping；第35行开始映射时观察index/score，第37行取rows[index]['item_id']。这里测试样本不等于课堂A/X/B，不预设具体行号或反转；通过数据投影理解映射即可。回测试32–33行核结果模式和score_kind。

本测试使用真实BM25S，Chroma/Dense/Sparse编码为夹具替身，材料/文件为临时合成；不等于真实Embedding质量。独立A/X/B探针提供反转证据，不把测试中的样本冒充同一批词项。

### 两种模式手算与原生保存重开

`tests/test_sparse_retrieval.py::test_native_scores_match_hand_formula_and_scope_before_top_k[global]`及`[scope]`：测试58行选择不同population，61行正式store.query，62–65行比较原生得分、排序与完整Chunk。两个参数分别Debug Test，可对照生产分支，不需要修改测试或IDE。

`tests/test_sparse_retrieval_wiring.py::test_native_sparse_modes_after_restart[normal-False]`、`[mixed-False]`、`[normal-True]`：新进程从同一个PreparedQuery分别加载两种YAML并查询；禁catalog选择/编码/网络；查询前后保存BM25文件字节和mtime完全相同。mixed中局部空词行仍被正确处理，normal-True为空范围；真实Chroma/BM25/SQLite，Embedding为MockTransport。普通Debug Test不自动进入子进程，不自动改调试配置。

异常入口`tests/test_sparse_retrieval.py::test_native_score_faults_are_not_empty_results[nan-scope]`（另negative-scope）。get_scores被故障注入返回坏分数，query_index第33行报完整性错误，SparseRetriever包装QueryJobError并保留版本/编码报告；pytest.raises捕获预期异常所以测试通过。没有回退global或空结果。

## 本次实际验证

独立内存probe采用bm25s0.3.13与本项目parameters(BM25Settings(1.5,.75))，对[A,X,B]调用global完整模型、scope局部模型，独立math公式逐项np.allclose(rtol=1e-12,atol=1e-15)通过。输出：

```text
global N=3 avgdl=2.0 mapping=[0,1,2]
开关 df=2 idf=0.470004；校准 df=1 idf=0.980829
hits=[('B',0.392332),('A',0.268574)]
scope N=2 avgdl=2.0 mapping=[0,2]
开关 df=1 idf=0.693147；校准 df=1 idf=0.693147
hits=[('A',0.396084),('B',0.277259)]
```

这是新课堂人工例，与Spec0036的历史20片反例区分；本轮未重跑历史反例，不改其数据。

```sh
.venv/bin/python -m pytest -q \
  tests/test_sparse_retrieval.py::test_strict_yaml_roundtrip_and_actual_mode_switch \
  tests/test_sparse_retrieval.py::test_native_scores_match_hand_formula_and_scope_before_top_k \
  tests/test_sparse_retrieval.py::test_retriever_pins_scope_and_keeps_encoding \
  'tests/test_sparse_retrieval.py::test_native_score_faults_are_not_empty_results[nan-scope]' \
  'tests/test_sparse_retrieval.py::test_native_score_faults_are_not_empty_results[negative-scope]' \
  'tests/test_sparse_retrieval_wiring.py::test_native_sparse_modes_after_restart[normal-False]' \
  'tests/test_sparse_retrieval_wiring.py::test_native_sparse_modes_after_restart[mixed-False]' \
  'tests/test_sparse_retrieval_wiring.py::test_native_sparse_modes_after_restart[normal-True]'
# 10 passed in 14.71s
```

L1双模式配置/查询/模式结果已存在；L2实质全库复用/局部重建及来源映射；L3由10项和反转探针验证配置/手算/跨进程消费。真实模型0，未做真实业务质量、生产容量/延迟验收。只维护学习文档，无源码/依赖/本项目真实.env/运行配置/原索引改动；构建不适用，未跑全量，git diff --check退出0。

## 学习证据与唯一下一步

5.4已讲解，助手核源码/探针/接线；用户理解待反馈，本人独立调试/实现未评估。讲解覆盖25/34节，余9节（第5章4节、第6章5节）。唯一下一步：5.5双路互补与RRF，用两份候选名单手算融合排名，理解为何只用各路名次、不直接相加原始分数。
