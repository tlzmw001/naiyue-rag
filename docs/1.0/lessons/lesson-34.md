# Lesson 34：阶段B·5.5 双路互补与RRF

日期：2026-10-25。第5章共8节，本节第5节。目标：沿两份名次表手算等权RRF，再追HybridSearch的一次准备、双路执行、来源合并和整次失败合同。只学习现有实现，不新增权重、查询重写、Agent或配置变更。

## 本节在链路中的位置

```text
HybridSearch.search
  → 一次QueryPipeline.prepare：同一快照/范围/Dense向量/Sparse词项
  → 给两路各一个PreparedQuery防御副本
  ├─ DenseRetriever → DenseResult
  └─ SparseRetriever → SparseResult
  → 两路结果/错误收集
  → RRFFusion.fuse → fused_hits
  → HybridResult：准备结果、配置、两路原始hits、融合hits、总trace
  → 后续CoreReranker / ResponseBuilder（5.6、5.7）
```

双路提供互补的候选：Dense可能找到同义表达，Sparse能利用技术标识符、数值和显式词项；各自实际效果需评测。RRF负责合并候选名次，不进行语义理解、事实核查或回答生成。HybridResult含内部查询编码，不直接当未来MCP的最终证据响应。

## 为什么用名次融合

Dense的score=max(0,1-distance/2)，BM25为词项贡献之和，两者尺度与分布不同。原始分数直接相加会让数值较大的尺度支配结果，不能据此认为它提供了更多业务证据。

当前RRFFusion采用等权Reciprocal Rank Fusion，倒数排名融合。每路对命中片段贡献1/(k+rank)，从1计名次；未出现在某路名单，该路贡献0。对同一chunk.id累加各路贡献，再按高分优先排序。

它保留名次、不使用原始分数差距，因此某路第1/2名之间差距很大或很小，在RRF里只体现为两个名次。原始distance/score仍保存于HybridResult.dense_hits/sparse_hits，融合过程没有把它们当概率。RRF分数也不是置信度。

## 两份具体名单手算

课堂别名A/B/C对应现有合成单元测试中的三个完整Chunk，不是用户真实资料排名。测试构造：

| 片段 | Dense名次 | Dense原始score | Sparse名次 | BM25原始score |
|---|---:|---:|---:|---:|
| A | 1 | 0.9 | 未返回 | — |
| B | 2 | 0.8 | 1 | 4.0 |
| C | 3 | 0.7 | 2 | 2.0 |

取k=60、fusion_top_k=3，与现有参考式测试一致：

```text
A = 1/(60+1)                  = 0.016393443
B = 1/(60+2) + 1/(60+1)      = 0.032522475
C = 1/(60+3) + 1/(60+2)      = 0.032002048

融合顺序 B → C → A
```

A是Dense第1但只有一路支持；B在两路都靠前，累加后领先。一般情况下双路支持有累加优势，但并非任意配置/任意深名次的双路项一定胜过所有单路项。

融合后输出FusedHit：rank、完整chunk、融合score、dense_rank、sparse_rank。例如B为rank1、dense_rank2、sparse_rank1；A的sparse_rank=None，不伪造0或一份实际不存在的名单位置。

## k与三个top_k分别做什么

k是名次贡献平滑参数：k1时第1/2/3贡献0.5/0.333333/0.25；k60时为0.016393/0.016129/0.015873。k较大时，前几名的相对贡献差距变小；不能据此推导k越大质量越好。

- dense_top_k：向量路先保留多少候选。
- sparse_top_k：词项路先保留多少候选。
- fusion_top_k：两路ID并集算分后最终保留多少。
- rrf_k：上述贡献公式的k，不是候选条数。

本项目examples/hybrid.example.yaml显式20/20/10/60/global/true，沿已核参考配置，不把它当最优结论。没有被任何一路召回的片段不在并集里，增大fusion_top_k无法凭空补回；RRF也不保证每份文档或每个层级至少占一条。

## 核心代码：按ID累计，再排序截断

实际实现core/hybrid_results.py:45–56；query/fusion.py负责先核两个结果合同及同一PreparedQuery，再调用该函数。

```python
scores = {}
chunks = {}
ranks = {}
for label, hits in [('dense', dense), ('sparse', sparse)]:
    for hit in hits:
        uid = hit.chunk.id
        # 同ID若内容/元数据不一致，先拒绝
        scores[uid] = scores.get(uid, 0.0) + 1 / (k + hit.rank)
        ranks.setdefault(uid, {})[label] = hit.rank
```

这段为核心行摘录，完整源码还保存chunks、做来源一致性检查及构造严格结果，不是另建教学实现。首次Dense遇B：scores[B]=1/62；Sparse再遇B：scores[B]+=1/61。ranks[B]从{'dense':2}变成{'dense':2,'sparse':1}。chunks保存该ID的完整来源对象。

最后sorted(scores,key=lambda uid:(-scores[uid],uid))[:top_k]：负号表示高分在前，同分按ID；先合并全并集再截断。返回片段按新顺序重新从1编号，并保留两路旧名次。

去重依据是同一个chunk.id，不是相同文件名或相似正文。不同ID即使文字相同也不自动合并；同ID的Chunk.to_dict不一致则报错，不能随意留一个版本。两路PreparedQuery按完整序列化值核对，包含版本/范围/问题编码/准备报告；防御副本不要求Python对象identity相同。

HybridResult还会重核Dense/Sparse合同与按原名单重算的融合结果，防止序列化时改score、名次或来源。通过HybridSearch调试时fused_hits断点可能再次因结果校验触发，不等于又执行了一次模型/原生检索。

## 一次编码、并行检索与失败合同

HybridSearch.search第54行只prepare一次；第61行从该结果复制两份，63–67行按配置走ThreadPoolExecutor(max_workers=2)或串行路径。并行的是两路检索，不是改变M3原有Dense→Sparse编码顺序。

_dense/_sparse各返回(result,elapsed,error)。此处捕获Exception并传回错误供主编排处理，不是空catch。主编排收集两路终态，第69–76行记录错误并重新抛出；正常才到第78行RRF。两路都失败时按当前确定顺序Dense为主错误，Sparse固定安全日志保留，不以谁先完成决定主错误。

| 情况 | 当前结果 |
|---|---|
| 两路正常且有候选 | 合并ID、累加名次贡献、返回融合hits |
| Sparse正常但空hits，Dense有候选 | 合法融合，仅有Dense贡献；不是异常降级 |
| 两路正常且都空 | 融合空，union_count=0 |
| Dense或Sparse报错 | 整次QueryJobError，不执行成功融合、不交付部分hits |
| 同ID来源冲突/融合错误 | 明确失败，保留已知版本与编码报告 |

线程池不提供本地IO强制中断或整次硬截止，with退出仍可能等待工作完成；并行不承诺固定加速比。trace各路elapsed是各自耗时，不能简单相加当并行总耗时；eligible_count表示允许候选数，不是ANN实际比较次数。准备失败与本节运行边界沿Lesson12/30，不重复设计Agent重试。

## Debug Test：先看纯融合，后看编排

### 手算与来源一致性

入口：`tests/test_hybrid_search.py::test_reference_rrf_formula_and_rank_provenance`，无参数ID。Test Explorer点Debug Test，断点测试51行，此时ready、a/b/c、dense/sparse均已构造；测试49–50行的人为分数/名次与上表相同。

F11进入RRFFusion.fuse；必要时F5到core/hybrid_results.py:48跳过已学DTO校验。选fused_hits栈帧，跟49–54行：label、hit.rank、uid、scores、ranks；第48行后容器才存在，当前uid在第51行后存在。仅投影sorted(scores.values(),reverse=True)、list(ranks.values())，不展开全Chunk。

Dense处理结束时3个score各有一路贡献；Sparse处理B后B值增加，处理C后C值增加。第55行后order产生，第56行生成rank1/2/3。回测试52–54行后result已赋值，看[(h.dense_rank,h.sparse_rank,h.score) for h in result]；映射到B/C/A由测试中a.id/b.id/c.id核对，不猜hash字符。

测试55行给Sparse里B的metadata加测试标记；56行第二次fuse会在fused_hits第52行拒绝同ID不同内容。pytest.raises捕获预期ValueError，因此测试仍通过。真实BM25/资料包等由临时夹具准备，Dense/Sparse编码和Chroma查询为替身；融合本身是真实实现，名单为人工构造。

### 两路失败如何上报

`tests/test_hybrid_search.py::test_hybrid_errors_retain_stage_usage_and_never_degrade[sparse]`（另dense/both）。测试102行fail_sparse抛StorageError，104行monkeypatch检索器；HybridSearch._sparse第40行返回错误三元组，search第69–76行检查后抛出，最终QueryJobError(stage=sparse,code=bm25_query_failed)。错误捕获在测试117行，不进入成功融合；已完成prepare的编码用量保留。调线程内部需选相应worker帧；初学可先F5到主线程69行看outcomes，而不调并行启动。

### 并行与原生证据

`test_parallel_branch_start_is_proved_with_barrier`用Barrier证明两路都进入，非紧sleep猜并发。`tests/test_hybrid_search_wiring.py::test_native_hybrid_threaded_and_serial_after_restart[normal-global-False]`（另normal-scope-False/all-empty-scope-False）在新进程真实Chroma/BM25执行并行和串行，核相同ID/来源/名次/分数；all-empty中Sparse合法空，Dense仍工作。每次search编码模拟请求1，串并行两次共2；不是一次search请求2。未调用真实模型，不修改IDE子进程调试配置。

## 本次实际验证

标准库Fraction按两份名单计算精确分数，打印B0.032522475、C0.032002048、A0.016393443，与真实RRFFusion测试相符。探针是教学算术，不是实际文档质量对照。

```sh
.venv/bin/python -m pytest -q \
  tests/test_hybrid_search.py::test_reference_rrf_formula_and_rank_provenance \
  tests/test_hybrid_search.py::test_config_yaml_is_consumed_by_actual_branches \
  tests/test_hybrid_search.py::test_hybrid_once_encoding_same_snapshot_and_trace \
  tests/test_hybrid_search.py::test_parallel_branch_start_is_proved_with_barrier \
  tests/test_hybrid_search.py::test_explicit_empty_scope_still_runs_both_empty_branches \
  'tests/test_hybrid_search.py::test_hybrid_errors_retain_stage_usage_and_never_degrade[dense]' \
  'tests/test_hybrid_search.py::test_hybrid_errors_retain_stage_usage_and_never_degrade[sparse]' \
  'tests/test_hybrid_search.py::test_hybrid_errors_retain_stage_usage_and_never_degrade[both]' \
  'tests/test_hybrid_search.py::test_hybrid_result_is_strict_and_defensively_copied[rrf_score]' \
  'tests/test_hybrid_search.py::test_hybrid_result_is_strict_and_defensively_copied[source_rank]' \
  'tests/test_hybrid_search_wiring.py::test_native_hybrid_threaded_and_serial_after_restart[normal-global-False]' \
  'tests/test_hybrid_search_wiring.py::test_native_hybrid_threaded_and_serial_after_restart[normal-scope-False]' \
  'tests/test_hybrid_search_wiring.py::test_native_hybrid_threaded_and_serial_after_restart[all-empty-scope-False]'
# 16 passed in 20.96s
```

三个原生场景使用真实临时Bundle/Chroma/BM25/SQLite，源目录移开、新进程串并行实跑，Embedding为SDK MockTransport且阻断外网。真实模型0，未测真实语料质量/生产容量/加速比；人工名次和本地SDK证明与真实服务结果分开。

L1 HybridSearch/RRFFusion/结果合同已存在；L2实质一次准备/两路执行/等权合并/错误传播；L3有16项、原生串并行与算术探针证据。仅学习记录修改，无源码/依赖/本项目真实.env/运行配置/原索引修改；构建不适用，未跑全量，git diff --check退出0。

## 学习证据与唯一下一步

5.5已讲解，助手核源码/算术/接线；用户理解待反馈，本人独立调试/实现未评估。讲解覆盖26/34节，余8节（第5章3节、第6章5节）。唯一下一步：5.6重排，理解LLM/CrossEncoder怎样在固定融合候选上结合问题重新判断相关性，以及与RRF的职责区别。
